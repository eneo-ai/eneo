from datetime import datetime, timezone
from typing import Annotated, Literal, cast
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, Body, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from intric.admin.admin_models import (
    AdminApiKeysQueryParams,
    AdminApiKeyUsageQueryParams,
    AdminExpiringKeysQueryParams,
    AdminUsersQueryParams,
    PaginatedUsersResponse,
    PrivacyPolicy,
    UserDeletedListItem,
    UserStateListItem,
)

# Audit logging - module level imports for consistency
from intric.audit.application.audit_metadata import AuditMetadata
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType
from intric.authentication.api_key_lifecycle import ApiKeyLifecycleService
from intric.authentication.api_key_resolver import ApiKeyValidationError
from intric.authentication.api_key_router_helpers import (
    build_api_key_usage_page,
    build_api_key_usage_summary,
    error_responses,
    paginate_keys,
    raise_api_key_http_error,
)
from intric.authentication.api_key_v2_repo import ApiKeysV2Repository
from intric.authentication.auth_dependencies import require_api_key_permission
from intric.authentication.auth_models import (
    ApiKeyCreatedResponse,
    ApiKeyExactLookupRequest,
    ApiKeyExactLookupResponse,
    ApiKeyExtendRequest,
    ApiKeyNotificationPolicyResponse,
    ApiKeyNotificationPolicyUpdate,
    ApiKeyPermission,
    ApiKeyPolicyResponse,
    ApiKeyPolicyUpdate,
    ApiKeyRotateRequest,
    ApiKeySearchMatchReason,
    ApiKeyStateChangeRequest,
    ApiKeyUpdateRequest,
    ApiKeyUsageResponse,
    ApiKeyUserSnapshot,
    ApiKeyV2,
    ApiKeyV2InDB,
    ExpiringKeysSummary,
    ExpiringKeySummaryItem,
    SuperApiKeyStatus,
)
from intric.database.tables.users_table import Users
from intric.main.config import get_settings
from intric.main.container.container import Container
from intric.main.exceptions import BadRequestException
from intric.main.logging import get_logger
from intric.main.models import CursorPaginatedResponse, DeleteResponse
from intric.roles.role import RolePublic
from intric.server.dependencies.container import get_container
from intric.tenants.tenant import TenantPublic
from intric.users.user import (
    UserAddAdmin,
    UserAdminView,
    UserUpdatePublic,
)

logger = get_logger(__name__)
router = APIRouter()
AdminContainer = Annotated[Container, Depends(get_container(with_user=True))]
AdminApiKeyGuard = Annotated[
    None, Depends(require_api_key_permission(ApiKeyPermission.ADMIN))
]


def _classify_severity(
    expires_at: datetime, now: datetime
) -> Literal["notice", "warning", "urgent", "expired"]:
    if expires_at <= now:
        return "expired"
    days = (expires_at - now).total_seconds() / 86400
    if days <= 3:
        return "urgent"
    if days <= 14:
        return "warning"
    return "notice"


def _build_expiring_summary(
    items: list[ApiKeyV2InDB],
    total_count: int,
    now: datetime,
    cap: int = 10,
) -> ExpiringKeysSummary:
    counts: dict[str, int] = {"notice": 0, "warning": 0, "urgent": 0, "expired": 0}
    summary_items: list[ExpiringKeySummaryItem] = []

    for key in items[:cap]:
        assert key.expires_at is not None  # noqa: S101 — guaranteed by query
        sev = _classify_severity(key.expires_at, now)
        counts[sev] += 1
        summary_items.append(
            ExpiringKeySummaryItem(
                id=key.id,
                name=key.name,
                key_suffix=key.key_suffix,
                scope_type=key.scope_type,
                scope_id=key.scope_id,
                expires_at=key.expires_at,
                suspended_at=key.suspended_at,
                severity=sev,
            )
        )

    earliest = min((i.expires_at for i in summary_items), default=None)
    return ExpiringKeysSummary(
        total_count=total_count,
        counts_by_severity=counts,
        earliest_expiration=earliest,
        items=summary_items,
        truncated=total_count > len(summary_items),
        generated_at=now,
    )


@router.get(
    "/users/",
    response_model=PaginatedUsersResponse[UserAdminView],
    summary="List users with pagination and search",
    description="""
List tenant users with pagination, fuzzy search, and sorting capabilities.

**Performance Optimization:**
- Uses pg_trgm GIN indexes for efficient fuzzy text search (email and username)
- Uses composite B-tree indexes for fast tenant-scoped sorting
- Sub-second response time even with 10,000+ users per tenant

**Pagination:**
- Max depth: 100 pages (prevents deep pagination performance issues)
- Default: 100 users per page, sorted by creation date (newest first)
- Supports custom page sizes (1-100)

**Search:**
- Email search: Case-insensitive partial match (e.g., "john" matches john.doe@example.com)
- Name search: Case-insensitive partial match on username (e.g., "emma" matches emma.andersson)
- Combined search: Use both filters with AND logic

**Sorting:**
- Sort by: email, username, or created_at (default)
- Sort order: asc or desc (default)

**Example Requests:**

Default (first 100 users, newest first):
```
GET /api/v1/admin/users/
```

Custom page size (50 users per page):
```
GET /api/v1/admin/users/?page_size=50
```

Email search (find users at municipality domain):
```
GET /api/v1/admin/users/?search_email=@municipality.se
```

Name search (find users named Emma):
```
GET /api/v1/admin/users/?search_name=emma
```

Combined search and pagination:
```
GET /api/v1/admin/users/?search_email=@municipality.se&page=2&page_size=50
```

Sort by email ascending:
```
GET /api/v1/admin/users/?sort_by=email&sort_order=asc
```

**Response Format:**
```json
{
  "items": [...],
  "metadata": {
    "page": 1,
    "page_size": 100,
    "total_count": 543,
    "total_pages": 6,
    "has_next": true,
    "has_previous": false
  }
}
```

**Important Notes:**
- Only active users (not soft-deleted) are returned
- All results are isolated to your tenant (cross-tenant access is prevented)
- Max depth limit (100 pages) ensures consistent performance
""",
    responses={
        200: {
            "description": "Paginated list of users successfully retrieved",
            "content": {
                "application/json": {
                    "example": {
                        "items": [
                            {
                                "id": "123e4567-e89b-12d3-a456-426614174000",
                                "username": "emma.andersson",
                                "email": "emma.andersson@municipality.se",
                                "state": "active",
                                "used_tokens": 1250,
                                "is_active": True,
                                "email_verified": True,
                                "quota_limit": 50000000,
                                "quota_used": 12500000,
                                "created_at": "2025-09-01T08:30:00Z",
                                "updated_at": "2025-10-15T14:20:00Z",
                                "roles": [],
                                "user_groups": [],
                            }
                        ],
                        "metadata": {
                            "page": 1,
                            "page_size": 100,
                            "total_count": 543,
                            "total_pages": 6,
                            "has_next": True,
                            "has_previous": False,
                        },
                    }
                }
            },
        },
        400: {
            "description": "Invalid pagination parameters (page/page_size out of bounds)",
            "content": {
                "application/json": {
                    "example": {
                        "type": "about:blank",
                        "title": "Bad Request",
                        "status": 400,
                        "detail": "page must not exceed 100 (max depth limit)",
                        "instance": "/api/v1/admin/users/",
                    }
                }
            },
        },
        401: {"description": "Authentication required (invalid or missing API key)"},
        403: {"description": "Admin permissions required"},
    },
)
async def get_users(
    query_params: Annotated[AdminUsersQueryParams, Depends()],
    container: AdminContainer,
):
    """
    List tenant users with pagination, search, and sorting.

    **Frontend Update Needed:** The response format has changed from PaginatedResponse
    to PaginatedUsersResponse. The frontend (intric.js) must be updated to handle the
    new metadata structure.

    **TypeScript Interface (for frontend team):**
    ```typescript
    interface PaginationMetadata {
      page: number;
      page_size: number;
      total_count: number;
      total_pages: number;
      has_next: boolean;
      has_previous: boolean;
    }

    interface PaginatedUsersResponse<T> {
      items: T[];
      metadata: PaginationMetadata;
    }
    ```
    """
    try:
        service = container.admin_service()
        result = await service.list_users_paginated(query_params)

        return result
    except ValueError as e:
        # Convert ValueError from domain validation to BadRequestException (RFC 7807 format)
        raise BadRequestException(str(e)) from e


