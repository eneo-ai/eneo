from typing import TYPE_CHECKING
from uuid import UUID

from eneo.main.exceptions import (
    BadRequestException,
    NotFoundException,
    SkillRevisionConflictException,
    UnauthorizedException,
)
from eneo.roles.permissions import Permission
from eneo.skills.domain.skill import (
    NormalizedSkillContent,
    OrganizationSkillProjection,
    OrganizationSkillSummaryProjection,
    OrganizationSkillSummaryProjectionPage,
    PersonalChatPinAdvance,
    PersonalChatPinAdvanceOutcome,
    PublishedSkillProjection,
    PublishedSkillSummaryPage,
    PublishedSkillSummaryProjection,
    Skill,
    SkillAdoptionCursor,
    SkillAdoptionProjectionPage,
    SkillPublicationChange,
    SkillRevision,
    SkillRevisionChange,
    SkillRevisionConflictError,
    SkillRevisionPage,
    SkillRevisionRestore,
    parse_skill_revision_cursor,
    validate_skill_slug,
)
from eneo.skills.domain.skill_repo import SkillRepo
from eneo.users.user import UserInDB

if TYPE_CHECKING:
    from eneo.assistants.assistant_service import AssistantService
    from eneo.spaces.space_service import SpaceService


class OrganizationSkillService:
    def __init__(
        self,
        *,
        user: UserInDB,
        repo: SkillRepo,
        space_service: "SpaceService",
        assistant_service: "AssistantService",
    ) -> None:
        self.user = user
        self.repo = repo
        self.space_service = space_service
        # The one fit/activatability owner. Injected rather than imported so
        # this module keeps no dependency on the assistants package at import
        # time; only the pin-advance operation needs it.
        self.assistant_service = assistant_service

    def _require_catalogue_read(self) -> None:
        if (
            Permission.ADMIN not in self.user.permissions
            and Permission.SKILLS not in self.user.permissions
        ):
            raise UnauthorizedException(
                "You do not have permission to browse organisation Skills"
            )

    def _require_admin(self) -> None:
        if Permission.ADMIN not in self.user.permissions:
            raise UnauthorizedException(
                "Tenant administrator permission is required to publish "
                "or manage organisation Skills"
            )

    async def list_catalogue(
        self,
        *,
        limit: int,
        cursor: str | None,
        search: str | None = None,
    ) -> PublishedSkillSummaryPage:
        self._require_catalogue_read()
        normalized_search = search.strip() if search else None
        summaries = await self.repo.list_published_for_tenant(
            tenant_id=self.user.tenant_id,
            limit=limit + 1,
            after_slug=cursor,
            search=normalized_search or None,
        )
        visible = summaries[:limit]
        blocks = (
            await self.repo.list_active_execution_blocks(
                tenant_id=self.user.tenant_id,
                skill_ids=[summary.id for summary in visible],
            )
            if visible
            else {}
        )
        return PublishedSkillSummaryPage(
            items=tuple(
                PublishedSkillSummaryProjection(
                    skill=summary,
                    execution_blocked=summary.id in blocks,
                )
                for summary in visible
            ),
            limit=limit,
            next_cursor=(
                visible[-1].slug if len(summaries) > limit and visible else None
            ),
        )

    async def get_catalogue_skill(
        self,
        *,
        skill_id: UUID,
    ) -> PublishedSkillProjection:
        self._require_catalogue_read()
        skill = await self.repo.get_published_for_tenant(
            tenant_id=self.user.tenant_id,
            skill_id=skill_id,
        )
        if skill is None:
            raise NotFoundException()
        blocks = await self.repo.list_active_execution_blocks(
            tenant_id=self.user.tenant_id,
            skill_ids=[skill.summary.id],
        )
        return PublishedSkillProjection(
            skill=skill,
            execution_blocked=skill.summary.id in blocks,
        )

    async def list_organization_skills(
        self,
        *,
        limit: int,
        cursor: str | None,
        search: str | None = None,
    ) -> OrganizationSkillSummaryProjectionPage:
        self._require_admin()
        normalized_search = search.strip() if search else None
        summaries = await self.repo.list_organization_for_tenant(
            tenant_id=self.user.tenant_id,
            limit=limit + 1,
            after_slug=cursor,
            search=normalized_search or None,
        )
        visible = summaries[:limit]
        blocks = (
            await self.repo.list_active_execution_blocks(
                tenant_id=self.user.tenant_id,
                skill_ids=[summary.id for summary in visible],
            )
            if visible
            else {}
        )
        return OrganizationSkillSummaryProjectionPage(
            items=tuple(
                OrganizationSkillSummaryProjection(
                    skill=summary,
                    execution_blocked=summary.id in blocks,
                )
                for summary in visible
            ),
            limit=limit,
            next_cursor=(
                visible[-1].slug if len(summaries) > limit and visible else None
            ),
        )

    async def get_organization_skill(self, *, skill_id: UUID) -> Skill:
        self._require_admin()
        skill = await self.repo.get_organization_for_tenant(
            tenant_id=self.user.tenant_id,
            skill_id=skill_id,
        )
        if skill is None:
            raise NotFoundException()
        return skill

    async def project_organization_skill(
        self,
        *,
        skill: Skill,
    ) -> OrganizationSkillProjection:
        blocks = await self.repo.list_active_execution_blocks(
            tenant_id=self.user.tenant_id,
            skill_ids=[skill.id],
        )
        return OrganizationSkillProjection(
            skill=skill,
            execution_blocked=skill.id in blocks,
        )

    async def get_organization_skill_projection(
        self,
        *,
        skill_id: UUID,
    ) -> OrganizationSkillProjection:
        skill = await self.get_organization_skill(skill_id=skill_id)
        return await self.project_organization_skill(skill=skill)

    async def get_adoption_projection(
        self,
        *,
        skill_id: UUID,
        limit: int,
        cursor: str | None,
    ) -> SkillAdoptionProjectionPage:
        self._require_admin()
        after = SkillAdoptionCursor.parse(cursor)
        projection = await self.repo.get_organization_adoption_projection_page(
            tenant_id=self.user.tenant_id,
            skill_id=skill_id,
            limit=limit,
            after=after,
        )
        if projection is None:
            raise NotFoundException()
        return projection

    async def create_organization_skill(
        self,
        *,
        slug: str,
        display_name: str,
        description: str,
        instructions: str,
    ) -> Skill:
        self._require_admin()
        organization = await self.space_service.get_or_create_tenant_space()
        if (
            organization.id is None
            or organization.tenant_id != self.user.tenant_id
            or not organization.is_organization()
        ):
            raise RuntimeError("Tenant organisation Space is invalid")

        normalized_slug = validate_skill_slug(slug)
        content = NormalizedSkillContent.create(
            display_name=display_name,
            description=description,
            instructions=instructions,
        )
        return await self.repo.create(
            space_id=organization.id,
            slug=normalized_slug,
            display_name=content.display_name,
            description=content.description,
            instructions=content.instructions,
            content_digest=content.content_digest,
            created_by_user_id=self.user.id,
            is_active=False,
        )

    async def create_revision(
        self,
        *,
        skill_id: UUID,
        display_name: str,
        description: str,
        instructions: str,
    ) -> SkillRevisionChange:
        skill = await self.get_organization_skill(skill_id=skill_id)
        content = NormalizedSkillContent.create(
            display_name=display_name,
            description=description,
            instructions=instructions,
        )
        change = await self.repo.create_revision(
            skill_id=skill.id,
            display_name=content.display_name,
            description=content.description,
            instructions=content.instructions,
            content_digest=content.content_digest,
            created_by_user_id=self.user.id,
        )
        if change is None:
            raise NotFoundException()
        return change

    async def list_revision_summaries(
        self,
        *,
        skill_id: UUID,
        limit: int,
        cursor: str | None,
    ) -> SkillRevisionPage:
        skill = await self.get_organization_skill(skill_id=skill_id)
        before_revision_number = parse_skill_revision_cursor(cursor)
        revisions = await self.repo.list_revision_summaries(
            skill_id=skill.id,
            limit=limit + 1,
            before_revision_number=before_revision_number,
        )
        visible = revisions[:limit]
        return SkillRevisionPage(
            items=tuple(visible),
            limit=limit,
            next_cursor=(
                visible[-1].revision_number
                if len(revisions) > limit and visible
                else None
            ),
            total_count=await self.repo.count_revisions(skill_id=skill.id),
        )

    async def get_revision(
        self,
        *,
        skill_id: UUID,
        revision_id: UUID,
    ) -> SkillRevision:
        skill = await self.get_organization_skill(skill_id=skill_id)
        revision = await self.repo.get_revision(
            skill_id=skill.id,
            revision_id=revision_id,
        )
        if revision is None:
            raise NotFoundException()
        return revision

    async def restore_revision(
        self,
        *,
        skill_id: UUID,
        source_revision_id: UUID,
        reviewed_current_revision_id: UUID,
    ) -> SkillRevisionRestore:
        skill = await self.get_organization_skill(skill_id=skill_id)
        source_revision = await self.repo.get_revision(
            skill_id=skill.id,
            revision_id=source_revision_id,
        )
        if source_revision is None:
            raise NotFoundException()
        try:
            change = await self.repo.create_revision(
                skill_id=skill.id,
                display_name=source_revision.display_name,
                description=source_revision.description,
                instructions=source_revision.instructions,
                content_digest=source_revision.content_digest,
                created_by_user_id=self.user.id,
                expected_current_revision_id=reviewed_current_revision_id,
            )
        except SkillRevisionConflictError as error:
            raise SkillRevisionConflictException(
                "This Skill changed after you reviewed it. Compare the latest "
                "revision before restoring again."
            ) from error
        if change is None:
            raise NotFoundException()
        return SkillRevisionRestore(
            source_revision=source_revision,
            change=change,
        )

    async def publish(
        self,
        *,
        skill_id: UUID,
        expected_revision_id: UUID,
    ) -> SkillPublicationChange:
        self._require_admin()
        try:
            change = await self.repo.publish_organization(
                tenant_id=self.user.tenant_id,
                skill_id=skill_id,
                expected_revision_id=expected_revision_id,
            )
        except SkillRevisionConflictError as error:
            raise SkillRevisionConflictException(
                "This Skill changed since you reviewed it. Reload it before publishing."
            ) from error
        if change is None:
            raise NotFoundException()
        return change

    async def unpublish(self, *, skill_id: UUID) -> SkillPublicationChange:
        self._require_admin()
        change = await self.repo.unpublish_organization(
            tenant_id=self.user.tenant_id,
            skill_id=skill_id,
        )
        if change is None:
            raise NotFoundException()
        return change

    async def advance_personal_chat_binding(
        self,
        *,
        skill_id: UUID,
        expected_pinned_revision_id: UUID,
        expected_published_revision_id: UUID,
    ) -> PersonalChatPinAdvance:
        """Move the Personal Chat pin for one Skill to its published revision.

        Admin-only. The repo guards the write with the pinned revision the
        administrator reviewed; after an actual change, the same governance
        fit validation that guards every policy save runs against the new
        pin, so an advance can never admit a configuration the next save
        would reject. A failed validation raises and rolls the advance back.
        """
        self._require_admin()
        try:
            advance = await self.repo.advance_personal_chat_skill_pin(
                tenant_id=self.user.tenant_id,
                skill_id=skill_id,
                expected_pinned_revision_id=expected_pinned_revision_id,
                expected_published_revision_id=expected_published_revision_id,
            )
        except SkillRevisionConflictError as error:
            raise SkillRevisionConflictException(
                "The Skill's published version or its Personal Chat binding "
                "changed after you reviewed it. Reload the Skill and review "
                "again."
            ) from error
        if advance is None:
            raise NotFoundException()
        if advance.outcome is PersonalChatPinAdvanceOutcome.NOT_BOUND:
            raise NotFoundException("Personal Chat has no binding for this Skill")
        if advance.outcome is PersonalChatPinAdvanceOutcome.NOT_PUBLISHED:
            raise BadRequestException(
                "Personal Chat can only use published organisation Skill versions"
            )
        if advance.outcome is PersonalChatPinAdvanceOutcome.BLOCKED:
            raise BadRequestException(
                "Blocked organisation Skills cannot receive new or changed bindings"
            )
        if advance.outcome is PersonalChatPinAdvanceOutcome.ADVANCED:
            await (
                self.assistant_service.assert_personal_default_governance_context_fit()
            )
        return advance

    async def delete(self, *, skill_id: UUID) -> Skill:
        self._require_admin()
        deleted = await self.repo.delete_organization(
            tenant_id=self.user.tenant_id,
            skill_id=skill_id,
        )
        if deleted is None:
            raise NotFoundException()
        return deleted
