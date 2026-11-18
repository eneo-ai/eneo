# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from typing import TYPE_CHECKING, Any
from uuid import UUID

from eneo.audit.application.audit_config_service import AuditConfigService
from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.application.audit_service import AuditService
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.audit.infrastructure.audit_config_repository import AuditConfigRepositoryImpl
from eneo.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl
from eneo.feature_flag.feature_flag_repo import FeatureFlagRepository
from eneo.feature_flag.feature_flag_service import FeatureFlagService
from eneo.widgets.domain.widget import LIFECYCLE_FIELDS, Widget
from eneo.widgets.infrastructure.widget_repo_impl import WidgetRepoImpl

if TYPE_CHECKING:
    from eneo.database.database import AsyncSession
    from eneo.users.user import UserInDB


def audit_snapshot(widget: Widget) -> dict[str, Any]:
    """The settings every widget audit entry records."""
    return {
        "status": widget.status.value,
        "token_generation": widget.token_generation,
        "allowed_origins": list(widget.allowed_origins),
        "limits": widget.limits.model_dump(mode="json"),
        "privacy": widget.privacy.model_dump(mode="json"),
        "bot_protection": widget.bot_protection.value,
    }


def _audit_service(session: "AsyncSession") -> AuditService:
    return AuditService(
        repository=AuditLogRepositoryImpl(session),
        audit_config_service=AuditConfigService(AuditConfigRepositoryImpl(session)),
        feature_flag_service=FeatureFlagService(FeatureFlagRepository(session)),
    )


async def archive_widgets_of_deleted_assistant(
    session: "AsyncSession", *, assistant_id: UUID, user: "UserInDB"
) -> list[Widget]:
    """Archive the widgets serving an assistant that is being deleted.

    Widgets reference their assistant without a foreign key. Run in the
    deletion's transaction, so the widgets go with it or not at all; archived,
    they stop serving and no longer hold their template.
    """
    repo = WidgetRepoImpl(session)
    return await _archive(
        session,
        await repo.list_by_target(assistant_id),
        user=user,
        reason="assistant_deleted",
        because="its assistant was deleted",
    )


async def archive_drafts_of_moved_assistant(
    session: "AsyncSession", *, drafts: list[Widget], user: "UserInDB"
) -> list[Widget]:
    """Archive the draft widgets of an assistant moving to another space.

    A draft never served anyone, and in its old space it could never serve
    the moved assistant. Run in the move's transaction.
    """
    return await _archive(
        session,
        drafts,
        user=user,
        reason="assistant_moved",
        because="its assistant moved to another space",
    )


async def _archive(
    session: "AsyncSession",
    widgets: list[Widget],
    *,
    user: "UserInDB",
    reason: str,
    because: str,
) -> list[Widget]:
    repo = WidgetRepoImpl(session)
    archived: list[Widget] = []
    for widget in widgets:
        widget.archive()
        archived.append(
            await repo.update(widget, check_revision=False, only=LIFECYCLE_FIELDS)
        )
    if not archived:
        return archived
    audit = _audit_service(session)
    for widget in archived:
        assert widget.id is not None
        await audit.log_async(
            tenant_id=widget.tenant_id,
            user=user,
            action=ActionType.WIDGET_ARCHIVED,
            entity_type=EntityType.WIDGET,
            entity_id=widget.id,
            description=f"Archived widget '{widget.name}': {because}",
            metadata=AuditMetadata.standard(
                actor=user,
                target=widget,
                changes={"new": audit_snapshot(widget)},
                extra={
                    "public_id": widget.public_id,
                    "space_id": str(widget.space_id),
                    "reason": reason,
                },
            ),
        )
    return archived