@router.post(
    "/users/",
    response_model=UserAdminView,
    status_code=201,
    summary="Create new user in tenant",
    description="Creates a new user account within your tenant. The user will be created with the provided credentials and automatically associated with your organization. Personal API keys are no longer auto-provisioned; the user can create one via POST /api/v1/api-keys when needed.",
    responses={
        201: {"description": "User successfully created"},
        400: {"description": "Invalid input data or validation errors"},
        401: {"description": "Authentication required (invalid or missing API key)"},
        403: {"description": "Admin permissions required"},
        409: {"description": "Username or email already exists in your tenant"},
    },
)
async def register_user(
    new_user: UserAddAdmin,
    container: AdminContainer,
):
    """
    Create a new user account for your organization.

    Required fields:
    - email: Valid email address (must be unique within your tenant)

    Optional fields:
    - username: Unique identifier (if not provided, will use email prefix)
    - password: User password (minimum 7 characters, maximum 100)
    - quota_limit: Storage limit in bytes (minimum 1000 bytes = 1KB)
    - roles: List of role IDs to assign (empty list by default)

    Example request:
    {
      "email": "john.doe@municipality.se",
      "username": "john.doe",
      "password": "SecurePassword123!",
      "quota_limit": 50000000
    }
    """
    admin_service = container.admin_service()
    current_user = container.user()

    # Create user
    user, _ = await admin_service.register_tenant_user(new_user)

    # Build extra context for user creation
    extra: dict[str, object] = {
        "state": user.state.value if hasattr(user, "state") else "active",
        "tenant_id": str(current_user.tenant_id),
        "tenant_name": current_user.tenant.display_name or current_user.tenant.name,
    }

    # Add role information from the input request
    if new_user.roles:
        import sqlalchemy as sa

        from intric.database.tables.roles_table import Roles

        session = cast(AsyncSession, container.session())
        custom_role_ids = [role.id for role in new_user.roles]
        role_query = sa.select(Roles).where(Roles.id.in_(custom_role_ids))
        role_result = await session.execute(role_query)
        custom_roles = role_result.scalars().all()

        if custom_roles:
            extra["roles"] = [role.name for role in custom_roles]

    # Check if user object has roles loaded (in case service returns them)
    if hasattr(user, "roles") and user.roles and "roles" not in extra:
        extra["roles"] = [role.name for role in user.roles]

    if hasattr(user, "user_groups") and user.user_groups:
        extra["user_groups"] = [group.name for group in user.user_groups]

    # Add quota limit if set
    if new_user.quota_limit:
        extra["quota_limit"] = new_user.quota_limit

    # Audit logging
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=current_user.tenant_id,
        user=current_user,
        action=ActionType.USER_CREATED,
        entity_type=EntityType.USER,
        entity_id=user.id,
        description=f"Admin created user '{user.email}'",
        metadata=AuditMetadata.standard(
            actor=current_user,
            target=user,
            extra=extra,
        ),
    )

    user_admin_view = UserAdminView(**user.model_dump())

    return user_admin_view


@router.get(
    "/users/{username}/",
    response_model=UserAdminView,
    summary="Get user details",
    description="Retrieves a single user's complete details using their username. User must exist in your tenant and not be soft-deleted. Returns the same detailed information format as other admin endpoints.",
    responses={
        200: {"description": "User details successfully retrieved"},
        400: {"description": "Cross-tenant access attempt"},
        401: {"description": "Authentication required (invalid or missing API key)"},
        403: {"description": "Admin permissions required"},
        404: {"description": "User not found in your tenant (may be soft-deleted)"},
    },
)
async def get_user(
    username: str,
    container: AdminContainer,
):
    """
    Retrieve a single user's details by username.

    Path parameter:
    - username: The username of the user to retrieve

    Returns complete user information including:
    - Basic details (username, email, creation/update timestamps)
    - Status information (state, active status, email verification)
    - Usage statistics (token consumption, quota limits)
    - Role and group memberships

    Example response:
    {
      "id": "123e4567-e89b-12d3-a456-426614174000",
      "username": "emma.andersson",
      "email": "emma.andersson@municipality.se",
      "state": "ACTIVE",
      "used_tokens": 1250,
      "is_active": true,
      "roles": [],
      "user_groups": []
    }

    Note: This endpoint is useful for external systems that need to check individual user status
    without fetching the entire user list, providing better performance for single-user lookups.
    """
    service = container.admin_service()
    user = await service.get_tenant_user(username)

    user_admin_view = UserAdminView(**user.model_dump())

    return user_admin_view


