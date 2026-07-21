from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
BACKEND_SRC = BACKEND_ROOT / "src"
if str(BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC))

from eneo.flows.enums import (  # noqa: E402
    ACTIVE_FLOW_RUN_REVIEW_CHECKPOINT_STATES,
    ACTIVE_FLOW_STEP_RESULT_STATUSES,
    FLOW_RUN_STATUS_CAPABILITIES,
    OPEN_FLOW_STEP_ATTEMPT_STATUSES,
    RECONCILABLE_REVIEW_CHECKPOINT_STATES,
    FlowRunRerunOperationStatus,
    FlowRunReviewCheckpointState,
    FlowStepAttemptStatus,
    FlowStepResultStatus,
)
from eneo.flows.infrastructure.flow_docs_mermaid import (  # noqa: E402
    render_flow_docs_mermaid_block,
)
from eneo.flows.infrastructure.flow_docs_related_cards import (  # noqa: E402
    FLOW_DOCS_RELATED_NEXTRA_CARDS_IMPORT,
    FlowDocsRelatedNextraCard,
    render_flow_docs_related_nextra_cards,
)

FLOW_DEVELOPER_LIFECYCLE_DOCS_OUTPUT_PATH = (
    REPO_ROOT
    / "frontend"
    / "apps"
    / "docs-site"
    / "src"
    / "content"
    / "docs"
    / "flows-for-developers"
    / "run-lifecycle.mdx"
)


@dataclass(frozen=True, slots=True)
class SourceModule:
    label: str
    path: str
    owns: str


@dataclass(frozen=True, slots=True)
class GoldenPath:
    title: str
    diagram: str
    owner_notes: tuple[str, ...]


SOURCE_MODULES: tuple[SourceModule, ...] = (
    SourceModule(
        label="Run status vocabulary",
        path="backend/src/eneo/flows/enums.py",
        owns="run statuses, step statuses, status capabilities, review checkpoint states, and rerun operation states",
    ),
    SourceModule(
        label="Run router aggregate",
        path="backend/src/eneo/flows/api/flow_run_router.py",
        owns="feature-router registration for lifecycle, review, rerun, steps, and evidence",
    ),
    SourceModule(
        label="Run lifecycle API adapter",
        path="backend/src/eneo/flows/api/flow_run_lifecycle_router.py",
        owns="status capabilities, create, list, get, cancel, and redispatch HTTP adaptation",
    ),
    SourceModule(
        label="Run review API adapter",
        path="backend/src/eneo/flows/api/flow_run_review_router.py",
        owns="active, edit, approve, reject, and resume review checkpoint HTTP adaptation",
    ),
    SourceModule(
        label="Run rerun API adapter",
        path="backend/src/eneo/flows/api/flow_run_rerun_router.py",
        owns="step-rerun HTTP adaptation and dispatch scheduling",
    ),
    SourceModule(
        label="Run service",
        path="backend/src/eneo/flows/application/flow_run_service.py",
        owns="run creation, input normalization, and relational runtime-file binding",
    ),
    SourceModule(
        label="Dispatch coordinator",
        path="backend/src/eneo/flows/application/flow_dispatch.py",
        owns="due-attempt claim orchestration, broker send, and durable acceptance or failure recording",
    ),
    SourceModule(
        label="Dispatch recovery policy",
        path="backend/src/eneo/flows/domain/flow_run_recovery_policy.py",
        owns="bounded dispatch attempts, retry delays, and stale-running thresholds",
    ),
    SourceModule(
        label="Run repository",
        path="backend/src/eneo/flows/infrastructure/flow_run_repo.py",
        owns="dispatch compare-and-set, queued-to-running claim, parent-first step mutation locks, active step-result closure, and open-attempt closure",
    ),
    SourceModule(
        label="Runtime task",
        path="backend/src/eneo/flows/runtime/tasks.py",
        owns="worker entrypoint, actor resolution, tracing, executor construction, and stale-run task orchestration",
    ),
    SourceModule(
        label="Runtime health",
        path="backend/src/eneo/flows/runtime/flow_runtime_health.py",
        owns="dispatch backlog and stale-running health classification without lifecycle writes",
    ),
    SourceModule(
        label="Executor",
        path="backend/src/eneo/flows/runtime/executor.py",
        owns="step claim, step execution, review pause, rerun attempt linking, and finalization handoff",
    ),
    SourceModule(
        label="Terminalizer",
        path="backend/src/eneo/flows/application/flow_run_terminalization.py",
        owns="terminal run status writes, run error writes, active checkpoint cancellation, and active rerun closure",
    ),
    SourceModule(
        label="Run outcome",
        path="backend/src/eneo/flows/runtime/run_outcome.py",
        owns="final run outcome selection from current step results",
    ),
    SourceModule(
        label="Review checkpoint repository",
        path="backend/src/eneo/flows/infrastructure/flow_run_review_checkpoint_repo.py",
        owns="review checkpoint persistence, state transitions, and run await/resume transitions",
    ),
    SourceModule(
        label="Review checkpoint service",
        path="backend/src/eneo/flows/application/flow_run_review_checkpoint_service.py",
        owns="review API use cases and domain-error to API-error translation",
    ),
    SourceModule(
        label="Review expiry reconciler",
        path="backend/src/eneo/flows/application/flow_review_expiry_reconciliation.py",
        owns="expired review checkpoint reconciliation and run cancellation handoff",
    ),
    SourceModule(
        label="Rerun service",
        path="backend/src/eneo/flows/application/flow_run_rerun_service.py",
        owns="rerun request normalization, validation, fingerprinting, and command creation",
    ),
    SourceModule(
        label="Rerun graph",
        path="backend/src/eneo/flows/flow_run_rerun_graph.py",
        owns="downstream invalidation graph construction",
    ),
    SourceModule(
        label="Rerun repository",
        path="backend/src/eneo/flows/infrastructure/flow_run_rerun_repo.py",
        owns="rerun operation persistence, invalidated-step rows, input overrides, and run reset to queued",
    ),
    SourceModule(
        label="Step input validation",
        path="backend/src/eneo/flows/flow_run_step_inputs.py",
        owns="runtime step input normalization, upload access validation, and binding locks",
    ),
    SourceModule(
        label="Runtime file service",
        path="backend/src/eneo/flows/flow_runtime_file_service.py",
        owns="runtime upload validation and reusable upload registration",
    ),
    SourceModule(
        label="Runtime upload repository",
        path="backend/src/eneo/flows/flow_runtime_upload_repo.py",
        owns="runtime upload owner, tenant, flow, and step binding checks",
    ),
    SourceModule(
        label="Step input file rows",
        path="backend/src/eneo/flows/infrastructure/flow_run_step_input_file_rows.py",
        owns="relational run step-input file row construction and insertion",
    ),
)

