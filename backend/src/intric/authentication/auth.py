from fastapi import Header
from intric.main.exceptions import AuthenticationException
from intric.main.logging import get_logger
from intric.main.config import get_settings

logger = get_logger(__name__)


def authenticate_super_api_key(api_key_header: str | None = Header(None, alias="X-API-Key")):
    """
    Authenticate using super admin API key.

    Uses Header() with explicit alias instead of Security(API_KEY_HEADER) to ensure
    the header name is resolved at request time, not at module import time.
    This is crucial for tests that override settings.
    """
    super_api_key = get_settings().intric_super_api_key

    if api_key_header and super_api_key == api_key_header:
        return api_key_header
    else:
        raise AuthenticationException("Unauthorized")


def authenticate_super_duper_api_key(api_key_header: str | None = Header(None, alias="X-API-Key")):
    """
    Authenticate using super duper admin API key.

    Uses Header() with explicit alias instead of Security(API_KEY_HEADER) to ensure
    the header name is resolved at request time, not at module import time.
    This is crucial for tests that override settings.
    """
    super_duper_api_key = get_settings().intric_super_duper_api_key

    if api_key_header and super_duper_api_key == api_key_header:
        return api_key_header
    else:
        raise AuthenticationException("Unauthorized")