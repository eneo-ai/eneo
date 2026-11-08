import traceback
from typing import Annotated, Optional, Protocol, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.security.utils import get_authorization_scheme_param
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

# Audit logging - module level imports for consistency
from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.audit.domain.outcome import Outcome
from eneo.authentication import auth_dependencies
from eneo.authentication.auth_dependencies import (
    require_api_key_permission,
    require_api_key_scope_check,
    require_user_identity,
)
from eneo.authentication.auth_models import (
    AccessToken,
    ApiKeyPermission,
)
from eneo.authentication.endpoint_access import (
    Authentication,
    Authorization,
    endpoint_access,
)
from eneo.authentication.login_attempts import (
    LoginAttempt,
    clear_login_attempts,
    count_login_attempt,
)
from eneo.main.container.container import Container
from eneo.main.exceptions import AuthenticationException
from eneo.main.logging import get_logger, redact_values
from eneo.main.models import CursorPaginatedResponse
from eneo.main.request_context import ensure_correlation_id, get_request_context
from eneo.redis.rate_limit import (
    RateLimitConfig,
    RateLimitExceededError,
    RateLimitServiceUnavailableError,
    enforce_rate_limit,
    raise_rate_limited,
)
from eneo.roles.permissions import Permission
from eneo.server.dependencies.container import get_container
from eneo.server.exception_handlers import has_registered_handler
from eneo.server.protocol import responses
from eneo.tenants.tenant import TenantPublic
from eneo.users.password import (
    LOCAL_PASSWORD_POLICY,
    LocalPasswordPolicy,
    PasswordChangeError,
)
from eneo.users.password_lifecycle import password_status_for
from eneo.users.user import (
    EneoPasswordChangeCapabilityPublic,
    ExternalPasswordChangeCapabilityPublic,
    PasswordChangeRequest,
    PropUserInvite,
    PropUserUpdate,
    UserAdminView,
    UserInDB,
    UserLogin,
    UserProvision,
    UserPublic,
    UserSparse,
    UserUpdatePublic,
)

logger = get_logger(__name__)

router = APIRouter()
users_admin_router = APIRouter()

_PASSWORD_CHANGE_RATE_LIMIT = RateLimitConfig(
    max_requests=5,
    window_seconds=15 * 60,
    key_prefix="rate_limit:password_change",
)


class _ProvisioningService(Protocol):
    """Minimal protocol for the user provisioning service (container.user_creation_service)."""

    async def provision_user(self, *, access_token: str) -> None: ...


# ``UserLogin`` validates the OAuth2 form, whose field for the email is
# ``username``. Report locations the way FastAPI reports the form itself.
_LOGIN_FORM_FIELDS = {"email": "username"}


def _login_form_location(loc: tuple[int | str, ...]) -> tuple[int | str, ...]:
    if not loc:
        return ("body",)
    first, *rest = loc
    return ("body", _LOGIN_FORM_FIELDS.get(str(first), first), *rest)