@router.post(
    "/users/{username}/",
    response_model=UserAdminView,
    summary="Update existing user",
    description="Updates an existing user's details using their username. Only fields provided in the request body will be updated. User must exist in your tenant and not be soft-deleted.",
    responses={
        200: {"description": "User successfully updated"},
        400: {
            "description": "Invalid input data, validation errors, or cross-tenant access attempt"
        },
        401: {"description": "Authentication required (invalid or missing API key)"},
        403: {"description": "Admin permissions required"},
        404: {"description": "User not found in your tenant (may be soft-deleted)"},
        409: {"description": "Email already exists in your tenant"},
    },
)
async def update_user(
    username: str,
    user: UserUpdatePublic,
    container: AdminContainer,
):
    """
    Update an existing user's information.

    Path parameter:
    - username: The username of the user to update

    Optional fields (only provided fields are updated):
    - email: New email address (must be unique within your tenant)
    - password: New password (minimum 7 characters, maximum 100)
    - quota_limit: New storage limit in bytes (minimum 1000 bytes = 1KB)
    - state: User state (invited/active/inactive/deleted)
    - roles: List of role IDs (replaces existing roles)

    Note: Username cannot be changed after creation.

    Example request:
    {
      "email": "updated.email@municipality.se",
      "password": "NewSecurePassword456!",
      "quota_limit": 100000000,
      "state": "active"
    }
    """
    service = container.admin_service()
    current_user = container.user()

    # Get old state for change tracking
    old_user = await service.get_tenant_user(username)

    # Update user
    user_updated = await service.update_tenant_user(username, user)

    # Track comprehensive changes
    changes: dict[str, object] = {}

    # Basic field changes
    if user.email and user.email != old_user.email:
        changes["email"] = {"old": old_user.email, "new": user.email}
    if user.state and user.state != old_user.state:
        changes["state"] = {"old": old_user.state, "new": user.state}
    if user.quota_limit is not None and user.quota_limit != old_user.quota_limit:
        changes["quota_limit"] = {"old": old_user.quota_limit, "new": user.quota_limit}

    # Password change tracking (just flag, never log the actual password)
    if user.password:
        changes["password_changed"] = True

    # Track role changes (UserUpdatePublic supports full role management)
    if user.roles is not None:
        old_roles = (
            [role.name for role in old_user.roles]
            if hasattr(old_user, "roles") and old_user.roles
            else []
        )
        new_roles = (
            [role.name for role in user_updated.roles]
            if hasattr(user_updated, "roles") and user_updated.roles
            else []
        )
        if old_roles != new_roles:
            changes["roles"] = {"old": old_roles, "new": new_roles}

    # Track permission changes (computed from role changes)
    old_permissions = (
        sorted([p.value for p in old_user.permissions])
        if hasattr(old_user, "permissions")
        else []
    )
    new_permissions = (
        sorted([p.value for p in user_updated.permissions])
        if hasattr(user_updated, "permissions")
        else []
    )

    if old_permissions != new_permissions:
        added_perms = list(set(new_permissions) - set(old_permissions))
        removed_perms = list(set(old_permissions) - set(new_permissions))
        if added_perms or removed_perms:
            permissions_changes: dict[str, list[str]] = {}
            if added_perms:
                permissions_changes["added"] = sorted(added_perms)
            if removed_perms:
                permissions_changes["removed"] = sorted(removed_perms)
            changes["permissions"] = permissions_changes

    # Build extra context for current state
    extra: dict[str, object] = {
        "state": user_updated.state.value if hasattr(user_updated, "state") else None,
    }

    if hasattr(user_updated, "roles") and user_updated.roles:
        extra["roles"] = [role.name for role in user_updated.roles]

    if hasattr(user_updated, "user_groups") and user_updated.user_groups:
        extra["user_groups"] = [group.name for group in user_updated.user_groups]

    if hasattr(user_updated, "quota_limit") and user_updated.quota_limit:
        extra["quota_limit"] = user_updated.quota_limit

    # Audit logging
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=current_user.tenant_id,
        user=current_user,
        action=ActionType.USER_UPDATED,
        entity_type=EntityType.USER,
        entity_id=user_updated.id,
        description=f"Admin updated user '{user_updated.email}'",
        metadata=AuditMetadata.standard(
            actor=current_user,
            target=user_updated,
            changes=changes if changes else None,
            extra=extra,
        ),
    )

    user_admin_view = UserAdminView(**user_updated.model_dump())

    return user_admin_view


@router.delete(
    "/users/{username}",
    response_model=DeleteResponse,
    summary="Soft delete user",
    description="Soft deletes a user by setting deleted_at timestamp and UserState.DELETED. The user's record is preserved for audit purposes but they can no longer authenticate. This operation is irreversible through the API.",
    responses={
        200: {"description": "User successfully soft deleted"},
        400: {"description": "Cannot delete yourself or cross-tenant access attempt"},
        401: {"description": "Authentication required (invalid or missing API key)"},
        403: {"description": "Admin permissions required"},
        404: {
            "description": "User not found in your tenant (may already be soft-deleted)"
        },
    },
)
async def delete_user(username: str, container: AdminContainer):
    """
    Soft delete a user account.

    Path parameter:
    - username: The username of the user to delete

    This operation:
    - Marks the user as deleted (sets deleted_at timestamp)
    - Sets user state to DELETED
    - Preserves the user record for audit purposes
    - Prevents the user from authenticating
    - Cannot be reversed through the API

    Restrictions:
    - You cannot delete your own admin account
    - User must exist in your tenant
    - User must not already be soft-deleted
    """
    service = container.admin_service()
    current_user = container.user()

    # Get user details BEFORE deletion (snapshot pattern)
    user_to_delete = await service.get_tenant_user(username)

    # Delete user
    success = await service.delete_tenant_user(username)

    # Build extra context capturing what was deleted
    extra: dict[str, object] = {
        "state": user_to_delete.state.value
        if hasattr(user_to_delete, "state")
        else None,
    }

    if hasattr(user_to_delete, "roles") and user_to_delete.roles:
        extra["roles"] = [role.name for role in user_to_delete.roles]

    if hasattr(user_to_delete, "permissions"):
        extra["permissions"] = sorted([p.value for p in user_to_delete.permissions])

    if hasattr(user_to_delete, "user_groups") and user_to_delete.user_groups:
        extra["user_groups"] = [group.name for group in user_to_delete.user_groups]

    if hasattr(user_to_delete, "quota_limit") and user_to_delete.quota_limit:
        extra["quota_limit"] = user_to_delete.quota_limit

    # Audit logging
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=current_user.tenant_id,
        user=current_user,
        action=ActionType.USER_DELETED,
        entity_type=EntityType.USER,
        entity_id=user_to_delete.id,
        description=f"Admin deleted user '{user_to_delete.email}'",
        metadata=AuditMetadata.standard(
            actor=current_user,
            target=user_to_delete,
            extra=extra,
        ),
    )

    return DeleteResponse(success=success)


@router.post(
    "/users/{username}/deactivate",
    response_model=UserAdminView,
    summary="Deactivate user (temporary leave)",
    description="Sets user state to INACTIVE for temporary unavailability such as sick leave, vacation, or parental leave. User cannot login but account data is fully preserved. This is reversible through reactivation.",
    responses={
        200: {"description": "User successfully deactivated"},
        400: {
            "description": "Cannot deactivate yourself or cross-tenant access attempt"
        },
        401: {"description": "Authentication required (invalid or missing API key)"},
        403: {"description": "Admin permissions required"},
        404: {"description": "User not found in your tenant"},
    },
)
async def deactivate_user(username: str, container: AdminContainer):
    """
    Deactivate a user account for temporary leave.

    Path parameter:
    - username: The username of the user to deactivate

    This operation:
    - Sets user state to INACTIVE
    - Prevents the user from logging in
    - Preserves all account data and settings
    - Records timestamp for external tracking
    - Is fully reversible through reactivation

    Use cases:
    - Employee sick leave
    - Extended vacation or sabbatical
    - Parental leave
    - Training or educational leave
    - Temporary disciplinary suspension

    Restrictions:
    - You cannot deactivate your own admin account
    - User must exist in your tenant
    - User must not be from another tenant
    """
    service = container.admin_service()
    current_user = container.user()

    # Deactivate user
    user = await service.deactivate_tenant_user(username)

    # Audit logging
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=current_user.tenant_id,
        user=current_user,
        action=ActionType.USER_UPDATED,  # Deactivation is a state update
        entity_type=EntityType.USER,
        entity_id=user.id,
        description=f"Deactivated user '{user.email}'",
        metadata=AuditMetadata.standard(
            actor=current_user,
            target=user,
            changes={"state": {"old": "active", "new": "inactive"}},
        ),
    )

    return UserAdminView(**user.model_dump())


