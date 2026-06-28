from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

# Audit logging - module level imports for consistency
from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.integration.presentation.models import (
    AuthCallbackParams,
    AuthUrlPublic,
    UserIntegration,
)
from eneo.main.container.container import Container
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses

router = APIRouter()


@router.get(
    "/{tenant_integration_id}/url/",
    response_model=AuthUrlPublic,
    status_code=200,
    description="Generate the OAuth2 authorization URL for a tenant integration.",
    responses=responses.get_responses([400, 404]),
)
async def gen_url(
    tenant_integration_id: UUID,
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    # The backend generates and stores its own single-use CSRF state (see
    # oauth2_service.start_auth); callers no longer pass one in.
    oauth2_service = container.oauth2_service()
    user = container.user()

    return await oauth2_service.start_auth(
        tenant_integration_id=tenant_integration_id, user_id=user.id
    )


@router.post(
    "/callback/token/",
    status_code=200,
    response_model=UserIntegration,
    description="Complete the OAuth2 callback by exchanging the auth code for a user integration.",
    responses=responses.get_responses([400, 404]),
)
async def on_auth_callback(
    params: AuthCallbackParams,
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    oauth2_service = container.oauth2_service()
    user = container.user()
    assembler = container.user_integration_assembler()

    integration = await oauth2_service.auth_integration(
        user_id=user.id,
        tenant_integration_id=params.tenant_integration_id,
        auth_code=params.auth_code,
        state=params.state,
    )

    # Audit logging
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        user=user,
        action=ActionType.INTEGRATION_CONNECTED,
        entity_type=EntityType.INTEGRATION,
        entity_id=integration.id,
        description=f"Connected {integration.tenant_integration.integration.name} integration",
        metadata=AuditMetadata.standard(
            actor=user,
            target=integration,
            extra={
                "integration_name": integration.tenant_integration.integration.name,
                "integration_type": integration.integration_type,
            },
        ),
    )

    return assembler.from_domain_to_model(item=integration)
