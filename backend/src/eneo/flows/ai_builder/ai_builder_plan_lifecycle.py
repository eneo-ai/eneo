from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, NamedTuple
from uuid import UUID

from eneo.flows.ai_builder.ai_builder_api_models import (
    ApplyResultResponse,
)
from eneo.flows.ai_builder.ai_builder_authoring_policy import AIBuilderAuthoringPolicy
from eneo.flows.ai_builder.ai_builder_context import (
    serialize_space_kbs,
    serialize_space_mcps,
    serialize_space_models,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    BuilderPlan,
    BuilderSession,
    BuilderTurnState,
    FlowBuilderEditApproval,
    PlanStatus,
    SessionStatus,
    TargetKind,
)
from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderBadRequestException,
    AIBuilderErrorCode,
    AIBuilderUnauthorizedException,
)
from eneo.flows.ai_builder.ai_builder_proposal_telemetry import (
    ChangesetCountSummary,
    MaterializerProgressSnapshot,
    log_apply_failed,
)
from eneo.flows.ai_builder.ai_builder_repo import AIBuilderRepository
from eneo.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderResourceCatalog,
    build_ai_builder_resource_catalog,
)
from eneo.flows.application.flow_authoring_command import (
    AIBuilderFlowAuthoringOrigin,
    CreateFlowAuthoringCommand,
    EditFlowAuthoringCommand,
    FlowAuthoringCommand,
    FlowAuthoringCommandService,
)
from eneo.flows.application.flow_draft_materialization import (
    FlowDraftMaterializationProgress,
)
from eneo.flows.flow_authoring_spec import (
    FlowDraftSpecCore,
    InputSource,
    InputType,
)
from eneo.flows.flow_resource_bindings import LocalResourceBinding, LocalResourceKind

if TYPE_CHECKING:
    from eneo.flows.application.flow_service import FlowService
    from eneo.spaces.space_service import SpaceService
    from eneo.users.user import UserInDB


class CreateFromPlanOutcome(NamedTuple):
    """Result of the atomic approve-and-create command.

    ``replayed`` is True when the plan was already applied and the original
    outcome was returned without side effects — callers must not emit another
    creation audit event for a replay.
    """

    result: ApplyResultResponse
    replayed: bool


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
    return _edit_approval_for_apply(
        session=session,
        plan=plan,
    ).removed_existing_step_refs


