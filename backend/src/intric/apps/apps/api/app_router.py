from uuid import UUID

from fastapi import APIRouter, Depends

from intric.apps.app_runs.api.app_run_models import (
    AppRunPublic,
    AppRunSparse,
    RunAppRequest,
)
from intric.apps.apps.api.app_models import AppPublic, AppUpdateRequest
from intric.main.container.container import Container
from intric.main.models import PaginatedResponse
from intric.prompts.api.prompt_models import PromptSparse
from intric.server import protocol
from intric.server.dependencies.container import get_container
from intric.server.protocol import responses

router = APIRouter()


@router.get(
    "/{id}/",
    response_model=AppPublic,
    responses=responses.get_responses([403, 404]),
)
async def get_app(
    id: UUID,
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.app_service()
    assembler = container.app_assembler()

    app, permissions = await service.get_app(id)

    return assembler.from_app_to_model(app, permissions=permissions)


@router.patch(
    "/{id}/",
    response_model=AppPublic,
    responses=responses.get_responses([400, 403, 404]),
)
async def update_app(
    id: UUID,
    update_service_req: AppUpdateRequest,
    container: Container = Depends(get_container(with_user=True)),
):
    from intric.audit.application.audit_service import AuditService
    from intric.audit.domain.action_types import ActionType
    from intric.audit.domain.entity_types import EntityType
    from intric.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl

    service = container.app_service()
    assembler = container.app_assembler()
    current_user = container.user()

    # Get old state
    old_app, _ = await service.get_app(id)

    completion_model_id = (
        update_service_req.completion_model.id
        if update_service_req.completion_model is not None
        else None
    )
    transcription_model_id = (
        update_service_req.transcription_model.id
        if update_service_req.transcription_model is not None
        else None
    )
    prompt_text = update_service_req.prompt.text if update_service_req.prompt is not None else None
    prompt_description = (
        update_service_req.prompt.description if update_service_req.prompt is not None else None
    )

    app, permissions = await service.update_app(
        app_id=id,
        name=update_service_req.name,
        description=update_service_req.description,
        completion_model_id=completion_model_id,
        completion_model_kwargs=update_service_req.completion_model_kwargs,
        input_fields=update_service_req.input_fields,
        attachment_ids=update_service_req.attachments,
        prompt_text=prompt_text,
        prompt_description=prompt_description,
        transcription_model_id=transcription_model_id,
        data_retention_days=update_service_req.data_retention_days,
    )

    # Track changes
    changes = {}
    if update_service_req.name and update_service_req.name != old_app.name:
        changes["name"] = {"old": old_app.name, "new": update_service_req.name}
    if update_service_req.description is not None:
        changes["description"] = {"old": old_app.description, "new": update_service_req.description}

    # Audit logging
    session = container.session()
    audit_repo = AuditLogRepositoryImpl(session)
    audit_service = AuditService(audit_repo)

    await audit_service.log_async(
        tenant_id=current_user.tenant_id,
        actor_id=current_user.id,
        action=ActionType.APP_UPDATED,
        entity_type=EntityType.APP,
        entity_id=id,
        description=f"Updated app '{app.name}'",
        metadata={
            "actor": {
                "id": str(current_user.id),
                "name": current_user.username,
                "email": current_user.email,
            },
            "target": {
                "id": str(app.id),
                "name": app.name,
            },
            "changes": changes,
        },
    )

    return assembler.from_app_to_model(app, permissions=permissions)


@router.delete(
    "/{id}/",
    status_code=204,
    responses=responses.get_responses([403, 404]),
)
async def delete_app(
    id: UUID,
    container: Container = Depends(get_container(with_user=True)),
):
    from intric.audit.application.audit_service import AuditService
    from intric.audit.domain.action_types import ActionType
    from intric.audit.domain.entity_types import EntityType
    from intric.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl

    service = container.app_service()
    current_user = container.user()

    # Get app details BEFORE deletion
    app, _ = await service.get_app(id)

    # Delete app
    await service.delete_app(id)

    # Audit logging
    session = container.session()
    audit_repo = AuditLogRepositoryImpl(session)
    audit_service = AuditService(audit_repo)

    await audit_service.log_async(
        tenant_id=current_user.tenant_id,
        actor_id=current_user.id,
        action=ActionType.APP_DELETED,
        entity_type=EntityType.APP,
        entity_id=id,
        description=f"Deleted app '{app.name}'",
        metadata={
            "actor": {
                "id": str(current_user.id),
                "name": current_user.username,
                "email": current_user.email,
            },
            "target": {
                "id": str(app.id),
                "name": app.name,
            },
        },
    )


@router.post(
    "/{id}/runs/",
    status_code=203,
    response_model=AppRunPublic,
    responses=responses.get_responses([400, 403]),
)
async def run_app(
    id: UUID,
    run_app_req: RunAppRequest,
    container: Container = Depends(get_container(with_user=True)),
):
    from intric.audit.application.audit_service import AuditService
    from intric.audit.domain.action_types import ActionType
    from intric.audit.domain.entity_types import EntityType
    from intric.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl

    service = container.app_run_service()
    assembler = container.app_run_assembler()
    current_user = container.user()

    file_ids = [file.id for file in run_app_req.files]
    app_run = await service.queue_app_run(id, file_ids=file_ids, text=run_app_req.text)

    # Audit logging
    session = container.session()
    audit_repo = AuditLogRepositoryImpl(session)
    audit_service = AuditService(audit_repo)

    await audit_service.log_async(
        tenant_id=current_user.tenant_id,
        actor_id=current_user.id,
        action=ActionType.APP_EXECUTED,
        entity_type=EntityType.APP,
        entity_id=id,
        description=f"Executed app (run_id: {app_run.id})",
        metadata={
            "actor": {
                "id": str(current_user.id),
                "name": current_user.username,
                "email": current_user.email,
            },
            "target": {
                "app_id": str(id),
                "run_id": str(app_run.id),
                "file_count": len(file_ids),
            },
        },
    )

    return assembler.from_app_run_to_model(app_run)


@router.get(
    "/{id}/runs/",
    response_model=PaginatedResponse[AppRunSparse],
    responses=responses.get_responses([400, 403, 404]),
)
async def get_app_runs(
    id: UUID,
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.app_run_service()
    assembler = container.app_run_assembler()

    app_runs = await service.get_app_runs(app_id=id)
    app_runs_public = [assembler.from_app_run_to_sparse_model(app_run) for app_run in app_runs]

    return protocol.to_paginated_response(app_runs_public)


@router.get(
    "/{id}/prompts/",
    response_model=PaginatedResponse[PromptSparse],
    responses=responses.get_responses([403, 404]),
)
async def get_prompts(
    id: UUID,
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.app_service()
    assembler = container.prompt_assembler()

    prompts = await service.get_prompts_by_app(id)
    prompts = [assembler.from_prompt_to_model(prompt) for prompt in prompts]

    return protocol.to_paginated_response(prompts)


@router.post(
    "/{id}/publish/",
    response_model=AppPublic,
    responses=responses.get_responses([403, 404]),
)
async def publish_app(
    id: UUID,
    published: bool,
    container: Container = Depends(get_container(with_user=True)),
):
    from intric.audit.application.audit_service import AuditService
    from intric.audit.domain.action_types import ActionType
    from intric.audit.domain.entity_types import EntityType
    from intric.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl

    service = container.app_service()
    assembler = container.app_assembler()
    user = container.user()

    # Publish/unpublish app
    app, permissions = await service.publish_app(app_id=id, publish=published)

    # Audit logging
    session = container.session()
    audit_repo = AuditLogRepositoryImpl(session)
    audit_service = AuditService(audit_repo)

    await audit_service.log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.APP_PUBLISHED,
        entity_type=EntityType.APP,
        entity_id=id,
        description=f"{'Published' if published else 'Unpublished'} app",
        metadata={
            "actor": {
                "id": str(user.id),
                "name": user.username,
                "email": user.email,
            },
            "target": {
                "app_id": str(id),
                "app_name": app.name,
                "published": published,
            },
        },
    )

    return assembler.from_app_to_model(app=app, permissions=permissions)
