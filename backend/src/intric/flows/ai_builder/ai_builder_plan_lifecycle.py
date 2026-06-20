from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import UUID

from intric.flows.ai_builder.ai_builder_api_models import (
    ApplyResultResponse,
)
from intric.flows.ai_builder.ai_builder_authoring_policy import AIBuilderAuthoringPolicy
from intric.flows.ai_builder.ai_builder_context import (
    serialize_space_kbs,
    serialize_space_mcps,
    serialize_space_models,
)
from intric.flows.ai_builder.ai_builder_domain_models import (
    BuilderPlan,
    BuilderSession,
    PlanStatus,
    SessionStatus,
    TargetKind,
)
from intric.flows.ai_builder.ai_builder_edit_models import (
    BuilderPlanEditResult,
    CompiledEditResult,
)
from intric.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderBadRequestException,
    AIBuilderErrorCode,
    AIBuilderUnauthorizedException,
)
from intric.flows.ai_builder.ai_builder_proposal_telemetry import (
    ChangesetCountSummary,
    MaterializerProgressSnapshot,
    log_apply_failed,
)
from intric.flows.ai_builder.ai_builder_repo import AIBuilderRepository
from intric.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderResourceCatalog,
    build_ai_builder_resource_catalog,
)
from intric.flows.ai_builder.ai_builder_step_transition_policy import (
    normalize_ai_builder_spec,
)
from intric.flows.application.flow_authoring_command import (
    AIBuilderFlowAuthoringOrigin,
    CreateFlowAuthoringCommand,
    EditFlowAuthoringCommand,
    FlowAuthoringCommand,
    FlowAuthoringCommandService,
)
from intric.flows.application.flow_draft_materialization import (
    FlowDraftChangeSet,
    FlowDraftMaterializationProgress,
)
from intric.flows.application.flow_draft_materialization import (
    FlowDraftStepChangeKind as StepChangeKind,
)
from intric.flows.flow_authoring_spec import (
    FlowDraftSpecCore,
    InputSource,
    InputType,
)
from intric.flows.flow_resource_bindings import LocalResourceBinding, LocalResourceKind

if TYPE_CHECKING:
    from intric.flows.application.flow_service import FlowService
    from intric.spaces.space_service import SpaceService
    from intric.users.user import UserInDB


def _build_changeset_count_summary(
    changeset: FlowDraftChangeSet,
) -> ChangesetCountSummary:
    return ChangesetCountSummary(
        steps_created=sum(
            1
            for step in changeset.compiled_steps
            if step.change_kind == StepChangeKind.ADDED
        ),
        steps_updated=sum(
            1
            for step in changeset.compiled_steps
            if step.change_kind == StepChangeKind.MODIFIED
        ),
        steps_removed=len(changeset.assistants_to_delete),
        assistants_to_create=len(changeset.assistants_to_create),
        assistants_to_update=len(changeset.assistants_to_update),
        assistants_to_delete=len(changeset.assistants_to_delete),
    )


def _spec_has_assistant_resource_refs(spec: FlowDraftSpecCore) -> bool:
    for step in spec.steps:
        assistant_spec = step.assistant_spec
        if (
            assistant_spec.model_ref is not None
            or assistant_spec.knowledge_refs
            or assistant_spec.mcp_server_refs
            or assistant_spec.mcp_tool_refs
        ):
            return True
    return False


def _available_local_binding_targets(
    catalog: AIBuilderResourceCatalog,
) -> set[tuple[LocalResourceKind, UUID]]:
    targets: set[tuple[LocalResourceKind, UUID]] = set()
    for entry in (
        *catalog.models,
        *catalog.knowledge_bases,
        *catalog.mcp_servers,
        *catalog.mcp_tools,
    ):
        if entry.local_binding is not None:
            targets.add((entry.local_binding.local_kind, entry.local_binding.local_id))
    return targets


def _removed_existing_step_refs_for_apply(
    *,
    session: BuilderSession,
    plan: BuilderPlan,
) -> frozenset[str]:
    if session.target_kind != TargetKind.EDIT:
        return frozenset()
    compiled_edit = _compiled_edit_for_apply(session=session, plan=plan)
    return frozenset(
        operation.target_ref
        for operation in compiled_edit.original_draft.operations
        if operation.op == "remove" and operation.target_ref is not None
    )


