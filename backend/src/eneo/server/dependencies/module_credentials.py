"""Module dual credentials: a service sk_ key plus the module user's token.

Kept apart from ``module_auth.py`` so the request container (``container.py``)
can use it without an import cycle: ``module_auth.py`` builds dependencies on
top of ``get_container``.
"""

import jwt
from fastapi import Request

from eneo.main.container.container import Container
from eneo.main.exceptions import AuthenticationException
from eneo.modules.module_auth import MODULE_AUDIENCE_PREFIX, ModuleRequestPrincipal


def claimed_module_key(access_token: str) -> str | None:
    """Return the module a Bearer token claims to belong to, without trusting it.

    The value only selects the authentication path. The broker then verifies
    the signature, the audience for exactly this module, the key registration,
    the tenant and the user before anything is authorised.
    """
    try:
        claims = jwt.decode(access_token, options={"verify_signature": False})
    except jwt.PyJWTError:
        return None
    audience = claims.get("aud")
    if not isinstance(audience, str) or not audience.startswith(MODULE_AUDIENCE_PREFIX):
        return None
    return audience.removeprefix(MODULE_AUDIENCE_PREFIX) or None


async def authenticate_module_principal(
    *,
    module_key: str,
    access_token: str,
    api_key_secret: str,
    request: Request,
    container: Container,
) -> ModuleRequestPrincipal:
    """Authenticate the service key with its route guards, then the module user.

    Raises ``ApiKeyValidationError`` for a key the resolver refuses; callers
    translate it into their HTTP error the same way as for any API key.
    """
    service_user = await container.user_service().authenticate(
        api_key=api_key_secret,
        request=request,
    )
    resolved_key = service_user.active_api_key
    if resolved_key is None:
        raise AuthenticationException("Module API key authentication failed.")

    return await container.module_auth_broker().authenticate_resource_request(
        module_key=module_key,
        access_token=access_token,
        api_key=resolved_key,
    )
