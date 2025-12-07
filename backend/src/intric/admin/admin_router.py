from fastapi import APIRouter, Depends, Query
from typing import List

from intric.admin.admin_models import (
    AdminUsersQueryParams,
    PaginatedUsersResponse,
    PrivacyPolicy,
    StateFilter,
    UserDeletedListItem,
    UserStateListItem,
)
from intric.main.container.container import Container
from intric.main.exceptions import BadRequestException
from intric.main.logging import get_logger
from intric.main.models import DeleteResponse
from intric.predefined_roles.predefined_role import PredefinedRoleInDB
from intric.server.dependencies.container import get_container
from intric.tenants.tenant import TenantPublic
from intric.users.user import (
    SortField,
    SortOrder,
    UserAddAdmin,
    UserAdminView,
    UserCreatedAdminView,
    UserUpdatePublic,
)

# Audit logging - module level imports for consistency
from intric.audit.application.audit_metadata import AuditMetadata
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType

logger = get_logger(__name__)
router = APIRouter()


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
                                "predefined_roles": [],
                                "user_groups": []
                            }
                        ],
                        "metadata": {
                            "page": 1,
                            "page_size": 100,
                            "total_count": 543,
                            "total_pages": 6,
                            "has_next": True,
                            "has_previous": False
                        }
                    }
                }
            }
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
                        "instance": "/api/v1/admin/users/"
                    }
                }
            }
        },
        401: {"description": "Authentication required (invalid or missing API key)"},
        403: {"description": "Admin permissions required"},
    }
)
async def get_users(
    page: int = Query(1, ge=1, le=100, description="Page number (1-100)"),
    page_size: int = Query(100, ge=1, le=100, description="Users per page (1-100)"),
    search_email: str | None = Query(None, description="Search by email (case-insensitive, partial match)"),
    search_name: str | None = Query(None, description="Search by username (case-insensitive, partial match)"),
    sort_by: SortField = Query(SortField.EMAIL, description="Sort field (default: alphabetical by email)"),
    sort_order: SortOrder = Query(SortOrder.ASC, description="Sort order (default: ascending A-Z)"),
    state_filter: StateFilter | None = Query(None, description="Filter by user state (active includes invited, inactive for temporary leave)"),
    container: Container = Depends(get_container(with_user=True))
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
        # Create query params from FastAPI Query parameters
        query_params = AdminUsersQueryParams(
            page=page,
            page_size=page_size,
            search_email=search_email,
            search_name=search_name,
            sort_by=sort_by,
            sort_order=sort_order,
            state_filter=state_filter,
        )

        service = container.admin_service()
        result = await service.list_users_paginated(query_params)

        return result
    except ValueError as e:
        # Convert ValueError from domain validation to BadRequestException (RFC 7807 format)
        raise BadRequestException(str(e)) from e


@router.post(
    "/users/", 
    response_model=UserCreatedAdminView,
    status_code=201,
    summary="Create new user in tenant",
    description="Creates a new user account within your tenant. The user will be created with the provided credentials and automatically associated with your organization. Returns user details including a new API key for the user.",
    responses={
        201: {"description": "User successfully created"},
        400: {"description": "Invalid input data or validation errors"},
        401: {"description": "Authentication required (invalid or missing API key)"},
        403: {"description": "Admin permissions required"},
        409: {"description": "Username or email already exists in your tenant"},
    }
)
async def register_user(
    new_user: UserAddAdmin,
    container: Container = Depends(get_container(with_user=True)),
):
    """
    Create a new user account for your organization.
    
    Required fields:
    - email: Valid email address (must be unique within your tenant)
    
    Optional fields:
    - username: Unique identifier (if not provided, will use email prefix)
    - password: User password (minimum 7 characters, maximum 100)
    - quota_limit: Storage limit in bytes (minimum 1000 bytes = 1KB) 
    - roles: List of custom role IDs to assign (empty list by default)
    - predefined_roles: List of predefined role IDs to assign (empty list by default)
    
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
    user, _, api_key = await admin_service.register_tenant_user(new_user)

    # Build extra context for user creation
    extra = {
        "state": user.state.value if hasattr(user, 'state') else "active",
        "tenant_id": str(current_user.tenant_id),
        "tenant_name": current_user.tenant.display_name or current_user.tenant.name,
    }

    # Add role information from the input request
    if new_user.predefined_roles:
        from intric.database.tables.roles_table import PredefinedRoles
        import sqlalchemy as sa

        session = container.session()
        role_ids = [role.id for role in new_user.predefined_roles]
        role_query = sa.select(PredefinedRoles).where(PredefinedRoles.id.in_(role_ids))
        role_result = await session.execute(role_query)
        predefined_roles = role_result.scalars().all()

        role_names = [role.name for role in predefined_roles]
        all_permissions = set()
        for role in predefined_roles:
            all_permissions.update(role.permissions)

        if role_names:
            extra["predefined_roles"] = role_names
            extra["permissions"] = sorted(list(all_permissions))

    # Add custom roles if any
    if new_user.roles:
        from intric.database.tables.roles_table import Roles
        import sqlalchemy as sa

        session = container.session()
        custom_role_ids = [role.id for role in new_user.roles]
        role_query = sa.select(Roles).where(Roles.id.in_(custom_role_ids))
        role_result = await session.execute(role_query)
        custom_roles = role_result.scalars().all()

        if custom_roles:
            extra["roles"] = [role.name for role in custom_roles]

    # Check if user object has roles loaded (in case service returns them)
    if hasattr(user, 'predefined_roles') and user.predefined_roles and 'predefined_roles' not in extra:
        extra["predefined_roles"] = [role.name for role in user.predefined_roles]

    if hasattr(user, 'roles') and user.roles and 'roles' not in extra:
        extra["roles"] = [role.name for role in user.roles]

    if hasattr(user, 'user_groups') and user.user_groups:
        extra["user_groups"] = [group.name for group in user.user_groups]

    # Add quota limit if set
    if new_user.quota_limit:
        extra["quota_limit"] = new_user.quota_limit

    # Audit logging
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=current_user.tenant_id,
        actor_id=current_user.id,
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

    user_admin_view = UserCreatedAdminView(**user.model_dump(exclude={"api_key"}), api_key=api_key)

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
    }
)
async def get_user(
    username: str,
    container: Container = Depends(get_container(with_user=True)),
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
        400: {"description": "Invalid input data, validation errors, or cross-tenant access attempt"},
        401: {"description": "Authentication required (invalid or missing API key)"},
        403: {"description": "Admin permissions required"},
        404: {"description": "User not found in your tenant (may be soft-deleted)"},
        409: {"description": "Email already exists in your tenant"},
    }
)
async def update_user(
    username: str,
    user: UserUpdatePublic,
    container: Container = Depends(get_container(with_user=True)),
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
    - roles: List of custom role IDs (replaces existing roles)
    - predefined_roles: List of predefined role IDs (replaces existing)
    
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
    changes = {}

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
        old_roles = [role.name for role in old_user.roles] if hasattr(old_user, 'roles') and old_user.roles else []
        new_roles = [role.name for role in user_updated.roles] if hasattr(user_updated, 'roles') and user_updated.roles else []
        if old_roles != new_roles:
            changes["roles"] = {"old": old_roles, "new": new_roles}

    if user.predefined_roles is not None:
        old_pred_roles = [role.name for role in old_user.predefined_roles] if hasattr(old_user, 'predefined_roles') and old_user.predefined_roles else []
        new_pred_roles = [role.name for role in user_updated.predefined_roles] if hasattr(user_updated, 'predefined_roles') and user_updated.predefined_roles else []
        if old_pred_roles != new_pred_roles:
            changes["predefined_roles"] = {"old": old_pred_roles, "new": new_pred_roles}

    # Track permission changes (computed from role changes)
    old_permissions = sorted([p.value for p in old_user.permissions]) if hasattr(old_user, 'permissions') else []
    new_permissions = sorted([p.value for p in user_updated.permissions]) if hasattr(user_updated, 'permissions') else []

    if old_permissions != new_permissions:
        added_perms = list(set(new_permissions) - set(old_permissions))
        removed_perms = list(set(old_permissions) - set(new_permissions))
        if added_perms or removed_perms:
            changes["permissions"] = {}
            if added_perms:
                changes["permissions"]["added"] = sorted(added_perms)
            if removed_perms:
                changes["permissions"]["removed"] = sorted(removed_perms)

    # Build extra context for current state
    extra = {
        "state": user_updated.state.value if hasattr(user_updated, 'state') else None,
    }

    if hasattr(user_updated, 'predefined_roles') and user_updated.predefined_roles:
        extra["predefined_roles"] = [role.name for role in user_updated.predefined_roles]

    if hasattr(user_updated, 'roles') and user_updated.roles:
        extra["roles"] = [role.name for role in user_updated.roles]

    if hasattr(user_updated, 'user_groups') and user_updated.user_groups:
        extra["user_groups"] = [group.name for group in user_updated.user_groups]

    if hasattr(user_updated, 'quota_limit') and user_updated.quota_limit:
        extra["quota_limit"] = user_updated.quota_limit

    # Audit logging
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=current_user.tenant_id,
        actor_id=current_user.id,
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
        404: {"description": "User not found in your tenant (may already be soft-deleted)"},
    }
)
async def delete_user(username: str, container: Container = Depends(get_container(with_user=True))):
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
    extra = {
        "state": user_to_delete.state.value if hasattr(user_to_delete, 'state') else None,
    }

    if hasattr(user_to_delete, 'predefined_roles') and user_to_delete.predefined_roles:
        extra["predefined_roles"] = [role.name for role in user_to_delete.predefined_roles]

    if hasattr(user_to_delete, 'roles') and user_to_delete.roles:
        extra["roles"] = [role.name for role in user_to_delete.roles]

    if hasattr(user_to_delete, 'permissions'):
        extra["permissions"] = sorted([p.value for p in user_to_delete.permissions])

    if hasattr(user_to_delete, 'user_groups') and user_to_delete.user_groups:
        extra["user_groups"] = [group.name for group in user_to_delete.user_groups]

    if hasattr(user_to_delete, 'quota_limit') and user_to_delete.quota_limit:
        extra["quota_limit"] = user_to_delete.quota_limit

    # Audit logging
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=current_user.tenant_id,
        actor_id=current_user.id,
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
        400: {"description": "Cannot deactivate yourself or cross-tenant access attempt"},
        401: {"description": "Authentication required (invalid or missing API key)"},
        403: {"description": "Admin permissions required"},
        404: {"description": "User not found in your tenant"},
    }
)
async def deactivate_user(
    username: str, 
    container: Container = Depends(get_container(with_user=True))
):
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
        actor_id=current_user.id,
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
    }
)
async def reactivate_user(
    username: str,
    container: Container = Depends(get_container(with_user=True))
):
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
        actor_id=current_user.id,
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
    }
)
async def get_inactive_users(container: Container = Depends(get_container(with_user=True))):
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
    }
)
async def get_deleted_users(container: Container = Depends(get_container(with_user=True))):
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
    response_model=List[PredefinedRoleInDB],
    summary="Get predefined roles for tenant",
    description="Retrieves all predefined roles available for the authenticated tenant. Requires tenant admin (owner) permissions. Returns the same structure as the sysadmin endpoint for consistency.",
    responses={
        200: {
            "description": "List of predefined roles successfully retrieved",
            "content": {
                "application/json": {
                    "example": [
                        {
                            "id": "550e8400-e29b-41d4-a716-446655440001",
                            "name": "Owner",
                            "permissions": ["admin", "AI", "assistants", "group_chats"],
                            "created_at": "2024-01-15T10:30:00Z",
                            "updated_at": "2024-01-15T10:30:00Z"
                        },
                        {
                            "id": "550e8400-e29b-41d4-a716-446655440002",
                            "name": "AI Configurator",
                            "permissions": ["AI", "assistants"],
                            "created_at": "2024-01-15T10:30:00Z",
                            "updated_at": "2024-01-15T10:30:00Z"
                        }
                    ]
                }
            }
        },
        401: {"description": "Authentication required (invalid or missing API key)"},
        403: {"description": "Admin permissions required (owner role)"},
        500: {"description": "Internal server error while fetching predefined roles"},
    }
)
async def get_predefined_roles(container: Container = Depends(get_container(with_user=True))):
    """
    Get all predefined roles available for your tenant.

    This endpoint returns the predefined roles that can be assigned to users
    when creating or updating user accounts. The response format matches the
    sysadmin endpoint for API consistency.

    Predefined roles include:
    - **Owner**: Full admin permissions including user management
    - **AI Configurator**: AI and assistant configuration permissions
    - **User**: Basic user permissions for using assistants

    ## Important Notes

    - This endpoint requires admin (owner) permissions
    - Returns the same roles for all tenants (future: tenant-specific filtering)
    - Role IDs are stable and can be cached client-side
    - Use these IDs in POST /api/v1/admin/users/ for user provisioning

    ## Response Format

    Returns an array of PredefinedRoleInDB objects containing:
    - `id`: UUID of the role (use this when assigning roles)
    - `name`: Human-readable name of the role
    - `permissions`: List of permission strings granted by this role
    - `created_at`: Timestamp when the role was created
    - `updated_at`: Timestamp when the role was last modified
    """
    # Get admin service and validate permissions
    admin_service = container.admin_service()
    user = admin_service.user

    # Log the request for audit trail
    logger.info(
        f"Admin user '{user.username}' (ID: {user.id}) from tenant '{user.tenant_id}' "
        f"is retrieving predefined roles"
    )

    # Validate admin permissions (will raise UnauthorizedException if not admin)
    await admin_service.validate_admin_permission()

    # Get the predefined roles service
    predefined_role_service = container.predefined_role_service()

    # Fetch all predefined roles
    roles = await predefined_role_service.get_predefined_roles()

    # Log successful retrieval
    logger.info(
        f"Successfully retrieved {len(roles)} predefined roles for admin user "
        f"'{user.username}' in tenant '{user.tenant_id}'. "
        f"Roles: {[role.name for role in roles]}"
    )

    # Future enhancement: Filter roles based on tenant subscription/features
    # For now, return all roles as per requirements
    return roles


@router.post("/privacy-policy/", response_model=TenantPublic)
async def update_privacy_policy(
    url: PrivacyPolicy, container: Container = Depends(get_container(with_user=True))
):
    service = container.admin_service()
    user = container.user()

    # Update privacy policy
    updated_tenant = await service.update_privacy_policy(url)

    # Audit logging
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
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
