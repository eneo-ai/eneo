from uuid import UUID

from fastapi import APIRouter, Depends

from eneo.apps.app_runs.api.app_run_models import AppRunPublic

# Audit logging - module level imports for consistency
from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.main.container.container import Container
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses

router = APIRouter()
_WITH_USER = Depends(get_container(with_user=True))


@router.get(
    "/{id}/",
    response_model=AppRunPublic,
    description="Get an app run by id.",
    responses=responses.get_responses([403, 404]),
)
async def get_app_run(
    id: UUID,
    container: Container = _WITH_USER,
):
    service = container.app_run_service()
    assembler = container.app_run_assembler()

    app_run = await service.get_app_run(id)

    return assembler.from_app_run_to_model(app_run)


@router.delete(
    "/{id}/",
    status_code=204,
    description="Delete an app run by id.",
    responses=responses.get_responses([403, 404]),
)
async def delete_app_run(
    id: UUID,
    container: Container = _WITH_USER,
):
    service = container.app_run_service()
    user = container.user()

    # Get app run info before deletion (snapshot pattern)
    app_run = await service.get_app_run(id)

    # Delete app run
    await service.delete_app_run(id)

    # Audit logging
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        user=user,
        action=ActionType.APP_RUN_DELETED,
        entity_type=EntityType.APP_RUN,
        entity_id=id,
        description="Deleted app run",
        metadata=AuditMetadata.standard(
            actor=user,
            target=app_run,
            extra={"app_id": str(app_run.app_id)},
        ),
    )