@router.post(
    "/users/{username}/reactivate",
    response_model=UserAdminView,
    summary="Reactivate user (return to active)",
    description="Sets user state to ACTIVE from any previous state (INACTIVE or DELETED). Restores full system access and clears deletion timestamps if present. Use for employees returning from leave or rare rehire cases.",
    responses={
        200: {"description": "User successfully reactivated"},
        400: {"description": "Cross-tenant access attempt"},
        401: {"description": "Authentication required (invalid or missing API key)"},
        403: {"description": "Admin permissions required"},
        404: {"description": "User not found in your tenant"},
    },
)
async def reactivate_user(username: str, container: AdminContainer):
    """
    Reactivate a user account to restore full access.

    Path parameter:
    - username: The username of the user to reactivate

    This operation:
    - Sets user state to ACTIVE
    - Restores login capability immediately
    - Clears deletion timestamp if user was DELETED
    - Records timestamp for external tracking
    - Works from any previous state (INACTIVE or DELETED)

    Use cases:
    - Employee returning from sick leave
    - End of vacation or sabbatical
    - Return from parental leave
    - End of training period
    - Rare rehire of previously departed employee

    Restrictions:
    - User must exist in your tenant
    - User must not be from another tenant
    """
    service = container.admin_service()
    current_user = container.user()

    # Get old state
    old_user = await service.get_tenant_user(username)

    # Reactivate user
    user = await service.reactivate_tenant_user(username)

    # Audit logging
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=current_user.tenant_id,
        user=current_user,
        action=ActionType.USER_UPDATED,  # Reactivation is a state update
        entity_type=EntityType.USER,
        entity_id=user.id,
        description=f"Reactivated user '{user.email}'",
        metadata=AuditMetadata.standard(
            actor=current_user,
            target=user,
            changes={"state": {"old": str(old_user.state), "new": "active"}},
        ),
    )

    return UserAdminView(**user.model_dump())


@router.get(
    "/users/inactive",
    response_model=list[UserStateListItem],
    summary="List inactive users",
    description="Returns all users in INACTIVE state within your tenant. These are employees on temporary leave who cannot login but are still employed. Use for tracking who is temporarily unavailable.",
    responses={
        200: {"description": "List of inactive users successfully retrieved"},
        401: {"description": "Authentication required (invalid or missing API key)"},
        403: {"description": "Admin permissions required"},
    },
)
async def get_inactive_users(
    container: AdminContainer,
):
    """
    Get all users currently in INACTIVE state.

    This endpoint returns employees who are:
    - On sick leave
    - Taking vacation or sabbatical
    - On parental leave
    - In training or education programs
    - Under temporary disciplinary suspension

    Each user entry includes:
    - Username and email for identification
    - Current state (always 'inactive' for this list)
    - Timestamp when they were deactivated

    Use this for:
    - Tracking who is temporarily unavailable
    - Workforce planning and capacity management
    - Leave duration tracking (via external systems)
    """
    service = container.admin_service()
    return await service.get_inactive_tenant_users()


@router.get(
    "/users/deleted",
    response_model=list[UserDeletedListItem],
    summary="List deleted users",
    description="Returns all users in DELETED state within your tenant. These are employees who have left the organization and cannot login. Records are preserved for audit purposes and potential cleanup by external systems.",
    responses={
        200: {"description": "List of deleted users successfully retrieved"},
        401: {"description": "Authentication required (invalid or missing API key)"},
        403: {"description": "Admin permissions required"},
    },
)
async def get_deleted_users(
    container: AdminContainer,
):
    """
    Get all users currently in DELETED state.

    This endpoint returns employees who have:
    - Quit or resigned
    - Been terminated or fired
    - Retired from the organization
    - Transferred to different systems/departments

    Each user entry includes:
    - Username and email for identification
    - Current state (always 'deleted' for this list)
    - Timestamp when they were deleted (for compliance tracking)

    Use this for:
    - Tracking departed employees
    - Compliance monitoring (90-day rules, GDPR)
    - Audit trail maintenance
    - Planning permanent data cleanup

    Note: External systems handle business logic for when to
    permanently delete these records based on their own policies.
    """
    service = container.admin_service()
    return await service.get_deleted_tenant_users()


@router.get(
    "/predefined-roles/",
    response_model=list[RolePublic],
    summary="Get default roles for tenant",
    description="Retrieves all default (predefined-source) roles for the authenticated tenant.",
    responses={
        200: {"description": "List of default roles successfully retrieved"},
        401: {"description": "Authentication required"},
        403: {"description": "Admin permissions required"},
    },
)
async def get_predefined_roles(container: AdminContainer):
    """Get all default roles for your tenant (backward-compatible endpoint)."""
    admin_service = container.admin_service()
    await admin_service.validate_admin_permission()

    role_service = container.role_service()
    all_roles = await role_service.get_all_roles()
    return [role for role in all_roles if role.predefined_source]


@router.post("/privacy-policy/", response_model=TenantPublic)
async def update_privacy_policy(url: PrivacyPolicy, container: AdminContainer):
    service = container.admin_service()
    user = container.user()

    # Update privacy policy
    updated_tenant = await service.update_privacy_policy(url)

    # Audit logging
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        user=user,
        action=ActionType.TENANT_SETTINGS_UPDATED,
        entity_type=EntityType.TENANT_SETTINGS,
        entity_id=user.tenant_id,
        description="Updated privacy policy URL",
        metadata=AuditMetadata.standard(
            actor=user,
            target=updated_tenant,
            extra={"privacy_policy_url": url.url},
        ),
    )

    return updated_tenant


_ADMIN_API_KEY_STATE_CHANGE_EXAMPLE = {
    "reason_code": "security_concern",
    "reason_text": "Automated abuse detection triggered revocation.",
}

_ADMIN_API_KEY_EXAMPLE = {
    "id": "3cbf5fde-7288-4f03-bf06-f71c14f76854",
    "name": "Production Backend",
    "description": "Used by tenant integration workers",
    "key_type": "sk_",
    "permission": "write",
    "scope_type": "space",
    "scope_id": "11111111-1111-1111-1111-111111111111",
    "allowed_origins": None,
    "allowed_ips": ["203.0.113.0/24"],
    "rate_limit": 5000,
    "state": "active",
    "effective_state": "active",
    "key_prefix": "sk_",
    "key_suffix": "ab12cd34",
    "expires_at": "2030-01-01T00:00:00Z",
    "last_used_at": None,
    "created_at": "2026-02-05T12:00:00Z",
    "updated_at": "2026-02-05T12:00:00Z",
    "revoked_at": None,
    "suspended_at": None,
}

