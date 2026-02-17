# MIT License

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from intric.ai_models.model_enums import ModelStability
from intric.authentication.auth_dependencies import get_current_active_user
from intric.completion_models.presentation import CompletionModelPublic
from intric.database.database import AsyncSession, get_session_with_transaction
from intric.main.container.container import Container
from intric.server.dependencies.container import get_container
from intric.server.protocol import responses
from intric.users.user import UserInDB

router = APIRouter()


class TenantCompletionModelCreate(BaseModel):
    provider_id: UUID = Field(..., description="Model provider ID")
    name: str = Field(
        ...,
        description="Model identifier (e.g., 'gpt-4o', 'meta-llama/Meta-Llama-3-70B-Instruct')",
    )
    display_name: str = Field(..., description="User-friendly display name")
    token_limit: int = Field(default=128000, description="Maximum context tokens")
    vision: bool = Field(default=False, description="Supports vision/image inputs")
    reasoning: bool = Field(default=False, description="Supports extended reasoning")
    hosting: str = Field(default="swe", description="Hosting location (swe, eu, usa)")
    family: str = Field(default="openai", description="Model family (e.g., 'openai', 'anthropic', 'deepseek')")
    is_active: bool = Field(default=True, description="Enable in organization")
    is_default: bool = Field(default=False, description="Set as default model")


class TenantCompletionModelUpdate(BaseModel):
    name: str | None = Field(None, description="Model identifier (e.g., 'gpt-4o', 'claude-3-sonnet')")
    display_name: str | None = Field(None, description="User-friendly display name")
    description: str | None = Field(None, description="Model description")
    token_limit: int | None = Field(None, description="Maximum context tokens")
    vision: bool | None = Field(None, description="Supports vision/image inputs")
    reasoning: bool | None = Field(None, description="Supports extended reasoning")
    hosting: str | None = Field(None, description="Hosting location (swe, eu, usa)")
    open_source: bool | None = Field(None, description="Is the model open source")
    stability: str | None = Field(None, description="Model stability (stable, experimental)")


@router.post(
    "/",
    response_model=CompletionModelPublic,
    responses=responses.get_responses([400, 404]),
)
async def create_tenant_completion_model(
    model_create: TenantCompletionModelCreate,
    user: UserInDB = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session_with_transaction),
    container: Container = Depends(get_container(with_user=True)),
):
    """Create a new tenant-specific completion model."""
    from intric.database.tables.ai_models_table import CompletionModels
    from intric.database.tables.model_providers_table import ModelProviders
    import sqlalchemy as sa
    from intric.main.exceptions import BadRequestException, NotFoundException

    assembler = container.completion_model_assembler()

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
            sa.update(CompletionModels)
            .where(CompletionModels.tenant_id == user.tenant_id)
            .values(is_default=False)
        )
        await session.execute(stmt)

    # Create the completion model with settings directly on it
    # Note: litellm_model_name is set to None - TenantModelAdapter constructs it
    # at runtime as f"{provider.provider_type}/{model.name}"
    new_model = CompletionModels(
        tenant_id=user.tenant_id,
        provider_id=model_create.provider_id,
        name=model_create.name,  # Model identifier (may contain slashes)
        nickname=model_create.display_name,
        litellm_model_name=None,  # Constructed at runtime by TenantModelAdapter
        token_limit=model_create.token_limit,
        vision=model_create.vision,
        reasoning=model_create.reasoning,
        # Simplified defaults - these fields don't matter for tenant models (grouped by provider in UI)
        family=model_create.family,
        hosting=model_create.hosting,
        org=None,
        stability=ModelStability.STABLE.value,
        open_source=False,
        description=f"Tenant model: {model_create.display_name}",
        nr_billion_parameters=None,
        hf_link=None,
        is_deprecated=False,
        deployment_name=None,
        base_url=None,
        # Settings (now directly on model)
        is_enabled=model_create.is_active,
        is_default=model_create.is_default,
        security_classification_id=None,
    )

    session.add(new_model)
    await session.flush()

    # Load the model BEFORE committing
    from intric.completion_models.domain.completion_model_repo import CompletionModelRepository
    repo = CompletionModelRepository(session, user)
    completion_model = await repo.one(new_model.id)

    # Commit the transaction
    await session.commit()

    return assembler.from_completion_model_to_model(completion_model=completion_model)


@router.put(
    "/{model_id}/",
    response_model=CompletionModelPublic,
    responses=responses.get_responses([403, 404]),
)
async def update_tenant_completion_model(
    model_id: UUID,
    model_update: TenantCompletionModelUpdate,
    user: UserInDB = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session_with_transaction),
    container: Container = Depends(get_container(with_user=True)),
):
    """Update a tenant-specific completion model."""
    from intric.database.tables.ai_models_table import CompletionModels
    import sqlalchemy as sa
    from intric.main.exceptions import UnauthorizedException, NotFoundException

    assembler = container.completion_model_assembler()

    # Verify model exists and belongs to user's tenant
    stmt = sa.select(CompletionModels).where(
        CompletionModels.id == model_id,
        CompletionModels.tenant_id == user.tenant_id,
    )
    result = await session.execute(stmt)
    model = result.scalar_one_or_none()

    if not model:
        raise NotFoundException("Model not found or does not belong to your organization")

    # Cannot update global models
    if model.tenant_id is None:
        raise UnauthorizedException("Cannot update global models")

    # Update fields that were provided
    if model_update.name is not None:
        model.name = model_update.name
    if model_update.display_name is not None:
        model.nickname = model_update.display_name
    if model_update.description is not None:
        model.description = model_update.description
    if model_update.token_limit is not None:
        model.token_limit = model_update.token_limit
    if model_update.vision is not None:
        model.vision = model_update.vision
    if model_update.reasoning is not None:
        model.reasoning = model_update.reasoning
    if model_update.hosting is not None:
        model.hosting = model_update.hosting
    if model_update.open_source is not None:
        model.open_source = model_update.open_source
    if model_update.stability is not None:
        model.stability = model_update.stability

    await session.flush()

    # Load the updated model
    from intric.completion_models.domain.completion_model_repo import CompletionModelRepository
    repo = CompletionModelRepository(session, user)
    completion_model = await repo.one(model.id)

    await session.commit()

    return assembler.from_completion_model_to_model(completion_model=completion_model)


@router.delete(
    "/{model_id}/",
    responses=responses.get_responses([403, 404]),
)
async def delete_tenant_completion_model(
    model_id: UUID,
    user: UserInDB = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session_with_transaction),
):
    """Delete a tenant-specific completion model."""
    from intric.database.tables.ai_models_table import CompletionModels
    import sqlalchemy as sa
    from intric.main.exceptions import UnauthorizedException, NotFoundException, BadRequestException

    # Verify model exists and belongs to user's tenant
    stmt = sa.select(CompletionModels).where(
        CompletionModels.id == model_id,
        CompletionModels.tenant_id == user.tenant_id,
    )
    result = await session.execute(stmt)
    model = result.scalar_one_or_none()

    if not model:
        raise NotFoundException("Model not found or does not belong to your organization")

    # Cannot delete global models
    if model.tenant_id is None:
        raise UnauthorizedException("Cannot delete global models")

    # Delete the model (settings are now on the model itself)
    try:
        await session.delete(model)
        await session.commit()
    except sa.exc.IntegrityError:
        await session.rollback()
        raise BadRequestException("MODEL_IN_USE")

    return {"success": True}
