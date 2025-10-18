from fastapi import Request, Security
from fastapi.security import APIKeyHeader
from intric.main.exceptions import AuthenticationException
from intric.main.logging import get_logger
from intric.main.config import get_settings

logger = get_logger(__name__)


SUPER_API_KEY_SCHEME = APIKeyHeader(name="X-API-Key", auto_error=False)


def _resolve_api_key(request: Request, provided: str | None) -> str | None:
    """Resolve API key from provided security scheme or configured header name."""
    if provided:
        return provided

    header_name = get_settings().api_key_header_name
    if header_name and header_name.lower() != "x-api-key":
        return request.headers.get(header_name)

    return provided


def authenticate_super_api_key(
    request: Request,
    api_key_header: str | None = Security(SUPER_API_KEY_SCHEME),
):
    """
    Authenticate using super admin API key.

    Uses Header() with explicit alias instead of Security(API_KEY_HEADER) to ensure
    the header name is resolved at request time, not at module import time.
    This is crucial for tests that override settings.
    """
    super_api_key = get_settings().intric_super_api_key

    resolved_key = _resolve_api_key(request, api_key_header)

    if resolved_key and super_api_key == resolved_key:
        return resolved_key
    else:
        raise AuthenticationException("Unauthorized")


def authenticate_super_duper_api_key(
    request: Request,
    api_key_header: str | None = Security(SUPER_API_KEY_SCHEME),
):
    """
    Authenticate using super duper admin API key.

    Uses Header() with explicit alias instead of Security(API_KEY_HEADER) to ensure
    the header name is resolved at request time, not at module import time.
    This is crucial for tests that override settings.
    """
    super_duper_api_key = get_settings().intric_super_duper_api_key

    resolved_key = _resolve_api_key(request, api_key_header)

    if resolved_key and super_duper_api_key == resolved_key:
        return resolved_key
    else:
        raise AuthenticationException("Unauthorized")
