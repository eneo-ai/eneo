# MIT License

from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from intric.authentication.auth_dependencies import get_current_active_user
from intric.completion_models.presentation import CompletionModelPublic
from intric.database.database import AsyncSession, get_session_with_transaction
from intric.main.container.container import Container
from intric.main.models import ModelId
from intric.roles.permissions import Permission, validate_permission
from intric.server.dependencies.container import get_container
from intric.server.protocol import responses
from intric.tenant_models.application.tenant_model_service import (
    TenantCompletionModelService,
)
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
    description: str | None = None
    # Indicative USD per token. Pulled from LiteLLM by the wizard, or entered
    # manually by the admin. NULL = not tracked.
    input_cost_per_token: Decimal | None = None
    output_cost_per_token: Decimal | None = None
    security_classification: ModelId | None = None


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
    input_cost_per_token: Decimal | None = None
    output_cost_per_token: Decimal | None = None
    # Cross-cutting fields that used to live on the legacy /models/{id} update
    # endpoint. Folded in so the edit dialog can save everything in one round
    # trip — partial-success ("display name saved, classification didn't")
    # was the worst-case before. `is_default=True` unsets sibling defaults in
    # the same transaction; `security_classification` is validated against
    # the caller's tenant.
    is_default: bool | None = None
    security_classification: ModelId | None = None


def _service(
    session: AsyncSession, user: UserInDB, container: Container
) -> TenantCompletionModelService:
    return TenantCompletionModelService(
        session=session,
        user=user,
        audit_service=container.audit_service(),
    )


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
    assembler = container.completion_model_assembler()

    service = _service(session, user, container)
    completion_model = await service.create(model_create)
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
    assembler = container.completion_model_assembler()

    service = _service(session, user, container)
    completion_model = await service.update(model_id, model_update)
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
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    """Soft-delete a tenant-specific completion model."""
    validate_permission(user, Permission.ADMIN)

    service = _service(session, user, container)
    await service.delete(model_id)
    await session.commit()

    return {"success": True}
