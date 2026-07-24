from __future__ import annotations

from datetime import datetime, timezone
from typing import Awaitable, TypeVar, assert_never
from uuid import UUID

from eneo.flows.application.flow_run_access_policy import FlowRunAccessPolicy
from eneo.flows.application.flow_run_terminalization import FlowRunTerminalizer
from eneo.flows.domain.flow import (
    FlowPersistedJsonObject,
    FlowRunReviewCheckpoint,
    FlowRunStatus,
)
from eneo.flows.domain.flow_run_exceptions import FlowRunNotFoundError
from eneo.flows.domain.review_checkpoint_exceptions import (
    FLOW_REVIEW_CHECKPOINT_LIFECYCLE_FAILURE_CLASSES,
    FlowReviewCheckpointAlreadyResumedError,
    FlowReviewCheckpointCancelledError,
    FlowReviewCheckpointExpiredError,
    FlowReviewCheckpointLifecycleFailure,
    FlowReviewCheckpointNotActiveError,
    FlowReviewCheckpointNotApprovedError,
    FlowReviewCheckpointNotFoundError,
    FlowReviewCheckpointOpenTerminalInvariantFailure,
    FlowReviewCheckpointRejectedError,
    FlowReviewCheckpointStaleRevisionError,
    FlowReviewCheckpointStepResultIncompleteError,
    FlowReviewEditStepResultMissingError,
    FlowReviewMultipleActiveCheckpointsError,
    FlowReviewOpenBlockedByActiveCheckpointError,
    FlowReviewRunNoLongerAwaitingReviewError,
    FlowReviewRunNotAwaitingReviewError,
)
from eneo.flows.domain.step_output import (
    InlineStepText,
    StepOutputMetadataError,
    interpret_step_text,
)
from eneo.flows.enums import FlowRunLifecycleSource
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_api_exceptions import FlowBadRequestException
from eneo.flows.flow_run_error import FlowRunError
from eneo.flows.infrastructure.flow_run_repo import FlowRunRepository
from eneo.flows.infrastructure.flow_run_review_checkpoint_repo import (
    FlowRunReviewCheckpointRepository,
    FlowRunReviewCheckpointResumeResult,
)
from eneo.flows.output_processing import validate_against_contract
from eneo.flows.principal import FlowPrincipal
from eneo.main.config import get_settings
from eneo.main.exceptions import (
    NotFoundException,
    TypedIOValidationException,
)
from eneo.users.user import UserInDB

_ReviewOperationResult = TypeVar("_ReviewOperationResult")
_REVIEW_REJECT_REASON_MAX_LENGTH = 1024
_REVIEW_RESUME_IDEMPOTENCY_KEY_MAX_LENGTH = 255
_REVIEW_CHECKPOINT_SCHEMA_VERSION = 1
_REVIEW_EDITABLE_PAYLOAD_KEYS = frozenset({"text", "structured"})


def review_open_terminal_invariant_error(
    exc: FlowReviewCheckpointOpenTerminalInvariantFailure,
) -> tuple[FlowApiErrorCode, str]:
    match exc:
        case FlowReviewOpenBlockedByActiveCheckpointError():
            return (
                FlowApiErrorCode.REVIEW_OPEN_ACTIVE_CONFLICT_INVARIANT,
                "Review checkpoint opening failed because another checkpoint is active.",
            )
        case FlowReviewMultipleActiveCheckpointsError():
            return (
                FlowApiErrorCode.REVIEW_OPEN_MULTIPLE_ACTIVE_CHECKPOINTS_INVARIANT,
                "Review checkpoint opening failed because multiple checkpoints are active.",
            )
        case FlowReviewCheckpointStepResultIncompleteError():
            return (
                FlowApiErrorCode.REVIEW_OPEN_STEP_RESULT_INCOMPLETE_INVARIANT,
                "Review checkpoint opening failed because the completed step result was unavailable.",
            )
        case _:
            assert_never(exc)