_ADMIN_API_KEY_LIST_EXAMPLE = {
    "items": [_ADMIN_API_KEY_EXAMPLE],
    "limit": 50,
    "next_cursor": "2026-02-05T12:00:00Z",
    "previous_cursor": None,
    "total_count": 1,
}

_ADMIN_ROTATED_RESPONSE_EXAMPLE = {
    "api_key": _ADMIN_API_KEY_EXAMPLE,
    "secret": "sk_4d2a56d4207a...",
}


def _build_search_match_reasons(
    key: ApiKeyV2, search: str | None
) -> list[ApiKeySearchMatchReason]:
    if not search:
        return []

    normalized = search.strip().lower()
    if not normalized:
        return []

    reasons: list[ApiKeySearchMatchReason] = []
    if key.key_suffix and normalized in key.key_suffix.lower():
        reasons.append(ApiKeySearchMatchReason.KEY_SUFFIX)
    if normalized in key.name.lower() or normalized in (key.description or "").lower():
        reasons.append(ApiKeySearchMatchReason.NAME_OR_DESCRIPTION)
    owner_identity = " ".join(
        filter(
            None,
            [
                key.owner_user.username if key.owner_user else None,
                key.owner_user.email if key.owner_user else None,
                str(key.owner_user_id),
            ],
        )
    ).lower()
    if normalized in owner_identity:
        reasons.append(ApiKeySearchMatchReason.OWNER)
    creator_identity = " ".join(
        filter(
            None,
            [
                key.created_by_user.username if key.created_by_user else None,
                key.created_by_user.email if key.created_by_user else None,
                str(key.created_by_user_id) if key.created_by_user_id else None,
            ],
        )
    ).lower()
    if creator_identity and normalized in creator_identity:
        reasons.append(ApiKeySearchMatchReason.CREATOR)

    deduped: list[ApiKeySearchMatchReason] = []
    for reason in reasons:
        if reason not in deduped:
            deduped.append(reason)
    return deduped


async def _enrich_api_keys_with_user_snapshots(
    *,
    session: AsyncSession,
    tenant_id: UUID,
    keys: list[ApiKeyV2],
    search: str | None = None,
) -> list[ApiKeyV2]:
    if not keys:
        return []

    user_ids: set[UUID] = set()
    for key in keys:
        if key.owner_user_id is not None:
            user_ids.add(key.owner_user_id)
        if key.created_by_user_id is not None:
            user_ids.add(key.created_by_user_id)

    snapshot_map: dict[UUID, ApiKeyUserSnapshot] = {}
    if user_ids:
        query = (
            sa.select(Users.id, Users.email, Users.username)
            .where(Users.tenant_id == tenant_id)
            .where(Users.id.in_(user_ids))
        )
        for row in (await session.execute(query)).all():
            snapshot_map[row.id] = ApiKeyUserSnapshot(
                id=row.id,
                email=row.email,
                username=row.username,
            )

    enriched: list[ApiKeyV2] = []
    for key in keys:
        updated = key.model_copy(
            update={
                "owner_user": snapshot_map.get(key.owner_user_id)
                if key.owner_user_id is not None
                else None,
                "created_by_user": (
                    snapshot_map.get(key.created_by_user_id)
                    if key.created_by_user_id
                    else None
                ),
            }
        )
        reasons = _build_search_match_reasons(updated, search)
        if reasons:
            updated = updated.model_copy(update={"search_match_reasons": reasons})
        enriched.append(updated)

    return enriched


@router.get(
    "/api-key-policy",
    response_model=ApiKeyPolicyResponse,
    tags=["Admin API Keys"],
    summary="Get tenant API key policy",
    description="Get API key policy settings for the current tenant.",
    responses={
        200: {
            "description": "Current tenant API key policy.",
            "content": {
                "application/json": {
                    "example": {
                        "require_expiration": True,
                        "max_expiration_days": 90,
                        "auto_expire_unused_days": 180,
                        "max_delegation_depth": 3,
                        "revocation_cascade_enabled": True,
                        "max_rate_limit_override": 10000,
                    }
                }
            },
        },
        **error_responses([401, 403, 429]),
    },
)
async def get_api_key_policy(
    container: AdminContainer,
):
    admin_service = container.admin_service()
    await admin_service.validate_admin_permission()

    user = container.user()
    policy = dict(user.tenant.api_key_policy or {})
    if "rotation_grace_hours" not in policy:
        settings = get_settings()
        policy["rotation_grace_hours"] = settings.api_key_rotation_grace_hours
    return ApiKeyPolicyResponse.model_validate(policy)


@router.patch(
    "/api-key-policy",
    response_model=ApiKeyPolicyResponse,
    tags=["Admin API Keys"],
    summary="Update tenant API key policy",
    description="Update tenant policy guardrails used for API key creation and validation.",
    responses={
        200: {
            "description": "Updated tenant API key policy.",
            "content": {
                "application/json": {
                    "example": {
                        "require_expiration": True,
                        "max_expiration_days": 90,
                        "auto_expire_unused_days": 180,
                    }
                }
            },
        },
        **error_responses([400, 401, 403, 429]),
    },
)
async def update_api_key_policy(
    request: Annotated[
        ApiKeyPolicyUpdate,
        Body(
            ...,
            examples=[
                {
                    "require_expiration": True,
                    "max_expiration_days": 90,
                    "max_delegation_depth": 3,
                    "revocation_cascade_enabled": True,
                }
            ],
        ),
    ],
    container: AdminContainer,
    _guard: None = Depends(require_api_key_permission(ApiKeyPermission.ADMIN)),
):
    admin_service = container.admin_service()
    user = container.user()

    await admin_service.validate_admin_permission()

    settings = get_settings()

    updates = request.model_dump(exclude_unset=True)
    if not updates:
        policy = dict(user.tenant.api_key_policy or {})
        if "rotation_grace_hours" not in policy:
            policy["rotation_grace_hours"] = settings.api_key_rotation_grace_hours
        return ApiKeyPolicyResponse.model_validate(policy)

    tenant_service = container.tenant_service()
    before_policy: dict[str, object] = dict(user.tenant.api_key_policy or {})
    updated_tenant = await tenant_service.update_api_key_policy(user.tenant_id, updates)
    after_policy: dict[str, object] = dict(updated_tenant.api_key_policy or {})

    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        user=user,
        action=ActionType.TENANT_POLICY_UPDATED,
        entity_type=EntityType.TENANT_SETTINGS,
        entity_id=user.tenant_id,
        description="Updated tenant API key policy",
        metadata=AuditMetadata.standard(
            actor=user,
            target=updated_tenant,
            changes={"api_key_policy": {"old": before_policy, "new": after_policy}},
        ),
    )

    if "rotation_grace_hours" not in after_policy:
        after_policy["rotation_grace_hours"] = settings.api_key_rotation_grace_hours
    return ApiKeyPolicyResponse.model_validate(after_policy)


