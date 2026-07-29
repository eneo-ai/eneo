from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping


class FlowInputSource(str, Enum):
    FLOW_INPUT = "flow_input"
    PREVIOUS_STEP = "previous_step"
    ALL_PREVIOUS_STEPS = "all_previous_steps"
    HTTP_GET = "http_get"


class RerunDependencyKind(str, Enum):
    INPUT_SOURCE_PREVIOUS_STEP = "input_source.previous_step"
    INPUT_SOURCE_ALL_PREVIOUS_STEPS = "input_source.all_previous_steps"
    INPUT_BINDINGS_QUESTION = "input_bindings.question"
    INPUT_CONFIG_URL = "input_config.url"
    INPUT_CONFIG_HEADERS = "input_config.headers"
    INPUT_CONFIG_BODY_TEMPLATE = "input_config.body.template"
    OUTPUT_CONFIG_URL = "output_config.url"
    OUTPUT_CONFIG_HEADERS = "output_config.headers"
    OUTPUT_CONFIG_BODY_TEMPLATE = "output_config.body.template"
    OUTPUT_CONFIG_BINDINGS = "output_config.bindings"
    ASSISTANT_SNAPSHOT_INSTRUCTIONS = "assistant_snapshot.instructions"
    RUNTIME_ALIAS_PREVIOUS_STEP = "runtime_alias.previous_step"


class FlowAuthoringInputSource(str, Enum):
    FLOW_INPUT = FlowInputSource.FLOW_INPUT.value
    PREVIOUS_STEP = FlowInputSource.PREVIOUS_STEP.value
    ALL_PREVIOUS_STEPS = FlowInputSource.ALL_PREVIOUS_STEPS.value


class FlowInputType(str, Enum):
    TEXT = "text"
    JSON = "json"
    IMAGE = "image"
    AUDIO = "audio"
    DOCUMENT = "document"
    FILE = "file"
    ANY = "any"


class FlowAuthoringInputType(str, Enum):
    TEXT = FlowInputType.TEXT.value
    JSON = FlowInputType.JSON.value
    AUDIO = FlowInputType.AUDIO.value
    DOCUMENT = FlowInputType.DOCUMENT.value
    FILE = FlowInputType.FILE.value
    ANY = FlowInputType.ANY.value


class FlowOutputType(str, Enum):
    TEXT = "text"
    JSON = "json"
    PDF = "pdf"
    DOCX = "docx"


class FlowOutputMode(str, Enum):
    PASS_THROUGH = "pass_through"
    COMPOSE_TEXT = "compose_text"
    HTTP_POST = "http_post"
    TRANSCRIBE_ONLY = "transcribe_only"
    TEMPLATE_FILL = "template_fill"
    RENDER_VERBATIM = "render_verbatim"


FLOW_COMPLETION_MODEL_OUTPUT_MODES: frozenset[FlowOutputMode] = frozenset(
    {FlowOutputMode.PASS_THROUGH, FlowOutputMode.HTTP_POST}
)


def flow_output_mode_uses_completion_model(
    mode: FlowOutputMode | str,
) -> bool:
    """Whether the output mode invokes an assistant completion model."""

    try:
        output_mode = FlowOutputMode(mode)
    except ValueError:
        return False
    return output_mode in FLOW_COMPLETION_MODEL_OUTPUT_MODES


def flow_output_mode_has_outbound_delivery(mode: FlowOutputMode) -> bool:
    return mode == FlowOutputMode.HTTP_POST


class FlowAuthoringOutputMode(str, Enum):
    PASS_THROUGH = FlowOutputMode.PASS_THROUGH.value
    COMPOSE_TEXT = FlowOutputMode.COMPOSE_TEXT.value
    TRANSCRIBE_ONLY = FlowOutputMode.TRANSCRIBE_ONLY.value
    TEMPLATE_FILL = FlowOutputMode.TEMPLATE_FILL.value
    RENDER_VERBATIM = FlowOutputMode.RENDER_VERBATIM.value


FLOW_INPUT_SOURCE_VALUES = tuple(item.value for item in FlowInputSource)
FLOW_INPUT_TYPE_VALUES = tuple(item.value for item in FlowInputType)
FLOW_OUTPUT_MODE_VALUES = tuple(item.value for item in FlowOutputMode)
FLOW_OUTPUT_TYPE_VALUES = tuple(item.value for item in FlowOutputType)


class FlowRunStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_REVIEW = "awaiting_review"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# Rerun operation values currently mirror run statuses, but the operation
# lifecycle is a separate persisted contract.
class FlowRunRerunOperationStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class FlowRunRerunInvalidationRole(str, Enum):
    ROOT = "root"
    DOWNSTREAM = "downstream"


