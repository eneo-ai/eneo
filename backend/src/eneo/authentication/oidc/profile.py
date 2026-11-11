"""What Eneo uses of one OpenID provider: its stored config plus discovery.

A database federation config and the environment-only config have the same
keys. A key that is absent means today's behaviour, so existing configs need
no migration. Only protocol constants and security floors are fixed here.
"""

import asyncio
import ipaddress
import re
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import cast

import aiohttp
from yarl import URL

from eneo.authentication.auth_models import DEFAULT_EMAIL_VERIFIED_CLAIMS
from eneo.authentication.oidc import outbound
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
# The endpoints the backend sends a request to, by the name a refusal uses.
# userinfo is stored but never fetched, so it is not among them.
_FETCHED_ENDPOINTS = {"token endpoint": "token_endpoint", "JWKS URI": "jwks_uri"}
# A host name as allowed_endpoint_hosts lists it: no scheme, port, path or
# wildcard. An IP address may be listed too, IPv6 with or without brackets.
_HOST_NAME = re.compile(
    r"[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*"
)

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


class OidcProviderUnavailable(OidcProviderError):
    """The provider's discovery document cannot be read: unreachable, not
    answering 200, refused by the request rules, or not a JSON object."""


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
            raise OidcProviderUnavailable("Failed to fetch IdP configuration")
        # Marked before the fetch, so an outage costs one attempt per cooldown.
        entry.retry_at = time.monotonic() + DISCOVERY_RETRY_SECONDS
        entry.document = await download_discovery(url)
        entry.fetched_at = time.monotonic()
        entry.retry_at = 0.0
        return entry.document


async def download_discovery(url: str) -> dict[str, object]:
    """The provider's discovery document, fetched now, without the cache."""
    try:
        return await outbound.get_json(url)
    except outbound.OidcFetchError as exc:
        logger.error(
            "Failed to fetch OIDC discovery document",
            extra={
                "discovery_url": url,
                "reason": exc.reason,
                "http_status": exc.status,
            },
        )
        # The reason is fixed text: an operator may read it, a visitor never.
        raise OidcProviderUnavailable(
            f"Failed to fetch discovery document: {exc.reason}"
        ) from exc
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        logger.error(
            "Failed to fetch OIDC discovery document",
            extra={"discovery_url": url, "error_type": type(exc).__name__},
        )
        raise OidcProviderUnavailable("Failed to fetch IdP configuration") from exc


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


def _client(config: Mapping[str, object]) -> tuple[str, str]:
    client_id = _text(config.get("client_id"))
    client_secret = _text(config.get("client_secret"))
    if client_id is None or client_secret is None:
        raise OidcProviderError("The OIDC client is not configured")
    return client_id, client_secret


def _email_claim(config: Mapping[str, object]) -> str:
    return _mapped_claim(config.get("claims_mapping"), "email") or "email"


def _address(host: str) -> str | None:
    """An IP address in one written form, or None when the host is a name."""
    bare = host[1:-1] if host.startswith("[") and host.endswith("]") else host
    try:
        return ipaddress.ip_address(bare).compressed
    except ValueError:
        return None


def _host_key(host: str) -> str:
    """A host as the host rule compares it: an address in one form, a name
    lower-cased."""
    return _address(host) or host.lower()


def _url_host(url: str) -> str:
    """The host a request to ``url`` connects to, read as aiohttp reads it."""
    return _host_key(URL(url).raw_host or "")


def endpoint_host_names(hosts: object) -> tuple[str, ...]:
    """The other hosts the token and JWKS endpoints may be on, as the host
    rule compares them; refused unless a list of host names or addresses."""
    if hosts is None:
        return ()
    if not isinstance(hosts, list) or not all(
        isinstance(host, str)
        and (_address(host) is not None or _HOST_NAME.fullmatch(host.lower()))
        for host in cast(list[object], hosts)
    ):
        raise OidcProviderError(
            "allowed_endpoint_hosts must list host names or IP addresses, without scheme, port or path"
        )
    return tuple(_host_key(host) for host in cast(list[str], hosts))