async def login_with_password(
    *, request: Request, email: str, password: str, container: Container
) -> AccessToken:
    """The password login flow: validation, the failed-attempt limiter, logging
    and the public error contract (401 invalid_credentials with
    attempts_remaining, 429 too_many_login_attempts with retry_after_seconds and
    Retry-After, 403 account states, 422 form locations, login_unavailable).
    Every password login endpoint calls it."""

    correlation_id = ensure_correlation_id()
    # Trusted-proxy-aware, resolved once by RequestContextMiddleware; a raw
    # X-Forwarded-For is whatever the caller wrote.
    source_ip = cast(str | None, get_request_context().get("ip_address"))

    # The shared request-validation handler owns the public 422 contract.
    # Do not pass credentials into its exception or into structured logs.
    try:
        UserLogin(email=email, password=password)
    except ValidationError as e:
        errors = e.errors(include_input=False, include_context=False, include_url=False)
        logger.warning(
            "Login failed: validation error",
            extra={
                "correlation_id": correlation_id,
                "auth_method": "password",
                "source_ip": source_ip,
                "validation_types": [error["type"] for error in errors],
            },
        )
        raise RequestValidationError(
            [{**error, "loc": _login_form_location(error["loc"])} for error in errors]
        ) from None

    logger.info(
        "Username/password login initiated",
        extra={
            "correlation_id": correlation_id,
            "auth_method": "password",
            "email": email,
            "source_ip": source_ip,
        },
    )

    redis_client = container.redis_client()
    attempt: LoginAttempt | None
    try:
        attempt = await count_login_attempt(redis_client, email)
    except RateLimitServiceUnavailableError:
        # Without Redis the limit cannot be kept; logging in must still work.
        logger.warning(
            "Login attempt limiter unavailable; attempt not counted",
            extra={"correlation_id": correlation_id, "auth_method": "password"},
        )
        attempt = None

    if attempt is not None and not attempt.allowed:
        logger.warning(
            "Login refused: too many failed attempts",
            extra={
                "correlation_id": correlation_id,
                "auth_method": "password",
                "email": email,
                "source_ip": source_ip,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "too_many_login_attempts",
                "message": "Too many failed login attempts. Try again later.",
                "attempts_remaining": 0,
                "retry_after_seconds": attempt.retry_after_seconds,
            },
            headers={
                "X-Correlation-ID": correlation_id,
                "Retry-After": str(attempt.retry_after_seconds),
            },
        )

    # Authenticate user
    service = container.user_service()

    try:
        result = await service.login(email, password, correlation_id, source_ip)

        if attempt is not None:
            try:
                await clear_login_attempts(redis_client, email)
            except RateLimitServiceUnavailableError:
                logger.warning(
                    "Login attempt limiter unavailable; earlier attempts not cleared",
                    extra={"correlation_id": correlation_id},
                )

        # Log successful authentication
        logger.info(
            "Username/password login successful",
            extra={
                "correlation_id": correlation_id,
                "auth_method": "password",
                "email": email,
                "source_ip": source_ip,
            },
        )

        return result

    except AuthenticationException:
        # Expected authentication failure - use warning level (not error)
        logger.warning(
            "Login failed: invalid credentials",
            extra={
                "correlation_id": correlation_id,
                "auth_method": "password",
                "email": email,
                "source_ip": source_ip,
            },
        )
        detail: dict[str, object] = {
            "code": "invalid_credentials",
            "message": "Invalid credentials",  # Generic message for security
        }
        if attempt is not None:
            detail["attempts_remaining"] = attempt.remaining
            if attempt.remaining == 0:
                detail["retry_after_seconds"] = attempt.retry_after_seconds
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={"X-Correlation-ID": correlation_id},
        ) from None

    except Exception as e:
        if has_registered_handler(request.app, e):
            # A denial with a canonical response (inactive user, suspended
            # organisation, ...). The password was verified before it was
            # raised, so keep the origin on record.
            logger.warning(
                "Login refused after credential verification",
                extra={
                    "correlation_id": correlation_id,
                    "auth_method": "password",
                    "email": email,
                    "source_ip": source_ip,
                    "error_type": type(e).__name__,
                },
            )
            raise

        # Exception values and chained tracebacks may quote the submitted
        # password; redact it rather than drop the diagnostics.
        redacted_traceback = redact_values(
            "".join(traceback.format_exception(e)), password
        )
        logger.error(
            # Plain-text logging only renders the message, not extra fields.
            "Login failed: unexpected error\n%s",
            redacted_traceback,
            extra={
                "correlation_id": correlation_id,
                "auth_method": "password",
                "email": email,
                "source_ip": source_ip,
                "error_type": type(e).__name__,
                "error": redact_values(str(e), password),
                "traceback": redacted_traceback,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "login_unavailable",
                "message": "An unexpected error occurred during login",
            },
            headers={"X-Correlation-ID": correlation_id},
        ) from None


