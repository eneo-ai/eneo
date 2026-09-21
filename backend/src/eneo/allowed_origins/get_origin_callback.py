import asyncio
import time
from collections.abc import Iterable
from urllib.parse import urlparse

from starlette.datastructures import URL, Headers

from eneo.allowed_origins.allowed_origin_repo import AllowedOriginRepository
from eneo.allowed_origins.origin_matching import origin_matches_pattern
from eneo.authentication.api_key_resolver import (
    ApiKeyAuthResolver,
    ApiKeyValidationError,
)
from eneo.authentication.api_key_v2_repo import ApiKeysV2Repository
from eneo.authentication.auth_models import (
    ApiKeyState,
    ApiKeyType,
    compute_effective_state,
)
from eneo.database.database import sessionmanager
from eneo.main.config import get_settings
from eneo.main.logging import get_logger

logger = get_logger(__name__)

_PREFLIGHT_KEY_ORIGIN_CACHE_TTL_SECONDS = 30.0
_preflight_key_origin_patterns: tuple[str, ...] = ()
_preflight_key_origin_cache_expires_at = 0.0
_preflight_key_origin_cache_lock = asyncio.Lock()


def _matches(origin: str, patterns: Iterable[str]) -> bool:
    return any(origin_matches_pattern(origin, pattern) for pattern in patterns)


def _is_same_origin(origin: str, request_url: URL) -> bool:
    try:
        origin_url = URL(origin)
        default_port = {"http": 80, "https": 443}.get(request_url.scheme)
        return (
            default_port is not None
            and origin_url.scheme == request_url.scheme
            and origin_url.hostname is not None
            and origin_url.hostname == request_url.hostname
            and (origin_url.port if origin_url.port is not None else default_port)
            == (request_url.port if request_url.port is not None else default_port)
            and origin_url.username is None
            and not (origin_url.path or origin_url.query or origin_url.fragment)
        )
    except ValueError:
        return False


def _preflight_requests_api_key(headers: Headers, header_name: str) -> bool:
    if "access-control-request-method" not in headers:
        return False
    requested_headers = headers.get("access-control-request-headers", "")
    requested = {
        value.strip().lower() for value in requested_headers.split(",") if value.strip()
    }
    normalized_header_name = header_name.lower()
    if normalized_header_name not in requested:
        return False
    return normalized_header_name == "authorization" or "authorization" not in requested


def _has_bearer_token(headers: Headers) -> bool:
    authorization = headers.get("authorization", "")
    scheme, separator, credential = authorization.partition(" ")
    return bool(separator) and scheme.lower() == "bearer" and bool(credential.strip())


async def _get_preflight_key_origin_patterns(
    repo: ApiKeysV2Repository,
) -> tuple[str, ...]:
    global _preflight_key_origin_patterns
    global _preflight_key_origin_cache_expires_at

    now = time.monotonic()
    if now < _preflight_key_origin_cache_expires_at:
        return _preflight_key_origin_patterns

    async with _preflight_key_origin_cache_lock:
        now = time.monotonic()
        if now < _preflight_key_origin_cache_expires_at:
            return _preflight_key_origin_patterns

        patterns = await repo.list_relaxed_tenant_public_key_origin_patterns()
        _preflight_key_origin_patterns = tuple(patterns)
        _preflight_key_origin_cache_expires_at = (
            now + _PREFLIGHT_KEY_ORIGIN_CACHE_TTL_SECONDS
        )
        return _preflight_key_origin_patterns


async def get_origin(
    origin: str,
    request_headers: Headers | None = None,
    is_preflight: bool = False,
    request_url: URL | None = None,
) -> bool:
    parsed = urlparse(origin)
    if parsed.hostname in ("localhost", "127.0.0.1", "::1"):
        return True

    headers = request_headers or Headers()
    settings = get_settings()
    # Password and bearer requests to the API itself do not require CORS opt-in.
    # API-key requests still enforce their key and tenant origin policies.
    if (
        not is_preflight
        and request_url is not None
        and not headers.get(settings.api_key_header_name)
        and _is_same_origin(origin, request_url)
    ):
        return True

    async with sessionmanager.session() as session, session.begin():
        repo = AllowedOriginRepository(session)
        allowed_origins = await repo.get_all()
        matches = _matches(origin, [entry.url for entry in allowed_origins])
        api_key_repo = ApiKeysV2Repository(session)

        # Browsers do not include the API-key value in a CORS preflight.
        # A preflight may therefore use the global tenant allowlist or origins
        # from active public keys on relaxed tenants. The actual request is
        # checked against its specific key below and by API-key authentication.
        if is_preflight and _preflight_requests_api_key(
            headers, settings.api_key_header_name
        ):
            if not matches:
                patterns = await _get_preflight_key_origin_patterns(api_key_repo)
                matches = _matches(origin, patterns)
        else:
            plain_key = (
                None
                if _has_bearer_token(headers)
                else headers.get(settings.api_key_header_name)
            )
            if plain_key:
                try:
                    resolved = await ApiKeyAuthResolver(api_key_repo).resolve(plain_key)
                except ApiKeyValidationError:
                    resolved = None

                if resolved is not None:
                    key = resolved.key
                    tenant_origins = await repo.get_by_tenant(key.tenant_id)
                    tenant_matches = _matches(
                        origin, [entry.url for entry in tenant_origins]
                    )
                    require_tenant_origin = (
                        await api_key_repo.tenant_requires_allowed_origin(key.tenant_id)
                    )
                    state = compute_effective_state(
                        revoked_at=key.revoked_at,
                        suspended_at=key.suspended_at,
                        expires_at=key.expires_at,
                        rotation_grace_until=key.rotation_grace_until,
                    )
                    key_matches = (
                        ApiKeyType(key.key_type) == ApiKeyType.PK
                        and state == ApiKeyState.ACTIVE
                        and bool(key.allowed_origins)
                        and _matches(origin, key.allowed_origins or [])
                    )
                    matches = tenant_matches or (
                        not require_tenant_origin and key_matches
                    )

        logger.debug(
            f"Origin attempted to be resolved from database, success = {matches}"
        )

        return matches