STEP_RESULT_STATUS_NOTES: dict[FlowStepResultStatus, str] = {
    FlowStepResultStatus.PENDING: "preseeded result waiting for its upstream inputs",
    FlowStepResultStatus.RUNNING: "executor claimed the step and is dispatching the handler",
    FlowStepResultStatus.COMPLETED: "handler output and result files were persisted for an attempt",
    FlowStepResultStatus.FAILED: "typed or generic step failure was persisted and the run failed",
    FlowStepResultStatus.CANCELLED: "run cancellation or terminalization closed an active result",
}

STEP_ATTEMPT_STATUS_NOTES: dict[FlowStepAttemptStatus, str] = {
    FlowStepAttemptStatus.STARTED: "attempt row was opened before handler dispatch",
    FlowStepAttemptStatus.FAILED: "attempt finished with a typed or generic error",
    FlowStepAttemptStatus.COMPLETED: "attempt finished with persisted output",
    FlowStepAttemptStatus.CANCELLED: "attempt was closed because the run was cancelled",
}

REVIEW_CHECKPOINT_STATE_NOTES: dict[FlowRunReviewCheckpointState, str] = {
    FlowRunReviewCheckpointState.AWAITING_REVIEW: "newly opened checkpoint; review UI can edit, approve, or reject",
    FlowRunReviewCheckpointState.EDITED: "reviewer changed the proposed step output before deciding",
    FlowRunReviewCheckpointState.APPROVED: "checkpoint can be resumed with an idempotency key",
    FlowRunReviewCheckpointState.REJECTED: "terminal checkpoint decision; run is cancelled with `flow_review_rejected`",
    FlowRunReviewCheckpointState.RESUMED: "decision replay is idempotent and the run has moved back to queued",
    FlowRunReviewCheckpointState.CANCELLED: "terminal checkpoint state after run terminalization or cancellation",
    FlowRunReviewCheckpointState.EXPIRED: "terminal checkpoint state written by `FlowReviewExpiryReconciler`",
}

