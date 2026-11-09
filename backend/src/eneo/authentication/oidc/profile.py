"""What Eneo uses of one OpenID provider: its stored config plus discovery.

A database federation config and the environment-only config have the same
keys. A key that is absent means today's behaviour, so existing configs need
no migration. Only protocol constants and security floors are fixed here.
"""

import asyncio
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import cast

import aiohttp

from eneo.authentication.auth_models import DEFAULT_EMAIL_VERIFIED_CLAIMS
from eneo.main.aiohttp_client import aiohttp_client
from eneo.main.logging import get_logger

logger = get_logger(__name__)

# The ID token algorithms any provider may use. Symmetric algorithms and
# "none" are never accepted.
SIGNING_ALGORITHM_ALLOWLIST = frozenset(
    {
        "RS256",
        "RS384",
        "RS512",
        "PS256",
        "PS384",
        "PS512",
        "ES256",
        "ES384",
        "ES512",
        "EdDSA",
    }
)
# What Eneo verified with before providers could differ, for a provider whose
# discovery lists no algorithms.
DEFAULT_SIGNING_ALGORITHMS = ("RS256",)
# The scopes an IdP config gets when it names none; stored configs keep theirs.
DEFAULT_SCOPES = ("openid", "email", "profile")
DISCOVERY_RETRY_SECONDS = 30

_TOKEN_AUTH_METHODS = ("client_secret_post", "client_secret_basic")

TEMPLATED_ISSUER_GUIDANCE = (
    "The provider's issuer is a template; use your own directory's discovery endpoint"
)


def is_templated_issuer(issuer: str) -> bool:
    """An issuer with a placeholder, as a multi-tenant endpoint's discovery
    names it (Entra ``common``: ``.../{tenantid}/v2.0``). No ID token can
    match it, and URIs never contain an unescaped brace (RFC 3986)."""
    return "{" in issuer or "}" in issuer


class OidcProviderError(Exception):
    """The provider's config or discovery cannot be used to sign in."""


@dataclass(frozen=True)
class OidcProfile:
    # The issuer the ID token and the iss parameter must name: the stored
    # one, or discovery's when none is stored.
    issuer: str
    client_id: str
    client_secret: str
    authorization_endpoint: str
    token_endpoint: str
    token_endpoint_auth_method: str
    jwks_uri: str
    signing_algorithms: tuple[str, ...]
    scopes: tuple[str, ...]
    email_claim: str
    # The claim whose value is the subject an account is bound to.
    subject_claim: str
    email_verified_claims: tuple[str, ...]
    # RFC 9207: the provider puts its issuer in every authorization response.
    iss_parameter_supported: bool


@dataclass
class _CachedDiscovery:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    document: dict[str, object] | None = None
    fetched_at: float = 0.0
    retry_at: float = 0.0

    def fresh(self, ttl_seconds: int) -> dict[str, object] | None:
        if (
            self.document is not None
            and time.monotonic() - self.fetched_at <= ttl_seconds
        ):
            return self.document
        return None


# A process-wide cache keyed by URL with one TTL and no stale fallback;
# move it to Redis if workers ever need to agree on it.
_discovery_cache: dict[str, _CachedDiscovery] = {}


async def fetch_discovery(url: str, *, ttl_seconds: int) -> dict[str, object]:
    """The provider's discovery document, fetched at most once per TTL.

    As the JWKS cache does, concurrent misses share one fetch, and after a
    failed fetch the URL is not tried again for ``DISCOVERY_RETRY_SECONDS``.
    """
    entry = _discovery_cache.setdefault(url, _CachedDiscovery())
    if (document := entry.fresh(ttl_seconds)) is not None:
        return document
    async with entry.lock:
        if (document := entry.fresh(ttl_seconds)) is not None:
            return document
        if time.monotonic() < entry.retry_at:
            raise OidcProviderError("Failed to fetch IdP configuration")
        # Marked before the fetch, so an outage costs one attempt per cooldown.
        entry.retry_at = time.monotonic() + DISCOVERY_RETRY_SECONDS
        entry.document = await _download_discovery(url)
        entry.fetched_at = time.monotonic()
        entry.retry_at = 0.0
        return entry.document


async def _download_discovery(url: str) -> dict[str, object]:
    try:
        async with aiohttp_client().get(url) as resp:
            if resp.status != 200:
                logger.error(
                    f"Failed to fetch OIDC discovery document: HTTP {resp.status}",
                    extra={"discovery_url": url, "http_status": resp.status},
                )
                raise OidcProviderError(
                    f"Failed to fetch discovery document: HTTP {resp.status}"
                )
            document: object = await resp.json()
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
        logger.error(
            "Failed to fetch OIDC discovery document",
            extra={"discovery_url": url, "error_type": type(exc).__name__},
        )
        raise OidcProviderError("Failed to fetch IdP configuration") from exc
    if not isinstance(document, dict):
        raise OidcProviderError("Failed to fetch IdP configuration")
    return cast(dict[str, object], document)


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _texts(value: object, key: str) -> tuple[str, ...] | None:
    """A configured list of names; None when absent, refused when malformed."""
    if value is None:
        return None
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) and item for item in cast(list[object], value))
    ):
        raise OidcProviderError(f"Federation config key '{key}' must list names")
    return tuple(cast(list[str], value))


