from __future__ import annotations

from enum import Enum


class FlowInputSource(str, Enum):
    FLOW_INPUT = "flow_input"
    PREVIOUS_STEP = "previous_step"
    ALL_PREVIOUS_STEPS = "all_previous_steps"
    HTTP_GET = "http_get"
    HTTP_POST = "http_post"


class RerunDependencyKind(str, Enum):
    INPUT_SOURCE_PREVIOUS_STEP = "input_source.previous_step"
    INPUT_SOURCE_ALL_PREVIOUS_STEPS = "input_source.all_previous_steps"
    INPUT_BINDINGS_QUESTION = "input_bindings.question"
    INPUT_CONFIG_URL = "input_config.url"
    INPUT_CONFIG_HEADERS = "input_config.headers"
    INPUT_CONFIG_BODY_TEMPLATE = "input_config.body_template"
    INPUT_CONFIG_BODY_JSON = "input_config.body_json"
    OUTPUT_CONFIG_URL = "output_config.url"
    OUTPUT_CONFIG_HEADERS = "output_config.headers"
    OUTPUT_CONFIG_BODY_TEMPLATE = "output_config.body_template"
    OUTPUT_CONFIG_BODY_JSON = "output_config.body_json"
    OUTPUT_CONFIG_BINDINGS = "output_config.bindings"
    ASSISTANT_SNAPSHOT_INSTRUCTIONS = "assistant_snapshot.instructions"
    RUNTIME_ALIAS_PREVIOUS_STEP = "runtime_alias.previous_step"


class AIBuilderInputSource(str, Enum):
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


class AIBuilderInputType(str, Enum):
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
    HTTP_POST = "http_post"
    TRANSCRIBE_ONLY = "transcribe_only"
    TEMPLATE_FILL = "template_fill"


class AIBuilderOutputMode(str, Enum):
    PASS_THROUGH = FlowOutputMode.PASS_THROUGH.value
    TRANSCRIBE_ONLY = FlowOutputMode.TRANSCRIBE_ONLY.value
    TEMPLATE_FILL = FlowOutputMode.TEMPLATE_FILL.value


class FlowMcpPolicy(str, Enum):
    INHERIT = "inherit"
    RESTRICTED = "restricted"


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


ACTIVE_FLOW_RUN_STATUSES = frozenset(
    {
        FlowRunStatus.QUEUED,
        FlowRunStatus.RUNNING,
    }
)
TERMINAL_FLOW_RUN_STATUSES = frozenset(
    {
        FlowRunStatus.COMPLETED,
        FlowRunStatus.FAILED,
        FlowRunStatus.CANCELLED,
    }
)
CANCELLABLE_FLOW_RUN_STATUSES = frozenset(
    {
        FlowRunStatus.QUEUED,
        FlowRunStatus.RUNNING,
        FlowRunStatus.AWAITING_REVIEW,
    }
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
    DISPATCH_FAILURE = "dispatch_failure"
    REVIEW_REJECTED = "review_rejected"
    REVIEW_CHECKPOINT_OPENED = "review_checkpoint_opened"
    REVIEW_CHECKPOINT_EDITED = "review_checkpoint_edited"
    REVIEW_CHECKPOINT_APPROVED = "review_checkpoint_approved"
    REVIEW_CHECKPOINT_REJECTED = "review_checkpoint_rejected"
    REVIEW_CHECKPOINT_RESUMED = "review_checkpoint_resumed"
    REVIEW_CHECKPOINT_CANCELLED = "review_checkpoint_cancelled"


class FlowRunReviewCheckpointState(str, Enum):
    AWAITING_REVIEW = FlowRunStatus.AWAITING_REVIEW.value
    EDITED = "edited"
    APPROVED = "approved"
    REJECTED = "rejected"
    RESUMED = "resumed"
    CANCELLED = FlowRunStatus.CANCELLED.value


ACTIVE_FLOW_RUN_REVIEW_CHECKPOINT_STATES = frozenset(
    {
        FlowRunReviewCheckpointState.AWAITING_REVIEW,
        FlowRunReviewCheckpointState.EDITED,
        FlowRunReviewCheckpointState.APPROVED,
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
    RETRIED = "retried"
    FAILED = "failed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class FlowRuntimeInputFormat(str, Enum):
    DOCUMENT = "document"
    AUDIO = "audio"
    FILE = "file"


class FlowTemplateAssetStatus(str, Enum):
    READY = "ready"
    NEEDS_ACTION = "needs_action"
    READ_ONLY = "read_only"
    UNAVAILABLE = "unavailable"
