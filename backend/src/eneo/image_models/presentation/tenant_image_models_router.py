# MIT License

from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from eneo.authentication.auth_dependencies import get_current_active_user
from eneo.database.database import AsyncSession, get_session_with_transaction
from eneo.image_models.presentation.image_model_models import (
    ImageModelPublic,
    ImageQuality,
    ImageSize,
)
from eneo.main.container.container import Container
from eneo.main.models import ModelId
from eneo.roles.permissions import Permission, validate_permission
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses
from eneo.tenant_models.application.tenant_model_service import (
    TenantImageModelService,
)
from eneo.users.user import UserInDB

CurrentUser = Annotated[UserInDB, Depends(get_current_active_user)]
DBSession = Annotated[AsyncSession, Depends(get_session_with_transaction)]
ContainerDep = Annotated[Container, Depends(get_container(with_user=True))]

router = APIRouter()


class TenantImageModelCreate(BaseModel):
    provider_id: UUID = Field(..., description="Model provider ID")
    name: str = Field(
        ...,
        max_length=200,
        description=(
            "Model identifier as served by the provider (e.g. 'gpt-image-1', "
            "'imagen-4.0-generate-001', or the name a vLLM endpoint serves)"
        ),
    )
    display_name: str = Field(..., description="User-friendly display name")
    hosting: str = Field(default="swe", description="Hosting location (swe, eu, usa)")
    family: str = Field(
        default="openai",
        description="Model family (e.g., 'openai', 'google')",
    )
    is_active: bool = Field(default=True, description="Enable in organization")
    is_default: bool = Field(default=False, description="Set as default model")
    description: str | None = Field(default=None, description="Model description")
    cost_per_image: Decimal | None = Field(
        default=None, description="Indicative USD per generated image"
    )
    default_size: ImageSize = Field(
        default="auto", description="Size used when the assistant does not ask"
    )
    default_quality: ImageQuality = Field(
        default="auto", description="Quality used when the assistant does not ask"
    )
    security_classification: ModelId | None = Field(
        default=None, description="Security classification"
    )


class TenantImageModelUpdate(BaseModel):
    display_name: str | None = Field(None, description="User-friendly display name")
    description: str | None = Field(None, description="Model description")
    hosting: str | None = Field(None, description="Hosting location (swe, eu, usa)")
    open_source: bool | None = Field(None, description="Is the model open source")
    stability: str | None = Field(
        None, description="Model stability (stable, experimental)"
    )
    cost_per_image: Decimal | None = Field(
        None, description="Indicative USD per generated image"
    )
    default_size: ImageSize | None = Field(
        None, description="Size used when the assistant does not ask"
    )
    default_quality: ImageQuality | None = Field(
        None, description="Quality used when the assistant does not ask"
    )
    # See TenantCompletionModelUpdate for the rationale on folding these in.
    is_default: bool | None = Field(None, description="Set as tenant default")
    security_classification: ModelId | None = Field(
        None, description="Security classification reference (null clears it)"
    )


def _service(
    session: AsyncSession, user: UserInDB, container: Container
) -> TenantImageModelService:
    return TenantImageModelService(
        session=session,
        user=user,
        audit_service=container.audit_service(),
    )


@router.post(
    "/",
    description="Create a new tenant-specific image model.",
    response_model=ImageModelPublic,
    responses=responses.get_responses([400, 403, 404, 409]),
)
async def create_tenant_image_model(
    model_create: TenantImageModelCreate,
    user: CurrentUser,
    session: DBSession,
    container: ContainerDep,
):
    validate_permission(user, Permission.ADMIN)

    service = _service(session, user, container)
    image_model = await service.create(model_create)
    await session.commit()

    return ImageModelPublic.from_domain(image_model)


@router.put(
    "/{model_id}/",
    description="Update a tenant-specific image model.",
    response_model=ImageModelPublic,
    responses=responses.get_responses([403, 404, 409]),
)
async def update_tenant_image_model(
    model_id: UUID,
    model_update: TenantImageModelUpdate,
    user: CurrentUser,
    session: DBSession,
    container: ContainerDep,
):
    validate_permission(user, Permission.ADMIN)

    service = _service(session, user, container)
    image_model = await service.update(model_id, model_update)
    await session.commit()

    return ImageModelPublic.from_domain(image_model)


@router.delete(
    "/{model_id}/",
    description="Delete a tenant-specific image model.",
    response_model=None,
    responses=responses.get_responses([400, 403, 404]),
)
async def delete_tenant_image_model(
    model_id: UUID,
    user: CurrentUser,
    session: DBSession,
    container: ContainerDep,
):
    validate_permission(user, Permission.ADMIN)

    service = _service(session, user, container)
    await service.delete(model_id)
    await session.commit()

    return {"success": True}