RERUN_OPERATION_STATUS_NOTES: dict[FlowRunRerunOperationStatus, str] = {
    FlowRunRerunOperationStatus.QUEUED: "accepted operation waiting for the worker to execute the root invalidated step",
    FlowRunRerunOperationStatus.RUNNING: "root rerun attempt started and downstream invalidated steps are being rebuilt",
    FlowRunRerunOperationStatus.COMPLETED: "run terminalized successfully while the rerun operation was active",
    FlowRunRerunOperationStatus.FAILED: "run terminalized failed while the rerun operation was active",
    FlowRunRerunOperationStatus.CANCELLED: "run terminalized cancelled while the rerun operation was active",
}


def render_flow_developer_lifecycle_docs_page() -> str:
    _require_complete_state_notes()
    parts = [
        FLOW_DOCS_RELATED_NEXTRA_CARDS_IMPORT,
        "",
        "# The run lifecycle",
        "",
        "Use this page when a run pauses, reruns, fails, or needs a new status. It shows which module owns each transition before you edit code.",
        "",
        "## State map",
        "",
        _render_state_diagram(),
        "",
        "## Run status capabilities",
        "",
        _render_run_status_capabilities_table(),
        "",
        "### Run capability meanings",
        "",
        _render_run_status_capability_meanings_table(),
        "",
        "## Step result states",
        "",
        _render_step_result_state_table(),
        "",
        "## Step attempt states",
        "",
        _render_step_attempt_state_table(),
        "",
        "## Step failure and runtime file binding",
        "",
        _render_step_failure_and_upload_binding(),
        "",
        "## Review checkpoint states",
        "",
        "`Open` means a checkpoint can still receive a decision, be resumed, or be reconciled by expiry.",
        "",
        _render_review_checkpoint_state_table(),
        "",
        "## Rerun operation states",
        "",
        _render_rerun_operation_state_table(),
        "",
        "## Golden paths",
        "",
        *_render_golden_paths(),
        "## Source guards",
        "",
        _render_source_guard_table(),
        "",
        "## Related",
        "",
        render_flow_docs_related_nextra_cards(
            (
                FlowDocsRelatedNextraCard(
                    "Key decisions",
                    "/docs/flows-for-developers/key-decisions",
                ),
                FlowDocsRelatedNextraCard(
                    "When things fail",
                    "/docs/flows-for-developers/when-things-fail",
                ),
            )
        ),
        "",
    ]
    return "\n".join(parts)


def write_flow_developer_lifecycle_docs_page(
    output_path: Path = FLOW_DEVELOPER_LIFECYCLE_DOCS_OUTPUT_PATH,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        render_flow_developer_lifecycle_docs_page(),
        encoding="utf-8",
    )


def _require_complete_state_notes() -> None:
    missing_step_result_statuses = set(FlowStepResultStatus) - set(
        STEP_RESULT_STATUS_NOTES
    )
    missing_step_attempt_statuses = set(FlowStepAttemptStatus) - set(
        STEP_ATTEMPT_STATUS_NOTES
    )
    missing_review_states = set(FlowRunReviewCheckpointState) - set(
        REVIEW_CHECKPOINT_STATE_NOTES
    )
    missing_rerun_statuses = set(FlowRunRerunOperationStatus) - set(
        RERUN_OPERATION_STATUS_NOTES
    )
    if (
        missing_step_result_statuses
        or missing_step_attempt_statuses
        or missing_review_states
        or missing_rerun_statuses
    ):
        raise ValueError(
            "Lifecycle docs notes are incomplete. "
            f"Missing step result statuses: {sorted(item.value for item in missing_step_result_statuses)}; "
            f"missing step attempt statuses: {sorted(item.value for item in missing_step_attempt_statuses)}; "
            f"Missing review states: {sorted(item.value for item in missing_review_states)}; "
            f"missing rerun statuses: {sorted(item.value for item in missing_rerun_statuses)}"
        )


