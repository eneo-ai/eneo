from uuid import UUID

from fastapi import APIRouter, Depends

from intric.main.container.container import Container
from intric.main.models import PaginatedResponse
from intric.roles.permissions import Permission, validate_permission
from intric.server.dependencies.container import get_container
from intric.server.protocol import responses
from intric.transcription_models.presentation.transcription_model_models import (
    TranscriptionModelPublic,
    TranscriptionModelUpdate,
)

router = APIRouter()


@router.get(
    "/",
    response_model=PaginatedResponse[TranscriptionModelPublic],
)
async def get_transcription_models(
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.transcription_model_crud_service()

    models = await service.get_transcription_models()

    return PaginatedResponse(
        items=[TranscriptionModelPublic.from_domain(model) for model in models]
    )


@router.post(
    "/{id}/",
    response_model=TranscriptionModelPublic,
    responses=responses.get_responses([404]),
)
async def update_transcription_model(
    id: UUID,
    update_flags: TranscriptionModelUpdate,
    container: Container = Depends(get_container(with_user=True)),
):
    from intric.audit.application.audit_service import AuditService
    from intric.audit.domain.action_types import ActionType
    from intric.audit.domain.entity_types import EntityType
    from intric.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl
    from intric.main.models import NOT_PROVIDED

    service = container.transcription_model_crud_service()
    user = container.user()

    # Validate admin permissions first
    validate_permission(user, Permission.ADMIN)

    # Get old state for change tracking (bypass access check since admin is already validated)
    transcription_model_repo = container.transcription_model_repo()
    old_model = await transcription_model_repo.one(model_id=id)

    # Update model
    transcription_model = await service.update_transcription_model(
        model_id=id,
        is_org_enabled=update_flags.is_org_enabled,
        is_org_default=update_flags.is_org_default,
        security_classification=update_flags.security_classification,
    )

    # Build consolidated changes dict (one API call = one audit log)
    changes = {}

    # Track is_org_enabled changes
    if update_flags.is_org_enabled is not NOT_PROVIDED:
        if old_model.is_org_enabled != transcription_model.is_org_enabled:
            changes["is_org_enabled"] = {
                "old": old_model.is_org_enabled,
                "new": transcription_model.is_org_enabled,
            }

    # Track is_org_default changes
    if update_flags.is_org_default is not NOT_PROVIDED:
        if old_model.is_org_default != transcription_model.is_org_default:
            changes["is_org_default"] = {
                "old": old_model.is_org_default,
                "new": transcription_model.is_org_default,
            }

    # Track security classification changes
    if update_flags.security_classification is not NOT_PROVIDED:
        old_sc_name = old_model.security_classification.name if old_model.security_classification else None
        new_sc_name = transcription_model.security_classification.name if transcription_model.security_classification else None
        if old_sc_name != new_sc_name:
            changes["security_classification"] = {
                "old": old_sc_name,
                "new": new_sc_name,
            }

    # Only log if there were actual changes (ONE entry with all changes)
    if changes:
        session = container.session()
        audit_repo = AuditLogRepositoryImpl(session)
        audit_service = AuditService(audit_repo)

        await audit_service.log_async(
            tenant_id=user.tenant_id,
            actor_id=user.id,
            action=ActionType.TRANSCRIPTION_MODEL_UPDATED,
            entity_type=EntityType.TRANSCRIPTION_MODEL,
            entity_id=id,
            description=f"Updated settings for {transcription_model.name}",
            metadata={
                "actor": {
                    "id": str(user.id),
                    "name": user.username,
                    "email": user.email,
                },
                "target": {
                    "id": str(id),
                    "name": transcription_model.name,
                    "tenant_id": str(user.tenant_id),
                    "tenant_name": user.tenant.display_name or user.tenant.name,
                },
                "changes": changes,
            },
        )

    return TranscriptionModelPublic.from_domain(transcription_model)
