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

router = APIRouter(deprecated=True)


@router.get("/users/", response_model=PaginatedResponse[UserAdminView])
async def get_users(container: Container = Depends(get_container(with_user=True))):
    service = container.admin_service()
    users = await service.get_tenant_users()

    users_admin_view = [UserAdminView(**user.model_dump()) for user in users]

    return protocol.to_paginated_response(users_admin_view)


@router.post("/users/", response_model=UserCreatedAdminView)
async def register_user(
    new_user: UserAddAdmin,
    container: Container = Depends(get_container(with_user=True)),
):
    admin_service = container.admin_service()
    user, _, api_key = await admin_service.register_tenant_user(new_user)

    user_admin_view = UserCreatedAdminView(**user.model_dump(exclude={"api_key"}), api_key=api_key)

    return user_admin_view


@router.post("/users/{username}/", response_model=UserAdminView)
async def update_user(
    username: str,
    user: UserUpdatePublic,
    container: Container = Depends(get_container(with_user=True)),
):
    """Omitted fields are not updated."""
    service = container.admin_service()
    user_updated = await service.update_tenant_user(username, user)

    user_admin_view = UserAdminView(**user_updated.model_dump())

    return user_admin_view


@router.delete("/users/{username}", response_model=DeleteResponse)
async def delete_user(username: str, container: Container = Depends(get_container(with_user=True))):
    service = container.admin_service()
    success = await service.delete_tenant_user(username)

    return DeleteResponse(success=success)


@router.post("/privacy-policy/", response_model=TenantPublic)
async def update_privacy_policy(
    url: PrivacyPolicy, container: Container = Depends(get_container(with_user=True))
):
    service = container.admin_service()
    return await service.update_privacy_policy(url)


