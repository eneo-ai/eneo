# MIT License

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from intric.ai_models.model_enums import ModelFamily, ModelHostingLocation, ModelStability
from intric.authentication.auth_dependencies import get_current_active_user
from intric.transcription_models.presentation.transcription_model_models import TranscriptionModelPublic
from intric.database.database import AsyncSession, get_session_with_transaction
from intric.server.protocol import responses
from intric.users.user import UserInDB

router = APIRouter()


class TenantTranscriptionModelCreate(BaseModel):
    provider_id: UUID = Field(..., description="Model provider ID")
    name: str = Field(
        ...,
        description="Model identifier (e.g., 'whisper-1', 'distil-whisper-large-v3-en')",
    )
    display_name: str = Field(..., description="User-friendly display name")
    is_active: bool = Field(default=True, description="Enable in organization")
    is_default: bool = Field(default=False, description="Set as default model")


class TenantTranscriptionModelUpdate(BaseModel):
    display_name: str | None = Field(None, description="User-friendly display name")
    description: str | None = Field(None, description="Model description")
    hosting: str | None = Field(None, description="Hosting location (eu, usa)")
    open_source: bool | None = Field(None, description="Is the model open source")
    stability: str | None = Field(None, description="Model stability (stable, experimental)")


@router.post(
    "/",
    response_model=TranscriptionModelPublic,
    responses=responses.get_responses([400, 404]),
)
async def create_tenant_transcription_model(
    model_create: TenantTranscriptionModelCreate,
    user: UserInDB = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session_with_transaction),
):
    """Create a new tenant-specific transcription model."""
    from intric.database.tables.ai_models_table import TranscriptionModels
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

    # If setting as default, unset all other defaults first
    if model_create.is_default:
        stmt = (
            sa.update(TranscriptionModels)
            .where(TranscriptionModels.tenant_id == user.tenant_id)
            .values(is_default=False)
        )
        await session.execute(stmt)

    # Create unique name for tenant model
    # Since name must be unique globally, prefix with tenant ID
    unique_name = f"tenant_{user.tenant_id}_{model_create.name}"

    # Create the transcription model with settings directly on it
    new_model = TranscriptionModels(
        tenant_id=user.tenant_id,
        provider_id=model_create.provider_id,
        name=unique_name,  # Unique identifier
        model_name=model_create.name,  # Actual model name from provider
        # Simplified defaults - these fields don't matter for tenant models (grouped by provider in UI)
        family=ModelFamily.OPEN_AI.value,
        hosting=ModelHostingLocation.USA.value,
        org=None,
        stability=ModelStability.STABLE.value,
        open_source=False,
        description=f"Tenant model: {model_create.display_name}",
        hf_link=None,
        is_deprecated=False,
        base_url="",  # Will be set from provider config at runtime
        # Settings (now directly on model)
        is_enabled=model_create.is_active,
        is_default=model_create.is_default,
        security_classification_id=None,
    )

    session.add(new_model)
    await session.flush()

    # Load the model BEFORE committing
    from intric.transcription_models.domain.transcription_model_repo import TranscriptionModelRepository
    repo = TranscriptionModelRepository(session, user)
    transcription_model = await repo.one(new_model.id)

    # Commit the transaction
    await session.commit()

    return TranscriptionModelPublic.from_domain(transcription_model)


@router.put(
    "/{model_id}/",
    response_model=TranscriptionModelPublic,
    responses=responses.get_responses([403, 404]),
)
async def update_tenant_transcription_model(
    model_id: UUID,
    model_update: TenantTranscriptionModelUpdate,
    user: UserInDB = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session_with_transaction),
):
    """Update a tenant-specific transcription model."""
    from intric.database.tables.ai_models_table import TranscriptionModels
    import sqlalchemy as sa
    from intric.main.exceptions import UnauthorizedException, NotFoundException

    # Verify model exists and belongs to user's tenant
    stmt = sa.select(TranscriptionModels).where(
        TranscriptionModels.id == model_id,
        TranscriptionModels.tenant_id == user.tenant_id,
    )
    result = await session.execute(stmt)
    model = result.scalar_one_or_none()

    if not model:
        raise NotFoundException("Model not found or does not belong to your organization")

    # Cannot update global models
    if model.tenant_id is None:
        raise UnauthorizedException("Cannot update global models")

    # Update fields that were provided
    if model_update.display_name is not None:
        model.description = f"Tenant model: {model_update.display_name}"
    if model_update.description is not None:
        model.description = model_update.description
    if model_update.hosting is not None:
        model.hosting = model_update.hosting
    if model_update.open_source is not None:
        model.open_source = model_update.open_source
    if model_update.stability is not None:
        model.stability = model_update.stability

    await session.flush()

    # Load the updated model
    from intric.transcription_models.domain.transcription_model_repo import TranscriptionModelRepository
    repo = TranscriptionModelRepository(session, user)
    transcription_model = await repo.one(model.id)

    await session.commit()

    return TranscriptionModelPublic.from_domain(transcription_model)


@router.delete(
    "/{model_id}/",
    responses=responses.get_responses([403, 404]),
)
async def delete_tenant_transcription_model(
    model_id: UUID,
    user: UserInDB = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session_with_transaction),
):
    """Delete a tenant-specific transcription model."""
    from intric.database.tables.ai_models_table import TranscriptionModels
    import sqlalchemy as sa
    from intric.main.exceptions import UnauthorizedException, NotFoundException

    # Verify model exists and belongs to user's tenant
    stmt = sa.select(TranscriptionModels).where(
        TranscriptionModels.id == model_id,
        TranscriptionModels.tenant_id == user.tenant_id,
    )
    result = await session.execute(stmt)
    model = result.scalar_one_or_none()

    if not model:
        raise NotFoundException("Model not found or does not belong to your organization")

    # Cannot delete global models
    if model.tenant_id is None:
        raise UnauthorizedException("Cannot delete global models")

    # Delete the model (settings are now on the model itself)
    await session.delete(model)
    await session.commit()

    return {"success": True}
