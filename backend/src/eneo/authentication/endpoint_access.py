"""Explicit endpoint admission, shared by authentication and route validation.

Admission is separate from object authorization: admitting an authenticated
caller never grants access to another user's resource or another tenant.
Those checks remain in the domain services that load and change the objects.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, TypeVar, cast

from fastapi import HTTPException
from fastapi.dependencies.models import Dependant
from starlette.requests import HTTPConnection

from eneo.roles.permissions import Permission, validate_permission

if TYPE_CHECKING:
    from eneo.users.user import UserInDB

_Endpoint = TypeVar("_Endpoint", bound=Callable[..., object])


class Authentication(str, Enum):
    USER = "user_token_or_api_key"
    SESSION = "user_session"
    ASSISTANT = "user_token_or_assistant_api_key"
    API_KEY = "api_key"
    SYSADMIN = "super_api_key"
    SCIM = "tenant_scim_token"
    MODULE = "module_user_token_and_service_key"
    SIGNED_URL = "signed_file_token"
    WEBSOCKET = "websocket_user_token"
    PUBLIC = "public"


class Authorization(str, Enum):
    # An explicit grant of endpoint admission to authenticated users. The
    # endpoint's service must still enforce object ownership/membership.
    AUTHENTICATED = "authenticated_caller"
    SYSADMIN = "deployment_administrator"
    SCIM = "token_tenant_provisioning"
    MODULE = "assigned_module_user"
    SIGNED_URL = "token_file_and_tenant"
    PUBLIC = "public"


_USER_AUTHENTICATION = frozenset(
    {
        Authentication.USER,
        Authentication.SESSION,
        Authentication.ASSISTANT,
        Authentication.API_KEY,
        Authentication.WEBSOCKET,
    }
)
_SPECIAL_AUTHORIZATION = {
    Authentication.SYSADMIN: Authorization.SYSADMIN,
    Authentication.SCIM: Authorization.SCIM,
    Authentication.MODULE: Authorization.MODULE,
    Authentication.SIGNED_URL: Authorization.SIGNED_URL,
    Authentication.PUBLIC: Authorization.PUBLIC,
}


@dataclass(frozen=True)
class EndpointAccess:
    authentication: Authentication
    authorization: Permission | Authorization
    reason: str

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise ValueError("Endpoint access requires a reason for the grant")
        if self.authentication in _USER_AUTHENTICATION:
            if not (
                isinstance(self.authorization, Permission)
                or self.authorization is Authorization.AUTHENTICATED
            ):
                raise ValueError("User authentication requires user authorization")
        elif _SPECIAL_AUTHORIZATION.get(self.authentication) is not self.authorization:
            raise ValueError("Authentication and authorization policies do not match")


def endpoint_access(
    *,
    authentication: Authentication,
    authorization: Permission | Authorization,
    reason: str,
) -> Callable[[_Endpoint], _Endpoint]:
    """Declare both decisions on an endpoint, immediately below @router.*.

    No defaults and no router-wide inheritance: adding an endpoint requires a
    new decision. The decorator preserves the callable/signature for FastAPI.
    """
    policy = EndpointAccess(authentication, authorization, reason)

    def declare(endpoint: _Endpoint) -> _Endpoint:
        if access_for(endpoint) is not None:
            raise ValueError("Endpoint already has an access policy")
        setattr(endpoint, "__eneo_endpoint_access__", policy)
        return endpoint

    return declare


def access_for(endpoint: object) -> EndpointAccess | None:
    policy = getattr(endpoint, "__eneo_endpoint_access__", None)
    return policy if isinstance(policy, EndpointAccess) else None


def authenticates(
    authentication: Authentication,
) -> Callable[[_Endpoint], _Endpoint]:
    """Identify a real authentication dependency, without wrapping its work."""

    def declare(dependency: _Endpoint) -> _Endpoint:
        setattr(dependency, "__eneo_authentication__", authentication)
        return dependency

    return declare


def authentication_dependencies(dependant: Dependant) -> set[Authentication]:
    schemes: set[Authentication] = set()
    scheme = getattr(dependant.call, "__eneo_authentication__", None)
    if isinstance(scheme, Authentication):
        schemes.add(scheme)
    for dependency in dependant.dependencies:
        schemes.update(authentication_dependencies(dependency))
    return schemes


def has_authentication(policy: EndpointAccess, dependant: Dependant | None) -> bool:
    if policy.authentication is Authentication.PUBLIC:
        return True
    if dependant is None:
        return False
    required = policy.authentication
    if required in (Authentication.SESSION, Authentication.API_KEY):
        required = Authentication.USER
    return required in authentication_dependencies(dependant)


def authorize_user(connection: HTTPConnection | None, user: "UserInDB") -> None:
    """Enforce admission after canonical authentication, before domain work.

    Internal worker calls have no HTTP connection. Their existing domain
    authorization is unaffected; this contract belongs to exposed endpoints.
    """
    if connection is None:
        return
    endpoint = connection.scope.get("endpoint")
    if endpoint is None:
        # Authentication is also used to verify credentials before routing,
        # e.g. in the module broker. Route admission has a separate guard.
        return
    policy = access_for(endpoint)
    if policy is None:
        raise HTTPException(403, "Endpoint access has not been declared")
    if (
        policy.authentication is Authentication.SESSION
        and user.active_api_key is not None
    ):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "session_auth_required",
                "message": "This endpoint requires a session token.",
            },
        )
    if policy.authentication is Authentication.API_KEY and user.active_api_key is None:
        raise HTTPException(403, "This endpoint requires an API key")
    if isinstance(policy.authorization, Permission):
        validate_permission(user, policy.authorization)


async def require_endpoint_access(connection: HTTPConnection) -> None:
    """Check admission wiring on every request, before endpoint dependencies.

    FastAPI 0.138 carries inherited dependencies in an effective context. Keep
    this adapter covered by the nested-router HTTP test when upgrading FastAPI.
    No credentials are resolved here: the existing dependency still owns that
    work and its ordering relative to API-key scope/permission dependencies.
    """
    policy = access_for(connection.scope.get("endpoint"))
    if policy is None:
        raise HTTPException(403, "Endpoint access has not been declared")
    # FastAPI currently has no public accessor for the matched effective
    # context. Isolate this version-specific scope layout here; the inherited
    # dependency tests must fail closed if it changes during an upgrade.
    fastapi_scope: object = connection.scope.get("fastapi")
    effective = (
        cast(Mapping[str, object], fastapi_scope).get("effective_route_context")
        if isinstance(fastapi_scope, Mapping)
        else None
    )
    dependant = getattr(effective, "dependant", None)
    if not isinstance(dependant, Dependant):
        dependant = getattr(connection.scope.get("route"), "dependant", None)
    if not has_authentication(
        policy, dependant if isinstance(dependant, Dependant) else None
    ):
        raise HTTPException(403, "Endpoint authentication has not been configured")
