import base64
import hashlib
import secrets
import string
from datetime import datetime, timedelta, timezone
from uuid import UUID

import bcrypt
import jwt
from pydantic import ValidationError

from intric.authentication.api_key_repo import ApiKeysRepository
from intric.authentication.auth_models import (
    ApiKey,
    ApiKeyCreated,
    JWTCreds,
    JWTMeta,
    JWTPayload,
)
from intric.main.config import get_settings
from intric.main.exceptions import AuthenticationException
from intric.main.logging import get_logger
from intric.users.user import UserBase, UserInDB

logger = get_logger(__name__)

JWT_ALGORITHM = get_settings().jwt_algorithm
JWT_AUDIENCE = get_settings().jwt_audience
JWT_EXPIRY_TIME_MINUTES = get_settings().jwt_expiry_time
JWT_SECRET = get_settings().jwt_secret
OIDC_CLOCK_LEEWAY_SECONDS = get_settings().oidc_clock_leeway_seconds


class AuthService:
    def __init__(self, api_key_repo: ApiKeysRepository):
        self.api_key_repo = api_key_repo

    @staticmethod
    def _generate_salt() -> bytes:
        return bcrypt.gensalt()

    @staticmethod
    def _hash_password(password: str, salt: bytes) -> str:
        pwd_bytes = password.encode("utf-8")
        return bcrypt.hashpw(password=pwd_bytes, salt=salt).decode("utf-8")

    @staticmethod
    def hash_api_key(api_key: str):
        return hashlib.sha256(api_key.encode()).hexdigest()

    def create_salt_and_hashed_password(self, plaintext_password: str | None):
        if plaintext_password == None:
            plaintext_password = ""
        pwd_bytes = plaintext_password.encode("utf-8")
        salt = bcrypt.gensalt()
        hashed_password = bcrypt.hashpw(password=pwd_bytes, salt=salt)
        return salt.decode(), hashed_password.decode("utf-8")

    @staticmethod
    def verify_password(password: str, hashed_pw: str) -> bool:
        """Verify that incoming password+salt matches hashed pw"""
        password_byte_enc = password.encode("utf-8")
        return bcrypt.checkpw(
            password=password_byte_enc, hashed_password=hashed_pw.encode("utf-8")
        )

    @staticmethod
    def generate_password(length: int):
        alphabet = string.ascii_letters + string.digits
        password = "".join(secrets.choice(alphabet) for _ in range(length))

        return password

    def create_access_token_for_user(
        self,
        user: UserInDB,
        secret_key: str = str(JWT_SECRET),
        audience: str = JWT_AUDIENCE,
        expires_in: int = JWT_EXPIRY_TIME_MINUTES,
    ) -> str:
        if not user or not isinstance(user, UserBase):
            return None

        jwt_meta = JWTMeta(
            aud=audience,
            iat=datetime.timestamp(
                datetime.now(timezone.utc) - timedelta(seconds=2)
            ),  # Fix bug where JWT had not become valid
            exp=datetime.timestamp(
                datetime.now(timezone.utc) + timedelta(minutes=expires_in)
            ),
        )
        jwt_creds = JWTCreds(sub=user.email, username=user.username)
        token_payload = JWTPayload(
            **jwt_meta.model_dump(),
            **jwt_creds.model_dump(),
        )
        # NOTE - previous versions of pyjwt ("<2.0") returned the token as bytes insted of a string.
        # That is no longer the case and the `.decode("utf-8")` has been removed.
        access_token = jwt.encode(
            token_payload.model_dump(), secret_key, algorithm=JWT_ALGORITHM
        )
        return access_token

    def _generate_api_key(self) -> str:
        return secrets.token_hex(get_settings().api_key_length)

    def _create_api_key(self, prefix: str):
        api_key = self._generate_api_key()
        prefix_api_key = f"{prefix}_{api_key}"
        truncated_key = prefix_api_key[-4:]

        return ApiKey(key=prefix_api_key, truncated_key=truncated_key)

    def _create_and_hash_api_key(self, prefix: str):
        api_key = self._create_api_key(prefix)
        hashed_key = self.hash_api_key(api_key.key)

        return ApiKeyCreated(**api_key.model_dump(), hashed_key=hashed_key)

    async def create_user_api_key(
        self, prefix: str, user_id: UUID, delete_old: bool = True
    ):
        api_key = self._create_and_hash_api_key(prefix=prefix)
        key_to_save = ApiKey(
            key=api_key.hashed_key, truncated_key=api_key.truncated_key
        )

        if delete_old:
            await self.api_key_repo.delete_by_user(user_id)

        await self.api_key_repo.add(api_key=key_to_save, user_id=user_id)

        return api_key

    async def create_assistant_api_key(
        self,
        prefix: str,
        assistant_id: int,
        delete_old: bool = True,
        hash_key: bool = True,
    ):
        api_key = self._create_and_hash_api_key(prefix=prefix)
        key = api_key.hashed_key if hash_key else api_key.key
        key_to_save = ApiKey(key=key, truncated_key=api_key.truncated_key)

        if delete_old:
            await self.api_key_repo.delete_by_assistant(assistant_id)

        await self.api_key_repo.add(api_key=key_to_save, assistant_id=assistant_id)

        return api_key

    async def get_api_key(self, plain_key: str, *, hash_key: bool = True):
        if hash_key:
            key = self.hash_api_key(plain_key)
        else:
            key = plain_key

        return await self.api_key_repo.get(key)

    def get_username_from_token(self, token: str, secret_key: str) -> str:
        return self.get_jwt_payload(token, key=str(secret_key)).username

    def get_jwt_payload(
        self,
        token: str,
        key: str,
        aud: str = JWT_AUDIENCE,
        algs: list[str] = [JWT_ALGORITHM],
    ):
        try:
            decoded_token = jwt.decode(token, key=key, audience=aud, algorithms=algs)
            payload = JWTPayload(**decoded_token)

        except (jwt.PyJWTError, ValidationError):
            raise AuthenticationException("Could not validate token credentials.")

        return payload

    def get_payload_from_openid_jwt(
        self,
        *,
        id_token: str,
        access_token: str,
        key: jwt.PyJWK,
        signing_algos: list[str],
        client_id: str,
        options: dict = None,
        correlation_id: str = None,
    ):
        correlation_id = correlation_id or "no-correlation-id"

        jwt_options = dict(options or {})
        leeway_applied = False
        if OIDC_CLOCK_LEEWAY_SECONDS:
            jwt_options.setdefault("leeway", OIDC_CLOCK_LEEWAY_SECONDS)
            leeway_applied = True

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
                options=jwt_options or None,
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
            logger.error(
                "JWT not yet valid",
                extra={
                    "correlation_id": correlation_id,
                    "server_time": datetime.now(timezone.utc).isoformat(),
                    "leeway_seconds": OIDC_CLOCK_LEEWAY_SECONDS if leeway_applied else 0,
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
        options: dict = None,
        correlation_id: str = None,
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
