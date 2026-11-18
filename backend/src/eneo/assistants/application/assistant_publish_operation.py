"""Publishing or unpublishing an assistant, for every caller that does it.

The refusals, the change, its ``ASSISTANT_PUBLISHED`` audit entry and the
follow-ups run as one sequence, so publishing through the REST API and on a
person's behalf write the same entry, with that person as actor. The caller
owns the transaction.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast
from uuid import UUID

from eneo.assistants.application.assistant_guards import raise_if_helper_chat
from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.authentication.api_key_notification_auto_follow import (
    auto_follow_on_publish,
)
from eneo.authentication.auth_models import ApiKeyNotificationTargetType
from eneo.database.database import AsyncSession

if TYPE_CHECKING:
    from eneo.assistants.assistant import Assistant
    from eneo.main.container.container import Container
    from eneo.main.models import ResourcePermission

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AppliedAssistantPublish:
    """The assistant as publishing left it, with the caller's permissions on
    it."""

    assistant: Assistant
    permissions: list[ResourcePermission]


async def apply_assistant_publish(
    container: Container,
    *,
    assistant_id: UUID,
    published: bool,
    audit_context: Mapping[str, str] | None = None,
) -> AppliedAssistantPublish:
    """Publish or unpublish the assistant as the container's user and audit
    it.

    A helper chat's assistant answers as one that does not exist, before
    anything is written; the service refuses a user who may not publish and a
    flow-managed assistant. The ``ASSISTANT_PUBLISHED`` entry names the
    container's user as actor. ``audit_context`` is merged into the entry's
    metadata extra (over a key the entry sets itself), for a caller that
    publishes on the user's behalf. Publishing then makes the user follow the
    assistant's API key expiry notifications where their preferences ask for
    it; a failure there is logged and does not undo the publishing.
    """
    await raise_if_helper_chat(container, assistant_id)
    service = container.assistant_service()
    user = container.user()

    # Publish/unpublish assistant
    assistant, permissions = await service.publish_assistant(
        assistant_id=assistant_id, publish=published
    )

    # Get space for context
    space = None
    if assistant.space_id:
        try:
            space_service = container.space_service()
            space = await space_service.get_space(assistant.space_id)
        except Exception:
            space = None

    # Build extra context
    extra: dict[str, object] = {
        "published": published,
        "action": "published" if published else "unpublished",
    }
    if audit_context:
        extra = {**extra, **audit_context}

    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        user=user,
        action=ActionType.ASSISTANT_PUBLISHED,
        entity_type=EntityType.ASSISTANT,
        entity_id=assistant_id,
        description=f"{'Published' if published else 'Unpublished'} assistant '{assistant.name}'",
        metadata=AuditMetadata.standard(
            actor=user,
            target=assistant,
            space=space,
            extra=extra,
        ),
    )

    if published:
        try:
            session = cast(AsyncSession, container.session())
            await auto_follow_on_publish(
                session=session,
                user=user,
                target_type=ApiKeyNotificationTargetType.ASSISTANT,
                target_id=assistant_id,
            )
        except Exception:
            logger.exception(
                "Failed to auto-follow API key expiry notifications for published assistant %s",
                assistant_id,
            )

    return AppliedAssistantPublish(assistant=assistant, permissions=permissions)
