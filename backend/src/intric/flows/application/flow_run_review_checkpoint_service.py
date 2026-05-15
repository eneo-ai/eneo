from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from intric.flows.application.flow_run_access_policy import FlowRunAccessPolicy
from intric.flows.application.flow_run_terminalization import FlowRunTerminalizer
from intric.flows.domain.flow import (
    FlowRunReviewCheckpoint,
    FlowRunStatus,
    JsonObject,
)
from intric.flows.enums import FlowRunLifecycleSource
from intric.flows.flow_run_error import FlowRunError
from intric.flows.infrastructure.flow_run_repo import (
    FlowRunRepository,
    FlowRunReviewCheckpointResumeResult,
)
from intric.flows.output_processing import validate_against_contract
from intric.flows.principal import FlowPrincipal
from intric.main.exceptions import BadRequestException, TypedIOValidationException
from intric.users.user import UserInDB

_REVIEW_REJECT_REASON_MAX_LENGTH = 1024
_REVIEW_RESUME_IDEMPOTENCY_KEY_MAX_LENGTH = 255


class FlowRunReviewCheckpointService:
    def __init__(
        self,
        *,
        user: UserInDB,
        flow_run_repo: FlowRunRepository,
        access_policy: FlowRunAccessPolicy,
        flow_run_terminalizer: FlowRunTerminalizer,
    ):
        self.user = user
        self.flow_run_repo = flow_run_repo
        self.access_policy = access_policy
        self.flow_run_terminalizer = flow_run_terminalizer

    def _principal(self) -> FlowPrincipal:
        return FlowPrincipal.from_user(self.user)

    async def get_active_review_checkpoint(
        self,
        *,
        flow_id: UUID,
        run_id: UUID,
    ) -> FlowRunReviewCheckpoint | None:
        run = await self.access_policy.load_run(
            run_id=run_id,
            flow_id=flow_id,
            access_kind="content",
        )
        return await self.flow_run_repo.get_active_review_checkpoint(
            run_id=run.id,
            tenant_id=self.user.tenant_id,
        )

    async def edit_review_checkpoint(
        self,
        *,
        flow_id: UUID,
        run_id: UUID,
        checkpoint_id: UUID,
        expected_checkpoint_revision: int,
        current_payload_json: JsonObject,
    ) -> FlowRunReviewCheckpoint:
        principal = self._principal()
        run = await self.access_policy.load_run(
            run_id=run_id,
            flow_id=flow_id,
            access_kind="content",
        )
        checkpoint = await self.flow_run_repo.get_review_checkpoint_for_edit(
            checkpoint_id=checkpoint_id,
            tenant_id=self.user.tenant_id,
            flow_id=flow_id,
            flow_run_id=run.id,
            expected_revision=expected_checkpoint_revision,
        )
        self._validate_review_checkpoint_edit_payload(
            checkpoint=checkpoint,
            current_payload_json=current_payload_json,
        )
        return await self.flow_run_repo.edit_review_checkpoint_payload(
            checkpoint_id=checkpoint_id,
            tenant_id=self.user.tenant_id,
            flow_id=flow_id,
            flow_run_id=run.id,
            expected_revision=expected_checkpoint_revision,
            current_payload_json=current_payload_json,
            principal=principal,
        )

    @staticmethod
    def _validate_review_checkpoint_edit_payload(
        *,
        checkpoint: FlowRunReviewCheckpoint,
        current_payload_json: JsonObject,
    ) -> None:
        if checkpoint.output_contract_json is None:
            return
        context: dict[str, object] = {
            "checkpoint_id": str(checkpoint.id),
            "step_id": str(checkpoint.step_id),
            "step_order": checkpoint.step_order,
            "payload_field": "structured",
        }
        if "structured" not in current_payload_json:
            raise TypedIOValidationException(
                f"Review checkpoint step {checkpoint.step_order} output: "
                "field `structured` is required for contract validation.",
                code="typed_io_contract_violation",
                context=context,
            )
        try:
            validate_against_contract(
                current_payload_json["structured"],
                checkpoint.output_contract_json,
                label=f"Review checkpoint step {checkpoint.step_order} output",
            )
        except TypedIOValidationException as exc:
            exc.context = context
            raise

    async def approve_review_checkpoint(
        self,
        *,
        flow_id: UUID,
        run_id: UUID,
        checkpoint_id: UUID,
        expected_checkpoint_revision: int,
    ) -> FlowRunReviewCheckpoint:
        principal = self._principal()
        run = await self.access_policy.load_run(
            run_id=run_id,
            flow_id=flow_id,
            access_kind="content",
        )
        return await self.flow_run_repo.approve_review_checkpoint(
            checkpoint_id=checkpoint_id,
            tenant_id=self.user.tenant_id,
            flow_id=flow_id,
            flow_run_id=run.id,
            expected_revision=expected_checkpoint_revision,
            principal=principal,
        )

    async def reject_review_checkpoint(
        self,
        *,
        flow_id: UUID,
        run_id: UUID,
        checkpoint_id: UUID,
        expected_checkpoint_revision: int,
        reason: str,
    ) -> FlowRunReviewCheckpoint:
        principal = self._principal()
        normalized_reason = self._normalize_review_reject_reason(reason)
        run = await self.access_policy.load_run(
            run_id=run_id,
            flow_id=flow_id,
            access_kind="content",
        )
        checkpoint = await self.flow_run_repo.reject_review_checkpoint(
            checkpoint_id=checkpoint_id,
            tenant_id=self.user.tenant_id,
            flow_id=flow_id,
            flow_run_id=run.id,
            expected_revision=expected_checkpoint_revision,
            reason=normalized_reason,
            principal=principal,
        )
        await self.flow_run_terminalizer.terminalize_run(
            run_id=run.id,
            tenant_id=self.user.tenant_id,
            target_status=FlowRunStatus.CANCELLED,
            source=FlowRunLifecycleSource.REVIEW_REJECTED,
            error=FlowRunError.from_source(
                FlowRunLifecycleSource.REVIEW_REJECTED,
                code="flow_review_rejected",
                message=normalized_reason,
            ),
            cancelled_at=datetime.now(timezone.utc),
            principal=principal,
        )
        return checkpoint

    @staticmethod
    def _normalize_review_reject_reason(reason: str) -> str:
        normalized_reason = reason.strip()
        if not normalized_reason:
            raise BadRequestException(
                "Review rejection reason is required.",
                code="flow_review_reject_reason_required",
            )
        if len(normalized_reason) > _REVIEW_REJECT_REASON_MAX_LENGTH:
            raise BadRequestException(
                "Review rejection reason must be at most "
                f"{_REVIEW_REJECT_REASON_MAX_LENGTH} characters.",
                code="flow_review_reject_reason_too_long",
                context={"max_length": _REVIEW_REJECT_REASON_MAX_LENGTH},
            )
        return normalized_reason

    async def resume_review_checkpoint(
        self,
        *,
        flow_id: UUID,
        run_id: UUID,
        checkpoint_id: UUID,
        expected_checkpoint_revision: int,
        idempotency_key: str | None,
    ) -> FlowRunReviewCheckpointResumeResult:
        principal = self._principal()
        normalized_key = self._validate_review_resume_idempotency_key(idempotency_key)
        run = await self.access_policy.load_run(
            run_id=run_id,
            flow_id=flow_id,
            access_kind="content",
        )
        return await self.flow_run_repo.resume_review_checkpoint(
            checkpoint_id=checkpoint_id,
            tenant_id=self.user.tenant_id,
            flow_id=flow_id,
            flow_run_id=run.id,
            expected_revision=expected_checkpoint_revision,
            resume_idempotency_key=normalized_key,
            principal=principal,
        )

    @staticmethod
    def _validate_review_resume_idempotency_key(key: str | None) -> str:
        if key is None or not key.strip():
            raise BadRequestException(
                "Review resume requires an Idempotency-Key header.",
                code="flow_review_idempotency_key_required",
            )
        normalized = key.strip()
        if len(normalized) > _REVIEW_RESUME_IDEMPOTENCY_KEY_MAX_LENGTH:
            raise BadRequestException(
                "Idempotency key must be between 1 and "
                f"{_REVIEW_RESUME_IDEMPOTENCY_KEY_MAX_LENGTH} characters.",
                code="flow_run_invalid_idempotency_key",
                context={"max_length": _REVIEW_RESUME_IDEMPOTENCY_KEY_MAX_LENGTH},
            )
        return normalized
