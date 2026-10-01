# MIT License

from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, field_validator

from eneo.ai_models.completion_models.completion_model import (
    TOKEN_LIMIT_UPDATE_SCHEMA,
    refuse_blank_token_limit,
)
from eneo.authentication.auth_dependencies import get_current_active_user
from eneo.authentication.endpoint_access import Authentication, endpoint_access
from eneo.completion_models.domain.model_kwargs_capabilities import (
    SupportedModelKwargs,
)
from eneo.completion_models.presentation import CompletionModelPublic
from eneo.database.database import AsyncSession, get_session_with_transaction
from eneo.main.container.container import Container
from eneo.main.models import ModelId
from eneo.roles.permissions import Permission
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses
from eneo.tenant_models.application.tenant_model_service import (
    TenantCompletionModelService,
)
from eneo.users.user import UserInDB

router = APIRouter()


class TenantCompletionModelCreate(BaseModel):
    provider_id: UUID
    name: str
    display_name: str
    max_input_tokens: int = Field(gt=0)
    max_output_tokens: int = Field(gt=0)
    vision: bool = False
    reasoning: bool = False
    supports_tool_calling: bool = False
    supports_strict_tool_schema: bool = False
    hosting: str = "swe"
    family: str = "openai"
    is_active: bool = True
    is_default: bool = False
    description: str | None = None
    # Indicative USD per token. Pulled from LiteLLM by the wizard, or entered
    # manually by the admin. NULL = not tracked.
    input_cost_per_token: Decimal | None = None
    output_cost_per_token: Decimal | None = None
    model_kwargs_capabilities: SupportedModelKwargs | None = None
    security_classification: ModelId | None = None


class TenantCompletionModelUpdate(BaseModel):
    model_config = ConfigDict(json_schema_extra=TOKEN_LIMIT_UPDATE_SCHEMA)

    name: str | None = None
    display_name: str | None = None
    description: str | None = None
    max_input_tokens: int | None = Field(default=None, gt=0)
    max_output_tokens: int | None = Field(default=None, gt=0)
    vision: bool | None = None
    reasoning: bool | None = None
    supports_tool_calling: bool | None = None
    supports_strict_tool_schema: bool | None = None
    hosting: str | None = None
    open_source: bool | None = None
    stability: str | None = None
    input_cost_per_token: Decimal | None = None
    output_cost_per_token: Decimal | None = None
    model_kwargs_capabilities: SupportedModelKwargs | None = None
    # Cross-cutting fields that used to live on the legacy /models/{id} update
    # endpoint. Folded in so the edit dialog can save everything in one round
    # trip — partial-success ("display name saved, classification didn't")
    # was the worst-case before. `is_default=True` unsets sibling defaults in
    # the same transaction; `security_classification` is validated against
    # the caller's tenant.
    is_default: bool | None = None
    security_classification: ModelId | None = None

    @field_validator("max_input_tokens", "max_output_tokens")
    @classmethod
    def _refuse_blank_token_limit(cls, value: int | None) -> int | None:
        # Omitting a limit keeps it; null would leave the model unable to
        # serve any request, so it is refused rather than stored.
        return refuse_blank_token_limit(value)


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
    description="Create a new tenant-specific completion model.",
    responses=responses.get_responses([400, 403, 404, 409]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Permission.ADMIN,
    reason="This operation requires Permission.ADMIN before accessing tenant resources.",
)
async def create_tenant_completion_model(
    model_create: TenantCompletionModelCreate,
    user: Annotated[UserInDB, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session_with_transaction)],
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    """Create a new tenant-specific completion model."""
    assembler = container.completion_model_assembler()

    service = _service(session, user, container)
    completion_model = await service.create(model_create)
    await session.commit()

    return assembler.from_completion_model_to_model(completion_model=completion_model)


@router.put(
    "/{model_id}/",
    response_model=CompletionModelPublic,
    description="Update a tenant-specific completion model.",
    responses=responses.get_responses([403, 404, 409]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Permission.ADMIN,
    reason="This operation requires Permission.ADMIN before accessing tenant resources.",
)
async def update_tenant_completion_model(
    model_id: UUID,
    model_update: TenantCompletionModelUpdate,
    user: Annotated[UserInDB, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session_with_transaction)],
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    """Update a tenant-specific completion model."""
    assembler = container.completion_model_assembler()

    service = _service(session, user, container)
    completion_model = await service.update(model_id, model_update)
    await session.commit()

    return assembler.from_completion_model_to_model(completion_model=completion_model)


@router.delete(
    "/{model_id}/",
    response_model=None,
    description="Soft-delete a tenant-specific completion model.",
    responses=responses.get_responses([403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Permission.ADMIN,
    reason="This operation requires Permission.ADMIN before accessing tenant resources.",
)
async def delete_tenant_completion_model(
    model_id: UUID,
    user: Annotated[UserInDB, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session_with_transaction)],
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    """Soft-delete a tenant-specific completion model."""

    service = _service(session, user, container)
    await service.delete(model_id)
    await session.commit()

    return {"success": True}