def _edit_approval_for_apply(
    *,
    session: BuilderSession,
    plan: BuilderPlan,
) -> FlowBuilderEditApproval:
    edit = plan.proposal.content.edit
    if edit is not None:
        return edit
    raise AIBuilderBadRequestException(
        "Approved edit plan is missing edit approval metadata.",
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
    edit = _edit_approval_for_apply(session=session, plan=plan)
    expected_revision = edit.base_flow_revision
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

    async def _lock_session_then_plan(
        self, plan_id: UUID
    ) -> tuple[BuilderPlan, BuilderSession]:
        """Lock the session row, then the plan row, and return fresh reads.

        Every plan lifecycle transition goes through this so transitions
        serialize against each other AND against message-turn preflight
        (which locks the session row). The initial unlocked plan read only
        resolves the session id; the locked plan re-read is authoritative.
        """
        plan_probe = await self._get_plan(plan_id)
        session = await self.repo.get_session_for_update(
            session_id=plan_probe.session_id,
            tenant_id=self.user.tenant_id,
        )
        self._require_creator(session)
        plan = await self.repo.get_plan_for_update(
            plan_id=plan_id,
            tenant_id=self.user.tenant_id,
        )
        return plan, session

    @staticmethod
    def _require_actionable_session(
        *, session: BuilderSession, plan: BuilderPlan
    ) -> None:
        """Post-lock invariants shared by every non-replay plan transition.

        Locking only makes a competing command WAIT; these checks make it
        reject the authoritative state it observes after waiting. Without
        them a legacy approve/apply could act on a superseded plan or run
        while a refinement turn is streaming.
        """
        if session.status != SessionStatus.AWAITING_APPROVAL:
            raise AIBuilderBadRequestException(
                "The session is not awaiting approval.",
                code=AIBuilderErrorCode.INVALID_SESSION_TRANSITION,
            )
        if session.latest_plan_id != plan.id:
            raise AIBuilderBadRequestException(
                "The plan is no longer the session's latest proposal.",
                code=AIBuilderErrorCode.PLAN_SESSION_MISMATCH,
            )
        latest_turn = session.latest_turn
        if latest_turn is not None and latest_turn.state in (
            BuilderTurnState.OPEN,
            BuilderTurnState.PROCESSING,
        ):
            raise AIBuilderBadRequestException(
                "Another AI Builder message is already being processed.",
                code=AIBuilderErrorCode.SESSION_MESSAGE_IN_PROGRESS,
            )

    async def approve_plan(self, *, plan_id: UUID) -> BuilderPlan:
        plan, session = await self._lock_session_then_plan(plan_id)
        self._require_actionable_session(session=session, plan=plan)
        self._require_plan_status(
            plan=plan,
            expected_status=PlanStatus.PROPOSED,
            action="approve",
        )
        transitioned = await self.repo.update_plan_status_if(
            plan_id=plan.id,
            tenant_id=self.user.tenant_id,
            expected_status=PlanStatus.PROPOSED,
            status=PlanStatus.APPROVED,
        )
        if not transitioned:
            raise AIBuilderBadRequestException(
                "Plan status changed before approval could be recorded.",
                code=AIBuilderErrorCode.INVALID_PLAN_STATUS,
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

        plan, session = await self._lock_session_then_plan(plan_id)
        if plan.status != PlanStatus.PROPOSED:
            raise AIBuilderBadRequestException(
                "Can only revise proposed plans.",
                code=AIBuilderErrorCode.PLAN_NOT_PROPOSED,
            )
        self._require_actionable_session(session=session, plan=plan)

        revised_content = plan.proposal.content.model_copy(
            update={"description_override_manual": True}
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

    async def approve_and_apply_create_plan(
        self, *, plan_id: UUID
    ) -> CreateFromPlanOutcome:
        """Approve and materialize a create-mode plan as one user action.

        The whole call runs inside the request transaction, so the approval
        transition and the flow materialization commit or roll back together —
        on failure nothing is persisted and the client may truthfully say so.
        The plan row is read under a FOR UPDATE lock, which serializes
        concurrent create requests for the same plan: the loser waits, then
        observes APPLIED and takes the replay branch instead of materializing
        a duplicate flow. Replaying an already-applied plan returns the
        original outcome (``replayed=True`` so the caller can skip duplicate
        audit events). Edit sessions keep the explicit two-step approve/apply
        lifecycle and are rejected here.
        """
        plan, session = await self._lock_session_then_plan(plan_id)
        if session.target_kind != TargetKind.CREATE:
            raise AIBuilderBadRequestException(
                "Approve-and-create is only available for create sessions. "
                "Edit plans require explicit approve and apply.",
                code=AIBuilderErrorCode.INVALID_SESSION_TRANSITION,
            )
        if plan.status == PlanStatus.APPLIED:
            replayed = await self._replay_applied_create_result(
                session=session, plan=plan
            )
            return CreateFromPlanOutcome(result=replayed, replayed=True)
        self._require_actionable_session(session=session, plan=plan)
        if plan.status == PlanStatus.PROPOSED:
            transitioned = await self.repo.update_plan_status_if(
                plan_id=plan.id,
                tenant_id=self.user.tenant_id,
                expected_status=PlanStatus.PROPOSED,
                status=PlanStatus.APPROVED,
            )
            if not transitioned:
                raise AIBuilderBadRequestException(
                    "Plan status changed before approval could be recorded.",
                    code=AIBuilderErrorCode.INVALID_PLAN_STATUS,
                )
            plan = await self._get_plan(plan.id)
        self._require_plan_status(
            plan=plan,
            expected_status=PlanStatus.APPROVED,
            action="apply",
        )
        result = await self._apply_approved_plan(
            plan=plan,
            session=session,
            expected_revision=None,
        )
        return CreateFromPlanOutcome(result=result, replayed=False)

    async def _replay_applied_create_result(
        self,
        *,
        session: BuilderSession,
        plan: BuilderPlan,
    ) -> ApplyResultResponse:
        flow_id = session.flow_id
        if flow_id is None:
            raise AIBuilderBadRequestException(
                "Plan is applied but its session has no flow.",
                code=AIBuilderErrorCode.INVALID_PLAN_STATUS,
            )
        flow = await self.flow_service.get_flow(flow_id)
        return ApplyResultResponse(
            flow_id=flow_id,
            flow_name=flow.name,
            steps_created=len(plan.spec.steps),
            steps_updated=0,
            steps_removed=0,
        )

    async def apply_plan(
        self,
        *,
        plan_id: UUID,
        expected_revision: int | None = None,
    ) -> ApplyResultResponse:
        plan, session = await self._lock_session_then_plan(plan_id)
        self._require_actionable_session(session=session, plan=plan)
        self._require_plan_status(
            plan=plan,
            expected_status=PlanStatus.APPROVED,
            action="apply",
        )
        return await self._apply_approved_plan(
            plan=plan,
            session=session,
            expected_revision=expected_revision,
        )

    async def _apply_approved_plan(
        self,
        *,
        plan: BuilderPlan,
        session: BuilderSession,
        expected_revision: int | None,
    ) -> ApplyResultResponse:
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
        spec = plan.spec
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
                changeset_counts=ChangesetCountSummary.from_preview(prepared.preview),
                materializer_progress=materializer_progress,
            )
            raise

        flow_id_for_create = (
            authoring_result.flow_id
            if session.target_kind == TargetKind.CREATE
            else None
        )
        await self.repo.mark_plan_applied(
            plan_id=plan.id,
            session_id=session.id,
            tenant_id=self.user.tenant_id,
            flow_id=flow_id_for_create,
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
            description_override_manual=plan.proposal.content.description_override_manual,
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
        self._require_creator(session)
        return session

    def _require_creator(self, session: BuilderSession) -> None:
        if session.actor_user_id != self.user.id:
            raise AIBuilderUnauthorizedException(
                "Only the session creator can manage plans.",
                code=AIBuilderErrorCode.SESSION_CREATOR_REQUIRED,
                context={"auth_layer": "session_creator"},
            )

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
