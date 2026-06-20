from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import UUID

from intric.flows.ai_builder.ai_builder_api_models import (
    ApplyResultResponse,
)
from intric.flows.ai_builder.ai_builder_context import (
    serialize_space_kbs,
    serialize_space_mcps,
    serialize_space_models,
)
from intric.flows.ai_builder.ai_builder_domain_models import (
    BuilderPlan,
    BuilderSession,
    FlowChangeSet,
    PlanStatus,
    SessionStatus,
    TargetKind,
)
from intric.flows.ai_builder.ai_builder_edit_models import (
    BuilderPlanEditResult,
)
from intric.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderBadRequestException,
    AIBuilderErrorCode,
    AIBuilderUnauthorizedException,
)
from intric.flows.ai_builder.ai_builder_materializer import (
    compile_changeset,
    execute_changeset,
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
from intric.flows.ai_builder.ai_builder_session_spec_validator import (
    normalize_compiled_spec_for_session,
    validate_compiled_spec_for_session,
)
from intric.flows.ai_builder.ai_builder_step_transition_policy import (
    normalize_ai_builder_spec,
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
    from intric.flows.domain.flow import Flow
    from intric.spaces.space_service import SpaceService
    from intric.users.user import UserInDB


def _build_changeset_count_summary(changeset: FlowChangeSet) -> ChangesetCountSummary:
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


class AIBuilderPlanLifecycle:
    def __init__(
        self,
        *,
        user: "UserInDB",
        repo: AIBuilderRepository,
        flow_service: "FlowService",
        space_service: "SpaceService",
    ) -> None:
        self.user = user
        self.repo = repo
        self.flow_service = flow_service
        self.space_service = space_service

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
        envelope = plan.envelope.model_copy(update={"reasoning": None})

        async with self.repo.savepoint():
            await self.repo.supersede_existing_plans(
                session_id=plan.session_id,
                tenant_id=self.user.tenant_id,
            )
            new_plan = await self.repo.create_plan(
                session_id=plan.session_id,
                tenant_id=self.user.tenant_id,
                spec=plan.spec,
                envelope=envelope,
                resource_bindings=plan.resource_bindings,
                edit_result=revised_edit_result,
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
        current_flow = await self._resolve_edit_flow(
            session=session,
            expected_revision=expected_revision,
        )
        default_transcription_model_id = (
            await self._resolve_default_transcription_model_id(session.space_id)
        )
        self._require_create_audio_transcription_model(
            session=session,
            plan=plan,
            default_transcription_model_id=default_transcription_model_id,
        )
        spec = normalize_compiled_spec_for_session(
            plan.spec,
            target_kind=session.target_kind,
        )
        spec, _ = normalize_ai_builder_spec(spec)
        resource_bindings = await self._plan_resource_bindings_for_apply(
            session=session,
            plan=plan,
            spec=spec,
        )
        self._require_valid_compiled_spec_for_session(
            session=session,
            spec=spec,
            current_flow=current_flow,
        )

        # Published flows cannot be mutated — require explicit unpublish first
        if current_flow is not None and current_flow.published_version is not None:
            raise AIBuilderBadRequestException(
                "Flow is currently published. Unpublish the flow before applying changes.",
                code=AIBuilderErrorCode.FLOW_IS_PUBLISHED,
                context={
                    "flow_id": str(current_flow.id),
                    "published_version": current_flow.published_version,
                },
            )

        await self.repo.update_session_status_without_send_lease(
            session_id=session.id,
            tenant_id=self.user.tenant_id,
            status=SessionStatus.APPLYING,
        )
        description_override_manual = (
            plan.edit_result.description_override_manual
            if plan.edit_result is not None
            else False
        )
        try:
            changeset = compile_changeset(
                spec,
                current_flow,
                default_transcription_model_id=default_transcription_model_id,
                description_override_manual=description_override_manual,
                ai_builder_origin={
                    "builder_session_id": str(session.id),
                    "builder_plan_id": str(plan.id),
                    "builder_spec_hash": plan.spec_hash,
                    "applied_at": datetime.now(timezone.utc).isoformat(),
                },
            )
        except Exception as exc:
            log_apply_failed(
                phase="compile_changeset",
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
            progress: MaterializerProgressSnapshot,
        ) -> None:
            nonlocal materializer_progress
            materializer_progress = progress

        try:
            result = await execute_changeset(
                changeset=changeset,
                flow_service=self.flow_service,
                space_id=session.space_id,
                flow_id=session.flow_id,
                expected_revision=expected_revision,
                resource_bindings=resource_bindings,
                progress_callback=record_materializer_progress,
            )
        except Exception as exc:
            log_apply_failed(
                phase="execute_changeset",
                plan_id=plan.id,
                session_id=session.id,
                target_kind=session.target_kind,
                flow_id=session.flow_id,
                exception=exc,
                changeset_counts=_build_changeset_count_summary(changeset),
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
                flow_id=result.flow_id,
            )

        return result

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

    async def _resolve_edit_flow(
        self,
        *,
        session: BuilderSession,
        expected_revision: int | None,
    ) -> "Flow | None":
        if session.target_kind != TargetKind.EDIT:
            return None
        if session.flow_id is None:
            raise AIBuilderBadRequestException(
                "Edit session has no flow_id.",
                code=AIBuilderErrorCode.EDIT_SESSION_FLOW_REQUIRED,
            )

        current_flow = await self.flow_service.get_flow(session.flow_id)
        if current_flow.space_id != session.space_id:
            raise AIBuilderBadRequestException(
                "Flow space does not match the AI builder session space.",
                code=AIBuilderErrorCode.FLOW_SPACE_MISMATCH,
            )
        if (
            expected_revision is not None
            and current_flow.draft_revision != expected_revision
        ):
            raise AIBuilderBadRequestException(
                "Flödet ändrades av en annan användare. "
                "Dina ändringar beräknas mot den nya versionen.",
                code=AIBuilderErrorCode.STALE_REVISION,
            )
        return current_flow

    def _require_valid_compiled_spec_for_session(
        self,
        *,
        session: BuilderSession,
        spec: FlowDraftSpecCore,
        current_flow: "Flow | None",
    ) -> None:
        valid_existing_step_refs = (
            [f"existing_step_{step.step_order}" for step in current_flow.steps]
            if current_flow is not None
            else None
        )
        validation = validate_compiled_spec_for_session(
            spec,
            target_kind=session.target_kind,
            valid_existing_step_refs=valid_existing_step_refs,
        )
        if not validation.errors:
            return

        first_error = validation.errors[0]
        raise AIBuilderBadRequestException(
            first_error.message,
            code=AIBuilderErrorCode.INVALID_EXISTING_STEP_REF,
            context={
                "step_ref": first_error.step_ref,
                "valid_refs": valid_existing_step_refs,
                "target_kind": session.target_kind.value,
            },
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