@router.get(
    "/api-keys/notification-policy",
    response_model=ApiKeyNotificationPolicyResponse,
    tags=["Admin API Keys"],
    summary="Get API key notification policy",
    description="Get tenant API key notification policy settings.",
    responses={
        200: {"description": "Current notification policy."},
        **error_responses([401, 403, 429]),
    },
)
async def get_api_key_notification_policy(
    container: AdminContainer,
):
    admin_service = container.admin_service()
    await admin_service.validate_admin_permission()

    user = container.user()
    tenant_policy: dict[str, object] = dict(user.tenant.api_key_policy or {})
    notification_policy_raw = tenant_policy.get("notification_policy")
    notification_policy: dict[str, object] = (
        dict(cast(dict[str, object], notification_policy_raw))
        if isinstance(notification_policy_raw, dict)
        else {}
    )
    return ApiKeyNotificationPolicyResponse.model_validate(notification_policy)


@router.put(
    "/api-keys/notification-policy",
    response_model=ApiKeyNotificationPolicyResponse,
    tags=["Admin API Keys"],
    summary="Update API key notification policy",
    description="Update tenant API key notification policy under api_key_policy.notification_policy.",
    responses={
        200: {"description": "Updated notification policy."},
        **error_responses([400, 401, 403, 429]),
    },
)
async def update_api_key_notification_policy(
    request: Annotated[
        ApiKeyNotificationPolicyUpdate,
        Body(
            ...,
            examples=[
                {"enabled": True, "default_days_before_expiry": [30, 14, 7, 3, 1]}
            ],
        ),
    ],
    container: AdminContainer,
    _guard: None = Depends(require_api_key_permission(ApiKeyPermission.ADMIN)),
):
    admin_service = container.admin_service()
    user = container.user()
    await admin_service.validate_admin_permission()

    updates = request.model_dump(exclude_unset=True)
    tenant_policy: dict[str, object] = dict(user.tenant.api_key_policy or {})
    current_notification_policy_raw = tenant_policy.get("notification_policy")
    current_notification_policy: dict[str, object] = (
        dict(cast(dict[str, object], current_notification_policy_raw))
        if isinstance(current_notification_policy_raw, dict)
        else {}
    )

    if not updates:
        return ApiKeyNotificationPolicyResponse.model_validate(
            current_notification_policy
        )

    merged_notification_policy = dict(current_notification_policy)
    merged_notification_policy.update(updates)
    normalized_policy = ApiKeyNotificationPolicyResponse.model_validate(
        merged_notification_policy
    )

    tenant_service = container.tenant_service()
    before_policy: dict[str, object] = dict(tenant_policy)
    updated_tenant = await tenant_service.update_api_key_policy(
        user.tenant_id,
        {"notification_policy": normalized_policy.model_dump(mode="json")},
    )
    after_policy: dict[str, object] = dict(updated_tenant.api_key_policy or {})

    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        user=user,
        action=ActionType.TENANT_POLICY_UPDATED,
        entity_type=EntityType.TENANT_SETTINGS,
        entity_id=user.tenant_id,
        description="Updated tenant API key notification policy",
        metadata=AuditMetadata.standard(
            actor=user,
            target=updated_tenant,
            changes={"api_key_policy": {"old": before_policy, "new": after_policy}},
        ),
    )

    after_notification_policy_raw = after_policy.get("notification_policy")
    after_notification_policy: dict[str, object] = (
        dict(cast(dict[str, object], after_notification_policy_raw))
        if isinstance(after_notification_policy_raw, dict)
        else {}
    )
    return ApiKeyNotificationPolicyResponse.model_validate(after_notification_policy)


@router.get(
    "/super-api-key-status",
    response_model=SuperApiKeyStatus,
    tags=["Admin API Keys"],
    summary="Get super API key status",
    description="Return whether super and super-duper API keys are configured in environment settings.",
    responses={
        200: {
            "description": "Super key configuration status.",
            "content": {
                "application/json": {
                    "example": {
                        "super_api_key_configured": True,
                        "super_duper_api_key_configured": False,
                    }
                }
            },
        },
        **error_responses([401, 403, 429]),
    },
)
async def get_super_api_key_status(
    container: AdminContainer,
):
    admin_service = container.admin_service()
    await admin_service.validate_admin_permission()

    import os

    settings = get_settings()

    # Legacy detection: INTRIC_* is set in the environment but ENEO_* is not.
    # If the user has added ENEO_* (even if INTRIC_* is still present), it's not legacy.
    super_legacy = (
        bool(settings.eneo_super_api_key)
        and "INTRIC_SUPER_API_KEY" in os.environ
        and "ENEO_SUPER_API_KEY" not in os.environ
    )
    super_duper_legacy = (
        bool(settings.eneo_super_duper_api_key)
        and "INTRIC_SUPER_DUPER_API_KEY" in os.environ
        and "ENEO_SUPER_DUPER_API_KEY" not in os.environ
    )

    return SuperApiKeyStatus(
        super_api_key_configured=bool(settings.eneo_super_api_key),
        super_duper_api_key_configured=bool(settings.eneo_super_duper_api_key),
        super_api_key_using_legacy=super_legacy,
        super_duper_api_key_using_legacy=super_duper_legacy,
    )


@router.get(
    "/api-keys",
    response_model=CursorPaginatedResponse[ApiKeyV2],
    tags=["Admin API Keys"],
    summary="List tenant API keys",
    description="List API keys across the tenant with filters and cursor pagination.",
    responses={
        200: {
            "description": "Paginated tenant API key list.",
            "content": {"application/json": {"example": _ADMIN_API_KEY_LIST_EXAMPLE}},
        },
        **error_responses([401, 403, 429]),
    },
)
async def list_api_keys_admin(
    query: Annotated[AdminApiKeysQueryParams, Depends()],
    container: AdminContainer,
):
    admin_service = container.admin_service()
    await admin_service.validate_admin_permission()

    repo: ApiKeysV2Repository = container.api_key_v2_repo()
    tenant_id = admin_service.user.tenant_id
    normalized_search = query.search.strip() if query.search else None
    owner_filter = query.owner_user_id
    creator_filter = query.created_by_user_id

    keys = await repo.list_paginated(
        tenant_id=tenant_id,
        limit=query.limit,
        cursor=query.cursor,
        previous=query.previous,
        scope_type=query.scope_type,
        scope_id=query.scope_id,
        state=query.state,
        key_type=query.key_type.value if query.key_type else None,
        owner_user_id=owner_filter,
        created_by_user_id=creator_filter,
        search=normalized_search,
        expires_within_days=query.expires_within_days,
    )
    total_count = await repo.count(
        tenant_id=tenant_id,
        scope_type=query.scope_type,
        scope_id=query.scope_id,
        state=query.state,
        key_type=query.key_type.value if query.key_type else None,
        owner_user_id=owner_filter,
        created_by_user_id=creator_filter,
        search=normalized_search,
        expires_within_days=query.expires_within_days,
    )

    paginated = paginate_keys(
        keys,
        total_count=total_count,
        limit=query.limit,
        cursor=query.cursor,
        previous=query.previous,
    )
    session = cast(AsyncSession, container.session())
    items = cast(list[ApiKeyV2], paginated["items"])
    paginated["items"] = await _enrich_api_keys_with_user_snapshots(
        session=session,
        tenant_id=tenant_id,
        keys=items,
        search=normalized_search,
    )
    return paginated


