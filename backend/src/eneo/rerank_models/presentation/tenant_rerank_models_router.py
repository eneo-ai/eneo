from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from eneo.authentication.auth_dependencies import get_current_active_user
from eneo.authentication.endpoint_access import Authentication, endpoint_access
from eneo.database.database import AsyncSession, get_session_with_transaction
from eneo.main.container.container import Container
from eneo.main.models import ModelId
from eneo.rerank_models.presentation.rerank_model_models import RerankModelPublic
from eneo.roles.permissions import Permission
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses
from eneo.tenant_models.application.tenant_model_service import (
    TenantRerankModelService,
)
from eneo.users.user import UserInDB

CurrentUser = Annotated[UserInDB, Depends(get_current_active_user)]
DBSession = Annotated[AsyncSession, Depends(get_session_with_transaction)]
ContainerDep = Annotated[Container, Depends(get_container(with_user=True))]

router = APIRouter()


class TenantRerankModelCreate(BaseModel):
    provider_id: UUID = Field(..., description="Model provider ID")
    name: str = Field(
        ...,
        max_length=200,
        description=(
            "Model identifier as served by the provider (e.g. 'rerank-v3.5', "
            "'jina-reranker-v2-base-multilingual', or the name a TEI endpoint serves)"
        ),
    )
    display_name: str = Field(..., description="User-friendly display name")
    hosting: str = Field(default="swe", description="Hosting location (swe, eu, usa)")
    family: str | None = Field(
        default=None,
        description="Model family; defaults to the provider type (e.g. 'cohere')",
    )
    is_active: bool = Field(default=True, description="Enable in organization")
    is_default: bool = Field(default=False, description="Set as default model")
    description: str | None = Field(default=None, description="Model description")
    security_classification: ModelId | None = Field(
        default=None, description="Security classification"
    )


class TenantRerankModelUpdate(BaseModel):
    display_name: str | None = Field(None, description="User-friendly display name")
    description: str | None = Field(None, description="Model description")
    hosting: str | None = Field(None, description="Hosting location (swe, eu, usa)")
    open_source: bool | None = Field(None, description="Is the model open source")
    stability: str | None = Field(
        None, description="Model stability (stable, experimental)"
    )
    # See TenantCompletionModelUpdate for the rationale on folding these in.
    is_default: bool | None = Field(None, description="Set as tenant default")
    security_classification: ModelId | None = Field(
        None, description="Security classification reference (null clears it)"
    )


def _service(
    session: AsyncSession, user: UserInDB, container: Container
) -> TenantRerankModelService:
    return TenantRerankModelService(
        session=session,
        user=user,
        audit_service=container.audit_service(),
    )


@router.post(
    "/",
    description="Create a new tenant-specific rerank model.",
    response_model=RerankModelPublic,
    responses=responses.get_responses([400, 403, 404, 409]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Permission.ADMIN,
    reason="This operation requires Permission.ADMIN before accessing tenant resources.",
)
async def create_tenant_rerank_model(
    model_create: TenantRerankModelCreate,
    user: CurrentUser,
    session: DBSession,
    container: ContainerDep,
):
    service = _service(session, user, container)
    rerank_model = await service.create(model_create)
    await session.commit()

    return RerankModelPublic.from_domain(rerank_model)


@router.put(
    "/{model_id}/",
    description="Update a tenant-specific rerank model.",
    response_model=RerankModelPublic,
    responses=responses.get_responses([403, 404, 409]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Permission.ADMIN,
    reason="This operation requires Permission.ADMIN before accessing tenant resources.",
)
async def update_tenant_rerank_model(
    model_id: UUID,
    model_update: TenantRerankModelUpdate,
    user: CurrentUser,
    session: DBSession,
    container: ContainerDep,
):
    service = _service(session, user, container)
    rerank_model = await service.update(model_id, model_update)
    await session.commit()

    return RerankModelPublic.from_domain(rerank_model)


@router.delete(
    "/{model_id}/",
    description="Delete a tenant-specific rerank model.",
    response_model=None,
    responses=responses.get_responses([400, 403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Permission.ADMIN,
    reason="This operation requires Permission.ADMIN before accessing tenant resources.",
)
async def delete_tenant_rerank_model(
    model_id: UUID,
    user: CurrentUser,
    session: DBSession,
    container: ContainerDep,
):
    service = _service(session, user, container)
    await service.delete(model_id)
    await session.commit()

    return {"success": True}
