from fastapi import APIRouter, Depends

from intric.admin.admin_models import PrivacyPolicy, UserDeletedListItem, UserStateListItem
from intric.main.container.container import Container
from intric.main.models import DeleteResponse, PaginatedResponse
from intric.server import protocol
from intric.server.dependencies.container import get_container
from intric.tenants.tenant import TenantPublic
from intric.users.user import (
    UserAddAdmin,
    UserAdminView,
    UserCreatedAdminView,
    UserUpdatePublic,
)

router = APIRouter()


@router.get(
    "/users/", 
    response_model=PaginatedResponse[UserAdminView],
    summary="List all users in tenant",
    description="Returns all active users within your tenant. Only users from your organization will be visible. Soft-deleted users are excluded from results.",
    responses={
        200: {"description": "List of users successfully retrieved"},
        401: {"description": "Authentication required (invalid or missing API key)"},
        403: {"description": "Admin permissions required"},
    }
)
async def get_users(container: Container = Depends(get_container(with_user=True))):
    service = container.admin_service()
    users = await service.get_tenant_users()

    users_admin_view = [UserAdminView(**user.model_dump()) for user in users]

    return protocol.to_paginated_response(users_admin_view)


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
    user, _, api_key = await admin_service.register_tenant_user(new_user)

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
    user_updated = await service.update_tenant_user(username, user)

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
    success = await service.delete_tenant_user(username)

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
    user = await service.deactivate_tenant_user(username)
    
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
    user = await service.reactivate_tenant_user(username)
    
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


@router.post("/privacy-policy/", response_model=TenantPublic)
async def update_privacy_policy(
    url: PrivacyPolicy, container: Container = Depends(get_container(with_user=True))
):
    service = container.admin_service()
    return await service.update_privacy_policy(url)
