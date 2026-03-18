from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from intric.flows.ai_builder.ai_builder_materializer import (
    compile_changeset,
    execute_changeset,
)
from intric.flows.ai_builder.ai_builder_models import (
    ApplyResultResponse,
    BuilderPlan,
    BuilderSession,
    FlowDraftSpecCore,
    InputSource,
    InputType,
    PlanStatus,
    SessionStatus,
    TargetKind,
)
from intric.flows.ai_builder.ai_builder_repo import AIBuilderRepository
from intric.flows.ai_builder.ai_builder_session_spec_validator import (
    normalize_compiled_spec_for_session,
    validate_compiled_spec_for_session,
)
from intric.main.exceptions import BadRequestException, UnauthorizedException
from intric.main.logging import get_logger

if TYPE_CHECKING:
    from intric.flows.flow import Flow
    from intric.flows.flow_service import FlowService
    from intric.spaces.space_service import SpaceService
    from intric.users.user import UserInDB

logger = get_logger(__name__)


class AIBuilderPlanLifecycle:
    def __init__(
        self,
        *,
        user: "UserInDB",
        repo: AIBuilderRepository,
        flow_service: "FlowService",
        space_service: "SpaceService | None" = None,
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
        default_transcription_model_id = await self._resolve_default_transcription_model_id(
            session.space_id
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
        self._require_valid_compiled_spec_for_session(
            session=session,
            spec=spec,
            current_flow=current_flow,
        )

        await self.repo.update_session_status(
            session_id=session.id,
            tenant_id=self.user.tenant_id,
            status=SessionStatus.APPLYING,
        )

        try:
            changeset = compile_changeset(
                spec,
                current_flow,
                default_transcription_model_id=default_transcription_model_id,
            )
            result = await execute_changeset(
                changeset=changeset,
                flow_service=self.flow_service,
                space_id=session.space_id,
                flow_id=session.flow_id,
                expected_revision=expected_revision,
            )
        except Exception:
            await self._rollback_session_status(session.id)
            # For create mode, attempt to clean up the temp flow created by
            # execute_changeset. This prevents orphaned empty flows on failure.
            if session.target_kind == TargetKind.CREATE and session.flow_id is None:
                await self._cleanup_orphaned_create_artifacts(session.space_id)
            raise

        await self.repo.update_plan_status(
            plan_id=plan.id,
            tenant_id=self.user.tenant_id,
            status=PlanStatus.APPLIED,
        )
        await self.repo.update_session_status(
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
        if self.space_service is None:
            return None

        space = await self.space_service.get_space(space_id)
        model = space.get_default_transcription_model()
        return None if model is None else model.id

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
            raise UnauthorizedException(
                "Only the session creator can manage plans.",
                code="session_creator_required",
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
            raise BadRequestException("Edit session has no flow_id.")

        current_flow = await self.flow_service.get_flow(session.flow_id)
        if current_flow.space_id != session.space_id:
            raise BadRequestException(
                "Flow space does not match the AI builder session space.",
                code="flow_space_mismatch",
            )
        if (
            expected_revision is not None
            and current_flow.draft_revision != expected_revision
        ):
            raise BadRequestException(
                "Flödet ändrades av en annan användare. "
                "Dina ändringar beräknas mot den nya versionen.",
                code="stale_revision",
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
        raise BadRequestException(
            first_error.message,
            code="invalid_existing_step_ref",
            context={
                "step_ref": first_error.step_ref,
                "valid_refs": valid_existing_step_refs,
                "target_kind": session.target_kind.value,
            },
        )

    async def _rollback_session_status(self, session_id: UUID) -> None:
        try:
            await self.repo.update_session_status(
                session_id=session_id,
                tenant_id=self.user.tenant_id,
                status=SessionStatus.AWAITING_APPROVAL,
            )
        except Exception as error:
            logger.warning(
                "Failed to rollback AI builder session status",
                exc_info=error,
            )

    async def _cleanup_orphaned_create_artifacts(self, space_id: UUID) -> None:
        """Best-effort cleanup of orphaned temp flows from failed create-mode apply.

        The temp flow is created with empty steps by execute_changeset.
        If the apply fails mid-way, this flow remains as an orphan.
        """
        try:
            flows = await self.flow_service.list_flows(space_id=space_id, sparse=False)
            for flow in flows:
                if len(flow.steps) == 0:
                    # Empty flow likely created by a failed apply — but only
                    # delete if it was just created (within last 60 seconds)
                    if flow.created_at is not None:
                        from datetime import datetime, timezone
                        age = (datetime.now(timezone.utc) - flow.created_at).total_seconds()
                        if age < 60:
                            logger.info(
                                "Cleaning up orphaned temp flow %s from failed create apply",
                                flow.id,
                            )
                            await self.flow_service.delete_flow(flow.id)
        except Exception as cleanup_error:
            logger.warning(
                "Failed to clean up orphaned create artifacts",
                exc_info=cleanup_error,
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
        raise BadRequestException(
            f"Cannot {action} plan in status '{plan.status.value}'. "
            f"Plan must be {expected_status.value} first."
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
            step.input_source == InputSource.FLOW_INPUT and step.input_type == InputType.AUDIO
            for step in plan.spec.steps
        ):
            return
        raise BadRequestException(
            "A transcription model must be selected when using audio input steps.",
            code="transcription_model_required",
        )
