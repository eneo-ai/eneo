from __future__ import annotations

from typing import TYPE_CHECKING

from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.skills.domain.skill import Skill

if TYPE_CHECKING:
    from eneo.main.container.container import Container


def skill_audit_extra(skill: Skill) -> dict[str, object]:
    revision = skill.current_revision
    return {
        "slug": skill.slug,
        "is_active": skill.is_active,
        "current_revision_number": revision.revision_number,
        "current_revision_id": str(revision.id),
        "content_digest": revision.content_digest,
        "instruction_length": len(revision.instructions),
        "published_revision_number": skill.published_revision_number,
        "publication_state": skill.publication_state.value,
    }


async def audit_skill_created(*, container: Container, skill: Skill) -> None:
    user = container.user()
    await container.audit_service().log_async(
        tenant_id=user.tenant_id,
        user=user,
        action=ActionType.SKILL_CREATED,
        entity_type=EntityType.SKILL,
        entity_id=skill.id,
        description=f"Created Skill '{skill.current_revision.display_name}'",
        metadata=AuditMetadata.standard(
            actor=user,
            target=skill,
            extra=skill_audit_extra(skill),
        ),
    )
