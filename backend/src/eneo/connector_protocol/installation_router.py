from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.authentication.endpoint_access import Authentication, endpoint_access
from eneo.connector_protocol.installation import (
    ConnectorInstallation,
    ConnectorInstallationCreate,
    ConnectorInstallationCreated,
    ConnectorInstallationPublic,
)
from eneo.main.container.container import Container
from eneo.main.models import PaginatedResponse
from eneo.roles.permissions import Permission
from eneo.server import protocol
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses

router = APIRouter()

_ContainerWithUser = Annotated[Container, Depends(get_container(with_user=True))]
_ADMIN_REASON = (
    "Tenant administrators decide which installations of other systems may "
    "call Eneo for the tenant's people; ConnectorInstallationService holds "
    "every read and change to the caller's tenant."
)


async def _audit(
    container: Container, action: ActionType, installation: ConnectorInstallation
) -> None:
    user = container.user()
    verb = "Added" if action is ActionType.CONNECTOR_INSTALLATION_ADDED else "Removed"
    await container.audit_service().log_async(
        tenant_id=user.tenant_id,
        user=user,
        action=action,
        entity_type=EntityType.TENANT_SETTINGS,
        entity_id=user.tenant_id,
        description=f"{verb} connected installation '{installation.name}'",
        metadata=AuditMetadata.standard(
            actor=user,
            target=user.tenant,
            # Never the key or its digest.
            extra={
                "installation_id": str(installation.id),
                "installation_name": installation.name,
                "base_url": installation.base_url,
            },
        ),
    )


@router.get(
    "/",
    response_model=PaginatedResponse[ConnectorInstallationPublic],
    description=(
        "List the installations of other systems the tenant lets call Eneo "
        "over the connector protocol."
    ),
    responses=responses.get_responses([403]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Permission.ADMIN,
    reason=_ADMIN_REASON,
)
async def list_installations(container: _ContainerWithUser):
    installations = await container.connector_installation_service().list()
    return protocol.to_paginated_response(
        [
            ConnectorInstallationPublic.model_validate(installation)
            for installation in installations
        ]
    )


@router.post(
    "/",
    response_model=ConnectorInstallationCreated,
    status_code=201,
    description=(
        "Let an installation call Eneo. The answer carries the shared key to "
        "enter in that installation; it is shown this once."
    ),
    responses=responses.get_responses([400, 403]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Permission.ADMIN,
    reason=_ADMIN_REASON,
)
async def add_installation(
    body: ConnectorInstallationCreate, container: _ContainerWithUser
):
    installation, key = await container.connector_installation_service().add(
        name=body.name, base_url=body.base_url
    )
    await _audit(container, ActionType.CONNECTOR_INSTALLATION_ADDED, installation)
    return ConnectorInstallationCreated(
        **ConnectorInstallationPublic.model_validate(installation).model_dump(),
        key=key,
    )


@router.delete(
    "/{id}/",
    status_code=204,
    description=(
        "Stop an installation from calling Eneo. Its shared key is refused "
        "from the next call on."
    ),
    responses=responses.get_responses([403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Permission.ADMIN,
    reason=_ADMIN_REASON,
)
async def remove_installation(id: UUID, container: _ContainerWithUser) -> None:
    installation = await container.connector_installation_service().remove(id)
    await _audit(container, ActionType.CONNECTOR_INSTALLATION_REMOVED, installation)