def _compiled_edit_for_apply(
    *,
    session: BuilderSession,
    plan: BuilderPlan,
) -> CompiledEditResult:
    compiled_edit = plan.edit_result.compiled_edit if plan.edit_result else None
    if compiled_edit is not None:
        return compiled_edit
    raise AIBuilderBadRequestException(
        "Approved edit plan is missing the compiled edit artifact.",
        code=AIBuilderErrorCode.BAD_REQUEST,
        context={
            "plan_id": str(plan.id),
            "session_id": str(session.id),
            "target_kind": session.target_kind.value,
        },
    )


def _expected_revision_for_apply(
    *,
    session: BuilderSession,
    plan: BuilderPlan,
    requested_expected_revision: int | None,
) -> int | None:
    if session.target_kind != TargetKind.EDIT:
        return None
    compiled_edit = _compiled_edit_for_apply(session=session, plan=plan)
    expected_revision = compiled_edit.base_flow_revision
    if (
        requested_expected_revision is not None
        and requested_expected_revision != expected_revision
    ):
        raise AIBuilderBadRequestException(
            "Expected revision does not match the approved edit proposal.",
            code=AIBuilderErrorCode.STALE_REVISION,
            context={
                "plan_id": str(plan.id),
                "session_id": str(session.id),
                "requested_expected_revision": requested_expected_revision,
                "proposal_base_revision": expected_revision,
            },
        )
    return expected_revision


