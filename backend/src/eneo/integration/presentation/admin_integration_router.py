from typing import Annotated

from fastapi import APIRouter, Depends

from eneo.authentication.endpoint_access import Authentication, endpoint_access
from eneo.integration.presentation.admin_models import (
    AdminIntegrationKnowledgeItem,
    AdminIntegrationKnowledgeOverview,
    AdminIntegrationKnowledgeSpace,
    AdminPersonalIntegrationKnowledge,
)
from eneo.integration.presentation.assemblers.integration_knowledge_assembler import (
    IntegrationKnowledgeAssembler,
)
from eneo.main.container.container import Container
from eneo.roles.permissions import Permission
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses

router = APIRouter()


@router.get(
    "/knowledge/",
    response_model=AdminIntegrationKnowledgeOverview,
    description="Every integration knowledge item in the tenant's shared and "
    "organization spaces with its sync status. Items in personal spaces are "
    "only counted. Requires the admin permission.",
    responses=responses.get_responses([403]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Permission.ADMIN,
    reason="Organization administration requires the admin permission.",
)
async def get_integration_knowledge_overview(
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> AdminIntegrationKnowledgeOverview:
    overview = await container.integration_knowledge_service().tenant_overview()
    return AdminIntegrationKnowledgeOverview(
        items=[
            AdminIntegrationKnowledgeItem(
                space=AdminIntegrationKnowledgeSpace(
                    id=item.placement.space_id,
                    name=item.placement.space_name,
                    organization=item.placement.organization,
                    can_open=item.can_open_space,
                ),
                knowledge=IntegrationKnowledgeAssembler.to_space_knowledge_model(
                    item.knowledge
                ),
            )
            for item in overview.items
        ],
        personal=AdminPersonalIntegrationKnowledge(
            items=overview.personal_items, failing=overview.personal_failing
        ),
    )
