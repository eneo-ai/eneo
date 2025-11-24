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

    # Create unique name for tenant model
    # Since name must be unique globally, prefix with tenant ID
    unique_name = f"tenant_{user.tenant_id}_{model_create.name}"

    # Create the transcription model
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
    )

    session.add(new_model)
    await session.flush()

    # Create model settings if is_default is True or is_active
    if model_create.is_default or model_create.is_active:
        from intric.database.tables.ai_models_table import TranscriptionModelSettings

        # If setting as default, unset all other defaults first
        if model_create.is_default:
            stmt = (
                sa.update(TranscriptionModelSettings)
                .where(TranscriptionModelSettings.tenant_id == user.tenant_id)
                .values(is_org_default=False)
            )
            await session.execute(stmt)

        # Create settings for this model
        model_settings = TranscriptionModelSettings(
            transcription_model_id=new_model.id,
            tenant_id=user.tenant_id,
            is_org_enabled=model_create.is_active,
            is_org_default=model_create.is_default,
            security_classification_id=None,
        )
        session.add(model_settings)
        await session.flush()

    # Load the model with settings BEFORE committing
    from intric.transcription_models.domain.transcription_model_repo import TranscriptionModelRepository
    repo = TranscriptionModelRepository(session, user)
    transcription_model = await repo.one(new_model.id)

    # Commit the transaction
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
    from intric.database.tables.ai_models_table import TranscriptionModels, TranscriptionModelSettings
    import sqlalchemy as sa
    from intric.main.exceptions import ForbiddenException, NotFoundException

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
        raise ForbiddenException("Cannot delete global models")

    # Delete model settings first
    stmt = sa.delete(TranscriptionModelSettings).where(
        TranscriptionModelSettings.transcription_model_id == model_id,
        TranscriptionModelSettings.tenant_id == user.tenant_id,
    )
    await session.execute(stmt)

    # Delete the model
    await session.delete(model)
    await session.commit()

    return {"success": True}