def check_endpoint_hosts(
    discovery_url: str, endpoints: Mapping[str, str], allowed_hosts: Sequence[str]
) -> None:
    """Refuse an endpoint the backend must not send a request to.

    Each endpoint passes the request rules and is on the discovery host or on
    a host the operator listed: a discovery document, or a stored config, must
    not point the request carrying the code and the client secret, or the one
    fetching the keys that sign the ID token, at another host. The reason
    names the host, so the operator knows what to list.
    """
    hosts = {_url_host(discovery_url), *map(_host_key, allowed_hosts)}
    for name, url in endpoints.items():
        try:
            outbound.check_url(url)
        except outbound.OidcFetchError as exc:
            raise OidcProviderError(f"The {name}: {exc.reason}") from exc
        host = _url_host(url)
        if host not in hosts:
            raise OidcProviderError(
                f"The {name} is on {host}, which is neither the discovery host "
                "nor in allowed_endpoint_hosts"
            )


def _discovery_url(config: Mapping[str, object]) -> str | None:
    url = _text(config.get("discovery_endpoint"))
    if url is not None:
        try:
            outbound.check_url(url)
        except outbound.OidcFetchError as exc:
            raise OidcProviderError(f"The discovery endpoint: {exc.reason}") from exc
    return url


def check_config(config: Mapping[str, object]) -> None:
    """Refuse a federation config that no discovery document can make usable.

    These are the rules the config decides on its own, so a save that fetches
    nothing applies them; ``build_profile`` applies them first. A key that
    discovery decides at sign-in, such as the issuer of a config moved from
    the OIDC_* settings, may be absent here.
    """
    _client(config)
    subject_claim(config.get("claims_mapping"), email_claim=_email_claim(config))
    _texts(config.get("scopes"), "scopes")
    _texts(config.get("email_verified_claims"), "email_verified_claims")
    if config.get("signing_algorithms") is not None:
        _signing_algorithms(config, {})
    issuer = _text(config.get("issuer"))
    if issuer is not None and is_templated_issuer(issuer):
        raise OidcProviderError(TEMPLATED_ISSUER_GUIDANCE)
    hosts = endpoint_host_names(config.get("allowed_endpoint_hosts"))
    discovery_url = _discovery_url(config)
    stored = {
        name: url
        for name, key in _FETCHED_ENDPOINTS.items()
        if (url := _text(config.get(key))) is not None
    }
    if discovery_url is not None:
        check_endpoint_hosts(discovery_url, stored, hosts)


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

    check_config(config)
    client_id, client_secret = _client(config)
    mapping = config.get("claims_mapping")
    email_claim = _email_claim(config)
    issuer = resolve("issuer", "Failed to resolve the provider's issuer")
    if is_templated_issuer(issuer):
        raise OidcProviderError(TEMPLATED_ISSUER_GUIDANCE)
    discovery_url = _discovery_url(config)
    if discovery_url is None:
        raise OidcProviderError("No discovery endpoint configured")
    endpoints = {
        name: resolve(key, f"Failed to resolve {name}")
        for name, key in _FETCHED_ENDPOINTS.items()
    }
    check_endpoint_hosts(
        discovery_url,
        endpoints,
        endpoint_host_names(config.get("allowed_endpoint_hosts")),
    )
    return OidcProfile(
        issuer=issuer,
        client_id=client_id,
        client_secret=client_secret,
        authorization_endpoint=resolve(
            "authorization_endpoint", "Failed to resolve authorization endpoint"
        ),
        token_endpoint=endpoints["token endpoint"],
        token_endpoint_auth_method=_token_auth_method(config, discovery),
        jwks_uri=endpoints["JWKS URI"],
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
