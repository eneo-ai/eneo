from eneo.skills.domain.skill import (
    ResolvedSkillBinding,
    Skill,
    SkillBindingReference,
    SkillRevision,
)
from eneo.skills.presentation.skill_models import (
    SkillBindingReferenceInput,
    SkillBindingSummary,
    SkillPublic,
    SkillRevisionPublic,
    SkillSparse,
)


def skill_binding_references_from_input(
    references: list[SkillBindingReferenceInput],
) -> list[SkillBindingReference]:
    return [
        SkillBindingReference(
            skill_id=reference.skill_id,
            skill_revision_id=reference.skill_revision_id,
        )
        for reference in references
    ]


def skill_binding_audit_entries(
    bindings: list[ResolvedSkillBinding],
) -> list[dict[str, object]]:
    return [
        {
            "skill_id": str(binding.skill_id),
            "skill_revision_id": str(binding.skill_revision_id),
            "revision_number": binding.revision_number,
            "content_digest": binding.content_digest,
            "position": binding.position,
        }
        for binding in bindings
    ]


class SkillAssembler:
    @staticmethod
    def revision_to_public(revision: SkillRevision) -> SkillRevisionPublic:
        return SkillRevisionPublic(
            id=revision.id,
            skill_id=revision.skill_id,
            revision_number=revision.revision_number,
            display_name=revision.display_name,
            description=revision.description,
            instructions=revision.instructions,
            content_digest=revision.content_digest,
            created_by_user_id=revision.created_by_user_id,
            created_at=revision.created_at,
        )

    @classmethod
    def to_sparse(cls, skill: Skill) -> SkillSparse:
        revision = skill.current_revision
        return SkillSparse(
            id=skill.id,
            space_id=skill.space_id,
            slug=skill.slug,
            is_active=skill.is_active,
            current_revision_id=revision.id,
            current_revision_number=skill.current_revision_number,
            display_name=revision.display_name,
            description=revision.description,
            content_digest=revision.content_digest,
            created_by_user_id=skill.created_by_user_id,
            created_at=skill.created_at,
            updated_at=skill.updated_at,
        )

    @classmethod
    def to_public(cls, skill: Skill) -> SkillPublic:
        return SkillPublic(
            **cls.to_sparse(skill).model_dump(),
            current_revision=cls.revision_to_public(skill.current_revision),
        )

    @staticmethod
    def binding_to_summary(binding: ResolvedSkillBinding) -> SkillBindingSummary:
        return SkillBindingSummary(
            skill_id=binding.skill_id,
            skill_revision_id=binding.skill_revision_id,
            slug=binding.slug,
            revision_number=binding.revision_number,
            display_name=binding.display_name,
            description=binding.description,
            content_digest=binding.content_digest,
            position=binding.position,
            is_active=binding.is_active,
        )
