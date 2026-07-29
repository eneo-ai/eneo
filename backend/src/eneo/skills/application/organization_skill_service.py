from typing import TYPE_CHECKING, cast
from uuid import UUID, uuid4

from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.main.exceptions import (
    BadRequestException,
    NotFoundException,
    SkillRevisionConflictException,
    UnauthorizedException,
)
from eneo.roles.permissions import Permission
from eneo.skills.domain.skill import (
    AssistantFleetAdvanceCursor,
    AssistantFleetChunkOutcome,
    AssistantPinAdvanceOutcome,
    AssistantPinAdvanceTarget,
    AssistantPinAdvanceTargetResult,
    NormalizedSkillContent,
    OrganizationSkillProjection,
    OrganizationSkillSummaryProjection,
    OrganizationSkillSummaryProjectionPage,
    PersonalChatPinAdvance,
    PersonalChatPinAdvanceOutcome,
    PersonalChatPinConfirmOutcome,
    PersonalChatPinOverride,
    PublishedSkillProjection,
    PublishedSkillSummaryPage,
    PublishedSkillSummaryProjection,
    Skill,
    SkillAdoptionCursor,
    SkillAdoptionProjectionPage,
    SkillBindingReference,
    SkillBlockedForBindingError,
    SkillNotPublishedForBindingError,
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
from eneo.skills.presentation.skill_audit import skill_audit_extra
from eneo.spaces.space_repo import AssistantMCPServerProjection
from eneo.users.user import UserInDB

if TYPE_CHECKING:
    from eneo.ai_models.completion_models.completion_model import (
        CompletionModel as AICompletionModel,
    )
    from eneo.assistants.assistant_service import AssistantService
    from eneo.audit.application.audit_service import AuditService
    from eneo.spaces.space_service import SpaceService


_FLEET_ADVANCE_CHUNK_SIZE = 100


class OrganizationSkillService:
    def __init__(
        self,
        *,
        user: UserInDB,
        repo: SkillRepo,
        space_service: "SpaceService",
        assistant_service: "AssistantService",
        audit_service: "AuditService",
    ) -> None:
        self.user = user
        self.repo = repo
        self.space_service = space_service
        # The one fit/activatability owner. Injected rather than imported so
        # this module keeps no dependency on the assistants package at import
        # time; only the pin-advance operation needs it.
        self.assistant_service = assistant_service
        self.audit_service = audit_service

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

        Admin-only, in three steps sharing one transaction: the repo reads the
        candidate and fit-input snapshot without locks, the governance fit
        owner validates with that candidate pin, and a short confirm locks,
        rechecks, and writes. Any refusal raises.
        """
        self._require_admin()
        try:
            stage = await self.repo.stage_personal_chat_skill_pin_advance(
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
        if stage is None:
            raise NotFoundException()
        advance = stage.advance
        if advance.outcome is PersonalChatPinAdvanceOutcome.NOT_BOUND:
            raise NotFoundException("Personal Chat has no binding for this Skill")
        if advance.outcome is PersonalChatPinAdvanceOutcome.NOT_PUBLISHED:
            raise SkillNotPublishedForBindingError
        if advance.outcome is PersonalChatPinAdvanceOutcome.BLOCKED:
            raise SkillBlockedForBindingError
        if advance.outcome is PersonalChatPinAdvanceOutcome.ADVANCED:
            assert (
                advance.from_revision_id is not None
                and advance.to_revision_id is not None
                and stage.personal_defaults_snapshot is not None
            )
            await self.assistant_service.assert_personal_default_governance_context_fit(
                personal_chat_pin_override=PersonalChatPinOverride(
                    skill_id=skill_id,
                    from_revision_id=advance.from_revision_id,
                    to_revision_id=advance.to_revision_id,
                )
            )
            assert stage.policy_id is not None and stage.policy_version is not None
            confirm = await self.repo.confirm_personal_chat_skill_pin_advance(
                tenant_id=self.user.tenant_id,
                skill_id=skill_id,
                policy_id=stage.policy_id,
                policy_version=stage.policy_version,
                personal_defaults_snapshot=stage.personal_defaults_snapshot,
                expected_pinned_revision_id=expected_pinned_revision_id,
                expected_published_revision_id=expected_published_revision_id,
            )
            if confirm is PersonalChatPinConfirmOutcome.BLOCKED:
                raise SkillBlockedForBindingError
            if confirm is not PersonalChatPinConfirmOutcome.CONFIRMED:
                raise SkillRevisionConflictException(
                    "The Personal Chat policy or the Skill changed while the "
                    "move was being validated. Reload the Skill and review "
                    "again."
                )
        return advance

    async def advance_assistant_bindings(
        self,
        *,
        skill_id: UUID,
        expected_published_revision_id: UUID,
        cursor: str | None,
    ) -> AssistantFleetChunkOutcome:
        self._require_admin()
        parsed_cursor = AssistantFleetAdvanceCursor.parse(cursor)
        if parsed_cursor is not None and (
            parsed_cursor.skill_id != skill_id
            or parsed_cursor.expected_published_revision_id
            != expected_published_revision_id
        ):
            raise BadRequestException("Assistant fleet cursor does not match request")
        run_id = parsed_cursor.run_id if parsed_cursor is not None else uuid4()
        try:
            skill = await self.repo.get_assistant_fleet_advance_candidate(
                tenant_id=self.user.tenant_id,
                skill_id=skill_id,
                expected_published_revision_id=expected_published_revision_id,
            )
        except SkillRevisionConflictError as error:
            raise SkillRevisionConflictException(
                "The Skill's published version changed after you reviewed it. "
                "Reload the Skill and review again."
            ) from error
        if skill is None:
            raise NotFoundException()
        targets, next_after = await self.repo.list_assistant_pin_advance_targets(
            tenant_id=self.user.tenant_id,
            skill_id=skill_id,
            expected_published_revision_id=expected_published_revision_id,
            after_assistant_id=(
                parsed_cursor.after_assistant_id if parsed_cursor is not None else None
            ),
            limit=_FLEET_ADVANCE_CHUNK_SIZE,
        )
        if not targets:
            return AssistantFleetChunkOutcome(
                run_id=run_id,
                cursor=None,
                results=(),
                advanced_count=0,
                concurrent_change_count=0,
                incompatible_count=0,
            )

        runtime_policy_snapshot = await self.repo.get_runtime_policy_snapshot(
            tenant_id=self.user.tenant_id
        )
        assistant_ids = [target.assistant_id for target in targets]
        validation_inputs = await self.assistant_service.repo.get_by_ids_for_validation(
            tenant_id=self.user.tenant_id,
            assistant_ids=assistant_ids,
        )
        resolutions = await self.assistant_service.skill_service.resolve_assistant_bindings_for_runtime_batch(
            assistant_ids
        )
        candidate_bindings = await self.repo.resolve_references_for_execution_snapshot(
            tenant_id=self.user.tenant_id,
            parent_space_id=skill.space_id,
            references=[
                SkillBindingReference(
                    skill_id=skill_id,
                    skill_revision_id=expected_published_revision_id,
                )
            ],
        )
        if len(candidate_bindings) != 1:
            raise SkillRevisionConflictException(
                "The Skill's published version changed after you reviewed it. "
                "Reload the Skill and review again."
            )
        candidate_binding = candidate_bindings[0]
        models = {
            validation_input.assistant.completion_model.id: (
                validation_input.assistant.completion_model
            )
            for validation_input in validation_inputs.values()
            if validation_input.assistant.completion_model is not None
        }
        preflight_adapters = await self.assistant_service.completion_service.load_skill_activation_preflight_adapters(
            [cast("AICompletionModel", model) for model in models.values()]
        )
        mcp_projections = [
            AssistantMCPServerProjection(
                space_id=validation_input.assistant.space_id,
                assistant_id=assistant_id,
                mcp_servers=validation_input.configured_mcp_servers,
            )
            for assistant_id, validation_input in validation_inputs.items()
            if validation_input.configured_mcp_servers
            and not validation_input.has_knowledge
        ]
        projected_mcp_servers = (
            await self.assistant_service.space_repo.project_assistants_mcp_servers(
                mcp_projections
            )
            if mcp_projections
            else {}
        )

        validation_results: list[AssistantPinAdvanceTargetResult] = []
        write_targets: list[AssistantPinAdvanceTarget] = []
        for target in targets:
            validation_input = validation_inputs.get(target.assistant_id)
            if validation_input is None:
                validation_results.append(
                    AssistantPinAdvanceTargetResult(
                        assistant_id=target.assistant_id,
                        outcome=AssistantPinAdvanceOutcome.CONCURRENT_CHANGE,
                    )
                )
                continue
            resolution = resolutions[target.assistant_id]
            source_binding_present = any(
                binding.skill_id == skill_id
                and binding.skill_revision_id == target.from_revision_id
                for binding in (*resolution.eligible, *resolution.blocked)
            )
            if not source_binding_present:
                validation_results.append(
                    AssistantPinAdvanceTargetResult(
                        assistant_id=target.assistant_id,
                        outcome=AssistantPinAdvanceOutcome.CONCURRENT_CHANGE,
                    )
                )
                continue
            validation_input.assistant.mcp_servers = projected_mcp_servers.get(
                target.assistant_id,
                [],
            )
            incompatible_reason = await self.assistant_service.assert_assistant_fits_candidate_pin(
                assistant=validation_input.assistant,
                space_is_personal=validation_input.space_is_personal,
                candidate=PersonalChatPinOverride(
                    skill_id=skill_id,
                    from_revision_id=target.from_revision_id,
                    to_revision_id=expected_published_revision_id,
                ),
                candidate_binding=candidate_binding,
                resolution=resolution,
                runtime_policy=runtime_policy_snapshot.policy,
                preflight_adapters=preflight_adapters,
                completion_prompt_files=(
                    await self.assistant_service.repo.hydrate_completion_files_for_validation(
                        assistant=validation_input.assistant,
                        derived_image_metadata=validation_input.derived_image_metadata,
                    )
                ),
            )
            if incompatible_reason is not None:
                validation_results.append(
                    AssistantPinAdvanceTargetResult(
                        assistant_id=target.assistant_id,
                        outcome=AssistantPinAdvanceOutcome.INCOMPATIBLE,
                        reason=incompatible_reason,
                    )
                )
                continue
            write_targets.append(target)

        try:
            write_results = await self.repo.advance_assistant_skill_pins(
                tenant_id=self.user.tenant_id,
                skill_id=skill_id,
                expected_published_revision_id=expected_published_revision_id,
                expected_runtime_policy_version=runtime_policy_snapshot.row_version,
                targets=write_targets,
            )
        except SkillRevisionConflictError as error:
            raise SkillRevisionConflictException(
                "The Skill's published version changed after you reviewed it. "
                "Reload the Skill and review again."
            ) from error

        results = tuple(
            sorted(
                [*validation_results, *write_results],
                key=lambda result: result.assistant_id,
            )
        )
        advanced_count = sum(
            result.outcome is AssistantPinAdvanceOutcome.ADVANCED for result in results
        )
        concurrent_change_count = sum(
            result.outcome is AssistantPinAdvanceOutcome.CONCURRENT_CHANGE
            for result in results
        )
        incompatible_count = sum(
            result.outcome is AssistantPinAdvanceOutcome.INCOMPATIBLE
            for result in results
        )
        next_cursor = (
            AssistantFleetAdvanceCursor(
                skill_id=skill_id,
                expected_published_revision_id=expected_published_revision_id,
                run_id=run_id,
                after_assistant_id=next_after,
            )
            if next_after is not None
            else None
        )
        outcome = AssistantFleetChunkOutcome(
            run_id=run_id,
            cursor=next_cursor,
            results=results,
            advanced_count=advanced_count,
            concurrent_change_count=concurrent_change_count,
            incompatible_count=incompatible_count,
        )
        if advanced_count:
            assert skill.published_revision_number is not None
            await self.audit_service.log(
                tenant_id=self.user.tenant_id,
                user=self.user,
                action=ActionType.SKILL_BINDINGS_ADVANCED,
                entity_type=EntityType.SKILL,
                entity_id=skill.id,
                description=(
                    f"Moved Assistant bindings of Skill "
                    f"'{skill.current_revision.display_name}' to published "
                    f"revision {skill.published_revision_number}"
                ),
                metadata=AuditMetadata.standard(
                    actor=self.user,
                    target=skill,
                    changes={
                        "advanced": advanced_count,
                        "concurrent_change": concurrent_change_count,
                        "incompatible": incompatible_count,
                    },
                    extra={
                        **skill_audit_extra(skill),
                        "surface": "assistant",
                        "run_id": str(run_id),
                    },
                ),
            )
        return outcome

    async def delete(self, *, skill_id: UUID) -> Skill:
        self._require_admin()
        deleted = await self.repo.delete_organization(
            tenant_id=self.user.tenant_id,
            skill_id=skill_id,
        )
        if deleted is None:
            raise NotFoundException()
        return deleted