@dataclass(frozen=True)
class FlowRunStatusCapability:
    status: FlowRunStatus
    is_active: bool
    should_poll: bool
    is_terminal: bool
    is_cancellable: bool
    is_awaiting_review: bool
    can_request_redispatch: bool
    is_rerun_eligible: bool


FLOW_RUN_STATUS_CAPABILITIES: Mapping[FlowRunStatus, FlowRunStatusCapability] = (
    MappingProxyType(
        {
            FlowRunStatus.QUEUED: FlowRunStatusCapability(
                status=FlowRunStatus.QUEUED,
                is_active=True,
                should_poll=True,
                is_terminal=False,
                is_cancellable=True,
                is_awaiting_review=False,
                can_request_redispatch=True,
                is_rerun_eligible=False,
            ),
            FlowRunStatus.RUNNING: FlowRunStatusCapability(
                status=FlowRunStatus.RUNNING,
                is_active=True,
                should_poll=True,
                is_terminal=False,
                is_cancellable=True,
                is_awaiting_review=False,
                can_request_redispatch=False,
                is_rerun_eligible=False,
            ),
            FlowRunStatus.AWAITING_REVIEW: FlowRunStatusCapability(
                status=FlowRunStatus.AWAITING_REVIEW,
                is_active=False,
                should_poll=True,
                is_terminal=False,
                is_cancellable=True,
                is_awaiting_review=True,
                can_request_redispatch=False,
                is_rerun_eligible=False,
            ),
            FlowRunStatus.COMPLETED: FlowRunStatusCapability(
                status=FlowRunStatus.COMPLETED,
                is_active=False,
                should_poll=False,
                is_terminal=True,
                is_cancellable=False,
                is_awaiting_review=False,
                can_request_redispatch=False,
                is_rerun_eligible=True,
            ),
            FlowRunStatus.FAILED: FlowRunStatusCapability(
                status=FlowRunStatus.FAILED,
                is_active=False,
                should_poll=False,
                is_terminal=True,
                is_cancellable=False,
                is_awaiting_review=False,
                can_request_redispatch=False,
                is_rerun_eligible=True,
            ),
            FlowRunStatus.CANCELLED: FlowRunStatusCapability(
                status=FlowRunStatus.CANCELLED,
                is_active=False,
                should_poll=False,
                is_terminal=True,
                is_cancellable=False,
                is_awaiting_review=False,
                can_request_redispatch=False,
                is_rerun_eligible=False,
            ),
        }
    )
)
FLOW_RUN_STATUS_FILTER_ORDER = (
    FlowRunStatus.COMPLETED,
    FlowRunStatus.FAILED,
    FlowRunStatus.RUNNING,
    FlowRunStatus.QUEUED,
    FlowRunStatus.AWAITING_REVIEW,
    FlowRunStatus.CANCELLED,
)

ACTIVE_FLOW_RUN_STATUSES = frozenset(
    status
    for status, capability in FLOW_RUN_STATUS_CAPABILITIES.items()
    if capability.is_active
)
TERMINAL_FLOW_RUN_STATUSES = frozenset(
    status
    for status, capability in FLOW_RUN_STATUS_CAPABILITIES.items()
    if capability.is_terminal
)
TERMINAL_FLOW_RUN_STATUS_VALUES = tuple(
    status.value for status in FlowRunStatus if status in TERMINAL_FLOW_RUN_STATUSES
)
RERUN_OPERATION_TERMINAL_STATUS_BY_RUN_STATUS: Mapping[
    FlowRunStatus, FlowRunRerunOperationStatus
] = MappingProxyType(
    {
        FlowRunStatus.COMPLETED: FlowRunRerunOperationStatus.COMPLETED,
        FlowRunStatus.FAILED: FlowRunRerunOperationStatus.FAILED,
        FlowRunStatus.CANCELLED: FlowRunRerunOperationStatus.CANCELLED,
    }
)
CANCELLABLE_FLOW_RUN_STATUSES = frozenset(
    status
    for status, capability in FLOW_RUN_STATUS_CAPABILITIES.items()
    if capability.is_cancellable
)
RERUN_ELIGIBLE_FLOW_RUN_STATUSES = frozenset(
    status
    for status, capability in FLOW_RUN_STATUS_CAPABILITIES.items()
    if capability.is_rerun_eligible
)
RERUN_ELIGIBLE_FLOW_RUN_STATUS_VALUES = tuple(
    status.value
    for status in FlowRunStatus
    if status in RERUN_ELIGIBLE_FLOW_RUN_STATUSES
)


