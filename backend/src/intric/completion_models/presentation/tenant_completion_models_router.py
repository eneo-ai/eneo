# MIT License

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from intric.authentication.auth_dependencies import get_current_active_user
from intric.completion_models.presentation import CompletionModelPublic
from intric.database.database import AsyncSession, get_session_with_transaction
from intric.main.container.container import Container
from intric.roles.permissions import Permission, validate_permission
from intric.server.dependencies.container import get_container
from intric.server.protocol import responses
from intric.users.user import UserInDB

router = APIRouter()


class TenantCompletionModelCreate(BaseModel):
    provider_id: UUID
    name: str
    display_name: str
    max_input_tokens: int
    max_output_tokens: int
    vision: bool = False
    reasoning: bool = False
    supports_tool_calling: bool = False
    hosting: str = "swe"
    family: str = "openai"
    is_active: bool = True
    is_default: bool = False


class TenantCompletionModelUpdate(BaseModel):
    name: str | None = None
    display_name: str | None = None
    description: str | None = None
    max_input_tokens: int | None = None
    max_output_tokens: int | None = None
    vision: bool | None = None
    reasoning: bool | None = None
    supports_tool_calling: bool | None = None
    hosting: str | None = None
    open_source: bool | None = None
    stability: str | None = None


@router.post(
    "/",
    response_model=CompletionModelPublic,
    responses=responses.get_responses([400, 404]),
)
async def create_tenant_completion_model(
    model_create: TenantCompletionModelCreate,
    user: Annotated[UserInDB, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session_with_transaction)],
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    """Create a new tenant-specific completion model."""
    validate_permission(user, Permission.ADMIN)
    import sqlalchemy as sa

    from intric.database.tables.ai_models_table import CompletionModels
    from intric.database.tables.model_providers_table import ModelProviders
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
        raise NotFoundException(
            "Model provider not found or does not belong to your organization"
        )

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
    new_model = CompletionModels()
    new_model.tenant_id = user.tenant_id
    new_model.provider_id = model_create.provider_id
    new_model.name = model_create.name  # Model identifier (may contain slashes)
    new_model.nickname = model_create.display_name
    new_model.litellm_model_name = None  # Constructed at runtime by TenantModelAdapter
    new_model.max_input_tokens = model_create.max_input_tokens
    new_model.max_output_tokens = model_create.max_output_tokens
    new_model.vision = model_create.vision
    new_model.reasoning = model_create.reasoning
    new_model.supports_tool_calling = model_create.supports_tool_calling
    # Simplified defaults - these fields don't matter for tenant models (grouped by provider in UI)
    new_model.family = model_create.family
    new_model.hosting = model_create.hosting
    new_model.org = None
    new_model.stability = "stable"
    new_model.open_source = False
    new_model.description = f"Tenant model: {model_create.display_name}"
    new_model.nr_billion_parameters = None
    new_model.hf_link = None
    new_model.is_deprecated = False
    new_model.deployment_name = None
    new_model.base_url = None
    # Settings (now directly on model)
    new_model.is_enabled = model_create.is_active
    new_model.is_default = model_create.is_default
    new_model.security_classification_id = None

    session.add(new_model)
    await session.flush()

    # Load the model BEFORE committing
    from intric.completion_models.domain.completion_model_repo import (
        CompletionModelRepository,
    )

    repo = CompletionModelRepository(session, user)
    completion_model = await repo.one(model_id=new_model.id)

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
    user: Annotated[UserInDB, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session_with_transaction)],
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    """Update a tenant-specific completion model."""
    validate_permission(user, Permission.ADMIN)
    import sqlalchemy as sa

    from intric.database.tables.ai_models_table import CompletionModels
    from intric.main.exceptions import NotFoundException, UnauthorizedException

    assembler = container.completion_model_assembler()

    # Verify model exists and belongs to user's tenant
    stmt = sa.select(CompletionModels).where(
        CompletionModels.id == model_id,
        CompletionModels.tenant_id == user.tenant_id,
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

    # Update fields that were provided
    if model_update.name is not None:
        model.name = model_update.name
    if model_update.display_name is not None:
        model.nickname = model_update.display_name
    if model_update.description is not None:
        model.description = model_update.description
    if model_update.max_input_tokens is not None:
        model.max_input_tokens = model_update.max_input_tokens
    if model_update.max_output_tokens is not None:
        model.max_output_tokens = model_update.max_output_tokens
    if model_update.vision is not None:
        model.vision = model_update.vision
    if model_update.reasoning is not None:
        model.reasoning = model_update.reasoning
    if model_update.supports_tool_calling is not None:
        model.supports_tool_calling = model_update.supports_tool_calling
    if model_update.hosting is not None:
        model.hosting = model_update.hosting
    if model_update.open_source is not None:
        model.open_source = model_update.open_source
    if model_update.stability is not None:
        model.stability = model_update.stability

    await session.flush()

    # Load the updated model
    from intric.completion_models.domain.completion_model_repo import (
        CompletionModelRepository,
    )

    repo = CompletionModelRepository(session, user)
    completion_model = await repo.one(model_id=model.id)

    await session.commit()

    return assembler.from_completion_model_to_model(completion_model=completion_model)


@router.delete(
    "/{model_id}/",
    responses=responses.get_responses([403, 404]),
)
async def delete_tenant_completion_model(
    model_id: UUID,
    user: Annotated[UserInDB, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session_with_transaction)],
):
    """Delete a tenant-specific completion model."""
    validate_permission(user, Permission.ADMIN)
    import sqlalchemy as sa

    from intric.database.tables.ai_models_table import CompletionModels
    from intric.main.exceptions import (
        BadRequestException,
        NotFoundException,
        UnauthorizedException,
    )

    # Verify model exists and belongs to user's tenant
    stmt = sa.select(CompletionModels).where(
        CompletionModels.id == model_id,
        CompletionModels.tenant_id == user.tenant_id,
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

    # Delete the model (settings are now on the model itself)
    try:
        await session.delete(model)
        await session.commit()
    except sa.exc.IntegrityError:
        await session.rollback()
        raise BadRequestException("MODEL_IN_USE")

    return {"success": True}
