# MIT License

from decimal import Decimal
from typing import Annotated
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from intric.authentication.auth_dependencies import get_current_active_user
from intric.database.database import AsyncSession, get_session_with_transaction
from intric.database.tables.ai_models_table import EmbeddingModels
from intric.database.tables.collections_table import CollectionsTable
from intric.database.tables.integration_table import IntegrationKnowledge
from intric.database.tables.model_providers_table import ModelProviders
from intric.database.tables.websites_table import Websites
from intric.embedding_models.domain.embedding_model_repo import EmbeddingModelRepository
from intric.embedding_models.presentation.embedding_model_models import (
    EmbeddingModelPublic,
)
from intric.main.exceptions import (
    BadRequestException,
    ModelInUseException,
    NotFoundException,
    UnauthorizedException,
)
from intric.main.models import ModelId
from intric.roles.permissions import Permission, validate_permission
from intric.security_classifications.tenant_validation import (
    resolve_tenant_security_classification,
)
from intric.server.protocol import responses
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


@router.post(
    "/",
    response_model=EmbeddingModelPublic,
    responses=responses.get_responses([400, 404]),
)
async def create_tenant_embedding_model(
    model_create: TenantEmbeddingModelCreate,
    user: Annotated[UserInDB, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session_with_transaction)],
):
    """Create a new tenant-specific embedding model."""
    validate_permission(user, Permission.ADMIN)

    # Verify provider exists and belongs to user's tenant
    stmt = sa.select(ModelProviders).where(
        ModelProviders.id == model_create.provider_id,
        ModelProviders.tenant_id == user.tenant_id,
    )
    result = await session.execute(stmt)
    provider = result.scalar_one_or_none()

    if not provider:
        raise NotFoundException(
            "Model provider not found or does not belong to your organization"
        )

    if not provider.is_active:
        raise BadRequestException("Model provider is not active")

    # If setting as default, unset all other defaults first
    if model_create.is_default:
        stmt = (
            sa.update(EmbeddingModels)
            .where(EmbeddingModels.tenant_id == user.tenant_id)
            .values(is_default=False)
        )
        await session.execute(stmt)

    security_classification_id = await resolve_tenant_security_classification(
        session,
        model_create.security_classification,
        user.tenant_id,
    )

    # Create the embedding model with settings directly on it
    new_model = EmbeddingModels(
        **dict(  # type: ignore[call-arg]
            tenant_id=user.tenant_id,
            provider_id=model_create.provider_id,
            name=model_create.name,
            litellm_model_name=None,  # Constructed at runtime by TenantModelAdapter
            dimensions=model_create.dimensions,
            max_input=model_create.max_input,
            family=model_create.family,  # User-specified family
            # Simplified defaults for other fields
            hosting=model_create.hosting,
            org=None,
            stability="stable",
            open_source=False,
            nickname=model_create.display_name,
            description=model_create.description,
            hf_link=None,
            is_deprecated=False,
            max_batch_size=None,
            input_cost_per_token=model_create.input_cost_per_token,
            output_cost_per_token=model_create.output_cost_per_token,
            # Settings (now directly on model)
            is_enabled=model_create.is_active,
            is_default=model_create.is_default,
            security_classification_id=security_classification_id,
        )
    )

    session.add(new_model)
    await session.flush()

    # Load the model BEFORE committing
    repo = EmbeddingModelRepository(session, user)
    embedding_model = await repo.one(new_model.id)

    # Commit the transaction
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
):
    """Update a tenant-specific embedding model."""
    validate_permission(user, Permission.ADMIN)

    # Verify model exists and belongs to user's tenant
    stmt = sa.select(EmbeddingModels).where(
        EmbeddingModels.id == model_id,
        EmbeddingModels.tenant_id == user.tenant_id,
    )
    result = await session.execute(stmt)
    model = result.scalar_one_or_none()

    if not model:
        raise NotFoundException(
            "Model not found or does not belong to your organization"
        )

    # Cannot update global models
    if model.tenant_id is None:
        raise UnauthorizedException("Cannot update global models")

    provided = model_update.model_fields_set

    # Update fields that were provided
    if model_update.display_name is not None:
        model.nickname = model_update.display_name
    if "description" in provided:
        model.description = model_update.description
    if model_update.family is not None:
        model.family = model_update.family
    if "dimensions" in provided:
        model.dimensions = model_update.dimensions
    if "max_input" in provided:
        model.max_input = model_update.max_input
    if model_update.hosting is not None:
        model.hosting = model_update.hosting
    if model_update.open_source is not None:
        model.open_source = model_update.open_source
    if model_update.stability is not None:
        model.stability = model_update.stability
    if "input_cost_per_token" in provided:
        model.input_cost_per_token = model_update.input_cost_per_token
    if "output_cost_per_token" in provided:
        model.output_cost_per_token = model_update.output_cost_per_token

    await session.flush()

    # Load the updated model
    repo = EmbeddingModelRepository(session, user)
    embedding_model = await repo.one(model.id)

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
):
    """Delete a tenant-specific embedding model."""
    validate_permission(user, Permission.ADMIN)

    # Verify model exists and belongs to user's tenant
    stmt = sa.select(EmbeddingModels).where(
        EmbeddingModels.id == model_id,
        EmbeddingModels.tenant_id == user.tenant_id,
    )
    result = await session.execute(stmt)
    model = result.scalar_one_or_none()

    if not model:
        raise NotFoundException(
            "Model not found or does not belong to your organization"
        )

    # Cannot delete global models
    if model.tenant_id is None:
        raise UnauthorizedException("Cannot delete global models")

    # Check if the model is in use by any collections, websites, or integrations
    usage_counts = await session.execute(
        sa.select(
            sa.select(sa.func.count())
            .where(CollectionsTable.embedding_model_id == model_id)
            .correlate(None)
            .scalar_subquery()
            .label("collections"),
            sa.select(sa.func.count())
            .where(Websites.embedding_model_id == model_id)
            .correlate(None)
            .scalar_subquery()
            .label("websites"),
            sa.select(sa.func.count())
            .where(IntegrationKnowledge.embedding_model_id == model_id)
            .correlate(None)
            .scalar_subquery()
            .label("integrations"),
        )
    )
    row = usage_counts.one()
    if row.collections > 0 or row.websites > 0 or row.integrations > 0:
        raise ModelInUseException()

    # Delete the model (settings are now on the model itself)
    try:
        await session.delete(model)
        await session.commit()
    except sa.exc.IntegrityError:
        await session.rollback()
        raise ModelInUseException()

    return {"success": True}
