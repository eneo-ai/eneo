from dataclasses import dataclass
from uuid import UUID

from typing import NoReturn

from fastapi import Depends, HTTPException, Request, Security, status

from intric.authentication.auth_factory import get_auth_service
from intric.authentication.auth_service import AuthService
from intric.authentication.api_key_resolver import ApiKeyValidationError, check_resource_permission
from intric.authentication.api_key_router_helpers import raise_api_key_http_error
from intric.authentication.auth_models import ApiKeyPermission
from intric.main.config import get_settings
from intric.main.container.container import Container
from intric.server.dependencies.auth_definitions import OAUTH2_SCHEME
from intric.server.dependencies.container import get_container
from intric.users.user import UserInDB
from intric.roles.permissions import Permission, validate_permission
from intric.main.exceptions import UnauthorizedException
from intric.main.logging import get_logger

logger = get_logger(__name__)


def _raise_api_key_http_error(
    exc: ApiKeyValidationError,
    *,
    request: Request | None = None,
) -> NoReturn:
    raise_api_key_http_error(exc, request=request)


async def _get_api_key_from_header(
    request: Request,
) -> str | None:
    """
    Dynamically get API key from the header specified in settings.
    """
    header_name = get_settings().api_key_header_name

    # Get the API key from the dynamically determined header
    api_key = request.headers.get(header_name)

    return api_key


async def get_current_active_user(
    request: Request,
    token: str = Security(OAUTH2_SCHEME),
    api_key: str = Security(_get_api_key_from_header),
    container: Container = Depends(get_container()),
) -> UserInDB:
    user_service = container.user_service()
    try:
        return await user_service.authenticate(token, api_key, request=request)
    except ApiKeyValidationError as exc:
        _raise_api_key_http_error(exc, request=request)


async def get_current_active_user_with_quota(
    request: Request,
    token: str = Security(OAUTH2_SCHEME),
    api_key: str = Security(_get_api_key_from_header),
    container: Container = Depends(get_container()),
) -> UserInDB:
    user_service = container.user_service()
    try:
        return await user_service.authenticate(
            token, api_key, with_quota_used=True, request=request
        )
    except ApiKeyValidationError as exc:
        _raise_api_key_http_error(exc, request=request)


async def get_user_from_token_or_assistant_api_key(
    id: UUID,
    request: Request,
    token: str = Security(OAUTH2_SCHEME),
    api_key: str = Security(_get_api_key_from_header),
    container: Container = Depends(get_container()),
):
    user_service = container.user_service()
    try:
        return await user_service.authenticate_with_assistant_api_key(
            api_key, token, assistant_id=id, request=request
        )
    except ApiKeyValidationError as exc:
        _raise_api_key_http_error(exc, request=request)


async def get_user_from_token_or_assistant_api_key_without_assistant_id(
    request: Request,
    token: str = Security(OAUTH2_SCHEME),
    api_key: str = Security(_get_api_key_from_header),
    container: Container = Depends(get_container()),
):
    user_service = container.user_service()
    try:
        return await user_service.authenticate_with_assistant_api_key(
            api_key, token, request=request
        )
    except ApiKeyValidationError as exc:
        _raise_api_key_http_error(exc, request=request)


def get_api_key(hashed: bool = True):
    async def _get_api_key(
        api_key: str = Security(_get_api_key_from_header),
        auth_service: AuthService = Depends(get_auth_service),
    ):
        return await auth_service.get_api_key(api_key, hash_key=hashed)

    return _get_api_key


def require_permission(permission: Permission):
    async def _dep(user: UserInDB = Depends(get_current_active_user)):
        try:
            validate_permission(user, permission)
        except UnauthorizedException as e:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))

    return _dep


def get_api_key_context(request: Request):
    return getattr(request.state, "api_key", None)


def require_api_key_permission(required: ApiKeyPermission):
    """Endpoint-level guard: stash required API key permission for post-auth check.

    Like ``require_resource_permission_for_method``, this dependency runs
    BEFORE authentication sets ``request.state.api_key``.  It stores the
    required permission level on ``request.state``, and the actual enforcement
    happens inside ``_resolve_api_key`` (user_service) after authentication.

    Bearer-token requests are unaffected — no API key state means no check.
    NOT gated by the feature flag — management guards always enforce.
    """

    async def _api_key_permission_dep(request: Request) -> None:
        request.state._required_api_key_permission = required.value

    return _api_key_permission_dep


ASSISTANTS_READ_OVERRIDES: frozenset[str] = frozenset({
    "estimate_tokens",
    "ask_assistant",
    "ask_followup",
    "leave_feedback",
})
KNOWLEDGE_READ_OVERRIDES: frozenset[str] = frozenset({"run_semantic_search"})

CONVERSATIONS_READ_OVERRIDES: frozenset[str] = frozenset({
    "chat",
    "leave_feedback",
})

APPS_READ_OVERRIDES: frozenset[str] = frozenset({
    "run_service",
    "run_app",
})

