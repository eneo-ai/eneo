"""Administrator API for native transcription-service connections."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
)
from pydantic_core import PydanticCustomError

from eneo.authentication.auth_dependencies import get_current_active_user
from eneo.authentication.endpoint_access import Authentication, endpoint_access
from eneo.database.database import AsyncSession, get_session_with_transaction
from eneo.main.container.container import Container
from eneo.main.models import (
    NOT_PROVIDED,
    ModelId,
    NotProvided,
    OffsetPaginatedResponse,
    is_provided,
)
from eneo.roles.permissions import Permission
from eneo.security_classifications.presentation.security_classification_models import (
    SecurityClassificationPublic,
)
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses
from eneo.settings.encryption_service import EncryptionService
from eneo.transcription_services.models import (
    ServiceEndpointError,
    TranscriptionServiceConnection,
    parse_service_endpoint,
)
from eneo.transcription_services.repository import (
    TranscriptionServiceConnectionRepository,
)
from eneo.transcription_services.service import (
    ConnectionCheckOutcome,
    TranscriptionServiceConnectionService,
)
from eneo.users.user import UserInDB

router = APIRouter()

_ACCESS_REASON = (
    "Transcription services are organisation configuration holding a credential; "
    "managing them requires admin permission."
)

CurrentUser = Annotated[UserInDB, Depends(get_current_active_user)]
SessionDep = Annotated[AsyncSession, Depends(get_session_with_transaction)]


def get_connection_service(
    user: CurrentUser,
    session: SessionDep,
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> TranscriptionServiceConnectionService:
    return TranscriptionServiceConnectionService(
        user=user,
        repository=TranscriptionServiceConnectionRepository(session, user.tenant_id),
        encryption=container.encryption_service(),
        audit_service=container.audit_service(),
    )


ServiceDep = Annotated[
    TranscriptionServiceConnectionService, Depends(get_connection_service)
]

ServiceName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]
# Surrounding whitespace is a paste artefact, never part of a bearer key.
ServiceApiKey = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=EncryptionService.MAX_CREDENTIAL_LENGTH,
    ),
]
_ENDPOINT_DESCRIPTION = (
    "Base URL of the service's native jobs API, http or https, without "
    "credentials, query or fragment. A trailing /v1 is removed."
)
_API_KEY_DESCRIPTION = "Bearer key the service issued to this organisation. Write-only."


def _parsed_endpoint(value: str) -> str:
    try:
        return parse_service_endpoint(value)
    except ServiceEndpointError as error:
        raise PydanticCustomError(error.code, error.message) from None


class TranscriptionServiceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: ServiceName = Field(description="Unique within the organisation")
    endpoint_url: str = Field(description=_ENDPOINT_DESCRIPTION)
    api_key: ServiceApiKey = Field(description=_API_KEY_DESCRIPTION)
    is_enabled: bool = Field(default=True, description="Disabled: no new work")
    security_classification: ModelId | None = Field(
        default=None, description="Security classification of the service"
    )

    @field_validator("endpoint_url")
    @classmethod
    def _endpoint(cls, value: str) -> str:
        return _parsed_endpoint(value)


class TranscriptionServiceUpdate(BaseModel):
    """Only the fields sent change. Changing the endpoint requires a new
    ``api_key``: the stored key is never sent to another destination."""

    model_config = ConfigDict(extra="forbid")

    name: ServiceName | NotProvided = Field(default=NOT_PROVIDED)
    endpoint_url: str | NotProvided = Field(
        default=NOT_PROVIDED, description=_ENDPOINT_DESCRIPTION
    )
    api_key: ServiceApiKey | NotProvided = Field(
        default=NOT_PROVIDED, description=_API_KEY_DESCRIPTION
    )
    is_enabled: bool | NotProvided = Field(default=NOT_PROVIDED)
    security_classification: ModelId | None | NotProvided = Field(
        default=NOT_PROVIDED,
        description="Null clears the classification; omit to keep it",
    )

    @field_validator("endpoint_url")
    @classmethod
    def _endpoint(cls, value: str | NotProvided) -> str | NotProvided:
        return _parsed_endpoint(value) if is_provided(value) else value


class TranscriptionServicePublic(BaseModel):
    id: UUID
    name: str
    endpoint_url: str
    is_enabled: bool
    security_classification: SecurityClassificationPublic | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(
        cls, connection: TranscriptionServiceConnection
    ) -> TranscriptionServicePublic:
        return cls(
            id=connection.id,
            name=connection.name,
            endpoint_url=connection.endpoint_url,
            is_enabled=connection.is_enabled,
            security_classification=SecurityClassificationPublic.from_domain(
                connection.security_classification
            ),
            created_at=connection.created_at,
            updated_at=connection.updated_at,
        )


class TranscriptionServiceCheckPublic(BaseModel):
    outcome: ConnectionCheckOutcome
    detail: str = Field(description="What the service answered, without secrets")
    identifies_speakers: bool | None = Field(
        description=(
            "Whether the service reports it can identify speakers. Null: the "
            "service does not report which tasks it supports."
        )
    )
    service_version: str | None = Field(
        description="Version the service reports, when it reports one"
    )


@router.get(
    "/",
    response_model=OffsetPaginatedResponse[TranscriptionServicePublic],
    description="List the organisation's transcription services by name.",
    responses=responses.get_responses([403]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Permission.ADMIN,
    reason=_ACCESS_REASON,
)
async def list_transcription_services(
    service: ServiceDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> OffsetPaginatedResponse[TranscriptionServicePublic]:
    page, has_more = await service.list(limit=limit, offset=offset)
    return OffsetPaginatedResponse[TranscriptionServicePublic](
        items=[TranscriptionServicePublic.from_domain(item) for item in page],
        has_more=has_more,
    )


@router.post(
    "/",
    status_code=201,
    response_model=TranscriptionServicePublic,
    description="Connect a native transcription service.",
    responses=responses.get_responses([400, 403, 404, 409, 503]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Permission.ADMIN,
    reason=_ACCESS_REASON,
)
async def create_transcription_service(
    data: TranscriptionServiceCreate, service: ServiceDep
) -> TranscriptionServicePublic:
    connection = await service.create(
        name=data.name,
        endpoint_url=data.endpoint_url,
        api_key=data.api_key,
        is_enabled=data.is_enabled,
        security_classification=data.security_classification,
    )
    return TranscriptionServicePublic.from_domain(connection)


@router.get(
    "/{connection_id}/",
    response_model=TranscriptionServicePublic,
    description="One transcription service.",
    responses=responses.get_responses([403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Permission.ADMIN,
    reason=_ACCESS_REASON,
)
async def get_transcription_service(
    connection_id: UUID, service: ServiceDep
) -> TranscriptionServicePublic:
    return TranscriptionServicePublic.from_domain(await service.get(connection_id))


@router.patch(
    "/{connection_id}/",
    response_model=TranscriptionServicePublic,
    description=(
        "Change a transcription service. Changing its endpoint requires a new API key."
    ),
    responses=responses.get_responses([400, 403, 404, 409, 503]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Permission.ADMIN,
    reason=_ACCESS_REASON,
)
async def update_transcription_service(
    connection_id: UUID, data: TranscriptionServiceUpdate, service: ServiceDep
) -> TranscriptionServicePublic:
    connection = await service.update(
        connection_id,
        name=data.name,
        endpoint_url=data.endpoint_url,
        api_key=data.api_key,
        is_enabled=data.is_enabled,
        security_classification=data.security_classification,
    )
    return TranscriptionServicePublic.from_domain(connection)


@router.delete(
    "/{connection_id}/",
    status_code=204,
    response_model=None,
    description="Remove a transcription service and its space grants.",
    responses=responses.get_responses([403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Permission.ADMIN,
    reason=_ACCESS_REASON,
)
async def delete_transcription_service(
    connection_id: UUID, service: ServiceDep
) -> None:
    await service.delete(connection_id)


@router.post(
    "/{connection_id}/check/",
    response_model=TranscriptionServiceCheckPublic,
    description=(
        "Ask the service whether it would accept a job with this connection's "
        "key. Sends no audio and starts no job."
    ),
    responses=responses.get_responses([403, 404, 503]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Permission.ADMIN,
    reason=_ACCESS_REASON,
)
async def check_transcription_service(
    connection_id: UUID, service: ServiceDep
) -> TranscriptionServiceCheckPublic:
    check = await service.check(connection_id)
    return TranscriptionServiceCheckPublic(
        outcome=check.outcome,
        detail=check.detail,
        identifies_speakers=check.identifies_speakers,
        service_version=check.service_version,
    )
