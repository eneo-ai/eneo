from urllib.parse import urlparse

from starlette.datastructures import Headers

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


def _matches(origin: str, patterns: list[str]) -> bool:
    return any(origin_matches_pattern(origin, pattern) for pattern in patterns)


def _preflight_requests_api_key(headers: Headers, header_name: str) -> bool:
    if "access-control-request-method" not in headers:
        return False
    requested = headers.get("access-control-request-headers", "")
    return header_name.lower() in {
        value.strip().lower() for value in requested.split(",") if value.strip()
    }


async def get_origin(origin: str, request_headers: Headers | None = None) -> bool:
    parsed = urlparse(origin)
    if parsed.hostname in ("localhost", "127.0.0.1", "::1"):
        return True

    headers = request_headers or Headers()
    settings = get_settings()
    async with sessionmanager.session() as session, session.begin():
        repo = AllowedOriginRepository(session)
        allowed_origins = await repo.get_all()
        matches = _matches(origin, [entry.url for entry in allowed_origins])
        api_key_repo = ApiKeysV2Repository(session)

        # Browsers do not include the API-key value in a CORS preflight.
        # A preflight may therefore use the global tenant allowlist or origins
        # from active public keys on relaxed tenants. The actual request is
        # checked against its specific key below and by API-key authentication.
        if _preflight_requests_api_key(headers, settings.api_key_header_name):
            if not matches:
                patterns = (
                    await api_key_repo.list_relaxed_tenant_public_key_origin_patterns()
                )
                matches = _matches(origin, patterns)
        else:
            plain_key = headers.get(settings.api_key_header_name)
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
