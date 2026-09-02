import base64
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

import bcrypt
import jwt
from pydantic import ValidationError

from eneo.authentication.auth_models import (
    JWTCreds,
    JWTMeta,
    JWTPayload,
)
from eneo.main.config import get_settings
from eneo.main.exceptions import AuthenticationException
from eneo.main.logging import get_logger
from eneo.users.password import BCRYPT_MAX_PASSWORD_BYTES
from eneo.users.user import UserInDB

if TYPE_CHECKING:
    from jwt.types import Options

logger = get_logger(__name__)

JWT_ALGORITHM = get_settings().jwt_algorithm
JWT_AUDIENCE = get_settings().jwt_audience
JWT_EXPIRY_TIME_MINUTES = get_settings().jwt_expiry_time
JWT_ISSUER = get_settings().jwt_issuer
JWT_SECRET = get_settings().jwt_secret
OIDC_CLOCK_LEEWAY_SECONDS = get_settings().oidc_clock_leeway_seconds


class AuthService:
    # Dummy hash for timing attack mitigation
    # Pre-computed bcrypt hash of a random string to ensure constant-time password verification
    # Even when user is not found, we verify against this to maintain consistent response times
    DUMMY_HASH = "$2b$12$CfZ8Z9V6o4d0B.3n4WGNBe4oANd8FjKc7t2rggx5xeW5c0p1sS2yW"

    def create_salt_and_hashed_password(
        self, plaintext_password: str
    ) -> tuple[str, str]:
        pwd_bytes = plaintext_password.encode("utf-8")
        if len(pwd_bytes) > BCRYPT_MAX_PASSWORD_BYTES:
            raise ValueError("Password exceeds bcrypt's maximum input size.")
        salt = bcrypt.gensalt()
        hashed_password = bcrypt.hashpw(password=pwd_bytes, salt=salt)
        return salt.decode(), hashed_password.decode("utf-8")

    @staticmethod
    def verify_password(password: str, hashed_pw: str) -> bool:
        """Verify that incoming password+salt matches hashed pw"""
        password_byte_enc = password.encode("utf-8")
        # Older bcrypt releases silently truncated inputs at 72 bytes. Preserve
        # verification compatibility for historical hashes while all new
        # writes reject overlong values in the local password policy.
        password_byte_enc = password_byte_enc[:BCRYPT_MAX_PASSWORD_BYTES]
        try:
            return bcrypt.checkpw(
                password=password_byte_enc, hashed_password=hashed_pw.encode("utf-8")
            )
        except ValueError:
            # Malformed historical hashes and unsupported inputs authenticate as
            # invalid credentials; neither should become a server error.
            return False

    def create_access_token_for_user(
        self,
        user: UserInDB | None,
        secret_key: str | None = None,
        audience: str = JWT_AUDIENCE,
        expires_in: float = JWT_EXPIRY_TIME_MINUTES,
        extra_claims: dict[str, Any] | None = None,
    ) -> str:
        """Mint an access token; ``expires_in`` is in minutes.

        ``extra_claims`` follows the same contract as the MCP token above:
        unknown claims ride through ``JWTPayload`` on decode and are read out
        separately via :meth:`get_verified_claims`. Reserved JWT claims cannot
        be overridden through it.
        """
        if user is None:
            raise ValueError("user is required to create an access token")

        secret_key = secret_key or str(JWT_SECRET)

        jwt_meta = JWTMeta(
            aud=audience,
            iat=datetime.timestamp(
                datetime.now(timezone.utc) - timedelta(seconds=2)
            ),  # Fix bug where JWT had not become valid
            exp=datetime.timestamp(
                datetime.now(timezone.utc) + timedelta(minutes=expires_in)
            ),
        )
        jwt_creds = JWTCreds(
            sub=user.email,
            username=user.username,
            credential_version=getattr(user, "credential_version", 0),
        )
        token_payload = JWTPayload(
            **jwt_meta.model_dump(),
            **jwt_creds.model_dump(),
        )
        payload = token_payload.model_dump()
        if extra_claims:
            reserved = set(extra_claims) & set(payload)
            if reserved:
                raise ValueError(
                    f"extra_claims may not override reserved claims: {sorted(reserved)}"
                )
            payload.update(extra_claims)
        # NOTE - previous versions of pyjwt ("<2.0") returned the token as bytes insted of a string.
        # That is no longer the case and the `.decode("utf-8")` has been removed.
        access_token = jwt.encode(payload, secret_key, algorithm=JWT_ALGORITHM)
        return access_token

    def create_scoped_mcp_token(
        self,
        user: UserInDB,
        *,
        assistant_id: UUID,
        expires_in: int = 15,
    ) -> str:
        """Mint a short-lived access token for a loopback MCP server.

        Eneo attaches an ephemeral MCP server pointing at its own loopback
        endpoint, authenticated with this token. The token authenticates as
        ``user`` exactly like a normal access token (so the loopback endpoint
        reuses ``authenticate``), and additionally carries an ``assistant_id``
        claim so tools need no scope argument and cannot be redirected to
        another assistant. Unknown claims ride through ``JWTPayload`` (which
        ignores them on decode) and are read out separately by the loopback
        endpoint.
        """
        secret_key = str(JWT_SECRET)

        jwt_meta = JWTMeta(
            aud=JWT_AUDIENCE,
            iat=datetime.timestamp(datetime.now(timezone.utc) - timedelta(seconds=2)),
            exp=datetime.timestamp(
                datetime.now(timezone.utc) + timedelta(minutes=expires_in)
            ),
        )
        jwt_creds = JWTCreds(
            sub=user.email,
            username=user.username,
            credential_version=getattr(user, "credential_version", 0),
        )
        payload = {
            **JWTPayload(
                **jwt_meta.model_dump(),
                **jwt_creds.model_dump(),
            ).model_dump(),
            "assistant_id": str(assistant_id),
        }
        return jwt.encode(payload, secret_key, algorithm=JWT_ALGORITHM)

    @staticmethod
    def validate_credential_version(
        claims: Mapping[str, object], user: UserInDB
    ) -> None:
        """Reject an Eneo JWT minted before the user's latest credential change.

        Version 0 is the compatibility baseline for tokens created before the
        claim was introduced. Provider-issued identity tokens have a different
        issuer and remain owned by that provider; applying Eneo's counter to
        them would make every future provider login fail once the counter moved
        past zero. Every Eneo JWT consumer that resolves a live user must call
        this after signature verification and user lookup.
        """

        # New tokens are unambiguous: possession of the private Eneo claim
        # opts into version enforcement regardless of issuer text. For legacy
        # tokens without the claim, only the exact local issuer represents
        # Eneo's version-zero compatibility baseline. A different verified
        # issuer is provider-owned and outside Eneo session invalidation.
        if "credential_version" not in claims and claims.get("iss") != JWT_ISSUER:
            return

        AuthService.validate_local_credential_version(
            claims.get("credential_version", 0), user
        )

    @staticmethod
    def validate_local_credential_version(raw_version: object, user: UserInDB) -> None:
        """Strictly compare a local token or ticket version with live state."""

        if isinstance(raw_version, bool) or not isinstance(raw_version, int):
            raise AuthenticationException("Could not validate token credentials.")

        if raw_version != getattr(user, "credential_version", 0):
            raise AuthenticationException("Could not validate token credentials.")

    def get_verified_claims(
        self,
        token: str,
        key: str,
        aud: str = JWT_AUDIENCE,
        algs: list[str] | None = None,
    ) -> dict[str, Any]:
        """Verified raw claims, including ones ``JWTPayload`` does not model."""
        algs = algs or [JWT_ALGORITHM]
        try:
            return jwt.decode(token, key=key, audience=aud, algorithms=algs)
        except jwt.PyJWTError:
            raise AuthenticationException("Could not validate token credentials.")

    def get_jwt_payload(
        self,
        token: str,
        key: str,
        aud: str = JWT_AUDIENCE,
        algs: list[str] | None = None,
    ) -> JWTPayload:
        payload, _ = self.get_jwt_payload_with_claims(
            token, key=key, aud=aud, algs=algs
        )
        return payload

    def get_jwt_payload_with_claims(
        self,
        token: str,
        key: str,
        aud: str = JWT_AUDIENCE,
        algs: list[str] | None = None,
    ) -> tuple[JWTPayload, dict[str, Any]]:
        """Return both the typed payload and untouched verified claims.

        The raw mapping preserves whether optional private claims were absent;
        applying Pydantic defaults before credential-version routing would turn
        provider tokens into apparent legacy Eneo tokens.
        """

        claims = self.get_verified_claims(token, key=key, aud=aud, algs=algs)
        try:
            payload = JWTPayload(**claims)
        except ValidationError:
            raise AuthenticationException("Could not validate token credentials.")

        return payload, claims

    def get_payload_from_openid_jwt(
        self,
        *,
        id_token: str,
        access_token: str,
        key: jwt.PyJWK,
        signing_algos: list[str],
        client_id: str,
        options: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        correlation_id = correlation_id or "no-correlation-id"

        jwt_options = dict(options or {})
        clock_leeway = OIDC_CLOCK_LEEWAY_SECONDS or 0
        leeway_applied = clock_leeway > 0

        logger.debug(
            "OIDC: Starting JWT validation",
            extra={
                "correlation_id": correlation_id,
                "client_id": client_id,
                "signing_algos": signing_algos,
                "options": jwt_options or None,
                "id_token_length": len(id_token) if id_token else 0,
                "leeway_seconds": OIDC_CLOCK_LEEWAY_SECONDS if leeway_applied else 0,
            },
        )

        # Decode JWT header without verification to log details
        try:
            unverified_header = jwt.get_unverified_header(id_token)
            logger.debug(
                "JWT header decoded",
                extra={
                    "correlation_id": correlation_id,
                    "alg": unverified_header.get("alg"),
                    "kid": unverified_header.get("kid"),
                    "typ": unverified_header.get("typ"),
                },
            )
        except Exception as e:
            logger.error(
                "Failed to decode JWT header",
                extra={
                    "correlation_id": correlation_id,
                    "error": str(e),
                },
            )

        try:
            jwt_decoded = jwt.api_jwt.decode_complete(
                id_token,
                key=key,
                algorithms=signing_algos,
                audience=client_id,
                options=cast("Options", jwt_options) or None,
                leeway=clock_leeway,
            )

            payload = jwt_decoded["payload"]
            header = jwt_decoded["header"]

            logger.debug(
                "JWT decoded successfully",
                extra={
                    "correlation_id": correlation_id,
                    "audience_claim": payload.get("aud"),
                    "issuer": payload.get("iss"),
                    "subject": payload.get("sub"),
                    "exp": payload.get("exp"),
                    "iat": payload.get("iat"),
                    "has_at_hash": "at_hash" in payload,
                    "algorithm": header.get("alg"),
                },
            )

        except jwt.ExpiredSignatureError as e:
            logger.error(
                "JWT has expired",
                extra={
                    "correlation_id": correlation_id,
                    "error": str(e),
                },
            )
            raise
        except jwt.InvalidAudienceError as e:
            logger.error(
                "JWT audience validation failed",
                extra={
                    "correlation_id": correlation_id,
                    "expected_audience": client_id,
                    "error": str(e),
                },
            )
            raise
        except jwt.ImmatureSignatureError as e:
            drift_seconds = None
            iat_claim = None
            iat_iso = None
            server_dt = datetime.now(timezone.utc)
            server_time_iso = server_dt.isoformat()
            if id_token:
                try:
                    unverified_claims = jwt.decode(
                        id_token,
                        options={
                            "verify_signature": False,
                            "verify_exp": False,
                            "verify_aud": False,
                        },
                        algorithms=signing_algos,
                    )
                    iat_claim = unverified_claims.get("iat")
                    if isinstance(iat_claim, (int, float)):
                        drift_seconds = iat_claim - server_dt.timestamp()
                        iat_iso = datetime.fromtimestamp(
                            iat_claim, tz=timezone.utc
                        ).isoformat()
                except Exception:
                    # Best-effort diagnostics only
                    pass

            logger.error(
                "JWT not yet valid",
                extra={
                    "correlation_id": correlation_id,
                    "server_time": server_time_iso,
                    "server_timezone": "UTC",
                    "leeway_seconds": clock_leeway if leeway_applied else 0,
                    "iat_claim": iat_claim,
                    "iat_claim_iso": iat_iso,
                    "iat_drift_seconds": drift_seconds,
                    "error": str(e),
                },
            )
            raise
        except jwt.InvalidSignatureError as e:
            logger.error(
                "JWT signature validation failed",
                extra={
                    "correlation_id": correlation_id,
                    "error": str(e),
                },
            )
            raise
        except jwt.PyJWTError as e:
            logger.error(
                "JWT validation failed",
                extra={
                    "correlation_id": correlation_id,
                    "error_type": type(e).__name__,
                    "error": str(e),
                },
            )
            raise

        # Verify at_hash (OPTIONAL per OIDC spec)
        # If at_hash present in ID token → MUST validate (fail if mismatch)
        # If at_hash NOT present → Skip validation (valid per OIDC spec)
        # This allows compatibility with both MobilityGuard (includes at_hash)
        # and Entra ID (may omit at_hash in authorization code flow)
        expected_at_hash = payload.get("at_hash")

        if expected_at_hash:
            # at_hash present → MUST validate
            logger.debug(
                "at_hash present - validating",
                extra={
                    "correlation_id": correlation_id,
                    "algorithm": header["alg"],
                },
            )

            try:
                # Get the pyjwt algorithm object
                alg_obj = jwt.get_algorithm_by_name(header["alg"])

                # Compute at_hash
                digest = alg_obj.compute_hash_digest(access_token.encode())
                computed_at_hash = (
                    base64.urlsafe_b64encode(digest[: (len(digest) // 2)])
                    .rstrip(b"=")
                    .decode()
                )

                # Validate
                if computed_at_hash != expected_at_hash:
                    logger.error(
                        "at_hash validation failed",
                        extra={
                            "correlation_id": correlation_id,
                            "computed_at_hash": computed_at_hash,
                            "expected_at_hash": expected_at_hash,
                            "algorithm": header["alg"],
                        },
                    )
                    raise jwt.InvalidTokenError(
                        f"at_hash mismatch: expected {expected_at_hash}, got {computed_at_hash}"
                    )

                logger.debug(
                    "at_hash validated successfully",
                    extra={"correlation_id": correlation_id},
                )

            except jwt.InvalidTokenError:
                raise  # Re-raise at_hash mismatch
            except Exception as e:
                logger.error(
                    "at_hash verification error",
                    extra={
                        "correlation_id": correlation_id,
                        "error_type": type(e).__name__,
                        "error": str(e),
                    },
                )
                raise jwt.InvalidTokenError(f"at_hash verification failed: {str(e)}")
        else:
            # at_hash NOT present → Skip validation (optional per OIDC spec)
            logger.debug(
                "at_hash not present - skipping validation (optional per OIDC spec)",
                extra={"correlation_id": correlation_id},
            )

        return payload

    def get_username_and_email_from_openid_jwt(
        self,
        *,
        id_token: str,
        access_token: str,
        key: jwt.PyJWK,
        signing_algos: list[str],
        client_id: str,
        options: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> tuple[str, str]:
        correlation_id = correlation_id or "no-correlation-id"

        logger.debug(
            "Extracting username and email from OpenID JWT",
            extra={
                "correlation_id": correlation_id,
                "client_id": client_id,
                "options": options,
            },
        )

        payload = self.get_payload_from_openid_jwt(
            id_token=id_token,
            access_token=access_token,
            key=key,
            signing_algos=signing_algos,
            client_id=client_id,
            options=options,
            correlation_id=correlation_id,
        )

        username = payload.get("sub")
        email = payload.get("email")

        if not username or not email:
            logger.error(
                "JWT payload missing required fields",
                extra={
                    "correlation_id": correlation_id,
                    "has_sub": bool(username),
                    "has_email": bool(email),
                    "payload_keys": list(payload.keys()),
                },
            )
            raise ValueError(
                f"JWT missing required claims - sub: {bool(username)}, email: {bool(email)}"
            )

        logger.debug(
            "Successfully extracted username and email from JWT",
            extra={
                "correlation_id": correlation_id,
                "username": username,
                "email": email,
            },
        )

        return username, email
