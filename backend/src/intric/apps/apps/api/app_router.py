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
    space_service = container.space_service()

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

    # Get space for context (after app is updated)
    space = None
    if app.space_id:
        try:
            space = await space_service.get_space(app.space_id)
        except Exception:
            # If space retrieval fails, continue without it
            space = None

    # Helper function to track attachment changes
    def get_attachment_changes(old_attachments, new_attachments):
        """Compare attachment lists and return added/removed items."""
        old_items = {str(att.id): att.name for att in (old_attachments or [])}
        new_items = {str(att.id): att.name for att in (new_attachments or [])}

        added = [{"id": k, "name": new_items[k]} for k in new_items if k not in old_items]
        removed = [{"id": k, "name": old_items[k]} for k in old_items if k not in new_items]

        return added, removed

    # Track comprehensive changes
    changes = {}
    change_summary = []

    # Name change
    if update_service_req.name and update_service_req.name != old_app.name:
        changes["name"] = {"old": old_app.name, "new": update_service_req.name}
        change_summary.append("name")

    # Description change (with preview for long text)
    if update_service_req.description is not None and update_service_req.description != old_app.description:
        old_desc = old_app.description or ""
        new_desc = update_service_req.description or ""

        # Create preview for long descriptions
        old_preview = old_desc[:50] + "..." if len(old_desc) > 50 else old_desc
        new_preview = new_desc[:50] + "..." if len(new_desc) > 50 else new_desc

        changes["description"] = {
            "old": old_preview if old_desc else None,
            "new": new_preview if new_desc else None
        }
        change_summary.append("description")

    # Prompt change
    if update_service_req.prompt is not None:
        old_prompt_text = old_app.prompt.text if old_app.prompt else ""
        new_prompt_text = update_service_req.prompt.text or ""

        if new_prompt_text != old_prompt_text:
            # Create preview of prompt text
            prompt_preview = new_prompt_text[:50] + "..." if len(new_prompt_text) > 50 else new_prompt_text
            changes["prompt"] = {
                "changed": True,
                "preview": prompt_preview if new_prompt_text else "Removed prompt"
            }
            change_summary.append("prompt")

    # Model changes
    if completion_model_id and completion_model_id != old_app.completion_model.id:
        changes["model"] = {
            "old": old_app.completion_model.nickname if old_app.completion_model else None,
            "new": app.completion_model.nickname if app.completion_model else None,
            "old_id": str(old_app.completion_model.id) if old_app.completion_model else None,
            "new_id": str(completion_model_id)
        }
        change_summary.append("model")

    # Model behavior parameters (temperature, top_p)
    if update_service_req.completion_model_kwargs is not None:
        old_kwargs = old_app.completion_model_kwargs or {}
        new_kwargs = update_service_req.completion_model_kwargs or {}

        # Temperature
        old_temperature = old_kwargs.get('temperature') if isinstance(old_kwargs, dict) else getattr(old_kwargs, 'temperature', None)
        new_temperature = new_kwargs.get('temperature') if isinstance(new_kwargs, dict) else getattr(new_kwargs, 'temperature', None)

        if old_temperature != new_temperature and new_temperature is not None:
            changes["temperature"] = {"old": old_temperature, "new": new_temperature}
            if "parameters" not in change_summary:
                change_summary.append("parameters")

        # Top-p
        old_top_p = old_kwargs.get('top_p') if isinstance(old_kwargs, dict) else getattr(old_kwargs, 'top_p', None)
        new_top_p = new_kwargs.get('top_p') if isinstance(new_kwargs, dict) else getattr(new_kwargs, 'top_p', None)

        if old_top_p != new_top_p and new_top_p is not None:
            changes["top_p"] = {"old": old_top_p, "new": new_top_p}
            if "parameters" not in change_summary:
                change_summary.append("parameters")

    # Input fields changes
    if update_service_req.input_fields is not None:
        old_fields = old_app.input_fields or []
        new_fields = update_service_req.input_fields or []

        # Compare input fields
        old_field_dict = {i: {"type": f.type.value if hasattr(f.type, 'value') else str(f.type),
                               "description": f.description} for i, f in enumerate(old_fields)}
        new_field_dict = {i: {"type": f.type.value if hasattr(f.type, 'value') else str(f.type),
                               "description": f.description} for i, f in enumerate(new_fields)}

        if old_field_dict != new_field_dict:
            changes["input_fields"] = {
                "old_count": len(old_fields),
                "new_count": len(new_fields),
                "modified": True
            }
            change_summary.append("input fields")

    # Attachments changes
    if update_service_req.attachments is not None:
        attachments_added, attachments_removed = get_attachment_changes(
            old_app.attachments, app.attachments
        )

        if attachments_added or attachments_removed:
            attachment_changes = {}
            if attachments_added:
                attachment_changes["added"] = attachments_added
            if attachments_removed:
                attachment_changes["removed"] = attachments_removed
            changes["attachments"] = attachment_changes
            change_summary.append("attachments")

    # Data retention changes
    from intric.main.models import NOT_PROVIDED
    if update_service_req.data_retention_days is not NOT_PROVIDED:
        old_retention = old_app.data_retention_days
        new_retention = update_service_req.data_retention_days

        if old_retention != new_retention:
            changes["data_retention_days"] = {
                "old": old_retention,
                "new": new_retention
            }
            change_summary.append("retention")

    # Transcription model changes
    if transcription_model_id and (
        (old_app.transcription_model and transcription_model_id != old_app.transcription_model.id) or
        (not old_app.transcription_model)
    ):
        changes["transcription_model"] = {
            "old": old_app.transcription_model.nickname if old_app.transcription_model else None,
            "new": app.transcription_model.nickname if app.transcription_model else None
        }
        change_summary.append("transcription model")

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
                "name": current_user.username or current_user.email.split('@')[0],
                "email": current_user.email,
            },
            "target": {
                "id": str(app.id),
                "name": app.name,
                "space_id": str(app.space_id) if app.space_id else None,
                "space_name": space.name if space else None,
            },
            "changes": changes,
            "summary": f"Modified {', '.join(change_summary)}" if change_summary else "No changes detected",
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
    space_service = container.space_service()

    # Get app details BEFORE deletion
    app, _ = await service.get_app(id)

    # Get space for context
    space = None
    if app.space_id:
        try:
            space = await space_service.get_space(app.space_id)
        except Exception:
            # If space retrieval fails, continue without it
            space = None

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
                "name": current_user.username or current_user.email.split('@')[0],
                "email": current_user.email,
            },
            "target": {
                "id": str(app.id),
                "name": app.name,
                "space_id": str(app.space_id) if app.space_id else None,
                "space_name": space.name if space else None,
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
    space_service = container.space_service()

    # Publish/unpublish app
    app, permissions = await service.publish_app(app_id=id, publish=published)

    # Get space for context (after app is retrieved)
    space = None
    if app.space_id:
        try:
            space = await space_service.get_space(app.space_id)
        except Exception:
            # If space retrieval fails, continue without it
            space = None

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
                "name": user.username or user.email.split('@')[0],
                "email": user.email,
            },
            "target": {
                "app_id": str(id),
                "app_name": app.name,
                "space_id": str(app.space_id) if app.space_id else None,
                "space_name": space.name if space else None,
                "published": published,
            },
        },
    )

    return assembler.from_app_to_model(app=app, permissions=permissions)