def normalize_flow_run_status(status: FlowRunStatus | str) -> FlowRunStatus:
    if isinstance(status, FlowRunStatus):
        return status
    return FlowRunStatus(status)


def is_active_flow_run_status(status: FlowRunStatus | str) -> bool:
    return normalize_flow_run_status(status) in ACTIVE_FLOW_RUN_STATUSES


def is_terminal_flow_run_status(status: FlowRunStatus | str) -> bool:
    return normalize_flow_run_status(status) in TERMINAL_FLOW_RUN_STATUSES


def is_cancellable_flow_run_status(status: FlowRunStatus | str) -> bool:
    return normalize_flow_run_status(status) in CANCELLABLE_FLOW_RUN_STATUSES


class FlowRunLifecycleSource(str, Enum):
    EXECUTOR_COMPLETED = "executor_completed"
    EXECUTOR_FAILED = "executor_failed"
    DISPATCH_FAILURE = "dispatch_failure"
    FLOW_DELETED = "flow_deleted"
    DEFINITION_CHECKSUM_MISMATCH = "definition_checksum_mismatch"
    INVALID_FLOW_DEFINITION = "invalid_flow_definition"
    ASSISTANT_SNAPSHOT_DRIFT = "assistant_snapshot_drift"
    STEP_MISSING = "step_missing"
    TASK_TIMEOUT = "task_timeout"
    TASK_FAILURE = "task_failure"
    MISSING_PRINCIPAL = "missing_principal"
    STALE_RUNNING_RECONCILER = "stale_running_reconciler"
    USER_CANCEL = "user_cancel"
    REVIEW_REJECTED = "review_rejected"
    REVIEW_CHECKPOINT_OPENED = "review_checkpoint_opened"
    REVIEW_CHECKPOINT_EDITED = "review_checkpoint_edited"
    REVIEW_CHECKPOINT_APPROVED = "review_checkpoint_approved"
    REVIEW_CHECKPOINT_REJECTED = "review_checkpoint_rejected"
    REVIEW_CHECKPOINT_RESUMED = "review_checkpoint_resumed"
    REVIEW_CHECKPOINT_CANCELLED = "review_checkpoint_cancelled"
    REVIEW_EXPIRED = "review_expired"
    REVIEW_CHECKPOINT_EXPIRED = "review_checkpoint_expired"


class FlowRunReviewCheckpointState(str, Enum):
    AWAITING_REVIEW = FlowRunStatus.AWAITING_REVIEW.value
    EDITED = "edited"
    APPROVED = "approved"
    REJECTED = "rejected"
    RESUMED = "resumed"
    CANCELLED = FlowRunStatus.CANCELLED.value
    EXPIRED = "expired"


ACTIVE_FLOW_RUN_REVIEW_CHECKPOINT_STATES = frozenset(
    {
        FlowRunReviewCheckpointState.AWAITING_REVIEW,
        FlowRunReviewCheckpointState.EDITED,
        FlowRunReviewCheckpointState.APPROVED,
    }
)
RECONCILABLE_REVIEW_CHECKPOINT_STATES = frozenset(
    {
        FlowRunReviewCheckpointState.AWAITING_REVIEW,
        FlowRunReviewCheckpointState.EDITED,
    }
)


class FlowStepResultStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class FlowStepAttemptStatus(str, Enum):
    STARTED = "started"
    FAILED = "failed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


ACTIVE_FLOW_STEP_RESULT_STATUSES = frozenset(
    {
        FlowStepResultStatus.PENDING,
        FlowStepResultStatus.RUNNING,
    }
)
ACTIVE_FLOW_STEP_RESULT_STATUS_VALUES = tuple(
    status.value
    for status in FlowStepResultStatus
    if status in ACTIVE_FLOW_STEP_RESULT_STATUSES
)
OPEN_FLOW_STEP_ATTEMPT_STATUSES = frozenset(
    {
        FlowStepAttemptStatus.STARTED,
    }
)
OPEN_FLOW_STEP_ATTEMPT_STATUS_VALUES = tuple(
    status.value
    for status in FlowStepAttemptStatus
    if status in OPEN_FLOW_STEP_ATTEMPT_STATUSES
)


class FlowRuntimeInputFormat(str, Enum):
    DOCUMENT = "document"
    AUDIO = "audio"
    FILE = "file"


class FlowTemplateAssetStatus(str, Enum):
    READY = "ready"
    NEEDS_ACTION = "needs_action"
    READ_ONLY = "read_only"
    UNAVAILABLE = "unavailable"
