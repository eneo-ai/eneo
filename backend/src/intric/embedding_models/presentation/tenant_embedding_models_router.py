# MIT License

from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from intric.authentication.auth_dependencies import get_current_active_user
from intric.database.database import AsyncSession, get_session_with_transaction
from intric.embedding_models.presentation.embedding_model_models import (
    EmbeddingModelPublic,
)
from intric.main.container.container import Container
from intric.main.models import ModelId
from intric.roles.permissions import Permission, validate_permission
from intric.server.dependencies.container import get_container
from intric.server.protocol import responses
from intric.tenant_models.application.tenant_model_service import (
    TenantEmbeddingModelService,
)
from intric.users.user import UserInDB

router = APIRouter()


class TenantEmbeddingModelCreate(BaseModel):
    provider_id: UUID = Field(..., description="Model provider ID")
    name: str = Field(
        ...,
        description="Model identifier (e.g., 'text-embedding-3-large', 'intfloat/multilingual-e5-large')",
    )
    display_name: str = Field(..., description="User-friendly display name")
    family: str = Field(
        default="openai",
        description="Model family (e.g., 'openai', 'huggingface_e5', 'cohere', 'voyage')",
    )
    dimensions: int | None = Field(default=None, description="Embedding dimensions")
    max_input: int | None = Field(default=None, description="Maximum input tokens")
    hosting: str = Field(default="swe", description="Hosting location (swe, eu, usa)")
    is_active: bool = Field(default=True, description="Enable in organization")
    is_default: bool = Field(default=False, description="Set as default model")
    description: str | None = Field(default=None, description="Model description")
    input_cost_per_token: Decimal | None = Field(
        default=None, description="Indicative USD per input token"
    )
    output_cost_per_token: Decimal | None = Field(
        default=None, description="Indicative USD per output token (usually 0)"
    )
    security_classification: ModelId | None = Field(
        default=None, description="Security classification"
    )


class TenantEmbeddingModelUpdate(BaseModel):
    display_name: str | None = Field(None, description="User-friendly display name")
    description: str | None = Field(None, description="Model description")
    family: str | None = Field(None, description="Model family")
    dimensions: int | None = Field(None, description="Embedding dimensions")
    max_input: int | None = Field(None, description="Maximum input tokens")
    hosting: str | None = Field(None, description="Hosting location (swe, eu, usa)")
    open_source: bool | None = Field(None, description="Is the model open source")
    stability: str | None = Field(
        None, description="Model stability (stable, experimental)"
    )
    input_cost_per_token: Decimal | None = Field(
        None, description="Indicative USD per input token"
    )
    output_cost_per_token: Decimal | None = Field(
        None, description="Indicative USD per output token"
    )
    # See TenantCompletionModelUpdate for the rationale on folding these in.
    is_default: bool | None = Field(None, description="Set as tenant default")
    security_classification: ModelId | None = Field(
        None, description="Security classification reference (null clears it)"
    )


def _service(
    session: AsyncSession, user: UserInDB, container: Container
) -> TenantEmbeddingModelService:
    return TenantEmbeddingModelService(
        session=session,
        user=user,
        audit_service=container.audit_service(),
    )


@router.post(
    "/",
    response_model=EmbeddingModelPublic,
    responses=responses.get_responses([400, 404]),
)
async def create_tenant_embedding_model(
    model_create: TenantEmbeddingModelCreate,
    user: Annotated[UserInDB, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session_with_transaction)],
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    """Create a new tenant-specific embedding model."""
    validate_permission(user, Permission.ADMIN)

    service = _service(session, user, container)
    embedding_model = await service.create(model_create)
    await session.commit()

    return EmbeddingModelPublic.from_domain(embedding_model)


@router.put(
    "/{model_id}/",
    response_model=EmbeddingModelPublic,
    responses=responses.get_responses([403, 404]),
)
async def update_tenant_embedding_model(
    model_id: UUID,
    model_update: TenantEmbeddingModelUpdate,
    user: Annotated[UserInDB, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session_with_transaction)],
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    """Update a tenant-specific embedding model."""
    validate_permission(user, Permission.ADMIN)

    service = _service(session, user, container)
    embedding_model = await service.update(model_id, model_update)
    await session.commit()

    return EmbeddingModelPublic.from_domain(embedding_model)


@router.delete(
    "/{model_id}/",
    responses=responses.get_responses([403, 404]),
)
async def delete_tenant_embedding_model(
    model_id: UUID,
    user: Annotated[UserInDB, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session_with_transaction)],
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    """Delete a tenant-specific embedding model."""
    validate_permission(user, Permission.ADMIN)

    service = _service(session, user, container)
    await service.delete(model_id)
    await session.commit()

    return {"success": True}
