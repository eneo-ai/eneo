# MIT License

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from intric.ai_models.model_enums import ModelHostingLocation, ModelStability
from intric.authentication.auth_dependencies import get_current_active_user
from intric.embedding_models.presentation.embedding_model_models import EmbeddingModelPublic
from intric.database.database import AsyncSession, get_session_with_transaction
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
    is_active: bool = Field(default=True, description="Enable in organization")
    is_default: bool = Field(default=False, description="Set as default model")


@router.post(
    "/",
    response_model=EmbeddingModelPublic,
    responses=responses.get_responses([400, 404]),
)
async def create_tenant_embedding_model(
    model_create: TenantEmbeddingModelCreate,
    user: UserInDB = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session_with_transaction),
):
    """Create a new tenant-specific embedding model."""
    from intric.database.tables.ai_models_table import EmbeddingModels
    from intric.database.tables.model_providers_table import ModelProviders
    import sqlalchemy as sa
    from intric.main.exceptions import BadRequestException, NotFoundException

    # Verify provider exists and belongs to user's tenant
    stmt = sa.select(ModelProviders).where(
        ModelProviders.id == model_create.provider_id,
        ModelProviders.tenant_id == user.tenant_id,
    )
    result = await session.execute(stmt)
    provider = result.scalar_one_or_none()

    if not provider:
        raise NotFoundException("Model provider not found or does not belong to your organization")

    if not provider.is_active:
        raise BadRequestException("Model provider is not active")

    # Create the embedding model
    new_model = EmbeddingModels(
        tenant_id=user.tenant_id,
        provider_id=model_create.provider_id,
        name=model_create.name,
        litellm_model_name=None,  # Constructed at runtime by TenantModelAdapter
        dimensions=model_create.dimensions,
        max_input=model_create.max_input,
        family=model_create.family,  # User-specified family
        # Simplified defaults for other fields
        hosting=ModelHostingLocation.USA.value,
        org=None,
        stability=ModelStability.STABLE.value,
        open_source=False,
        description=f"Tenant model: {model_create.display_name}",
        hf_link=None,
        is_deprecated=False,
        max_batch_size=None,
    )

    session.add(new_model)
    await session.flush()

    # Create model settings if is_default is True or is_active
    if model_create.is_default or model_create.is_active:
        from intric.database.tables.ai_models_table import EmbeddingModelSettings

        # If setting as default, unset all other defaults first
        if model_create.is_default:
            stmt = (
                sa.update(EmbeddingModelSettings)
                .where(EmbeddingModelSettings.tenant_id == user.tenant_id)
                .values(is_org_default=False)
            )
            await session.execute(stmt)

        # Create settings for this model
        model_settings = EmbeddingModelSettings(
            embedding_model_id=new_model.id,
            tenant_id=user.tenant_id,
            is_org_enabled=model_create.is_active,
            is_org_default=model_create.is_default,
            security_classification_id=None,
        )
        session.add(model_settings)
        await session.flush()

    # Load the model with settings BEFORE committing
    from intric.embedding_models.domain.embedding_model_repo import EmbeddingModelRepository
    repo = EmbeddingModelRepository(session, user)
    embedding_model = await repo.one(new_model.id)

    # Commit the transaction
    await session.commit()

    return EmbeddingModelPublic.from_domain(embedding_model)


@router.delete(
    "/{model_id}/",
    responses=responses.get_responses([403, 404]),
)
async def delete_tenant_embedding_model(
    model_id: UUID,
    user: UserInDB = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session_with_transaction),
):
    """Delete a tenant-specific embedding model."""
    from intric.database.tables.ai_models_table import EmbeddingModels, EmbeddingModelSettings
    import sqlalchemy as sa
    from intric.main.exceptions import ForbiddenException, NotFoundException

    # Verify model exists and belongs to user's tenant
    stmt = sa.select(EmbeddingModels).where(
        EmbeddingModels.id == model_id,
        EmbeddingModels.tenant_id == user.tenant_id,
    )
    result = await session.execute(stmt)
    model = result.scalar_one_or_none()

    if not model:
        raise NotFoundException("Model not found or does not belong to your organization")

    # Cannot delete global models
    if model.tenant_id is None:
        raise ForbiddenException("Cannot delete global models")

    # Delete model settings first
    stmt = sa.delete(EmbeddingModelSettings).where(
        EmbeddingModelSettings.embedding_model_id == model_id,
        EmbeddingModelSettings.tenant_id == user.tenant_id,
    )
    await session.execute(stmt)

    # Delete the model
    await session.delete(model)
    await session.commit()

    return {"success": True}
