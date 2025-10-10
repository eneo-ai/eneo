from typing import Annotated

from fastapi import Header, WebSocketException, status
from fastapi.security import OAuth2PasswordBearer
from fastapi.security.api_key import APIKeyHeader

from intric.main.config import get_settings

def _get_oauth2_scheme():
    """Lazily create OAuth2 scheme with current settings."""
    login_endpoint = f"{get_settings().api_prefix}/users/login/token/"
    return OAuth2PasswordBearer(tokenUrl=login_endpoint, auto_error=False)

def _get_api_key_header():
    """Lazily create API key header with current settings."""
    return APIKeyHeader(name=get_settings().api_key_header_name, auto_error=False)

# Create singleton instances that will use settings at import time for production,
# but can be overridden for tests by reimporting after settings change
OAUTH2_SCHEME = _get_oauth2_scheme()
API_KEY_HEADER = _get_api_key_header()

AUTH_PREFIX = "auth_"


async def get_token_from_websocket_header(
    sec_websocket_protocol: Annotated[str | None, Header()] = None
):
    if sec_websocket_protocol is None:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)

    for header in sec_websocket_protocol.split(', '):
        if header.startswith(AUTH_PREFIX):
            return header[len(AUTH_PREFIX) :]

    # If there is no Bearer token in the header, raise
    raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)
