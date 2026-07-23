from eneo.skills.domain.skill import (
    PublishedSkill,
    PublishedSkillSummary,
    ResolvedSkillBinding,
    Skill,
    SkillAdoptionPersonalChat,
    SkillAdoptionProjectionPage,
    SkillAdoptionResource,
    SkillAdoptionRevisionCount,
    SkillAdoptionSummary,
    SkillBindingReference,
    SkillCatalogEntry,
    SkillRevision,
    SkillRevisionSummary,
    SkillSummary,
)
from eneo.skills.presentation.skill_models import (
    OrganizationSkillPublic,
    OrganizationSkillSummaryPublic,
    PublishedSkillPublic,
    PublishedSkillRevisionPublic,
    PublishedSkillSummaryPublic,
    SkillAdoptionPersonalChatPublic,
    SkillAdoptionProjectionPagePublic,
    SkillAdoptionResourcePublic,
    SkillAdoptionRevisionCountPublic,
    SkillAdoptionSummaryPublic,
    SkillBindingReferenceInput,
    SkillBindingSummary,
    SkillPublic,
    SkillRevisionPublic,
    SkillRevisionSummaryPublic,
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
    def adoption_resource_to_public(
        resource: SkillAdoptionResource,
    ) -> SkillAdoptionResourcePublic:
        return SkillAdoptionResourcePublic(
            kind=resource.kind,
            resource_id=resource.resource_id,
            name=resource.name,
            space_id=resource.space_id,
            space_name=resource.space_name,
            revision_id=resource.revision_id,
            revision_number=resource.revision_number,
            drift=resource.drift,
        )

    @staticmethod
    def adoption_personal_chat_to_public(
        personal_chat: SkillAdoptionPersonalChat,
    ) -> SkillAdoptionPersonalChatPublic:
        return SkillAdoptionPersonalChatPublic(
            revision_id=personal_chat.revision_id,
            revision_number=personal_chat.revision_number,
            drift=personal_chat.drift,
        )

    @staticmethod
    def adoption_revision_count_to_public(
        revision_count: SkillAdoptionRevisionCount,
    ) -> SkillAdoptionRevisionCountPublic:
        return SkillAdoptionRevisionCountPublic(
            revision_id=revision_count.revision_id,
            revision_number=revision_count.revision_number,
            assistant_count=revision_count.assistant_count,
            app_count=revision_count.app_count,
            personal_chat_pinned=revision_count.personal_chat_pinned,
        )

    @classmethod
    def adoption_summary_to_public(
        cls,
        summary: SkillAdoptionSummary,
    ) -> SkillAdoptionSummaryPublic:
        return SkillAdoptionSummaryPublic(
            assistant_count=summary.assistant_count,
            app_count=summary.app_count,
            distinct_space_count=summary.distinct_space_count,
            behind_published_count=summary.behind_published_count,
            personal_chat=(
                cls.adoption_personal_chat_to_public(summary.personal_chat)
                if summary.personal_chat is not None
                else None
            ),
            revision_counts=[
                cls.adoption_revision_count_to_public(revision_count)
                for revision_count in summary.revision_counts
            ],
        )

    @classmethod
    def adoption_projection_to_public(
        cls,
        projection: SkillAdoptionProjectionPage,
    ) -> SkillAdoptionProjectionPagePublic:
        return SkillAdoptionProjectionPagePublic(
            summary=cls.adoption_summary_to_public(projection.summary),
            items=[
                cls.adoption_resource_to_public(resource)
                for resource in projection.items
            ],
            limit=projection.limit,
            next_cursor=projection.next_cursor,
        )

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

    @staticmethod
    def revision_summary_to_public(
        revision: SkillRevisionSummary,
    ) -> SkillRevisionSummaryPublic:
        return SkillRevisionSummaryPublic(
            id=revision.id,
            skill_id=revision.skill_id,
            revision_number=revision.revision_number,
            display_name=revision.display_name,
            created_at=revision.created_at,
        )

    @classmethod
    def catalog_entry_to_sparse(cls, entry: SkillCatalogEntry) -> SkillSparse:
        return SkillSparse(
            id=entry.id,
            space_id=entry.space_id,
            slug=entry.slug,
            is_active=entry.is_active,
            current_revision_id=entry.current_revision_id,
            current_revision_number=entry.current_revision_number,
            display_name=entry.display_name,
            description=entry.description,
            content_digest=entry.content_digest,
            created_by_user_id=entry.created_by_user_id,
            created_at=entry.created_at,
            updated_at=entry.updated_at,
        )

    @staticmethod
    def to_sparse(skill: Skill) -> SkillSparse:
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
    def organization_summary_to_public(
        skill: SkillSummary,
    ) -> OrganizationSkillSummaryPublic:
        return OrganizationSkillSummaryPublic(
            id=skill.id,
            space_id=skill.space_id,
            slug=skill.slug,
            is_active=skill.is_active,
            current_revision_id=skill.current_revision_id,
            current_revision_number=skill.current_revision_number,
            display_name=skill.display_name,
            description=skill.description,
            content_digest=skill.content_digest,
            created_by_user_id=skill.created_by_user_id,
            created_at=skill.created_at,
            updated_at=skill.updated_at,
            published_revision_number=skill.published_revision_number,
            first_published_at=skill.first_published_at,
            publication_state=skill.publication_state,
        )

    @classmethod
    def organization_to_public(cls, skill: Skill) -> OrganizationSkillPublic:
        return OrganizationSkillPublic(
            **cls.to_sparse(skill).model_dump(),
            published_revision_number=skill.published_revision_number,
            first_published_at=skill.first_published_at,
            publication_state=skill.publication_state,
            current_revision=cls.revision_to_public(skill.current_revision),
        )

    @staticmethod
    def published_summary_to_public(
        skill: PublishedSkillSummary,
    ) -> PublishedSkillSummaryPublic:
        return PublishedSkillSummaryPublic(
            id=skill.id,
            slug=skill.slug,
            revision_id=skill.revision_id,
            revision_number=skill.revision_number,
            display_name=skill.display_name,
            description=skill.description,
            content_digest=skill.content_digest,
            first_published_at=skill.first_published_at,
        )

    @classmethod
    def published_to_public(cls, skill: PublishedSkill) -> PublishedSkillPublic:
        return PublishedSkillPublic(
            **cls.published_summary_to_public(skill.summary).model_dump(),
            revision=PublishedSkillRevisionPublic(
                id=skill.revision.id,
                skill_id=skill.revision.skill_id,
                revision_number=skill.revision.revision_number,
                display_name=skill.revision.display_name,
                description=skill.revision.description,
                instructions=skill.revision.instructions,
                content_digest=skill.revision.content_digest,
                created_at=skill.revision.created_at,
            ),
        )

    @staticmethod
    def binding_to_summary(binding: ResolvedSkillBinding) -> SkillBindingSummary:
        return SkillBindingSummary(
            skill_id=binding.skill_id,
            skill_revision_id=binding.skill_revision_id,
            attachable_revision_id=binding.attachable_revision_id,
            slug=binding.slug,
            revision_number=binding.revision_number,
            attachable_revision_number=binding.attachable_revision_number,
            display_name=binding.display_name,
            description=binding.description,
            content_digest=binding.content_digest,
            position=binding.position,
            is_active=binding.is_active,
            source=binding.source,
        )