def _render_state_diagram() -> str:
    return render_flow_docs_mermaid_block(
        "stateDiagram-v2",
        '  state "FlowRunStatus" as RunStatus {',
        "    [*] --> queued",
        "    queued --> running: worker starts",
        "    running --> awaiting_review: checkpoint opens",
        "    awaiting_review --> queued: approved checkpoint resumes",
        "    running --> completed: all steps complete",
        "    running --> failed: step or runtime failure",
        "    queued --> cancelled: user cancel or deleted flow",
        "    running --> cancelled: user cancel or deleted flow",
        "    awaiting_review --> cancelled: review rejected",
        "    awaiting_review --> cancelled: review expired",
        "    awaiting_review --> cancelled: user cancel or deleted flow",
        "    completed --> queued: rerun accepted",
        "    failed --> queued: rerun accepted",
        "  }",
        '  state "FlowRunReviewCheckpointState" as ReviewState {',
        "    [*] --> awaiting_review",
        "    awaiting_review --> edited: edit output",
        "    edited --> edited: edit again",
        "    awaiting_review --> approved: approve",
        "    edited --> approved: approve",
        "    approved --> resumed: resume",
        "    awaiting_review --> rejected: reject",
        "    edited --> rejected: reject",
        "    awaiting_review --> expired: expiry reconciler",
        "    edited --> expired: expiry reconciler",
        "    awaiting_review --> cancelled: run terminalized",
        "    edited --> cancelled: run terminalized",
        "    approved --> cancelled: run terminalized before resume",
        "  }",
        '  state "FlowRunRerunOperationStatus" as RerunState {',
        "    [*] --> queued",
        "    queued --> running: root attempt starts",
        "    queued --> completed: run terminalizes",
        "    running --> completed: run terminalizes",
        "    queued --> failed: run terminalizes",
        "    running --> failed: run terminalizes",
        "    queued --> cancelled: run terminalizes",
        "    running --> cancelled: run terminalizes",
        "  }",
    )


def _render_run_status_capabilities_table() -> str:
    rows = [
        (
            f"`{capability.status.value}`",
            _bool_text(capability.is_active),
            _bool_text(capability.should_poll),
            _bool_text(capability.is_terminal),
            _bool_text(capability.is_cancellable),
            _bool_text(capability.is_awaiting_review),
            _bool_text(capability.can_request_redispatch),
            _bool_text(capability.is_rerun_eligible),
        )
        for capability in FLOW_RUN_STATUS_CAPABILITIES.values()
    ]
    return _render_markdown_table(
        (
            "Status",
            "Active",
            "Poll",
            "Terminal",
            "Cancellable",
            "Awaiting review",
            "Redispatch",
            "Rerun eligible",
        ),
        rows,
    )


def _render_run_status_capability_meanings_table() -> str:
    return _render_markdown_table(
        ("Capability", "Meaning"),
        [
            (
                "`Active`",
                "run occupies active execution capacity while queued or running",
            ),
            ("`Poll`", "API consumers should keep polling for user-visible progress"),
            ("`Terminal`", "runtime execution is over for this run state"),
            ("`Cancellable`", "the cancel path may still transition the run"),
            (
                "`Awaiting review`",
                "the active review-checkpoint API is the next user action",
            ),
            (
                "`Redispatch`",
                "stale queued runs may be claimed and dispatched again",
            ),
            (
                "`Rerun eligible`",
                "the rerun API can accept a completed or failed run",
            ),
        ],
    )


def _render_review_checkpoint_state_table() -> str:
    rows = [
        (
            f"`{state.value}`",
            _bool_text(state in ACTIVE_FLOW_RUN_REVIEW_CHECKPOINT_STATES),
            _bool_text(state in RECONCILABLE_REVIEW_CHECKPOINT_STATES),
            _markdown_cell(REVIEW_CHECKPOINT_STATE_NOTES[state]),
        )
        for state in FlowRunReviewCheckpointState
    ]
    return _render_markdown_table(("State", "Open", "Expires", "Meaning"), rows)


def _render_step_result_state_table() -> str:
    rows = [
        (
            f"`{status.value}`",
            _bool_text(status in ACTIVE_FLOW_STEP_RESULT_STATUSES),
            _markdown_cell(STEP_RESULT_STATUS_NOTES[status]),
        )
        for status in FlowStepResultStatus
    ]
    return _render_markdown_table(("Status", "Active", "Meaning"), rows)


