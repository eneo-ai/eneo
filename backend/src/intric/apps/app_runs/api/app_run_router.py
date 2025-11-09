from uuid import UUID

from fastapi import APIRouter, Depends

from intric.apps.app_runs.api.app_run_models import AppRunPublic
from intric.main.container.container import Container
from intric.server.dependencies.container import get_container
from intric.server.protocol import responses

router = APIRouter()


@router.get(
    "/{id}/",
    response_model=AppRunPublic,
    responses=responses.get_responses([403, 404]),
)
async def get_app_run(
    id: UUID,
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.app_run_service()
    assembler = container.app_run_assembler()

    app_run = await service.get_app_run(id)

    return assembler.from_app_run_to_model(app_run)


@router.delete(
    "/{id}/",
    status_code=204,
    responses=responses.get_responses([403, 404]),
)
async def delete_app_run(
    id: UUID,
    container: Container = Depends(get_container(with_user=True)),
):
    from intric.audit.application.audit_service import AuditService
    from intric.audit.domain.action_types import ActionType
    from intric.audit.domain.entity_types import EntityType
    from intric.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl

    service = container.app_run_service()
    user = container.user()

    # Get app run info before deletion
    app_run = await service.get_app_run(id)

    # Delete app run
    await service.delete_app_run(id)

    # Audit logging
    session = container.session()
    audit_repo = AuditLogRepositoryImpl(session)
    audit_service = AuditService(audit_repo)

    await audit_service.log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.APP_RUN_DELETED,
        entity_type=EntityType.APP_RUN,
        entity_id=id,
        description="Deleted app run",
        metadata={
            "actor": {
                "id": str(user.id),
                "name": user.username,
                "email": user.email,
            },
            "target": {
                "app_run_id": str(id),
                "app_id": str(app_run.app_id),
            },
        },
    )