def _review_checkpoint_expired_context(
    exc: FlowReviewCheckpointExpiredError,
) -> dict[str, object]:
    context: dict[str, object] = {
        "checkpoint_id": str(exc.checkpoint_id),
        "state": exc.state,
    }
    if exc.expires_at is not None:
        expires_at = exc.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        context["expires_at"] = expires_at.isoformat()
    if exc.expired_at is not None:
        expired_at = exc.expired_at
        if expired_at.tzinfo is None:
            expired_at = expired_at.replace(tzinfo=timezone.utc)
        context["expired_at"] = expired_at.isoformat()
    return context


def _review_lifecycle_failure_to_api_exception(
    exc: FlowReviewCheckpointLifecycleFailure,
) -> FlowBadRequestException | NotFoundException:
    match exc:
        case FlowReviewCheckpointNotFoundError():
            return NotFoundException(
                "Review checkpoint not found.",
                code=FlowApiErrorCode.REVIEW_CHECKPOINT_NOT_FOUND,
            )
        case FlowReviewRunNotAwaitingReviewError():
            return FlowBadRequestException(
                "Flow run is not awaiting review.",
                code=FlowApiErrorCode.REVIEW_NOT_ACTIVE,
                context={"status": exc.status},
            )
        case FlowReviewRunNoLongerAwaitingReviewError():
            return FlowBadRequestException(
                "Flow run is no longer awaiting review.",
                code=FlowApiErrorCode.REVIEW_NOT_ACTIVE,
            )
        case FlowReviewCheckpointExpiredError():
            return FlowBadRequestException(
                "Review checkpoint has expired.",
                code=FlowApiErrorCode.REVIEW_EXPIRED,
                context=_review_checkpoint_expired_context(exc),
            )
        case FlowReviewCheckpointStaleRevisionError():
            return FlowBadRequestException(
                "Review checkpoint revision is stale.",
                code=FlowApiErrorCode.REVIEW_STALE_REVISION,
                context={
                    "expected_checkpoint_revision": exc.expected_checkpoint_revision,
                    "current_checkpoint_revision": exc.current_checkpoint_revision,
                },
            )
        case FlowReviewCheckpointNotActiveError():
            return FlowBadRequestException(
                "Review checkpoint is not active for this operation.",
                code=FlowApiErrorCode.REVIEW_NOT_ACTIVE,
                context={"state": exc.state},
            )
        case FlowReviewEditStepResultMissingError():
            return FlowBadRequestException(
                "Current step result projection was not found for review edit.",
                code=FlowApiErrorCode.REVIEW_STEP_RESULT_NOT_FOUND,
            )
        case FlowReviewCheckpointAlreadyResumedError():
            return FlowBadRequestException(
                "Review checkpoint has already been resumed.",
                code=FlowApiErrorCode.REVIEW_ALREADY_RESUMED,
            )
        case FlowReviewCheckpointRejectedError():
            return FlowBadRequestException(
                "Review checkpoint was rejected.",
                code=FlowApiErrorCode.REVIEW_REJECTED,
            )
        case FlowReviewCheckpointCancelledError():
            return FlowBadRequestException(
                "Review checkpoint was cancelled.",
                code=FlowApiErrorCode.REVIEW_CANCELLED,
            )
        case FlowReviewCheckpointNotApprovedError():
            return FlowBadRequestException(
                "Review checkpoint must be approved before resume.",
                code=FlowApiErrorCode.REVIEW_NOT_APPROVED,
                context={"state": exc.state},
            )
        case _:
            assert_never(exc)