def _render_step_attempt_state_table() -> str:
    rows = [
        (
            f"`{status.value}`",
            _bool_text(status in OPEN_FLOW_STEP_ATTEMPT_STATUSES),
            _markdown_cell(STEP_ATTEMPT_STATUS_NOTES[status]),
        )
        for status in FlowStepAttemptStatus
    ]
    return _render_markdown_table(("Status", "Open", "Meaning"), rows)


def _render_rerun_operation_state_table() -> str:
    active_states = {
        FlowRunRerunOperationStatus.QUEUED,
        FlowRunRerunOperationStatus.RUNNING,
    }
    rows = [
        (
            f"`{status.value}`",
            _bool_text(status in active_states),
            _markdown_cell(RERUN_OPERATION_STATUS_NOTES[status]),
        )
        for status in FlowRunRerunOperationStatus
    ]
    return _render_markdown_table(("Status", "Active", "Meaning"), rows)


def _render_step_failure_and_upload_binding() -> str:
    return "\n".join(
        [
            "### Step failure",
            "",
            render_flow_docs_mermaid_block(
                "stateDiagram-v2",
                '  state "FlowStepResultStatus" as StepResult {',
                "    [*] --> pending",
                "    pending --> running: executor claims step",
                "    running --> completed: handler output persisted",
                "    running --> failed: typed or generic failure",
                "    running --> cancelled: run cancellation",
                "    pending --> failed: failed run terminalization",
                "    pending --> cancelled: cancelled run terminalization",
                "  }",
                '  state "FlowStepAttemptStatus" as StepAttempt {',
                "    [*] --> started",
                "    started --> completed: output persisted",
                "    started --> failed: typed or generic failure",
                "    started --> cancelled: run cancellation",
                "  }",
            ),
            "",
            "- `backend/src/eneo/flows/runtime/executor.py` claims the step result, opens a step attempt, dispatches the handler, and handles typed or generic failures.",
            "- Typed failures go through `_handle_typed_step_failure`; generic exceptions go through `_handle_generic_step_failure`.",
            "- Both failure paths finish the open attempt, save a failed step result, and call `FlowRunTerminalizer` with a run error code.",
            "- Downstream steps do not continue after a failed step because terminalization moves the run to `failed`.",
            "- When the run fails, the terminalizer closes active `pending` or `running` step results and open attempts as failed; when the run is cancelled, it closes them as cancelled. Completed results stay unchanged.",
            "- `FlowRunRepository` locks the parent run before claiming a step result or opening an attempt, then rechecks that the run is still `queued` or `running`. Terminalization and child mutation therefore share parent-before-child lock order, and a losing child writer cannot recreate active work.",
            "- Attempt-start failures have no attempt number, so the executor saves the failed result with `attempt_no=None` and terminalizes the run.",
            "",
            "### Runtime upload binding",
            "",
            render_flow_docs_mermaid_block(
                "sequenceDiagram",
                '  participant UploadAPI as "Runtime upload API"',
                '  participant FileService as "FlowRuntimeFileService"',
                '  participant UploadRepo as "FlowRuntimeUploadRepository"',
                '  participant RunService as "FlowRunService"',
                '  participant StepInputs as "flow_run_step_inputs.py"',
                '  participant Rows as "flow_run_step_input_file_rows.py"',
                "  UploadAPI->>FileService: upload file for published step",
                "  FileService->>UploadRepo: create flow_runtime_uploaded_files row",
                "  RunService->>StepInputs: validate step_inputs[step_id].file_ids",
                "  StepInputs->>UploadRepo: list_bound_file_ids_for_owner(lock_for_binding=True)",
                "  RunService->>Rows: insert flow_run_step_input_files for attempt 1",
            ),
            "",
            "- `FlowRuntimeFileService` validates upload MIME type and size for a published runtime step before the file can be reused in a run.",
            "- `FlowRuntimeUploadRepository` writes `flow_runtime_uploaded_files` with the flow, tenant, step, and principal owner.",
            "- Run creation accepts `step_inputs[step_id].file_ids`; `flow_run_step_inputs.py` checks file access, limits, and existing upload binding.",
            "- Binding validation calls `list_bound_file_ids_for_owner(..., lock_for_binding=True)` before relational `flow_run_step_input_files` rows are inserted.",
            "- Reruns copy or replace `flow_run_step_input_files` rows for rerun attempts; there is no JSON step-input branch.",
        ]
    )