@router.get(
    "/api-keys/expiring-soon",
    response_model=ExpiringKeysSummary,
    tags=["Admin API Keys"],
    summary="Get expiring API key summary (tenant-wide)",
    description="Returns all expiring keys in the tenant within the specified window.",
    responses={
        200: {"description": "Tenant-wide expiring key summary."},
        **error_responses([401, 403, 429]),
    },
)
async def get_expiring_keys_admin(
    query: Annotated[AdminExpiringKeysQueryParams, Depends()],
    container: AdminContainer,
):
    admin_service = container.admin_service()
    await admin_service.validate_admin_permission()

    repo: ApiKeysV2Repository = container.api_key_v2_repo()
    tenant_id = admin_service.user.tenant_id
    now = datetime.now(timezone.utc)

    items, total_count = await repo.list_expiring_soon(
        tenant_id=tenant_id, now=now, days=query.days
    )

    return _build_expiring_summary(items, total_count, now)


@router.post(
    "/api-keys/lookup",
    response_model=ApiKeyExactLookupResponse,
    tags=["Admin API Keys"],
    summary="Find API key by exact secret",
    description="Resolve a full API key secret within the current tenant and return the matching key metadata.",
    responses={
        200: {
            "description": "Matching API key found.",
            "content": {
                "application/json": {
                    "example": {
                        "match_reason": "exact_secret",
                        "api_key": _ADMIN_API_KEY_EXAMPLE,
                    }
                }
            },
        },
        **error_responses([400, 401, 403, 404, 429]),
    },
)
async def lookup_api_key_admin(
    payload: ApiKeyExactLookupRequest,
    container: AdminContainer,
    _guard: None = Depends(require_api_key_permission(ApiKeyPermission.ADMIN)),
):
    admin_service = container.admin_service()
    await admin_service.validate_admin_permission()

    secret = payload.secret.strip()
    if not secret:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_request", "message": "secret must not be empty."},
        )

    resolver = container.api_key_auth_resolver()
    try:
        resolved = await resolver.resolve(
            secret,
            expected_tenant_id=admin_service.user.tenant_id,
        )
    except ApiKeyValidationError:
        raise HTTPException(
            status_code=404,
            detail={"code": "resource_not_found", "message": "API key not found."},
        )

    api_key = ApiKeyV2.model_validate(resolved.key).model_copy(
        update={"search_match_reasons": [ApiKeySearchMatchReason.EXACT_SECRET]}
    )
    session = cast(AsyncSession, container.session())
    enriched = await _enrich_api_keys_with_user_snapshots(
        session=session,
        tenant_id=admin_service.user.tenant_id,
        keys=[api_key],
    )
    return ApiKeyExactLookupResponse(api_key=enriched[0])


@router.get(
    "/api-keys/{id}/usage",
    response_model=ApiKeyUsageResponse,
    tags=["Admin API Keys"],
    summary="Get API key usage timeline",
    description="Returns key-centric usage and auth-failure audit events for a single API key.",
    responses={
        200: {
            "description": "API key usage response.",
        },
        **error_responses([401, 403, 404, 429]),
    },
)
async def get_api_key_usage_admin(
    id: UUID,
    query: Annotated[AdminApiKeyUsageQueryParams, Depends()],
    container: AdminContainer,
):
    admin_service = container.admin_service()
    await admin_service.validate_admin_permission()

    repo: ApiKeysV2Repository = container.api_key_v2_repo()
    key = await repo.get(key_id=id, tenant_id=admin_service.user.tenant_id)
    if key is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "resource_not_found", "message": "API key not found."},
        )

    session = cast(AsyncSession, container.session())
    tenant_id = admin_service.user.tenant_id
    summary = await build_api_key_usage_summary(
        session=session,
        tenant_id=tenant_id,
        key_id=id,
    )
    usage_events, next_cursor = await build_api_key_usage_page(
        session=session,
        tenant_id=tenant_id,
        key_id=id,
        limit=query.limit,
        cursor=query.cursor,
    )

    return ApiKeyUsageResponse(
        summary=summary,
        items=usage_events,
        limit=query.limit,
        next_cursor=next_cursor,
    )


@router.get(
    "/api-keys/{id}",
    response_model=ApiKeyV2,
    tags=["Admin API Keys"],
    summary="Get tenant API key",
    description="Get a single API key by ID within the tenant.",
    responses={
        200: {
            "description": "Tenant API key details.",
            "content": {"application/json": {"example": _ADMIN_API_KEY_EXAMPLE}},
        },
        **error_responses([401, 403, 404, 429]),
    },
)
async def get_api_key_admin(
    id: UUID,
    container: AdminContainer,
):
    admin_service = container.admin_service()
    await admin_service.validate_admin_permission()

    repo: ApiKeysV2Repository = container.api_key_v2_repo()
    key = await repo.get(key_id=id, tenant_id=admin_service.user.tenant_id)
    if key is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "resource_not_found", "message": "API key not found."},
        )

    api_key = ApiKeyV2.model_validate(key)
    session = cast(AsyncSession, container.session())
    enriched = await _enrich_api_keys_with_user_snapshots(
        session=session,
        tenant_id=admin_service.user.tenant_id,
        keys=[api_key],
    )
    return enriched[0]


@router.patch(
    "/api-keys/{id}",
    response_model=ApiKeyV2,
    tags=["Admin API Keys"],
    summary="Update tenant API key",
    description="Update API key metadata and guardrails as tenant admin.",
    responses={
        200: {
            "description": "Updated tenant API key.",
            "content": {"application/json": {"example": _ADMIN_API_KEY_EXAMPLE}},
        },
        **error_responses([400, 401, 403, 404, 429]),
    },
)
async def update_api_key_admin(
    id: UUID,
    payload: ApiKeyUpdateRequest,
    container: AdminContainer,
    _guard: None = Depends(require_api_key_permission(ApiKeyPermission.ADMIN)),
):
    admin_service = container.admin_service()
    await admin_service.validate_admin_permission()
    lifecycle: ApiKeyLifecycleService = container.api_key_lifecycle_service()
    try:
        return await lifecycle.update_key(
            key_id=id,
            request=payload,
            skip_manage_authorization=True,
        )
    except ApiKeyValidationError as exc:
        raise_api_key_http_error(exc)