@router.post(
    "/login/token/",
    response_model=AccessToken,
    name="Login",
    description="Authenticate with email and password (OAuth2 password flow).",
    responses=responses.get_responses([401, 403, 429, 500]),
)
@endpoint_access(
    authentication=Authentication.PUBLIC,
    authorization=Authorization.PUBLIC,
    reason="Login or provisioning entry point; the authentication service validates supplied credentials before granting a session.",
)
async def user_login_with_email_and_password(
    request: Request,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends(OAuth2PasswordRequestForm)],
    # The session commits before the token leaves, so its first request is
    # admitted.
    container: Annotated[
        Container, Depends(get_container(transaction_scope="function"))
    ],
) -> AccessToken:
    """OAuth2 Login with comprehensive error handling and logging"""
    token = await login_with_password(
        request=request,
        email=form_data.username,
        password=form_data.password,
        container=container,
    )
    # The token names its session, so signing out (POST /users/logout/)
    # ends every copy of it.
    return AccessToken(
        access_token=await container.browser_session_service().start(
            token.access_token
        ),
        token_type=token.token_type,
    )


@router.post(
    "/logout/",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
    name="Sign out",
    description=(
        "End the Eneo session the Bearer token names: a copy of the token "
        "stops working at once. 204 means no session remains that this token "
        "can use, also when it named none to end: no or an invalid token, a "
        "token without a session, a provider token, or one expired for longer "
        "than it was valid. A token without a session is not revoked and works "
        "until it expires. 503 "
        "`sign_out_unavailable` means the end is not confirmed: the session "
        "may already have ended, or the token may still work. Keep the token "
        "and retry; once the session has ended, a retry answers 204."
    ),
    responses=responses.get_responses([503]),
)
@endpoint_access(
    authentication=Authentication.PUBLIC,
    authorization=Authorization.PUBLIC,
    reason="Sign-out must also end a session whose token no longer authenticates (expired, restricted account); it reads only the Authorization header, never a cookie, so another site cannot sign a browser out.",
)
async def sign_out(
    request: Request,
    # The deletion commits before the response says signed out.
    container: Annotated[Container, Depends(get_container(with_transaction=False))],
) -> Response:
    scheme, token = get_authorization_scheme_param(request.headers.get("Authorization"))
    if scheme.lower() == "bearer" and token:
        await container.browser_session_service().revoke(token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/",
    response_model=CursorPaginatedResponse[UserSparse],
    description=(
        "List users in the current tenant. Available to authenticated tenant "
        "members; API keys require admin scope and permission."
    ),
    responses=responses.get_responses([403]),
    dependencies=[
        Depends(require_api_key_scope_check(resource_type="admin", path_param=None)),
        Depends(require_api_key_permission(ApiKeyPermission.ADMIN)),
    ],
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason="Tenant members may access their profile and tenant directory; identity guards restrict personal operations.",
)
async def get_tenant_users(
    container: Annotated[Container, Depends(get_container(with_user=True))],
    email: Annotated[Optional[str], Query(description="Email of user")] = None,
    limit: Annotated[
        Optional[int], Query(description="Users per page", ge=1, le=100)
    ] = None,
    cursor: Annotated[Optional[str], Query(description="Current cursor")] = None,
    previous: Annotated[
        Optional[bool], Query(description="Show previous page")
    ] = False,
):
    """List tenant members for member/group pickers.

    Returns `UserSparse` (id, email, username, timestamps) — a strict subset
    of the information any authenticated tenant member can retrieve via
    Microsoft 365 / Outlook GAL. Tenant-scoped at the repo layer; mutations
    on /users/admin/* remain gated on Permission.ADMIN.

    Bearer tokens: any authenticated tenant member may list. API keys: must
    be tenant-scoped with admin permission — the route-level guards above
    stash deferred-enforcement state consumed by `_resolve_api_key`, which
    is a no-op for bearer auth where `request.state.api_key` is unset.
    """
    user = container.user()
    user_assembler = container.user_assembler()
    user_service = container.user_service()

    previous = bool(previous)

    paginated_users = await user_service.get_all_users(
        tenant_id=user.tenant_id,
        limit=limit,
        cursor=cursor,
        previous=previous,
        filters=email,
    )

    total_count = await user_service.get_total_count(user.tenant_id, filters=email)

    public_paginated_users = user_assembler.users_to_paginated_response(
        users=paginated_users,
        total_count=total_count,
        limit=limit,
        cursor=cursor,
        previous=previous,
    )

    return public_paginated_users


