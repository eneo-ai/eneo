from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from eneo.authentication.auth_dependencies import get_current_active_user
from eneo.authentication.endpoint_access import Authentication, endpoint_access
from eneo.database.database import AsyncSession, get_session_with_transaction
from eneo.main.container.container import Container
from eneo.main.models import ModelId
from eneo.roles.permissions import Permission
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses
from eneo.tenant_models.application.tenant_model_service import (
    TenantTranscriptionModelService,
)
from eneo.transcription_models.presentation.transcription_model_models import (
    TranscriptionModelPublic,
)
from eneo.users.user import UserInDB

CurrentUser = Annotated[UserInDB, Depends(get_current_active_user)]
DBSession = Annotated[AsyncSession, Depends(get_session_with_transaction)]
ContainerDep = Annotated[Container, Depends(get_container(with_user=True))]

router = APIRouter()


class TenantTranscriptionModelCreate(BaseModel):
    provider_id: UUID = Field(..., description="Model provider ID")
    name: str = Field(
        ...,
        description="Model identifier (e.g., 'whisper-1', 'distil-whisper-large-v3-en')",
    )
    display_name: str = Field(..., description="User-friendly display name")
    hosting: str = Field(default="swe", description="Hosting location (swe, eu, usa)")
    family: str = Field(
        default="openai",
        description="Model family (e.g., 'openai', 'anthropic', 'deepseek')",
    )
    is_active: bool = Field(default=True, description="Enable in organization")
    is_default: bool = Field(default=False, description="Set as default model")
    description: str | None = Field(default=None, description="Model description")
    cost_per_minute: Decimal | None = Field(
        default=None, description="Indicative USD per minute of audio"
    )
    security_classification: ModelId | None = Field(
        default=None, description="Security classification"
    )
    supports_realtime: bool = Field(
        default=False,
        description=(
            "Live text: the model is served over vLLM's realtime API "
            "(/v1/realtime on the provider's endpoint). Allowed when the "
            "provider's realtime_eligibility is eligible: a vLLM provider with "
            "an endpoint, or an OpenAI provider whose endpoint is a gateway "
            "serving that API (not OpenAI's own service), without outbound "
            "headers and switched on. Otherwise 400 says what to change on the "
            "provider."
        ),
    )


class TenantTranscriptionModelUpdate(BaseModel):
    display_name: str | None = Field(None, description="User-friendly display name")
    description: str | None = Field(None, description="Model description")
    hosting: str | None = Field(None, description="Hosting location (swe, eu, usa)")
    open_source: bool | None = Field(None, description="Is the model open source")
    stability: str | None = Field(
        None, description="Model stability (stable, experimental)"
    )
    cost_per_minute: Decimal | None = Field(
        None, description="Indicative USD per minute of audio"
    )
    # See TenantCompletionModelUpdate for the rationale on folding these in.
    is_default: bool | None = Field(None, description="Set as tenant default")
    security_classification: ModelId | None = Field(
        None, description="Security classification reference (null clears it)"
    )
    supports_realtime: bool | None = Field(
        None,
        description=(
            "Turn live text on or off for this model. Turning it on needs a "
            "provider whose realtime_eligibility is eligible (a vLLM provider "
            "with an endpoint, or an OpenAI provider whose endpoint is a gateway "
            "serving vLLM's realtime API, without outbound headers and switched "
            "on); otherwise 400 says what to change on the provider. Sending "
            "true again for a "
            "model that is already marked succeeds even if its provider no "
            "longer qualifies; the model's streams_live then reads false. "
            "Turning it off always succeeds."
        ),
    )


def _service(
    session: AsyncSession, user: UserInDB, container: Container
) -> TenantTranscriptionModelService:
    return TenantTranscriptionModelService(
        session=session,
        user=user,
        audit_service=container.audit_service(),
    )


@router.post(
    "/",
    description=(
        "Create a new tenant-specific transcription model. Marking it for live "
        "text (supports_realtime) needs a provider whose realtime_eligibility "
        "is eligible. Otherwise (endpoint_required, unsupported_provider, "
        "outbound_headers_configured or provider_inactive) 400 says what to "
        "change on the provider."
    ),
    response_model=TranscriptionModelPublic,
    responses=responses.get_responses([400, 403, 404, 409]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Permission.ADMIN,
    reason="This operation requires Permission.ADMIN before accessing tenant resources.",
)
async def create_tenant_transcription_model(
    model_create: TenantTranscriptionModelCreate,
    user: CurrentUser,
    session: DBSession,
    container: ContainerDep,
):
    """Create a new tenant-specific transcription model."""

    service = _service(session, user, container)
    transcription_model = await service.create(model_create)
    await session.commit()

    return TranscriptionModelPublic.from_domain(transcription_model)


@router.put(
    "/{model_id}/",
    description=(
        "Update a tenant-specific transcription model. Only turning live text "
        "on (supports_realtime from false to true) checks the provider's "
        "realtime_eligibility and answers 400 when it is not eligible, a "
        "provider that is switched off included; a supports_realtime that "
        "does not change is accepted, and turning it off always works."
    ),
    response_model=TranscriptionModelPublic,
    responses=responses.get_responses([400, 403, 404, 409]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Permission.ADMIN,
    reason="This operation requires Permission.ADMIN before accessing tenant resources.",
)
async def update_tenant_transcription_model(
    model_id: UUID,
    model_update: TenantTranscriptionModelUpdate,
    user: CurrentUser,
    session: DBSession,
    container: ContainerDep,
):
    """Update a tenant-specific transcription model."""

    service = _service(session, user, container)
    transcription_model = await service.update(model_id, model_update)
    await session.commit()

    return TranscriptionModelPublic.from_domain(transcription_model)


@router.delete(
    "/{model_id}/",
    description="Delete a tenant-specific transcription model.",
    response_model=None,
    responses=responses.get_responses([400, 403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Permission.ADMIN,
    reason="This operation requires Permission.ADMIN before accessing tenant resources.",
)
async def delete_tenant_transcription_model(
    model_id: UUID,
    user: CurrentUser,
    session: DBSession,
    container: ContainerDep,
):
    """Delete a tenant-specific transcription model."""

    service = _service(session, user, container)
    await service.delete(model_id)
    await session.commit()

    return {"success": True}