@router.delete(
    "/api-keys/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    tags=["Admin API Keys"],
    summary="Revoke API key (deprecated alias)",
    responses={
        204: {"description": "API key revoked. No response body."},
        **error_responses([401, 403, 404, 429]),
    },
    deprecated=True,
    description="Deprecated. Use POST /api/v1/admin/api-keys/{id}/revoke with reason body.",
)
async def revoke_api_key_admin_deprecated(
    id: UUID,
    container: AdminContainer,
    _guard: None = Depends(require_api_key_permission(ApiKeyPermission.ADMIN)),
) -> Response:
    admin_service = container.admin_service()
    await admin_service.validate_admin_permission()
    lifecycle: ApiKeyLifecycleService = container.api_key_lifecycle_service()
    try:
        await lifecycle.revoke_key(
            key_id=id,
            skip_manage_authorization=True,
        )
    except ApiKeyValidationError as exc:
        raise_api_key_http_error(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/api-keys/{id}/revoke",
    response_model=ApiKeyV2,
    tags=["Admin API Keys"],
    summary="Revoke tenant API key",
    description="Revoke an API key as tenant admin with optional reason metadata.",
    responses={
        200: {
            "description": "Revoked tenant API key.",
            "content": {
                "application/json": {
                    "example": _ADMIN_API_KEY_EXAMPLE | {"state": "revoked"}
                }
            },
        },
        **error_responses([400, 401, 403, 404, 429]),
    },
)
async def revoke_api_key_admin(
    id: UUID,
    container: AdminContainer,
    _guard: None = Depends(require_api_key_permission(ApiKeyPermission.ADMIN)),
    payload: Annotated[
        ApiKeyStateChangeRequest | None,
        Body(examples=[_ADMIN_API_KEY_STATE_CHANGE_EXAMPLE]),
    ] = None,
):
    admin_service = container.admin_service()
    await admin_service.validate_admin_permission()
    lifecycle: ApiKeyLifecycleService = container.api_key_lifecycle_service()
    try:
        return await lifecycle.revoke_key(
            key_id=id,
            request=payload,
            skip_manage_authorization=True,
        )
    except ApiKeyValidationError as exc:
        raise_api_key_http_error(exc)


@router.post(
    "/api-keys/{id}/suspend",
    response_model=ApiKeyV2,
    tags=["Admin API Keys"],
    summary="Suspend tenant API key",
    description="Suspend an API key so it cannot authenticate until reactivated.",
    responses={
        200: {
            "description": "Suspended tenant API key.",
            "content": {
                "application/json": {
                    "example": _ADMIN_API_KEY_EXAMPLE | {"state": "suspended"}
                }
            },
        },
        **error_responses([400, 401, 403, 404, 429]),
    },
)
async def suspend_api_key_admin(
    id: UUID,
    container: AdminContainer,
    _guard: None = Depends(require_api_key_permission(ApiKeyPermission.ADMIN)),
    payload: Annotated[
        ApiKeyStateChangeRequest | None,
        Body(examples=[_ADMIN_API_KEY_STATE_CHANGE_EXAMPLE]),
    ] = None,
):
    admin_service = container.admin_service()
    await admin_service.validate_admin_permission()
    lifecycle: ApiKeyLifecycleService = container.api_key_lifecycle_service()
    try:
        return await lifecycle.suspend_key(
            key_id=id,
            request=payload,
            skip_manage_authorization=True,
        )
    except ApiKeyValidationError as exc:
        raise_api_key_http_error(exc)


@router.post(
    "/api-keys/{id}/reactivate",
    response_model=ApiKeyV2,
    tags=["Admin API Keys"],
    summary="Reactivate tenant API key",
    description="Reactivate a suspended API key.",
    responses={
        200: {
            "description": "Reactivated tenant API key.",
            "content": {"application/json": {"example": _ADMIN_API_KEY_EXAMPLE}},
        },
        **error_responses([400, 401, 403, 404, 429]),
    },
)
async def reactivate_api_key_admin(
    id: UUID,
    container: AdminContainer,
    _guard: None = Depends(require_api_key_permission(ApiKeyPermission.ADMIN)),
):
    admin_service = container.admin_service()
    await admin_service.validate_admin_permission()
    lifecycle: ApiKeyLifecycleService = container.api_key_lifecycle_service()
    try:
        return await lifecycle.reactivate_key(
            key_id=id,
            skip_manage_authorization=True,
        )
    except ApiKeyValidationError as exc:
        raise_api_key_http_error(exc)


@router.post(
    "/api-keys/{id}/rotate",
    response_model=ApiKeyCreatedResponse,
    tags=["Admin API Keys"],
    summary="Rotate tenant API key",
    description="Rotate an API key and return the new one-time secret.",
    responses={
        200: {
            "description": "Rotated tenant API key and one-time secret.",
            "content": {
                "application/json": {"example": _ADMIN_ROTATED_RESPONSE_EXAMPLE}
            },
        },
        **error_responses([400, 401, 403, 404, 429]),
    },
)
async def rotate_api_key_admin(
    id: UUID,
    container: AdminContainer,
    _guard: None = Depends(require_api_key_permission(ApiKeyPermission.ADMIN)),
    payload: Annotated[ApiKeyRotateRequest | None, Body()] = None,
):
    admin_service = container.admin_service()
    await admin_service.validate_admin_permission()
    lifecycle: ApiKeyLifecycleService = container.api_key_lifecycle_service()
    try:
        return await lifecycle.rotate_key(
            key_id=id,
            request=payload,
            skip_manage_authorization=True,
        )
    except ApiKeyValidationError as exc:
        raise_api_key_http_error(exc)


@router.post(
    "/api-keys/{id}/extend",
    response_model=ApiKeyV2,
    tags=["Admin API Keys"],
    summary="Change tenant API key expiration",
    description=(
        "Change an API key's expiration date. Pass null to remove the expiration "
        "if the tenant policy allows it."
    ),
    responses={
        200: {
            "description": "Updated API key.",
        },
        **error_responses([400, 401, 403, 404, 429]),
    },
)
async def extend_api_key_expiration_admin(
    id: UUID,
    payload: Annotated[
        ApiKeyExtendRequest,
        Body(examples=[{"expires_at": "2030-01-01T00:00:00Z"}]),
    ],
    container: AdminContainer,
    _guard: None = Depends(require_api_key_permission(ApiKeyPermission.ADMIN)),
):
    admin_service = container.admin_service()
    await admin_service.validate_admin_permission()
    lifecycle: ApiKeyLifecycleService = container.api_key_lifecycle_service()
    try:
        return await lifecycle.extend_expiration(
            key_id=id,
            request=payload,
            skip_manage_authorization=True,
        )
    except ApiKeyValidationError as exc:
        raise_api_key_http_error(exc)


@router.post(
    "/api-keys/{id}/purge",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    tags=["Admin API Keys"],
    summary="Permanently delete tenant API key",
    description=(
        "Permanently delete a revoked or expired API key. Audit history is "
        "preserved. Active or suspended keys cannot be deleted — revoke them first."
    ),
    responses={
        204: {"description": "API key permanently deleted."},
        **error_responses([400, 401, 403, 404, 429]),
    },
)
async def purge_api_key_admin(
    id: UUID,
    container: AdminContainer,
    _guard: None = Depends(require_api_key_permission(ApiKeyPermission.ADMIN)),
) -> Response:
    admin_service = container.admin_service()
    await admin_service.validate_admin_permission()
    lifecycle: ApiKeyLifecycleService = container.api_key_lifecycle_service()
    try:
        await lifecycle.purge_key(
            key_id=id,
            skip_manage_authorization=True,
        )
    except ApiKeyValidationError as exc:
        raise_api_key_http_error(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