@router.get(
    "/password-policy/",
    response_model=LocalPasswordPolicy,
    summary="Get the local password policy",
    description=(
        "Return the policy enforced when creating or changing passwords stored in Eneo. "
        "Available to authenticated users regardless of their own login provider, "
        "so administrators can manage local accounts. Provider-managed passwords "
        "use their provider's policy instead."
    ),
    responses=responses.get_responses([401, 403]),
    dependencies=[Depends(auth_dependencies.get_current_active_user)],
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason="Tenant members may access their profile and tenant directory; identity guards restrict personal operations.",
    reachable_before_password_change=True,
)
async def get_local_password_policy() -> LocalPasswordPolicy:
    return LOCAL_PASSWORD_POLICY


@router.get(
    "/me/",
    response_model=UserPublic,
    name="Get current user",
    responses=responses.get_responses([403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason="Tenant members may access their profile and tenant directory; identity guards restrict personal operations.",
    reachable_before_password_change=True,
)
async def get_currently_authenticated_user(
    current_user: Annotated[
        UserInDB, Depends(auth_dependencies.get_current_active_user_with_quota)
    ],
    container: Annotated[Container, Depends(get_container())],
):
    # Called on the user already loaded: as a dependency it would authenticate
    # the request a second time.
    await require_user_identity(current_user)
    api_key_repo = container.api_key_v2_repo()
    latest_key = await api_key_repo.get_latest_active_by_owner(
        tenant_id=current_user.tenant_id, owner_user_id=current_user.id
    )
    truncated_key = latest_key.key_suffix if latest_key is not None else None
    password_change = (
        EneoPasswordChangeCapabilityPublic()
        if current_user.password is not None
        else ExternalPasswordChangeCapabilityPublic()
    )
    return UserPublic(
        **current_user.model_dump(),
        truncated_api_key=truncated_key,
        password_change=password_change,
        password_status=password_status_for(current_user),
    )


async def _audit_password_change(
    *,
    container: Container,
    user: UserInDB,
    success: bool,
    failure_reason: str | None = None,
) -> None:
    action = (
        ActionType.PASSWORD_CHANGED if success else ActionType.PASSWORD_CHANGE_FAILED
    )
    await container.audit_service().log_async(
        tenant_id=user.tenant_id,
        user=user,
        action=action,
        entity_type=EntityType.USER,
        entity_id=user.id,
        description=(
            "Changed local Eneo password"
            if success
            else "Local Eneo password change failed"
        ),
        metadata=AuditMetadata.authentication(
            actor=user,
            method="local_password_change",
            success=success,
            failure_reason=failure_reason,
        ),
        outcome=Outcome.SUCCESS if success else Outcome.FAILURE,
        error_message=failure_reason if not success else None,
    )


@router.post(
    "/me/password/",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
    name="Change current user's local password",
    description=(
        "Change the authenticated user's local Eneo password and invalidate "
        "previously issued Eneo sessions."
    ),
    responses=responses.get_responses([400, 403, 404, 409, 429, 503]),
)
@endpoint_access(
    authentication=Authentication.SESSION,
    authorization=Authorization.AUTHENTICATED,
    reason="Tenant members may access their profile and tenant directory; identity guards restrict personal operations.",
    reachable_before_password_change=True,
)
async def change_current_user_password(
    password_change: PasswordChangeRequest,
    container: Annotated[
        Container,
        Depends(get_container(with_user=True, transaction_scope="function")),
    ],
) -> Response:
    """Change the caller's local Eneo password and revoke older Eneo JWTs."""

    current_user = container.user()
    try:
        await enforce_rate_limit(
            redis_client=container.redis_client(),
            user_id=current_user.id,
            tenant_id=current_user.tenant_id,
            config=_PASSWORD_CHANGE_RATE_LIMIT,
        )
    except RateLimitExceededError as exc:
        await _audit_password_change(
            container=container,
            user=current_user,
            success=False,
            failure_reason="rate_limit_exceeded",
        )
        raise_rate_limited(
            exc.result, "Too many password change attempts. Try again later."
        )
    except RateLimitServiceUnavailableError as exc:
        logger.warning("Password-change rate limiter unavailable", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "rate_limit_unavailable",
                "message": "Password changes are temporarily unavailable.",
            },
        ) from exc

    try:
        updated_user = await container.user_service().change_local_password(
            user_id=current_user.id,
            current_password=password_change.current_password.get_secret_value(),
            new_password=password_change.new_password.get_secret_value(),
        )
    except PasswordChangeError as exc:
        await _audit_password_change(
            container=container,
            user=current_user,
            success=False,
            failure_reason=exc.code,
        )
        raise

    await _audit_password_change(
        container=container,
        user=updated_user,
        success=True,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/me/sessions/invalidate/",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
    name="Invalidate current user's Eneo sessions",
    description=(
        "Invalidate previously issued Eneo sessions at the authenticated "
        "user's request."
    ),
    responses=responses.get_responses([403, 404]),
)
@endpoint_access(
    authentication=Authentication.SESSION,
    authorization=Authorization.AUTHENTICATED,
    reason="Tenant members may access their profile and tenant directory; identity guards restrict personal operations.",
    reachable_before_password_change=True,
)
async def invalidate_current_user_sessions(
    container: Annotated[
        Container,
        Depends(get_container(with_user=True, transaction_scope="function")),
    ],
) -> Response:
    """Invalidate previously issued Eneo sessions at the user's request."""

    current_user = container.user()
    updated_user = await container.user_service().invalidate_sessions(
        user_id=current_user.id
    )
    await container.audit_service().log_async(
        tenant_id=updated_user.tenant_id,
        user=updated_user,
        action=ActionType.SESSIONS_INVALIDATED,
        entity_type=EntityType.USER,
        entity_id=updated_user.id,
        description="Invalidated Eneo sessions at the user's request",
        metadata=AuditMetadata.authentication(
            actor=updated_user,
            method="user_session_invalidation",
            success=True,
        ),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/tenant/",
    response_model=TenantPublic,
    name="Get current user tenant",
    responses=responses.get_responses([404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason="Tenant members may access their profile and tenant directory; identity guards restrict personal operations.",
)
async def get_current_user_tenant(
    current_user: Annotated[
        UserInDB, Depends(auth_dependencies.get_current_active_user)
    ],
):
    tenant = current_user.tenant
    return TenantPublic(**tenant.model_dump())


@users_admin_router.post(
    "/admin/invite/",
    response_model=UserAdminView,
    status_code=201,
    description="Invite a new user to the tenant (admin).",
    responses=responses.get_responses([400, 403]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Permission.ADMIN,
    reason="This operation requires Permission.ADMIN before accessing tenant resources.",
)
async def invite_user(
    user_invite: PropUserInvite,
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    user_service = container.user_service()
    current_user = container.user()
    session = cast(AsyncSession, container.session())

    # Create user
    new_user = await user_service.invite_user(
        user_invite, tenant_id=current_user.tenant_id
    )

    # Build comprehensive extra context for user creation
    extra: dict[str, object] = {
        "email": new_user.email,
        "username": new_user.username,
        "state": user_invite.state.value if user_invite.state else "invited",
        "tenant_id": str(current_user.tenant_id),
        "tenant_name": current_user.tenant.display_name or current_user.tenant.name
        if current_user.tenant
        else None,
    }

    # Fetch role details if role was assigned
    if user_invite.role:
        import sqlalchemy as sa

        from eneo.database.tables.roles_table import Roles

        # Query for the role details
        role_query = sa.select(Roles).where(Roles.id == user_invite.role.id)
        role_result = await session.execute(role_query)
        assigned_role = role_result.scalar_one_or_none()

        if assigned_role:
            extra["role"] = assigned_role.name
            extra["permissions"] = sorted(assigned_role.permissions)

    # Include role/group information if available
    if hasattr(new_user, "roles") and new_user.roles:
        extra["roles"] = [role.name for role in new_user.roles]

    if hasattr(new_user, "user_groups") and new_user.user_groups:
        extra["user_groups"] = [group.name for group in new_user.user_groups]

    if hasattr(new_user, "quota_limit") and new_user.quota_limit:
        extra["quota_limit"] = new_user.quota_limit

    # Audit logging
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=current_user.tenant_id,
        user=current_user,
        action=ActionType.USER_CREATED,
        entity_type=EntityType.USER,
        entity_id=new_user.id,
        description=f"Invited user '{new_user.email}' to tenant",
        metadata=AuditMetadata.standard(
            actor=current_user,
            target=new_user,
            extra=extra,
        ),
    )

    return new_user


@users_admin_router.patch(
    "/admin/{id}/",
    response_model=UserAdminView,
    description="Update a user in the tenant (admin).",
    responses=responses.get_responses([400, 403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Permission.ADMIN,
    reason="This operation requires Permission.ADMIN before accessing tenant resources.",
)
async def update_user(
    id: UUID,
    user_update: PropUserUpdate,
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    user_service = container.user_service()
    current_user = container.user()

    # Get old state for change tracking — tenant-scoped
    old_user = await user_service.get_user(id)
    if old_user.tenant_id != current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    # Update user
    updated_user = await user_service.update_user(
        user_id=id,
        user_update_public=UserUpdatePublic(
            roles=[user_update.role] if user_update.role else None,
            state=user_update.state if user_update.state else None,
        ),
    )

    # Track comprehensive changes
    changes: dict[str, object] = {}

    # State change
    if user_update.state:
        old_state = old_user.state.value if hasattr(old_user, "state") else None
        if old_state and user_update.state.value != old_state:
            changes["state"] = {"old": old_state, "new": user_update.state.value}

    # Role change (PropUserUpdate has single role)
    if user_update.role:
        old_roles = []
        if hasattr(old_user, "roles") and old_user.roles:
            old_roles = [role.name for role in old_user.roles]

        # After update, get the new roles
        new_roles = []
        if hasattr(updated_user, "roles") and updated_user.roles:
            new_roles = [role.name for role in updated_user.roles]

        if old_roles != new_roles:
            changes["roles"] = {"old": old_roles, "new": new_roles}

    # Track permission changes (computed from role changes)
    old_permissions = (
        sorted([p.value for p in old_user.permissions])
        if hasattr(old_user, "permissions")
        else []
    )
    new_permissions = (
        sorted([p.value for p in updated_user.permissions])
        if hasattr(updated_user, "permissions")
        else []
    )

    if old_permissions != new_permissions:
        added_perms = list(set(new_permissions) - set(old_permissions))
        removed_perms = list(set(old_permissions) - set(new_permissions))
        if added_perms or removed_perms:
            changes["permissions"] = {}
            if added_perms:
                changes["permissions"]["added"] = sorted(added_perms)
            if removed_perms:
                changes["permissions"]["removed"] = sorted(removed_perms)

    # Build extra context with current user state
    extra: dict[str, object] = {
        "email": updated_user.email,
        "username": updated_user.username,
        "state": updated_user.state.value if hasattr(updated_user, "state") else None,
        "tenant_id": str(current_user.tenant_id),
        "tenant_name": current_user.tenant.display_name or current_user.tenant.name
        if current_user.tenant
        else None,
    }

    # Include current role/group information
    if hasattr(updated_user, "roles") and updated_user.roles:
        extra["roles"] = [role.name for role in updated_user.roles]

    if hasattr(updated_user, "user_groups") and updated_user.user_groups:
        extra["user_groups"] = [group.name for group in updated_user.user_groups]

    if hasattr(updated_user, "quota_limit") and updated_user.quota_limit:
        extra["quota_limit"] = updated_user.quota_limit

    # Build change summary for description
    change_summary = list(changes.keys()) if changes else []

    # Audit logging
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=current_user.tenant_id,
        user=current_user,
        action=ActionType.USER_UPDATED,
        entity_type=EntityType.USER,
        entity_id=id,
        description=f"Updated user '{updated_user.email}'"
        + (f" ({', '.join(change_summary)})" if change_summary else ""),
        metadata=AuditMetadata.standard(
            actor=current_user,
            target=updated_user,
            changes=changes if changes else None,
            extra=extra,
        ),
    )

    return updated_user


@users_admin_router.delete(
    "/admin/{id}/",
    status_code=204,
    description="Delete a user from the tenant (admin).",
    responses=responses.get_responses([400, 403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Permission.ADMIN,
    reason="This operation requires Permission.ADMIN before accessing tenant resources.",
)
async def delete_user(
    id: UUID,
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    user_service = container.user_service()
    current_user = container.user()

    # Get user details BEFORE deletion (snapshot pattern) — tenant-scoped
    user_to_delete = await user_service.get_user(id)
    if user_to_delete.tenant_id != current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    # Build extra context capturing what was deleted
    extra: dict[str, object] = {
        "email": user_to_delete.email,
        "username": user_to_delete.username,
        "state": user_to_delete.state.value
        if hasattr(user_to_delete, "state")
        else None,
        "tenant_id": str(current_user.tenant_id),
        "tenant_name": current_user.tenant.display_name or current_user.tenant.name
        if current_user.tenant
        else None,
        "created_at": user_to_delete.created_at.isoformat()
        if hasattr(user_to_delete, "created_at") and user_to_delete.created_at
        else None,
    }

    # Include full context of what was deleted
    if hasattr(user_to_delete, "roles") and user_to_delete.roles:
        extra["roles"] = [role.name for role in user_to_delete.roles]

    if hasattr(user_to_delete, "permissions"):
        extra["permissions"] = sorted([p.value for p in user_to_delete.permissions])

    if hasattr(user_to_delete, "user_groups") and user_to_delete.user_groups:
        extra["user_groups"] = [group.name for group in user_to_delete.user_groups]

    if hasattr(user_to_delete, "quota_limit") and user_to_delete.quota_limit:
        extra["quota_limit"] = user_to_delete.quota_limit

    # Delete user
    await user_service.delete_user(user_id=id)

    # Audit logging
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=current_user.tenant_id,
        user=current_user,
        action=ActionType.USER_DELETED,
        entity_type=EntityType.USER,
        entity_id=id,
        description=f"Deleted user '{user_to_delete.email}'",
        metadata=AuditMetadata.standard(
            actor=current_user,
            target=user_to_delete,
            extra=extra,
        ),
    )


_ZITADEL_MIGRATION_GUIDE_URL = (
    "https://docs.eneo.ai/guides/oidc-federation#migrate-from-the-zitadel-settings"
)


@router.post(
    "/provision/",
    status_code=201,
    description=(
        "Deprecated, removed in the next release, together with the Zitadel "
        "sign-in it served. People are created at their first OIDC sign-in, "
        "under the organisation's provisioning setting."
    ),
    response_model=None,
    responses=responses.get_responses([403]),
    deprecated=True,
)
@endpoint_access(
    authentication=Authentication.PUBLIC,
    authorization=Authorization.PUBLIC,
    reason="Login or provisioning entry point; the authentication service validates supplied credentials before granting a session.",
)
async def provision_user(
    user_provision: UserProvision,
    container: Annotated[Container, Depends(get_container())],
):
    # Before the service lookup, so every call is logged; never the token.
    logger.warning(
        "POST /api/v1/users/provision/ is deprecated and will be removed in the "
        "next release. People are created at their first OIDC sign-in instead. "
        f"See {_ZITADEL_MIGRATION_GUIDE_URL}"
    )
    user_service = cast(_ProvisioningService, container.user_creation_service())  # pyright: ignore[reportUnknownMemberType]  # not yet in container's typed interface

    await user_service.provision_user(access_token=user_provision.zitadel_token)