FILES_READ_OVERRIDES: frozenset[str] = frozenset({
    "generate_signed_url",
})


def require_resource_permission_for_method(
    resource_type: str,
    read_override_endpoints: frozenset[str] | None = None,
):
    """Router-level dependency: stores method→permission config for post-auth check.

    The actual permission check runs in ``_resolve_api_key`` (user_service)
    after authentication has set ``request.state.api_key``.  Router-level
    dependencies execute *before* route-level ``Depends()``, so we cannot
    inspect ``request.state.api_key`` here.
    """

    async def _resource_permission_dep(request: Request) -> None:
        request.state._resource_perm_config = {
            "resource_type": resource_type,
            "read_override_endpoints": read_override_endpoints,
        }

    return _resource_permission_dep


def require_api_key_scope_check(
    resource_type: str,
    path_param: str | None = "id",
    self_filtering: bool = False,
):
    """Router-level dependency: stores scope check config for post-auth enforcement.

    The actual scope check runs in ``_resolve_api_key`` (user_service) after
    authentication has set ``request.state.api_key``.

    Args:
        resource_type: The type of resource this route manages (e.g. "space",
            "assistant", "app", "admin"). Used to determine scope compatibility.
        path_param: URL path parameter holding the resource ID (e.g. "id",
            "session_id"). None means no path-level check (list endpoints or
            resources without extractable IDs).
        self_filtering: When True, the endpoint performs deterministic scope
            filtering (e.g. requires assistant_id param). Exempts from
            strict-mode blanket denial of list endpoints.
    """

    async def _scope_check_dep(request: Request) -> None:
        request.state._scope_check_config = {
            "resource_type": resource_type,
            "path_param": path_param,
            "self_filtering": self_filtering,
        }

    return _scope_check_dep


def require_resource_permission(resource_type: str, required: str):
    """Dependency factory for fine-grained per-resource permission checks.

    Fail-closed: if an API key header is present but request.state.api_key
    was not set by the auth dependency, raise 500 to surface a dependency
    ordering misconfiguration rather than silently allowing the request.
    """

    async def _resource_check_dep(request: Request) -> None:
        key = getattr(request.state, "api_key", None)
        if key is None:
            # Check if an API key header was provided but auth didn't run
            header_name = get_settings().api_key_header_name
            if request.headers.get(header_name):
                logger.error(
                    "API key header present but request.state.api_key missing — "
                    "auth dependency may not have run before resource permission guard",
                    extra={"resource_type": resource_type, "required": required},
                )
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail={
                        "code": "server_configuration_error",
                        "message": "Authentication state missing.",
                    },
                )
            return
        try:
            check_resource_permission(key, resource_type, required)
        except ApiKeyValidationError as exc:
            _raise_api_key_http_error(exc, request=request)

    return _resource_check_dep


def require_tenant_scope_for_delete():
    """Block DELETE requests for non-tenant-scoped API keys.

    Files are user-scoped (no space_id column). GET/POST are safe for scoped keys,
    but DELETE could affect files attached to conversations in other spaces.

    Uses the deferred-enforcement pattern: stashes a marker on ``request.state``
    so the actual check runs inside ``_resolve_api_key`` (after auth has populated
    ``api_key_scope_type``).  Router-level dependencies execute *before* endpoint
    dependencies, so we cannot inspect auth state here.
    """

    async def _stash(request: Request) -> None:
        if request.method == "DELETE":
            request.state._require_tenant_scope_for_delete = True

    return _stash


@dataclass(frozen=True, slots=True)
class ScopeFilter:
    """Immutable scope filter extracted from API key state at the router boundary.

    Passed to service/repo layers as an optional parameter for query-time filtering.
    None fields mean "no constraint from this scope dimension".
    """

    scope_type: str | None = None
    space_id: UUID | None = None
    assistant_id: UUID | None = None


def get_scope_filter(request: Request) -> ScopeFilter:
    """Extract scope filter from request state for scoped API keys.

    Returns an empty ScopeFilter for tenant-scoped keys, bearer auth, or when
    scope enforcement is disabled via env/tenant kill-switch.
    Called at the router boundary; the result is passed to service methods.
    """
    if getattr(request.state, "scope_enforcement_enabled", True) is False:
        return ScopeFilter()

    scope_type = getattr(request.state, "api_key_scope_type", None)
    scope_id = getattr(request.state, "api_key_scope_id", None)

    if scope_type is None or scope_id is None:
        return ScopeFilter()

    scope_type_str = scope_type.value if hasattr(scope_type, "value") else str(scope_type)

    if scope_type_str == "tenant":
        return ScopeFilter(scope_type=scope_type_str)
    elif scope_type_str == "space":
        return ScopeFilter(scope_type=scope_type_str, space_id=scope_id)
    elif scope_type_str == "assistant":
        return ScopeFilter(
            scope_type=scope_type_str, assistant_id=scope_id
        )
    else:
        return ScopeFilter(scope_type=scope_type_str)
