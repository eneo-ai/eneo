from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, TypeAlias, TypeVar, assert_never, cast
from uuid import UUID

from eneo.flows.application.flow_run_access_policy import FlowRunAccessPolicy
from eneo.flows.application.flow_run_terminalization import FlowRunTerminalizer
from eneo.flows.application.flow_transcript_corrections_propagation import (
    TranscriptCorrectionsFoldOutcome,
    build_folded_transcript,
    skip_folded_transcript,
)
from eneo.flows.application.flow_transcript_corrections_service import (
    extract_transcription_segments,
)
from eneo.flows.domain.flow import (
    FlowPersistedJsonObject,
    FlowRun,
    FlowRunReviewCheckpoint,
    FlowRunStatus,
    FlowStepResult,
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
from eneo.flows.domain.runtime_invariant_exceptions import FlowRuntimeInvariantError
from eneo.flows.domain.speaker_labels import apply_speaker_names
from eneo.flows.domain.step_output import (
    FileBackedStepText,
    StepOutputMetadataError,
    interpret_step_text,
)
from eneo.flows.domain.transcript_words import LocatedWord, locate_words
from eneo.flows.enums import FlowOutputType, FlowRunLifecycleSource
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_api_exceptions import FlowBadRequestException
from eneo.flows.flow_review_policy import FlowStepReviewMode
from eneo.flows.flow_run_error import FlowRunError
from eneo.flows.flow_run_input_envelope import (
    FLOW_INPUT_TRANSCRIPTION_KEY,
    FlowRunInputEnvelopePatch,
)
from eneo.flows.infrastructure.flow_run_repo import FlowRunRepository
from eneo.flows.infrastructure.flow_run_review_checkpoint_repo import (
    FlowRunReviewCheckpointRepository,
    FlowRunReviewCheckpointResumeResult,
)
from eneo.flows.infrastructure.flow_transcript_corrections_repo import (
    FlowTranscriptCorrectionsRepository,
)
from eneo.flows.infrastructure.flow_transcript_words_repo import (
    FlowTranscriptWordsRepository,
)
from eneo.flows.output_processing import (
    StructuredOutputValue,
    validate_against_contract,
)
from eneo.flows.principal import FlowPrincipal
from eneo.flows.runtime.speaker_mapping_runtime import (
    SpeakerMappingValidationError,
    mapping_to_names,
    validate_speaker_mapping,
)
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
# The reviewer edits the step's value; both persisted encodings of that value are
# rebuilt from it, so neither is accepted from the client.
_REVIEW_DERIVED_PAYLOAD_KEYS = frozenset({"text", "structured"})

# The authoritative value a reviewer submits: the text of a text step, or the
# structured value of a JSON step.
FlowReviewEditedValue: TypeAlias = str | StructuredOutputValue


@dataclass(frozen=True, slots=True)
class FlowReviewCheckpointApproval:
    """An approved checkpoint plus what happened to its transcript corrections.

    ``corrections_fold`` is None when the step has no correction set (or the
    service was wired without the corrections repository).
    """

    checkpoint: FlowRunReviewCheckpoint
    corrections_fold: TranscriptCorrectionsFoldOutcome | None


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


def _review_edit_not_allowed(
    *, message: str, context: dict[str, object]
) -> FlowBadRequestException:
    return FlowBadRequestException(
        message,
        code=FlowApiErrorCode.REVIEW_EDIT_NOT_ALLOWED,
        context=context,
    )


def _review_edit_value_kind_error(
    *, checkpoint: FlowRunReviewCheckpoint, expected: str
) -> TypedIOValidationException:
    return TypedIOValidationException(
        f"Review checkpoint step {checkpoint.step_order} edit expects {expected} "
        f"for a {checkpoint.output_type.value} output step.",
        code=FlowApiErrorCode.TYPED_IO_VALIDATION_FAILED,
        context={
            "checkpoint_id": str(checkpoint.id),
            "step_id": str(checkpoint.step_id),
            "step_order": checkpoint.step_order,
            "output_type": checkpoint.output_type.value,
        },
    )


def _structured_value(
    *, checkpoint: FlowRunReviewCheckpoint, edited_value: FlowReviewEditedValue
) -> StructuredOutputValue:
    if isinstance(edited_value, str):
        raise _review_edit_value_kind_error(
            checkpoint=checkpoint, expected="a JSON object or array"
        )
    return edited_value


def _text_value(
    *, checkpoint: FlowRunReviewCheckpoint, edited_value: FlowReviewEditedValue
) -> str:
    if not isinstance(edited_value, str):
        raise _review_edit_value_kind_error(checkpoint=checkpoint, expected="a string")
    return edited_value


def _rendered_json_text(
    *, checkpoint: FlowRunReviewCheckpoint, structured: StructuredOutputValue
) -> str:
    # `allow_nan` would emit NaN and Infinity, which no JSON reader downstream
    # of this payload is obliged to accept.
    try:
        return json.dumps(structured, ensure_ascii=False, allow_nan=False)
    except ValueError as exc:
        raise TypedIOValidationException(
            f"Review checkpoint step {checkpoint.step_order} edit is not "
            f"representable as JSON: {exc}",
            code=FlowApiErrorCode.TYPED_IO_VALIDATION_FAILED,
            context={
                "checkpoint_id": str(checkpoint.id),
                "step_id": str(checkpoint.step_id),
                "step_order": checkpoint.step_order,
                "output_type": checkpoint.output_type.value,
            },
        ) from exc


def _validate_against_output_contract(
    *, checkpoint: FlowRunReviewCheckpoint, structured: StructuredOutputValue
) -> None:
    if checkpoint.output_contract_json is None:
        return
    context: dict[str, object] = {
        "checkpoint_id": str(checkpoint.id),
        "step_id": str(checkpoint.step_id),
        "step_order": checkpoint.step_order,
        "payload_field": "structured",
    }
    try:
        validate_against_contract(
            structured,
            checkpoint.output_contract_json,
            label=f"Review checkpoint step {checkpoint.step_order} output",
        )
    except TypedIOValidationException as exc:
        exc.context = context
        raise


SPEAKER_MAPPING_PAYLOAD_KEY = "speaker_mapping"


def speaker_mapping_extension(
    payload: FlowPersistedJsonObject | None,
) -> dict[str, Any] | None:
    """The speaker-mapping step's payload extension, when the checkpoint is one."""
    if payload is None:
        return None
    extension = payload.get(SPEAKER_MAPPING_PAYLOAD_KEY)
    return cast(dict[str, Any], extension) if isinstance(extension, dict) else None


def _speaker_mapping_text(
    *,
    checkpoint: FlowRunReviewCheckpoint,
    extension: dict[str, Any],
    structured: StructuredOutputValue,
    source_text: str | None,
) -> tuple[str, StructuredOutputValue]:
    """Re-apply an edited mapping to the source transcript.

    The mapping is the value the reviewer owns; the step text is derived from it
    so the two never disagree. Names outside the participant list are allowed:
    the reviewer is correcting, not proposing.
    """
    if source_text is None:
        raise TypedIOValidationException(
            "Review checkpoint source transcript is unavailable.",
            code=FlowApiErrorCode.TYPED_IO_VALIDATION_FAILED,
            context={"checkpoint_id": str(checkpoint.id)},
        )
    inventory = extension.get("inventory")
    participants = extension.get("participants")
    try:
        mapping = validate_speaker_mapping(
            structured,
            inventory=cast(list[dict[str, Any]], inventory)
            if isinstance(inventory, list)
            else [],
            participants=cast(list[str], participants)
            if isinstance(participants, list)
            else [],
            allow_free_text=True,
        )
    except SpeakerMappingValidationError as exc:
        raise TypedIOValidationException(
            f"Review checkpoint step {checkpoint.step_order} speaker mapping is "
            f"invalid: {exc}",
            code=FlowApiErrorCode.TYPED_IO_VALIDATION_FAILED,
            context={"checkpoint_id": str(checkpoint.id)},
        ) from exc
    return apply_speaker_names(source_text, mapping_to_names(mapping)), mapping


def build_edited_review_payload(
    *,
    checkpoint: FlowRunReviewCheckpoint,
    edited_value: FlowReviewEditedValue,
    source_text: str | None = None,
) -> FlowPersistedJsonObject:
    """Rebuild the reviewed step's payload from the one value the reviewer owns.

    Both persisted encodings of a JSON step output — the structured value and its
    text rendering — are derived here, so an edit cannot leave them disagreeing.
    For a speaker-mapping step the text is the source transcript with the edited
    mapping applied, which needs ``source_text``.
    """
    if checkpoint.schema_version != _REVIEW_CHECKPOINT_SCHEMA_VERSION:
        raise TypedIOValidationException(
            "Review checkpoint schema_version is unsupported.",
            code=FlowApiErrorCode.TYPED_IO_VALIDATION_FAILED,
            context={
                "schema_version": checkpoint.schema_version,
                "supported_schema_version": _REVIEW_CHECKPOINT_SCHEMA_VERSION,
            },
        )
    if checkpoint.review_mode is not FlowStepReviewMode.EDIT:
        raise _review_edit_not_allowed(
            message="Review checkpoint was opened for viewing, not editing.",
            context={"review_mode": checkpoint.review_mode.value},
        )
    previous_payload = checkpoint.current_payload_json
    if previous_payload is None:
        raise TypedIOValidationException(
            "Review checkpoint current payload is missing.",
            code=FlowApiErrorCode.TYPED_IO_VALIDATION_FAILED,
        )
    try:
        previous_text = interpret_step_text(previous_payload)
    except StepOutputMetadataError as exc:
        raise TypedIOValidationException(
            f"Review checkpoint payload is invalid: {exc}",
            code=FlowApiErrorCode.TYPED_IO_VALIDATION_FAILED,
        ) from exc
    if isinstance(previous_text, FileBackedStepText):
        # The full output lives in a generated file this path cannot replace, so
        # an edit here would leave the file describing a superseded output.
        raise FlowBadRequestException(
            "Review edit is not supported for a step output stored as a generated file.",
            code=FlowApiErrorCode.REVIEW_EDIT_FILE_BACKED_UNSUPPORTED,
            context={"file_id": str(previous_text.file_id)},
        )

    structured: StructuredOutputValue | None = None
    match checkpoint.output_type:
        case FlowOutputType.TEXT:
            text = _text_value(checkpoint=checkpoint, edited_value=edited_value)
        case FlowOutputType.JSON:
            structured = _structured_value(
                checkpoint=checkpoint, edited_value=edited_value
            )
            extension = speaker_mapping_extension(previous_payload)
            if extension is not None:
                text, structured = _speaker_mapping_text(
                    checkpoint=checkpoint,
                    extension=extension,
                    structured=structured,
                    source_text=source_text,
                )
            else:
                text = _rendered_json_text(checkpoint=checkpoint, structured=structured)
        case FlowOutputType.PDF | FlowOutputType.DOCX:
            raise _review_edit_not_allowed(
                message=(
                    "Review edit is not supported for artifact-producing "
                    "PDF or DOCX steps."
                ),
                context={"output_type": checkpoint.output_type.value},
            )
        case _:
            assert_never(checkpoint.output_type)

    # Size is settled before schema validation so an oversized value cannot buy
    # unbounded validation work.
    max_inline_text_bytes = get_settings().flow_max_inline_text_bytes
    try:
        text_bytes = len(text.encode("utf-8"))
    except UnicodeEncodeError as exc:
        # A JSON request can carry an escaped lone surrogate, which is a valid
        # Python string and not encodable text.
        raise TypedIOValidationException(
            f"Review checkpoint step {checkpoint.step_order} edit contains text "
            "that is not valid UTF-8.",
            code=FlowApiErrorCode.TYPED_IO_VALIDATION_FAILED,
            context={
                "checkpoint_id": str(checkpoint.id),
                "step_id": str(checkpoint.step_id),
                "step_order": checkpoint.step_order,
                "output_type": checkpoint.output_type.value,
            },
        ) from exc
    if text_bytes > max_inline_text_bytes:
        raise FlowBadRequestException(
            "Review checkpoint output exceeds the inline output size limit.",
            code=FlowApiErrorCode.REVIEW_EDIT_OUTPUT_TOO_LARGE,
            context={
                "max_inline_text_bytes": max_inline_text_bytes,
                "text_bytes": text_bytes,
            },
        )
    if structured is not None:
        _validate_against_output_contract(checkpoint=checkpoint, structured=structured)

    payload: FlowPersistedJsonObject = {"text": text}
    if structured is not None:
        payload["structured"] = structured
    payload.update(
        {
            key: value
            for key, value in previous_payload.items()
            if key not in _REVIEW_DERIVED_PAYLOAD_KEYS
        }
    )
    return payload


def _inline_step_text(payload: FlowPersistedJsonObject | None) -> str | None:
    """A step's inline output text, or None when absent, invalid or file-backed."""
    if payload is None:
        return None
    try:
        step_text = interpret_step_text(payload)
    except StepOutputMetadataError:
        return None
    if isinstance(step_text, FileBackedStepText):
        return None
    return step_text.text


class FlowRunReviewCheckpointService:
    def __init__(
        self,
        *,
        user: UserInDB,
        flow_run_review_checkpoint_repo: FlowRunReviewCheckpointRepository,
        access_policy: FlowRunAccessPolicy,
        flow_run_terminalizer: FlowRunTerminalizer,
        flow_run_repo: FlowRunRepository | None = None,
        transcript_corrections_repo: FlowTranscriptCorrectionsRepository | None = None,
        transcript_words_repo: FlowTranscriptWordsRepository | None = None,
    ):
        self.user = user
        self.flow_run_review_checkpoint_repo = flow_run_review_checkpoint_repo
        self.access_policy = access_policy
        self.flow_run_terminalizer = flow_run_terminalizer
        # Only speaker-mapping edits need step results and the run input; the
        # dependency stays optional so plain review edits need no repository.
        self.flow_run_repo = flow_run_repo
        # Only checkpoint approval folds transcript corrections; the dependency
        # stays optional so other review flows need no corrections repository.
        self.transcript_corrections_repo = transcript_corrections_repo
        # Word timings only refine the timestamps of a folded split line;
        # without the repository the segment's window is reused.
        self.transcript_words_repo = transcript_words_repo

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
        edited_value: FlowReviewEditedValue,
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
        extension = speaker_mapping_extension(checkpoint.current_payload_json)
        source_text = (
            await self._load_speaker_mapping_source_text(run=run, extension=extension)
            if extension is not None
            else None
        )
        current_payload_json = build_edited_review_payload(
            checkpoint=checkpoint,
            edited_value=edited_value,
            source_text=source_text,
        )
        edited = await self._with_review_lifecycle_translation(
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
        if extension is not None and source_text is not None:
            await self._sync_run_transcript(
                run=run,
                checkpoint=checkpoint,
                source_text=source_text,
                new_text=str(current_payload_json.get("text", "")),
            )
        return edited

    async def _load_speaker_mapping_source_text(
        self, *, run: FlowRun, extension: dict[str, Any]
    ) -> str:
        """The transcript the mapping step read, from that step's stored output."""
        if self.flow_run_repo is None:
            raise FlowRuntimeInvariantError(
                "Speaker-mapping review edits need a flow run repository."
            )
        raw_step_id = extension.get("source_step_id")
        try:
            source_step_id = UUID(str(raw_step_id))
        except (TypeError, ValueError) as exc:
            raise TypedIOValidationException(
                "Review checkpoint speaker mapping has no source step.",
                code=FlowApiErrorCode.TYPED_IO_VALIDATION_FAILED,
            ) from exc
        source = await self.flow_run_repo.get_step_result(
            run_id=run.id, step_id=source_step_id, tenant_id=run.tenant_id
        )
        if source is None:
            raise NotFoundException(
                "The transcript step this speaker mapping was built from is missing."
            )
        expected_attempt = extension.get("source_attempt_no")
        if (
            isinstance(expected_attempt, int)
            and source.current_attempt_no is not None
            and source.current_attempt_no != expected_attempt
        ):
            raise FlowBadRequestException(
                "The transcript step was re-run after this mapping was proposed; "
                "re-run the speaker mapping step instead of editing it.",
                code=FlowApiErrorCode.TYPED_IO_VALIDATION_FAILED,
            )
        try:
            step_text = interpret_step_text(source.output_payload_json)
        except StepOutputMetadataError as exc:
            raise TypedIOValidationException(
                f"Transcript step output is invalid: {exc}",
                code=FlowApiErrorCode.TYPED_IO_VALIDATION_FAILED,
            ) from exc
        if isinstance(step_text, FileBackedStepText):
            raise FlowBadRequestException(
                "Review edit is not supported when the transcript is stored as a "
                "generated file.",
                code=FlowApiErrorCode.REVIEW_EDIT_FILE_BACKED_UNSUPPORTED,
                context={"file_id": str(step_text.file_id)},
            )
        return step_text.text

    async def _sync_run_transcript(
        self,
        *,
        run: FlowRun,
        checkpoint: FlowRunReviewCheckpoint,
        source_text: str,
        new_text: str,
    ) -> None:
        """Keep ``{{transkribering}}`` equal to the reviewed transcript.

        The run-level transcript is only replaced when it still carries the
        source transcript or this step's previous rendering, never text a later
        step or user wrote.
        """
        if self.flow_run_repo is None:
            return
        current = (run.input_payload_json or {}).get(FLOW_INPUT_TRANSCRIPTION_KEY)
        previous_payload = checkpoint.current_payload_json or {}
        previous_text = previous_payload.get("text")
        if current not in (source_text, previous_text):
            return
        run.input_payload_json = await self.flow_run_repo.update_input_payload(
            run_id=run.id,
            tenant_id=run.tenant_id,
            input_payload_patch=FlowRunInputEnvelopePatch.transcription(
                transcript=new_text
            ),
        )

    async def approve_review_checkpoint(
        self,
        *,
        flow_id: UUID,
        run_id: UUID,
        checkpoint_id: UUID,
        expected_checkpoint_revision: int,
    ) -> FlowReviewCheckpointApproval:
        principal = self._principal()
        run = await self.access_policy.load_run(
            run_id=run_id,
            flow_id=flow_id,
            access_kind="content",
        )
        fold: TranscriptCorrectionsFoldOutcome | None = None
        pre_fold_checkpoint: FlowRunReviewCheckpoint | None = None
        if (
            self.transcript_corrections_repo is not None
            and self.flow_run_repo is not None
        ):
            pre_fold_checkpoint = await self._with_review_lifecycle_translation(
                self.flow_run_review_checkpoint_repo.get_review_checkpoint_for_edit(
                    checkpoint_id=checkpoint_id,
                    tenant_id=self.user.tenant_id,
                    flow_id=flow_id,
                    flow_run_id=run.id,
                    expected_revision=expected_checkpoint_revision,
                )
            )
            fold = await self._fold_transcript_corrections(
                run=run,
                checkpoint=pre_fold_checkpoint,
            )
        folded_payload = fold.folded_payload if fold is not None else None
        approved = await self._with_review_lifecycle_translation(
            self.flow_run_review_checkpoint_repo.approve_review_checkpoint(
                checkpoint_id=checkpoint_id,
                tenant_id=self.user.tenant_id,
                flow_id=flow_id,
                flow_run_id=run.id,
                expected_revision=expected_checkpoint_revision,
                principal=principal,
                current_payload_json=folded_payload,
            )
        )
        if (
            fold is not None
            and folded_payload is not None
            and fold.previous_text is not None
            and pre_fold_checkpoint is not None
        ):
            await self._sync_run_transcript(
                run=run,
                checkpoint=pre_fold_checkpoint,
                source_text=fold.previous_text,
                new_text=str(folded_payload.get("text", "")),
            )
        return FlowReviewCheckpointApproval(
            checkpoint=approved,
            corrections_fold=fold,
        )

    async def _fold_transcript_corrections(
        self,
        *,
        run: FlowRun,
        checkpoint: FlowRunReviewCheckpoint,
    ) -> TranscriptCorrectionsFoldOutcome | None:
        """The reviewed transcript's correction set folded into the checkpoint.

        A transcription step's checkpoint folds into its own text. A
        speaker-mapping checkpoint reviews the *source* transcription step:
        its corrections fold into that step's label-form output and the
        names-applied payload is rebuilt from the result.

        Never raises for foldability problems: a stale set, a hand-edited
        text, or a file-backed output skips the fold (with a reason) so the
        approval itself always proceeds.
        """
        if self.transcript_corrections_repo is None or self.flow_run_repo is None:
            return None
        extension = speaker_mapping_extension(checkpoint.current_payload_json)
        source_step_id = checkpoint.step_id
        if extension is not None:
            try:
                source_step_id = UUID(str(extension.get("source_step_id")))
            except (TypeError, ValueError):
                return None
        correction_set = await self.transcript_corrections_repo.get_for_step(
            run_id=run.id,
            step_id=source_step_id,
            tenant_id=run.tenant_id,
        )
        if correction_set is None or (
            not correction_set.occurrences_json
            and not correction_set.speaker_edits_json
        ):
            return None
        step_result = await self.flow_run_repo.get_step_result(
            run_id=run.id,
            step_id=source_step_id,
            tenant_id=run.tenant_id,
        )
        words_by_segment = await self._fold_words(
            run=run,
            step_id=source_step_id,
            step_result=step_result,
            segments_hash=correction_set.segments_hash,
        )
        if extension is None:
            return build_folded_transcript(
                checkpoint=checkpoint,
                step_result=step_result,
                correction_set=correction_set,
                words_by_segment=words_by_segment,
            )
        source_text = _inline_step_text(
            step_result.output_payload_json if step_result is not None else None
        )
        if source_text is None:
            return skip_folded_transcript(
                correction_set, "source_transcript_unavailable"
            )
        structured = (checkpoint.current_payload_json or {}).get("structured")
        if not isinstance(structured, dict):
            return skip_folded_transcript(correction_set, "payload_invalid")
        mapping = cast(StructuredOutputValue, structured)
        expected_attempt = extension.get("source_attempt_no")

        def rebuild(folded_source: str) -> FlowPersistedJsonObject:
            return build_edited_review_payload(
                checkpoint=checkpoint,
                edited_value=mapping,
                source_text=folded_source,
            )

        return build_folded_transcript(
            checkpoint=checkpoint,
            step_result=step_result,
            correction_set=correction_set,
            source_text=source_text,
            expected_attempt_no=expected_attempt
            if isinstance(expected_attempt, int)
            else None,
            rebuild_payload=rebuild,
            words_by_segment=words_by_segment,
        )

    async def _fold_words(
        self,
        *,
        run: FlowRun,
        step_id: UUID,
        step_result: FlowStepResult | None,
        segments_hash: str,
    ) -> dict[int, list[LocatedWord]] | None:
        """The step's stored words located in its segments, when they still
        anchor to the same segment array as the correction set."""
        if self.transcript_words_repo is None or step_result is None:
            return None
        words = await self.transcript_words_repo.get_for_step(
            run_id=run.id, step_id=step_id, tenant_id=run.tenant_id
        )
        if words is None or words.segments_hash != segments_hash:
            return None
        segments = extract_transcription_segments(step_result.input_payload_json)
        if segments is None:
            return None
        located: dict[int, list[LocatedWord]] = {}
        for entry in words.words_json:
            index = entry.get("segment_index")
            if not isinstance(index, int) or not 0 <= index < len(segments):
                continue
            text = segments[index].get("text")
            entry_words = entry.get("words")
            if not isinstance(text, str) or not isinstance(entry_words, list):
                continue
            located[index] = locate_words(
                text, cast("list[dict[str, Any]]", entry_words)
            )
        return located

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
