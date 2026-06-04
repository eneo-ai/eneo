from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from intric.integration.presentation.models import (
    WebsiteIntegrationConfigCreate,
    WebsiteIntegrationConfigList,
    WebsiteIntegrationConfigPublic,
    WebsiteIntegrationConfigUpdate,
)
from intric.jobs.job_models import JobPublic
from intric.main.container.container import Container
from intric.roles.permissions import Permission
from intric.server.dependencies.container import get_container

router = APIRouter()


def _require_admin(container: Container) -> None:
    user = container.user()
    if Permission.ADMIN not in user.permissions:
        from intric.main.exceptions import UnauthorizedException

        raise UnauthorizedException("Admin permission is required")


@router.get("/websites/me/configs/", response_model=WebsiteIntegrationConfigList)
async def list_my_website_integrations(
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    service = container.website_integration_service()
    items = await service.list_configs(owner_type="user")
    return WebsiteIntegrationConfigList(items=items)


@router.post("/websites/me/configs/", response_model=WebsiteIntegrationConfigPublic)
async def create_my_website_integration(
    data: WebsiteIntegrationConfigCreate,
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    service = container.website_integration_service()
    return await service.create_config(owner_type="user", payload=data)


@router.patch(
    "/websites/me/configs/{config_id}/", response_model=WebsiteIntegrationConfigPublic
)
async def update_my_website_integration(
    config_id: UUID,
    data: WebsiteIntegrationConfigUpdate,
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    service = container.website_integration_service()
    return await service.update_config(
        config_id=config_id, owner_type="user", payload=data
    )


@router.delete("/websites/me/configs/{config_id}/", status_code=204)
async def delete_my_website_integration(
    config_id: UUID,
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    service = container.website_integration_service()
    await service.delete_config(config_id=config_id, owner_type="user")


@router.get("/websites/tenant/configs/", response_model=WebsiteIntegrationConfigList)
async def list_tenant_website_integrations(
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    _require_admin(container)
    service = container.website_integration_service()
    items = await service.list_configs(owner_type="tenant")
    return WebsiteIntegrationConfigList(items=items)


@router.post("/websites/tenant/configs/", response_model=WebsiteIntegrationConfigPublic)
async def create_tenant_website_integration(
    data: WebsiteIntegrationConfigCreate,
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    _require_admin(container)
    service = container.website_integration_service()
    return await service.create_config(owner_type="tenant", payload=data)


@router.patch(
    "/websites/tenant/configs/{config_id}/",
    response_model=WebsiteIntegrationConfigPublic,
)
async def update_tenant_website_integration(
    config_id: UUID,
    data: WebsiteIntegrationConfigUpdate,
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    _require_admin(container)
    service = container.website_integration_service()
    return await service.update_config(
        config_id=config_id, owner_type="tenant", payload=data
    )


@router.delete("/websites/tenant/configs/{config_id}/", status_code=204)
async def delete_tenant_website_integration(
    config_id: UUID,
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    _require_admin(container)
    service = container.website_integration_service()
    await service.delete_config(config_id=config_id, owner_type="tenant")


@router.post(
    "/websites/{config_id}/ping/",
    response_model=JobPublic,
    status_code=202,
)
async def ping_website_integration(
    config_id: UUID,
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    service = container.website_integration_service()
    job = await service.queue_sync(config_id=config_id)
    return JobPublic.model_validate(job)