class AIBuilderPlanLifecycle:
    def __init__(
        self,
        *,
        user: "UserInDB",
        repo: AIBuilderRepository,
        flow_service: "FlowService",
        space_service: "SpaceService",
        authoring_service: FlowAuthoringCommandService | None = None,
    ) -> None:
        self.user = user
        self.repo = repo
        self.flow_service = flow_service
        self.space_service = space_service
        self.authoring_service = authoring_service or FlowAuthoringCommandService()

    async def approve_plan(self, *, plan_id: UUID) -> BuilderPlan:
        plan = await self._get_plan(plan_id)
        self._require_plan_status(
            plan=plan,
            expected_status=PlanStatus.PROPOSED,
            action="approve",
        )
        await self._require_session_creator(plan.session_id)
        await self.repo.update_plan_status(
            plan_id=plan.id,
            tenant_id=self.user.tenant_id,
            status=PlanStatus.APPROVED,
        )
        return await self._get_plan(plan.id)

    async def revise_plan(
        self,
        *,
        plan_id: UUID,
        revision_type: str,
    ) -> BuilderPlan:
        if revision_type != "keep_current_description":
            raise AIBuilderBadRequestException(
                f"Unsupported revision type: {revision_type}",
                code=AIBuilderErrorCode.UNSUPPORTED_REVISION_TYPE,
            )

        plan = await self._get_plan(plan_id)
        if plan.status != PlanStatus.PROPOSED:
            raise AIBuilderBadRequestException(
                "Can only revise proposed plans.",
                code=AIBuilderErrorCode.PLAN_NOT_PROPOSED,
            )

        session = await self._require_session_creator(plan.session_id)
        if session.status != SessionStatus.AWAITING_APPROVAL:
            raise AIBuilderBadRequestException(
                "Can only revise plans when the session is awaiting approval.",
                code=AIBuilderErrorCode.INVALID_SESSION_TRANSITION,
            )

        revised_edit_result = (plan.edit_result or BuilderPlanEditResult()).model_copy(
            update={"description_override_manual": True}
        )
        revised_content = plan.proposal.content.model_copy(
            update={"edit_result": revised_edit_result}
        )
        revised_proposal = plan.proposal.model_copy(
            update={
                "content": revised_content,
                "reasoning": None,
            }
        )

        async with self.repo.savepoint():
            await self.repo.supersede_existing_plans(
                session_id=plan.session_id,
                tenant_id=self.user.tenant_id,
            )
            new_plan = await self.repo.create_plan(
                session_id=plan.session_id,
                tenant_id=self.user.tenant_id,
                proposal=revised_proposal,
            )
            await self.repo.update_session_latest_plan_without_send_lease(
                session_id=plan.session_id,
                tenant_id=self.user.tenant_id,
                plan_id=new_plan.id,
            )

        return new_plan

    async def apply_plan(
        self,
        *,
        plan_id: UUID,
        expected_revision: int | None = None,
    ) -> ApplyResultResponse:
        plan = await self._get_plan(plan_id)
        self._require_plan_status(
            plan=plan,
            expected_status=PlanStatus.APPROVED,
            action="apply",
        )

        session = await self._require_session_creator(plan.session_id)
        canonical_expected_revision = _expected_revision_for_apply(
            session=session,
            plan=plan,
            requested_expected_revision=expected_revision,
        )
        default_transcription_model_id = (
            await self._resolve_default_transcription_model_id(session.space_id)
        )
        self._require_create_audio_transcription_model(
            session=session,
            plan=plan,
            default_transcription_model_id=default_transcription_model_id,
        )
        spec, _ = normalize_ai_builder_spec(plan.spec)
        removed_existing_step_refs = _removed_existing_step_refs_for_apply(
            session=session,
            plan=plan,
        )
        resource_bindings = await self._plan_resource_bindings_for_apply(
            session=session,
            plan=plan,
            spec=spec,
        )
        command = self._build_authoring_command(
            session=session,
            plan=plan,
            spec=spec,
            expected_revision=canonical_expected_revision,
            removed_existing_step_refs=removed_existing_step_refs,
            resource_bindings=resource_bindings,
            default_transcription_model_id=default_transcription_model_id,
        )

        await self.repo.update_session_status_without_send_lease(
            session_id=session.id,
            tenant_id=self.user.tenant_id,
            status=SessionStatus.APPLYING,
        )
        if command.origin.kind != "ai_builder":
            raise RuntimeError("AI Builder apply constructed a non-AI Builder command.")
        origin_policy = AIBuilderAuthoringPolicy(command.origin)
        try:
            prepared = await self.authoring_service.prepare(
                command=command,
                flow_service=self.flow_service,
                origin_policy=origin_policy,
            )
        except Exception as exc:
            log_apply_failed(
                phase="prepare_authoring",
                plan_id=plan.id,
                session_id=session.id,
                target_kind=session.target_kind,
                flow_id=session.flow_id,
                exception=exc,
                changeset_counts=None,
                materializer_progress=None,
            )
            raise

        materializer_progress: MaterializerProgressSnapshot | None = None

        def record_materializer_progress(
            progress: FlowDraftMaterializationProgress,
        ) -> None:
            nonlocal materializer_progress
            materializer_progress = MaterializerProgressSnapshot(
                stage=progress.stage.value,
                assistants_created=progress.assistants_created,
                assistants_configured=progress.assistants_configured,
                assistants_updated=progress.assistants_updated,
                assistants_deleted=progress.assistants_deleted,
                flow_created=progress.flow_created,
                flow_updated=progress.flow_updated,
            )

        try:
            authoring_result = await self.authoring_service.apply_prepared(
                prepared=prepared,
                flow_service=self.flow_service,
                progress_callback=record_materializer_progress,
            )
        except Exception as exc:
            log_apply_failed(
                phase="apply_authoring",
                plan_id=plan.id,
                session_id=session.id,
                target_kind=session.target_kind,
                flow_id=session.flow_id,
                exception=exc,
                changeset_counts=_build_changeset_count_summary(prepared.changeset),
                materializer_progress=materializer_progress,
            )
            raise

        await self.repo.update_plan_status(
            plan_id=plan.id,
            tenant_id=self.user.tenant_id,
            status=PlanStatus.APPLIED,
        )
        await self.repo.update_session_status_without_send_lease(
            session_id=session.id,
            tenant_id=self.user.tenant_id,
            status=SessionStatus.APPLIED,
        )

        if session.target_kind == TargetKind.CREATE:
            await self.repo.update_session_flow_id(
                session_id=session.id,
                tenant_id=self.user.tenant_id,
                flow_id=authoring_result.flow_id,
            )

        return ApplyResultResponse(
            flow_id=authoring_result.flow_id,
            flow_name=authoring_result.flow_name,
            steps_created=authoring_result.steps_created,
            steps_updated=authoring_result.steps_updated,
            steps_removed=authoring_result.steps_removed,
        )

    def _build_authoring_command(
        self,
        *,
        session: BuilderSession,
        plan: BuilderPlan,
        spec: FlowDraftSpecCore,
        expected_revision: int | None,
        removed_existing_step_refs: frozenset[str],
        resource_bindings: tuple[LocalResourceBinding, ...],
        default_transcription_model_id: UUID | None,
    ) -> FlowAuthoringCommand:
        origin = AIBuilderFlowAuthoringOrigin(
            session_id=session.id,
            plan_id=plan.id,
            spec_hash=plan.spec_hash,
            applied_at=datetime.now(timezone.utc),
            description_override_manual=(
                plan.edit_result.description_override_manual
                if plan.edit_result is not None
                else False
            ),
        )
        if session.target_kind == TargetKind.CREATE:
            return CreateFlowAuthoringCommand(
                space_id=session.space_id,
                spec=spec,
                origin=origin,
                resource_bindings=resource_bindings,
                default_transcription_model_id=default_transcription_model_id,
            )
        if session.flow_id is None:
            raise AIBuilderBadRequestException(
                "Edit session has no flow_id.",
                code=AIBuilderErrorCode.EDIT_SESSION_FLOW_REQUIRED,
            )
        if expected_revision is None:
            raise AIBuilderBadRequestException(
                "Edit plans require an approved base Flow revision.",
                code=AIBuilderErrorCode.STALE_REVISION,
                context={"plan_id": str(plan.id), "session_id": str(session.id)},
            )
        return EditFlowAuthoringCommand(
            space_id=session.space_id,
            flow_id=session.flow_id,
            expected_revision=expected_revision,
            spec=spec,
            removed_existing_step_refs=removed_existing_step_refs,
            origin=origin,
            resource_bindings=resource_bindings,
            default_transcription_model_id=default_transcription_model_id,
        )

    async def _resolve_default_transcription_model_id(
        self,
        space_id: UUID,
    ) -> UUID | None:
        space = await self.space_service.get_space(space_id)
        model = space.get_default_transcription_model()
        return None if model is None else model.id

    async def _plan_resource_bindings_for_apply(
        self,
        *,
        session: BuilderSession,
        plan: BuilderPlan,
        spec: FlowDraftSpecCore,
    ) -> tuple[LocalResourceBinding, ...]:
        if not _spec_has_assistant_resource_refs(spec):
            return tuple()

        if not plan.resource_bindings:
            raise AIBuilderBadRequestException(
                "The plan is missing resource bindings. Generate a new proposal and try again.",
                code=AIBuilderErrorCode.AI_BUILDER_PLAN_RESOURCE_BINDINGS_MISSING,
                context={
                    "plan_id": str(plan.id),
                    "session_id": str(session.id),
                },
            )

        space = await self.space_service.get_space(session.space_id)
        catalog = build_ai_builder_resource_catalog(
            available_models=serialize_space_models(space),
            available_kbs=serialize_space_kbs(space),
            available_mcps=serialize_space_mcps(space),
        )
        available_targets = _available_local_binding_targets(catalog)
        for binding in plan.resource_bindings:
            if (binding.local_kind, binding.local_id) in available_targets:
                continue
            raise AIBuilderBadRequestException(
                "A resource used by the plan is no longer available in this space. "
                "Generate a new proposal and choose available resources.",
                code=AIBuilderErrorCode.AI_BUILDER_PLAN_RESOURCE_BINDING_UNAVAILABLE,
                context={
                    "plan_id": str(plan.id),
                    "session_id": str(session.id),
                    "slot_ref": binding.slot_ref.ref,
                    "slot_kind": binding.slot_ref.kind.value,
                    "local_kind": binding.local_kind.value,
                },
            )
        return plan.resource_bindings

    async def _get_plan(self, plan_id: UUID) -> BuilderPlan:
        return await self.repo.get_plan(
            plan_id=plan_id,
            tenant_id=self.user.tenant_id,
        )

    async def _require_session_creator(self, session_id: UUID) -> BuilderSession:
        session = await self.repo.get_session(
            session_id=session_id,
            tenant_id=self.user.tenant_id,
        )
        if session.actor_user_id != self.user.id:
            raise AIBuilderUnauthorizedException(
                "Only the session creator can manage plans.",
                code=AIBuilderErrorCode.SESSION_CREATOR_REQUIRED,
                context={"auth_layer": "session_creator"},
            )
        return session

    @staticmethod
    def _require_plan_status(
        *,
        plan: BuilderPlan,
        expected_status: PlanStatus,
        action: str,
    ) -> None:
        if plan.status == expected_status:
            return
        raise AIBuilderBadRequestException(
            f"Cannot {action} plan in status '{plan.status.value}'. "
            f"Plan must be {expected_status.value} first.",
            code=AIBuilderErrorCode.INVALID_PLAN_STATUS,
        )

    @staticmethod
    def _require_create_audio_transcription_model(
        *,
        session: BuilderSession,
        plan: BuilderPlan,
        default_transcription_model_id: UUID | None,
    ) -> None:
        if session.target_kind != TargetKind.CREATE:
            return
        if default_transcription_model_id is not None:
            return
        if not any(
            step.input_source == InputSource.FLOW_INPUT
            and step.input_type == InputType.AUDIO
            for step in plan.spec.steps
        ):
            return
        raise AIBuilderBadRequestException(
            "A transcription model must be selected when using audio input steps.",
            code=AIBuilderErrorCode.TRANSCRIPTION_MODEL_REQUIRED,
        )
