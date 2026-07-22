from typing import TYPE_CHECKING
from uuid import UUID

from eneo.main.exceptions import (
    NameCollisionException,
    NotFoundException,
    UnauthorizedException,
)
from eneo.roles.permissions import Permission
from eneo.skills.domain.skill import (
    NormalizedSkillContent,
    PublishedSkill,
    PublishedSkillDeletionError,
    PublishedSkillSummaryPage,
    Skill,
    SkillHasActiveAppRunsError,
    SkillHasBindingsError,
    SkillPublicationChange,
    SkillRevision,
    SkillRevisionChange,
    SkillRevisionConflictError,
    SkillRevisionPage,
    SkillRevisionRestore,
    SkillSlugConflictError,
    SkillSummaryPage,
    parse_skill_revision_cursor,
    validate_skill_slug,
)
from eneo.skills.domain.skill_repo import SkillRepo
from eneo.users.user import UserInDB

if TYPE_CHECKING:
    from eneo.spaces.space_service import SpaceService


class OrganizationSkillService:
    def __init__(
        self,
        *,
        user: UserInDB,
        repo: SkillRepo,
        space_service: "SpaceService",
    ) -> None:
        self.user = user
        self.repo = repo
        self.space_service = space_service

    def _require_catalogue_read(self) -> None:
        if (
            Permission.ADMIN not in self.user.permissions
            and Permission.SKILLS not in self.user.permissions
        ):
            raise UnauthorizedException(
                "You do not have permission to browse organisation Skills"
            )

    def _require_management(self) -> None:
        self._require_admin()

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
        return PublishedSkillSummaryPage(
            items=tuple(visible),
            limit=limit,
            next_cursor=(
                visible[-1].slug if len(summaries) > limit and visible else None
            ),
        )

    async def get_catalogue_skill(self, *, skill_id: UUID) -> PublishedSkill:
        self._require_catalogue_read()
        skill = await self.repo.get_published_for_tenant(
            tenant_id=self.user.tenant_id,
            skill_id=skill_id,
        )
        if skill is None:
            raise NotFoundException()
        return skill

    async def list_organization_skills(
        self,
        *,
        limit: int,
        cursor: str | None,
        search: str | None = None,
    ) -> SkillSummaryPage:
        self._require_management()
        normalized_search = search.strip() if search else None
        summaries = await self.repo.list_organization_for_tenant(
            tenant_id=self.user.tenant_id,
            limit=limit + 1,
            after_slug=cursor,
            search=normalized_search or None,
        )
        visible = summaries[:limit]
        return SkillSummaryPage(
            items=tuple(visible),
            limit=limit,
            next_cursor=(
                visible[-1].slug if len(summaries) > limit and visible else None
            ),
        )

    async def get_organization_skill(self, *, skill_id: UUID) -> Skill:
        self._require_management()
        skill = await self.repo.get_organization_for_tenant(
            tenant_id=self.user.tenant_id,
            skill_id=skill_id,
        )
        if skill is None:
            raise NotFoundException()
        return skill

    async def create_organization_skill(
        self,
        *,
        slug: str,
        display_name: str,
        description: str,
        instructions: str,
    ) -> Skill:
        self._require_management()
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
        try:
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
        except SkillSlugConflictError as error:
            raise NameCollisionException(
                f"A Skill with slug '{normalized_slug}' already exists "
                "in the organisation catalogue"
            ) from error

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
    ) -> SkillRevisionRestore:
        skill = await self.get_organization_skill(skill_id=skill_id)
        source_revision = await self.repo.get_revision(
            skill_id=skill.id,
            revision_id=source_revision_id,
        )
        if source_revision is None:
            raise NotFoundException()
        change = await self.repo.create_revision(
            skill_id=skill.id,
            display_name=source_revision.display_name,
            description=source_revision.description,
            instructions=source_revision.instructions,
            content_digest=source_revision.content_digest,
            created_by_user_id=self.user.id,
        )
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
            raise NameCollisionException(
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

    async def delete(self, *, skill_id: UUID) -> Skill:
        self._require_admin()
        try:
            deleted = await self.repo.delete_organization(
                tenant_id=self.user.tenant_id,
                skill_id=skill_id,
            )
        except PublishedSkillDeletionError as error:
            raise NameCollisionException(
                "Unpublish this Skill before deleting it."
            ) from error
        except SkillHasActiveAppRunsError as error:
            raise NameCollisionException(
                "This Skill is required by a queued or running App run. "
                "Wait for it to finish before deleting the Skill."
            ) from error
        except SkillHasBindingsError as error:
            raise NameCollisionException(
                "This Skill is still attached. Remove every binding before deleting it."
            ) from error
        if deleted is None:
            raise NotFoundException()
        return deleted