def _render_golden_paths() -> list[str]:
    parts: list[str] = []
    for path in _golden_paths():
        parts.extend(
            [
                f"### {path.title}",
                "",
                path.diagram,
                "",
                _render_owner_notes(path.owner_notes),
                "",
            ]
        )
    return parts


def _golden_paths() -> tuple[GoldenPath, ...]:
    return (
        GoldenPath(
            title="Create and execute a run",
            diagram=render_flow_docs_mermaid_block(
                "sequenceDiagram",
                '  participant API as "Run API"',
                '  participant Service as "FlowRunService"',
                '  participant Dispatch as "Flow dispatch coordinator"',
                '  participant Worker as "flows.execute task"',
                '  participant Executor as "FlowRunExecutor"',
                '  participant Terminalizer as "FlowRunTerminalizer"',
                "  API->>Service: create run as queued",
                "  API->>Dispatch: dispatch queued epoch after commit",
                "  Dispatch->>Worker: publish revisioned task",
                "  Worker->>Executor: execute run",
                "  Executor->>Terminalizer: terminalize completed, failed, or cancelled",
            ),
            owner_notes=(
                "`backend/src/eneo/flows/api/flow_run_lifecycle_router.py` parses the create request and schedules dispatch after commit.",
                "`backend/src/eneo/flows/application/flow_run_service.py` creates the run and binds validated runtime inputs.",
                "`backend/src/eneo/flows/application/flow_dispatch.py` owns due-attempt claim, broker send, and durable acceptance or failure recording. Broker delivery remains at-least-once: the bounded recovery clock stays armed until the repository's status-and-revision compare-and-set claims the run, so duplicate deliveries are harmless.",
                "`backend/src/eneo/flows/runtime/tasks.py` resolves the runtime actor and constructs the executor.",
                "`backend/src/eneo/flows/infrastructure/flow_run_repo.py` writes queued to running through `mark_running_if_claimable`.",
                "`backend/src/eneo/flows/runtime/executor.py` runs steps and hands terminal outcomes to the terminalizer.",
                "`backend/src/eneo/flows/application/flow_run_terminalization.py` writes terminal run state.",
            ),
        ),
        GoldenPath(
            title="Step execution and handler dispatch",
            diagram=render_flow_docs_mermaid_block(
                "sequenceDiagram",
                '  participant Executor as "FlowRunExecutor"',
                '  participant Repo as "FlowRunRepository"',
                '  participant Runtime as "StepExecutionRuntime"',
                '  participant Outcome as "run_outcome.py"',
                "  Executor->>Repo: claim step result",
                "  Executor->>Runtime: execute typed step handler",
                "  Runtime-->>Executor: output or typed failure",
                "  Executor->>Repo: persist step result and attempt",
                "  Executor->>Outcome: finalize when no active step remains",
            ),
            owner_notes=(
                "`backend/src/eneo/flows/runtime/executor.py` owns the step loop and failure handling.",
                "`backend/src/eneo/flows/infrastructure/flow_run_repo.py` serializes step claims and attempt starts against terminalization by locking and revalidating the parent run before child mutation.",
                "`backend/src/eneo/flows/runtime/step_execution_runtime.py` owns handler dispatch.",
                "`backend/src/eneo/flows/runtime/run_outcome.py` chooses the terminal run outcome from step results.",
            ),
        ),
        GoldenPath(
            title="Review checkpoint pause, decision, and resume",
            diagram=render_flow_docs_mermaid_block(
                "sequenceDiagram",
                '  participant Executor as "FlowRunExecutor"',
                '  participant Repo as "ReviewCheckpointRepository"',
                '  participant API as "Review API"',
                '  participant Terminalizer as "FlowRunTerminalizer"',
                '  participant Dispatch as "Flow dispatch coordinator"',
                '  participant Worker as "flows.execute task"',
                "  Executor->>Repo: open checkpoint for completed reviewed step",
                "  Repo-->>Executor: run becomes awaiting_review",
                "  API->>Repo: edit and approve checkpoint",
                "  API->>Repo: resume approved checkpoint with idempotency key",
                "  Repo-->>API: run is queued",
                "  API->>Dispatch: dispatch resumed queued epoch after commit",
                "  Dispatch->>Worker: publish revisioned task",
                "  API->>Repo: reject active checkpoint",
                "  API->>Terminalizer: terminalize run as cancelled with flow_review_rejected",
            ),
            owner_notes=(
                "`backend/src/eneo/flows/runtime/executor.py` requests checkpoint opening after a reviewed step completes.",
                "`backend/src/eneo/flows/infrastructure/flow_run_review_checkpoint_repo.py` writes checkpoint states and run await/resume transitions.",
                "`backend/src/eneo/flows/application/flow_run_review_checkpoint_service.py` validates review API use cases.",
                "`backend/src/eneo/flows/application/flow_dispatch.py` owns the resumed queue epoch's bounded dispatch lifecycle.",
                "`backend/src/eneo/flows/runtime/tasks.py` executes the queued run after resume dispatch.",
                "`backend/src/eneo/flows/application/flow_review_expiry_reconciliation.py` expires active checkpoints and cancels the run through the terminalizer; `runtime/tasks.py` owns the `flows.reconcile_review_expiry` task.",
            ),
        ),
        GoldenPath(
            title="Rerun with invalidation",
            diagram=render_flow_docs_mermaid_block(
                "sequenceDiagram",
                '  participant API as "Rerun API"',
                '  participant Service as "FlowRunRerunService"',
                '  participant Graph as "Rerun graph"',
                '  participant Repo as "FlowRunRerunRepository"',
                '  participant Dispatch as "Flow dispatch coordinator"',
                '  participant Worker as "flows.execute task"',
                '  participant Executor as "FlowRunExecutor"',
                "  API->>Service: request rerun for one completed step",
                "  Service->>Graph: collect downstream invalidated steps",
                "  Service->>Repo: accept or replay operation",
                "  Repo-->>API: run reset to queued with invalidation rows",
                "  API->>Dispatch: dispatch rerun queue epoch after commit",
                "  Dispatch->>Worker: publish revisioned task when operation is new",
                "  Executor->>Repo: link new attempts as invalidated steps rerun",
            ),
            owner_notes=(
                "`backend/src/eneo/flows/application/flow_run_rerun_service.py` normalizes request payloads and fingerprinting.",
                "`backend/src/eneo/flows/flow_run_rerun_graph.py` owns downstream invalidation graph construction.",
                "`backend/src/eneo/flows/infrastructure/flow_run_rerun_repo.py` persists rerun operations and resets the run to queued.",
                "`backend/src/eneo/flows/application/flow_dispatch.py` owns the rerun queue epoch's bounded dispatch lifecycle.",
                "`backend/src/eneo/flows/runtime/executor.py` links rerun invalidated steps to new attempts.",
            ),
        ),
    )