def _mapped_claim(mapping: object, key: str) -> str | None:
    if not isinstance(mapping, Mapping):
        return None
    return _text(cast(Mapping[str, object], mapping).get(key))


def subject_claim(mapping: object, *, email_claim: str) -> str:
    """The claim a claims mapping names for the subject, else ``sub``.

    A provider whose ``sub`` differs per client can name a stable id claim
    instead. It must not be the email claim, nor the standard ``email`` claim
    when the mapping reads the address from another: an address can be
    reassigned, and the subject is what keeps a reassigned address out of the
    account.
    """
    claim = _mapped_claim(mapping, "subject") or "sub"
    if claim in (email_claim, "email"):
        raise OidcProviderError(
            "The claims mapping names the email claim as the subject claim"
        )
    return claim


def _token_auth_method(
    config: Mapping[str, object], discovery: Mapping[str, object]
) -> str:
    """The stored method, else the first supported of post and basic."""
    stored = _text(config.get("token_endpoint_auth_method"))
    if stored is None:
        for source in (
            config.get("token_endpoint_auth_methods_supported"),
            discovery.get("token_endpoint_auth_methods_supported"),
        ):
            if isinstance(source, list) and source:
                methods = [str(m).lower() for m in cast(list[object], source) if m]
                stored = next(
                    (m for m in _TOKEN_AUTH_METHODS if m in methods), methods[0]
                )
                break
    if stored is not None and stored not in _TOKEN_AUTH_METHODS:
        logger.warning(
            "Unsupported token endpoint auth method; defaulting to client_secret_post",
            extra={"requested_method": stored},
        )
    return stored if stored in _TOKEN_AUTH_METHODS else "client_secret_post"


def _signing_algorithms(
    config: Mapping[str, object], discovery: Mapping[str, object]
) -> tuple[str, ...]:
    configured = _texts(config.get("signing_algorithms"), "signing_algorithms")
    advertised = discovery.get("id_token_signing_alg_values_supported")
    candidates: Sequence[object] = (
        configured
        or (cast(list[object], advertised) if isinstance(advertised, list) else None)
        or DEFAULT_SIGNING_ALGORITHMS
    )
    allowed = tuple(
        dict.fromkeys(
            alg
            for alg in candidates
            if isinstance(alg, str) and alg in SIGNING_ALGORITHM_ALLOWLIST
        )
    )
    if not allowed:
        raise OidcProviderError("The provider signs with no algorithm Eneo accepts")
    return allowed


def build_profile(
    config: Mapping[str, object], discovery: Mapping[str, object]
) -> OidcProfile:
    """The profile for a resolved federation config and its discovery document.

    Stored endpoints and issuer win over discovery, as before.
    """

    def resolve(key: str, missing: str) -> str:
        value = _text(config.get(key)) or _text(discovery.get(key))
        if value is None:
            raise OidcProviderError(missing)
        return value

    client_id = _text(config.get("client_id"))
    client_secret = _text(config.get("client_secret"))
    if client_id is None or client_secret is None:
        raise OidcProviderError("The OIDC client is not configured")
    mapping = config.get("claims_mapping")
    email_claim = _mapped_claim(mapping, "email") or "email"
    issuer = resolve("issuer", "Failed to resolve the provider's issuer")
    if is_templated_issuer(issuer):
        raise OidcProviderError(TEMPLATED_ISSUER_GUIDANCE)
    return OidcProfile(
        issuer=issuer,
        client_id=client_id,
        client_secret=client_secret,
        authorization_endpoint=resolve(
            "authorization_endpoint", "Failed to resolve authorization endpoint"
        ),
        token_endpoint=resolve("token_endpoint", "Failed to resolve token endpoint"),
        token_endpoint_auth_method=_token_auth_method(config, discovery),
        jwks_uri=resolve("jwks_uri", "Failed to resolve JWKS URI"),
        signing_algorithms=_signing_algorithms(config, discovery),
        scopes=_texts(config.get("scopes"), "scopes") or DEFAULT_SCOPES,
        email_claim=email_claim,
        subject_claim=subject_claim(mapping, email_claim=email_claim),
        email_verified_claims=_texts(
            config.get("email_verified_claims"), "email_verified_claims"
        )
        or DEFAULT_EMAIL_VERIFIED_CLAIMS,
        iss_parameter_supported=discovery.get(
            "authorization_response_iss_parameter_supported"
        )
        is True,
    )


async def load_profile(
    config: Mapping[str, object], *, discovery_ttl_seconds: int
) -> OidcProfile:
    discovery_url = _text(config.get("discovery_endpoint"))
    if discovery_url is None:
        raise OidcProviderError("No discovery endpoint configured")
    discovery = await fetch_discovery(discovery_url, ttl_seconds=discovery_ttl_seconds)
    return build_profile(config, discovery)