class FlowRunReviewCheckpointService:
    def __init__(
        self,
        *,
        user: UserInDB,
        flow_run_review_checkpoint_repo: FlowRunReviewCheckpointRepository,
        flow_run_repo: FlowRunRepository,
        access_policy: FlowRunAccessPolicy,
        flow_run_terminalizer: FlowRunTerminalizer,
    ):
        self.user = user
        self.flow_run_review_checkpoint_repo = flow_run_review_checkpoint_repo
        self.flow_run_repo = flow_run_repo
        self.access_policy = access_policy
        self.flow_run_terminalizer = flow_run_terminalizer

    def _principal(self) -> FlowPrincipal:
        return FlowPrincipal.from_user(self.user)

    @staticmethod
    async def _with_review_lifecycle_translation(
        operation: Awaitable[_ReviewOperationResult],
    ) -> _ReviewOperationResult:
        try:
            return await operation
        except FlowRunNotFoundError as exc:
            raise NotFoundException("Flow run not found.") from exc
        except FLOW_REVIEW_CHECKPOINT_LIFECYCLE_FAILURE_CLASSES as exc:
            raise _review_lifecycle_failure_to_api_exception(exc) from exc

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
        return await self.flow_run_review_checkpoint_repo.get_active_review_checkpoint(
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
        current_payload_json: FlowPersistedJsonObject,
    ) -> FlowRunReviewCheckpoint:
        principal = self._principal()
        run = await self.access_policy.load_run(
            run_id=run_id,
            flow_id=flow_id,
            access_kind="content",
        )
        checkpoint = await self._with_review_lifecycle_translation(
            self.flow_run_review_checkpoint_repo.get_review_checkpoint_for_edit(
                checkpoint_id=checkpoint_id,
                tenant_id=self.user.tenant_id,
                flow_id=flow_id,
                flow_run_id=run.id,
                expected_revision=expected_checkpoint_revision,
            )
        )
        await self._validate_review_checkpoint_edit_payload(
            checkpoint=checkpoint,
            run_id=run.id,
            current_payload_json=current_payload_json,
        )
        return await self._with_review_lifecycle_translation(
            self.flow_run_review_checkpoint_repo.edit_review_checkpoint_payload(
                checkpoint_id=checkpoint_id,
                tenant_id=self.user.tenant_id,
                flow_id=flow_id,
                flow_run_id=run.id,
                expected_revision=expected_checkpoint_revision,
                current_payload_json=current_payload_json,
                principal=principal,
            )
        )

    async def _validate_review_checkpoint_edit_payload(
        self,
        *,
        checkpoint: FlowRunReviewCheckpoint,
        run_id: UUID,
        current_payload_json: FlowPersistedJsonObject,
    ) -> None:
        if checkpoint.schema_version != _REVIEW_CHECKPOINT_SCHEMA_VERSION:
            raise TypedIOValidationException(
                "Review checkpoint schema_version is unsupported.",
                code=FlowApiErrorCode.TYPED_IO_VALIDATION_FAILED,
                context={
                    "schema_version": checkpoint.schema_version,
                    "supported_schema_version": _REVIEW_CHECKPOINT_SCHEMA_VERSION,
                },
            )

        try:
            step_text = interpret_step_text(current_payload_json)
        except StepOutputMetadataError as exc:
            raise TypedIOValidationException(
                f"Review checkpoint payload is invalid: {exc}",
                code=FlowApiErrorCode.TYPED_IO_VALIDATION_FAILED,
            ) from exc

        previous_payload = checkpoint.current_payload_json
        if previous_payload is None:
            raise TypedIOValidationException(
                "Review checkpoint current payload is missing.",
                code=FlowApiErrorCode.TYPED_IO_VALIDATION_FAILED,
            )
        runtime_owned_keys = set(previous_payload) - _REVIEW_EDITABLE_PAYLOAD_KEYS
        if any(
            key not in current_payload_json
            or current_payload_json[key] != previous_payload[key]
            for key in runtime_owned_keys
        ) or any(
            key not in previous_payload and key not in _REVIEW_EDITABLE_PAYLOAD_KEYS
            for key in current_payload_json
        ):
            raise TypedIOValidationException(
                "Review checkpoint runtime-owned payload fields must be preserved unchanged.",
                code=FlowApiErrorCode.TYPED_IO_VALIDATION_FAILED,
            )

        if isinstance(step_text, InlineStepText):
            max_inline_text_bytes = get_settings().flow_max_inline_text_bytes
            if len(step_text.text.encode("utf-8")) > max_inline_text_bytes:
                raise TypedIOValidationException(
                    "Review checkpoint text exceeds the inline output size limit.",
                    code=FlowApiErrorCode.TYPED_IO_VALIDATION_FAILED,
                    context={"max_inline_text_bytes": max_inline_text_bytes},
                )
        else:
            if previous_payload.get("text") != current_payload_json.get("text"):
                raise TypedIOValidationException(
                    "Review checkpoint overflow-backed text preview cannot be changed.",
                    code=FlowApiErrorCode.TYPED_IO_VALIDATION_FAILED,
                )
            result_file = await self.flow_run_repo.get_result_file(
                run_id=run_id,
                tenant_id=self.user.tenant_id,
                file_id=step_text.file_id,
            )
            if result_file is None or (
                result_file.flow_run_id != run_id
                or result_file.flow_id != checkpoint.flow_id
                or result_file.tenant_id != self.user.tenant_id
                or result_file.step_id != checkpoint.step_id
                or result_file.attempt_no != checkpoint.attempt_no
                or result_file.file_id != step_text.file_id
                or result_file.source != "generated_output"
            ):
                raise TypedIOValidationException(
                    "Review checkpoint text_overflow reference is missing or has invalid ownership.",
                    code=FlowApiErrorCode.TYPED_IO_VALIDATION_FAILED,
                )

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
                code=FlowApiErrorCode.TYPED_IO_CONTRACT_VIOLATION,
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
        return await self._with_review_lifecycle_translation(
            self.flow_run_review_checkpoint_repo.approve_review_checkpoint(
                checkpoint_id=checkpoint_id,
                tenant_id=self.user.tenant_id,
                flow_id=flow_id,
                flow_run_id=run.id,
                expected_revision=expected_checkpoint_revision,
                principal=principal,
            )
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
        checkpoint = await self._with_review_lifecycle_translation(
            self.flow_run_review_checkpoint_repo.reject_review_checkpoint(
                checkpoint_id=checkpoint_id,
                tenant_id=self.user.tenant_id,
                flow_id=flow_id,
                flow_run_id=run.id,
                expected_revision=expected_checkpoint_revision,
                reason=normalized_reason,
                principal=principal,
            )
        )
        try:
            await self.flow_run_terminalizer.terminalize_run(
                run_id=run.id,
                tenant_id=self.user.tenant_id,
                target_status=FlowRunStatus.CANCELLED,
                source=FlowRunLifecycleSource.REVIEW_REJECTED,
                error=FlowRunError.from_source(
                    FlowRunLifecycleSource.REVIEW_REJECTED,
                    code=FlowApiErrorCode.REVIEW_REJECTED,
                    message=normalized_reason,
                ),
                cancelled_at=datetime.now(timezone.utc),
                principal=principal,
            )
        except FlowRunNotFoundError as exc:
            raise NotFoundException("Flow run not found.") from exc
        return checkpoint

    @staticmethod
    def _normalize_review_reject_reason(reason: str) -> str:
        normalized_reason = reason.strip()
        if not normalized_reason:
            raise FlowBadRequestException(
                "Review rejection reason is required.",
                code=FlowApiErrorCode.REVIEW_REJECT_REASON_REQUIRED,
            )
        if len(normalized_reason) > _REVIEW_REJECT_REASON_MAX_LENGTH:
            raise FlowBadRequestException(
                "Review rejection reason must be at most "
                f"{_REVIEW_REJECT_REASON_MAX_LENGTH} characters.",
                code=FlowApiErrorCode.REVIEW_REJECT_REASON_TOO_LONG,
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
        return await self._with_review_lifecycle_translation(
            self.flow_run_review_checkpoint_repo.resume_review_checkpoint(
                checkpoint_id=checkpoint_id,
                tenant_id=self.user.tenant_id,
                flow_id=flow_id,
                flow_run_id=run.id,
                expected_revision=expected_checkpoint_revision,
                resume_idempotency_key=normalized_key,
                principal=principal,
            )
        )

    @staticmethod
    def _validate_review_resume_idempotency_key(key: str | None) -> str:
        if key is None or not key.strip():
            raise FlowBadRequestException(
                "Review resume requires an Idempotency-Key header.",
                code=FlowApiErrorCode.REVIEW_IDEMPOTENCY_KEY_REQUIRED,
            )
        normalized = key.strip()
        if len(normalized) > _REVIEW_RESUME_IDEMPOTENCY_KEY_MAX_LENGTH:
            raise FlowBadRequestException(
                "Idempotency key must be between 1 and "
                f"{_REVIEW_RESUME_IDEMPOTENCY_KEY_MAX_LENGTH} characters.",
                code=FlowApiErrorCode.RUN_INVALID_IDEMPOTENCY_KEY,
                context={"max_length": _REVIEW_RESUME_IDEMPOTENCY_KEY_MAX_LENGTH},
            )
        return normalized