def _render_owner_notes(notes: tuple[str, ...]) -> str:
    return "\n".join(f"- {note}" for note in notes)


def _render_source_guard_table() -> str:
    rows = [
        (
            f"`{module.path}`",
            _markdown_cell(f"{module.label}: {module.owns}."),
        )
        for module in SOURCE_MODULES
    ]
    rows.append(
        (
            "`backend/tests/unittests/flows/test_flow_docs_site_contract.py`",
            "Committed lifecycle page parity, enum coverage, and source-reference drift guard.",
        )
    )
    return _render_markdown_table(("Source", "Guarded lifecycle role"), rows)


def _render_markdown_table(
    headers: tuple[str, ...],
    rows: list[tuple[str, ...]],
) -> str:
    widths = [
        max(len(row[column_index]) for row in (headers, *rows))
        for column_index in range(len(headers))
    ]

    def render_row(cells: tuple[str, ...]) -> str:
        padded_cells = [
            cell.ljust(widths[column_index]) for column_index, cell in enumerate(cells)
        ]
        return f"| {' | '.join(padded_cells)} |"

    separator = tuple("-" * max(3, width) for width in widths)
    return "\n".join(
        [render_row(headers), render_row(separator), *map(render_row, rows)]
    )


def _bool_text(value: bool) -> str:
    return "yes" if value else "no"


def _markdown_cell(value: str) -> str:
    return " ".join(value.split()).replace("|", "\\|")
