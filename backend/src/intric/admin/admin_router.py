from fastapi import APIRouter, Depends

from intric.admin.admin_models import PrivacyPolicy
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


@router.post("/privacy-policy/", response_model=TenantPublic)
async def update_privacy_policy(
    url: PrivacyPolicy, container: Container = Depends(get_container(with_user=True))
):
    service = container.admin_service()
    return await service.update_privacy_policy(url)
