from __future__ import annotations

import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_SRC = REPO_ROOT / "backend" / "src"
if str(BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC))

from eneo.flows.application.flow_run_lifecycle_events import (  # noqa: E402
    FLOW_RUN_LIFECYCLE_EVENT_NAME,
    FLOW_RUN_LIFECYCLE_LOG_MESSAGE,
    FLOW_RUN_TERMINALIZATION_OPERATION,
)
from eneo.flows.infrastructure.flow_docs_mermaid import (  # noqa: E402
    render_flow_docs_mermaid_block,
)
from eneo.flows.infrastructure.flow_docs_related_cards import (  # noqa: E402
    FlowDocsRelatedNextraCard,
    render_flow_docs_related_nextra_cards,
)
from eneo.flows.runtime.flow_runtime_trace import (  # noqa: E402
    FLOW_RUN_EXECUTE_SPAN_NAME,
    FLOW_RUN_SPAN_ATTRIBUTE_KEYS,
    FLOW_STEP_EXECUTE_SPAN_NAME,
    FLOW_STEP_SPAN_ATTRIBUTE_KEYS,
)

FLOW_DEVELOPER_REVIEWER_GUIDE_DOCS_OUTPUT_PATH = (
    REPO_ROOT
    / "frontend"
    / "apps"
    / "docs-site"
    / "src"
    / "content"
    / "docs"
    / "flows-for-developers"
    / "reviewing-flows-code.mdx"
)

REVIEWER_CHECKLIST_TOPIC_SLUGS = (
    "single-owner",
    "typed-errors",
    "tenant-principal-scope",
    "behavior-tests",
    "no-legacy",
    "docs-parity",
    "api-consumer",
    "observability",
)
REVIEWER_ROUTE_SLUGS = (
    "api-router",
    "runtime-executor",
    "step-handler",
    "runtime-file-upload",
    "schema-migration",
    "error-code",
    "review-checkpoint",
    "docs",
)
REVIEWER_VALIDATION_COMMAND_SLUGS = (
    "docs-regen",
    "docs-contract",
    "ruff",
    "pyright",
    "docs-prettier",
    "targeted-pytest",
    "import-boundary",
)
REVIEWER_DEBUG_RUNBOOK_STEP_SLUGS = (
    "start-from-run-contract",
    "queued-without-worker-span",
    "run-span-correlation",
    "step-span-correlation",
    "terminalization-event",
    "persisted-state-owner",
    "consumer-facing-error",
)

_MAX_FIELD_LENGTH = 210
_SENTENCE_END_PATTERN = re.compile(r"[.!?]")
_PATH_PREFIXES = ("backend/", "docs/", "frontend/")
_FLOW_SIGNAL_TRUTH: Final[frozenset[str]] = frozenset(
    {
        FLOW_RUN_EXECUTE_SPAN_NAME,
        FLOW_STEP_EXECUTE_SPAN_NAME,
        *FLOW_RUN_SPAN_ATTRIBUTE_KEYS,
        *FLOW_STEP_SPAN_ATTRIBUTE_KEYS,
    }
)
_ALLOWED_DEBUG_SIGNALS: Final[frozenset[str]] = frozenset(
    {
        *_FLOW_SIGNAL_TRUTH,
        FLOW_RUN_LIFECYCLE_EVENT_NAME,
        FLOW_RUN_LIFECYCLE_LOG_MESSAGE,
        FLOW_RUN_TERMINALIZATION_OPERATION,
        "FlowRunPublic.id",
        "FlowRunPublic.status",
        "FlowRunPublic.trace_id",
        "FlowRunPublic.revision",
        "FlowRunStatus",
        "FlowStepResultStatus",
        "FlowRunReviewCheckpointState",
        "FlowRunRerunOperationStatus",
        "can_request_redispatch",
        "flow_dispatch_failed",
        "flow_worker_stalled",
        "flow_task_failure",
        "flow_step_execution_failed",
        "redispatched_count",
        "run.error.code",
        "steps_requiring_review",
        "trace_id",
        "error_code",
        "audit_outbox_id",
    }
)

ReviewGuideWorkdir = Literal["backend", "frontend", "repo root"]


@dataclass(frozen=True, slots=True)
class ReviewerGuideSourceRef:
    label: str
    path: str


@dataclass(frozen=True, slots=True)
class ReviewerChecklistTopic:
    slug: str
    title: str
    check: str
    reject: str
    source_refs: tuple[ReviewerGuideSourceRef, ...]


@dataclass(frozen=True, slots=True)
class ProcedureStep:
    title: str
    body: str


@dataclass(frozen=True, slots=True)
class ReviewerRoute:
    slug: str
    change_type: str
    start_here: str
    proof: str
    source_refs: tuple[ReviewerGuideSourceRef, ...]
    procedure_title: str | None = None
    procedure_steps: tuple[ProcedureStep, ...] = ()


@dataclass(frozen=True, slots=True)
class ReviewerValidationCommand:
    slug: str
    label: str
    command: str
    workdir: ReviewGuideWorkdir
    when_to_run: str
    referenced_paths: tuple[str, ...]
    requires_path_arguments: bool = True


@dataclass(frozen=True, slots=True)
class ReviewerDebugRunbookStep:
    slug: str
    inspect: str
    signals: tuple[str, ...]
    next_action: str
    source_refs: tuple[ReviewerGuideSourceRef, ...]


def _source(label: str, path: str) -> ReviewerGuideSourceRef:
    return ReviewerGuideSourceRef(label=label, path=path)


def _topic(
    slug: str,
    title: str,
    check: str,
    reject: str,
    source_refs: tuple[ReviewerGuideSourceRef, ...],
) -> ReviewerChecklistTopic:
    return ReviewerChecklistTopic(
        slug=slug,
        title=title,
        check=check,
        reject=reject,
        source_refs=source_refs,
    )


def _route(
    slug: str,
    change_type: str,
    start_here: str,
    proof: str,
    source_refs: tuple[ReviewerGuideSourceRef, ...],
    procedure_title: str | None = None,
    procedure_steps: tuple[ProcedureStep, ...] = (),
) -> ReviewerRoute:
    return ReviewerRoute(
        slug=slug,
        change_type=change_type,
        start_here=start_here,
        proof=proof,
        source_refs=source_refs,
        procedure_title=procedure_title,
        procedure_steps=procedure_steps,
    )


def _command(
    slug: str,
    label: str,
    command: str,
    workdir: ReviewGuideWorkdir,
    when_to_run: str,
    referenced_paths: tuple[str, ...],
    requires_path_arguments: bool = True,
) -> ReviewerValidationCommand:
    return ReviewerValidationCommand(
        slug=slug,
        label=label,
        command=command,
        workdir=workdir,
        when_to_run=when_to_run,
        referenced_paths=referenced_paths,
        requires_path_arguments=requires_path_arguments,
    )


def _runbook_step(
    slug: str,
    inspect: str,
    signals: tuple[str, ...],
    next_action: str,
    source_refs: tuple[ReviewerGuideSourceRef, ...],
) -> ReviewerDebugRunbookStep:
    return ReviewerDebugRunbookStep(
        slug=slug,
        inspect=inspect,
        signals=signals,
        next_action=next_action,
        source_refs=source_refs,
    )


REVIEWER_CHECKLIST_TOPICS: tuple[ReviewerChecklistTopic, ...] = (
    _topic(
        slug="single-owner",
        title="Single owner",
        check="Name the module that owns the changed Flow concept.",
        reject="Reject parallel owners, pass-through services, and duplicate state.",
        source_refs=(
            _source(
                "Maintainability standard",
                "docs/engineering/maintainability-standards.md",
            ),
            _source(
                "Layer map",
                "frontend/apps/docs-site/src/content/docs/flows-for-developers/how-built.mdx",
            ),
            _source(
                "Key decisions",
                "frontend/apps/docs-site/src/content/docs/flows-for-developers/key-decisions.mdx",
            ),
        ),
    ),
    _topic(
        slug="typed-errors",
        title="Typed errors",
        check="Translate Flow failures through typed domain or API error codes.",
        reject="Reject public 400s that expose internal invariant text.",
        source_refs=(
            _source("API standard", "docs/engineering/api-design-standard.md"),
            _source(
                "Error-code enum",
                "backend/src/eneo/flows/flow_api_error_code.py",
            ),
            _source(
                "Review exceptions",
                "backend/src/eneo/flows/domain/review_checkpoint_exceptions.py",
            ),
        ),
    ),
    _topic(
        slug="tenant-principal-scope",
        title="Tenant and principal scope",
        check="Tenant filters use tenant_id, and runtime ownership checks use FlowPrincipal plus cross-principal denial tests.",
        reject="Reject synthetic users, tenant-free queries, and tests that skip service-key or cross-principal denial.",
        source_refs=(
            _source("Flow principal", "backend/src/eneo/flows/principal.py"),
            _source(
                "Run access policy",
                "backend/src/eneo/flows/application/flow_run_access_policy.py",
            ),
            _source(
                "Runtime actor",
                "backend/src/eneo/flows/runtime/flow_run_actor.py",
            ),
        ),
    ),
    _topic(
        slug="behavior-tests",
        title="Behavior tests",
        check="Tests prove user-visible behavior, lifecycle rules, or public contracts.",
        reject="Reject tests that only preserve mocks, wiring, or deleted legacy paths.",
        source_refs=(
            _source("Testing standard", "docs/engineering/testing-standard.md"),
            _source(
                "Docs contract tests",
                "backend/tests/unittests/flows/test_flow_docs_site_contract.py",
            ),
            _source(
                "Runtime worker contract",
                "backend/tests/integration/flows/test_flow_runtime_worker_contract.py",
            ),
        ),
    ),
    _topic(
        slug="no-legacy",
        title="No legacy reintroduction",
        check="Pre-production legacy paths stay deleted unless a current contract requires them.",
        reject="Reject compatibility bridges, dual-read paths, and hidden fallbacks.",
        source_refs=(
            _source(
                "HTTP validator",
                "backend/src/eneo/flows/flow_validators_http.py",
            ),
            _source(
                "HTTP runtime",
                "backend/src/eneo/flows/runtime/http_runtime.py",
            ),
            _source(
                "Key decisions",
                "frontend/apps/docs-site/src/content/docs/flows-for-developers/key-decisions.mdx",
            ),
        ),
    ),
    _topic(
        slug="docs-parity",
        title="Docs parity",
        check="Guarded Flow docs change in the same commit as guarded concepts.",
        reject="Reject docs that can drift from schemas, errors, modules, or lifecycle states.",
        source_refs=(
            _source(
                "Docs contract tests",
                "backend/tests/unittests/flows/test_flow_docs_site_contract.py",
            ),
            _source(
                "Developer docs section",
                "frontend/apps/docs-site/src/content/docs/flows-for-developers/index.mdx",
            ),
        ),
    ),
    _topic(
        slug="api-consumer",
        title="API consumer clarity",
        check="A consumer can see what failed, why, and the next action.",
        reject="Reject vague errors, undocumented response shape changes, and source-only contracts.",
        source_refs=(
            _source(
                "API guide",
                "frontend/apps/docs-site/src/content/guides/flows-api-guide.mdx",
            ),
            _source(
                "Failure taxonomy",
                "frontend/apps/docs-site/src/content/docs/flows-for-developers/when-things-fail.mdx",
            ),
            _source(
                "Error taxonomy",
                "backend/src/eneo/flows/flow_error_taxonomy.py",
            ),
        ),
    ),
    _topic(
        slug="observability",
        title="Observability",
        check="Runtime changes preserve low-cardinality spans and run-step correlation.",
        reject="Reject span names with dynamic IDs and uncorrelated runtime failures.",
        source_refs=(
            _source(
                "Runtime trace helpers",
                "backend/src/eneo/flows/runtime/flow_runtime_trace.py",
            ),
            _source(
                "Lifecycle events",
                "backend/src/eneo/flows/application/flow_run_lifecycle_events.py",
            ),
            _source(
                "Lifecycle docs",
                "frontend/apps/docs-site/src/content/docs/flows-for-developers/run-lifecycle.mdx",
            ),
        ),
    ),
)


REVIEWER_ROUTES: tuple[ReviewerRoute, ...] = (
    _route(
        slug="api-router",
        change_type="API router or response schema",
        start_here="Start in `api/`, then follow the application service it delegates to.",
        proof="Prove OpenAPI shape, FlowApiErrorCode mapping, and docs parity.",
        source_refs=(
            _source(
                "Run router aggregate",
                "backend/src/eneo/flows/api/flow_run_router.py",
            ),
            _source(
                "Run lifecycle router",
                "backend/src/eneo/flows/api/flow_run_lifecycle_router.py",
            ),
            _source(
                "Run review router",
                "backend/src/eneo/flows/api/flow_run_review_router.py",
            ),
            _source(
                "Run rerun router",
                "backend/src/eneo/flows/api/flow_run_rerun_router.py",
            ),
            _source(
                "API design standard",
                "docs/engineering/api-design-standard.md",
            ),
        ),
    ),
    _route(
        slug="runtime-executor",
        change_type="Runtime executor or worker behavior",
        start_here="Start in `runtime/`, then identify the persisted state owner.",
        proof="Prove idempotency, terminalization, retry behavior, and trace correlation.",
        source_refs=(
            _source("Executor", "backend/src/eneo/flows/runtime/executor.py"),
            _source("Runtime tasks", "backend/src/eneo/flows/runtime/tasks.py"),
            _source(
                "Worker contract tests",
                "backend/tests/integration/flows/test_flow_runtime_worker_contract.py",
            ),
        ),
        procedure_title="Change a run state",
        procedure_steps=(
            ProcedureStep(
                "Update status vocabulary",
                "Start in `backend/src/eneo/flows/enums.py` and update the status vocabulary plus capability mappings together.",
            ),
            ProcedureStep(
                "Change the writer",
                "Change the application or runtime owner that writes the state, such as `backend/src/eneo/flows/application/flow_run_terminalization.py` or `backend/src/eneo/flows/runtime/executor.py`.",
            ),
            ProcedureStep(
                "Use canonical persistence",
                "Update repository writes only through the canonical persistence owner, not ad hoc SQL.",
            ),
            ProcedureStep(
                "Test lifecycle behavior",
                "Add lifecycle behavior tests, then run `make docs:regen` and the Flow docs contract test.",
            ),
        ),
    ),
    _route(
        slug="step-handler",
        change_type="Step handler or output mode",
        start_here="Start runtime handler construction at `FlowRunExecutor._build_step_handler` and keep concrete behavior in `runtime/step_handlers/`",
        proof="Prove parser validation, handler or output-processing behavior, and typed errors.",
        source_refs=(
            _source(
                "Handler construction",
                "backend/src/eneo/flows/runtime/executor.py",
            ),
            _source(
                "Handler contract",
                "backend/src/eneo/flows/runtime/step_handlers/base.py",
            ),
            _source("Output modes", "backend/src/eneo/flows/output_modes.py"),
            _source(
                "Output processing",
                "backend/src/eneo/flows/output_processing.py",
            ),
            _source(
                "Step definition parser",
                "backend/src/eneo/flows/runtime/step_definition_parser.py",
            ),
        ),
        procedure_title="Add a step capability",
        procedure_steps=(
            ProcedureStep(
                "Define capability shape",
                "Start in `backend/src/eneo/flows/flow_capability_manifest.py` and define the supported input, output, and artifact shape.",
            ),
            ProcedureStep(
                "Add runtime support",
                "Update executor handler construction when the capability needs a runtime handler; keep behavior in `runtime/step_handlers/`.",
            ),
            ProcedureStep(
                "Update parsing and output",
                "Update parser or output ownership in `backend/src/eneo/flows/runtime/step_definition_parser.py`, `backend/src/eneo/flows/output_modes.py`, or `backend/src/eneo/flows/output_processing.py`.",
            ),
            ProcedureStep(
                "Test and regenerate docs",
                "Add behavior tests for the capability and run `make docs:regen` plus the Flow docs contract test.",
            ),
        ),
    ),
    _route(
        slug="runtime-file-upload",
        change_type="Runtime file or upload binding",
        start_here="Start at `FlowRuntimeFileService`, then follow `step_inputs` validation and row inserts.",
        proof="Prove tenant/principal ownership, `lock_for_binding`, delete behavior, and run/rerun step-input rows.",
        source_refs=(
            _source(
                "Runtime file service",
                "backend/src/eneo/flows/flow_runtime_file_service.py",
            ),
            _source(
                "Runtime upload repository",
                "backend/src/eneo/flows/flow_runtime_upload_repo.py",
            ),
            _source(
                "Step input validation",
                "backend/src/eneo/flows/flow_run_step_inputs.py",
            ),
            _source(
                "Step input row builder",
                "backend/src/eneo/flows/infrastructure/flow_run_step_input_file_rows.py",
            ),
        ),
    ),
    _route(
        slug="schema-migration",
        change_type="Schema, migration, or JSONB boundary",
        start_here="Start at the SQLAlchemy table, then find the typed boundary owner.",
        proof="Prove constraints, tenant scope, JSONB ownership, and generated schema docs.",
        source_refs=(
            _source(
                "Flow tables",
                "backend/src/eneo/database/tables/flow_tables.py",
            ),
            _source(
                "JSONB ownership",
                "backend/src/eneo/flows/infrastructure/flow_jsonb_ownership.py",
            ),
            _source(
                "Data schema docs",
                "frontend/apps/docs-site/src/content/docs/flows-for-developers/data-schema.mdx",
            ),
        ),
        procedure_title="Add a JSONB field",
        procedure_steps=(
            ProcedureStep(
                "Start at the table",
                "Start at the SQLAlchemy column in `backend/src/eneo/database/tables/flow_tables.py` or the table module that owns the row.",
            ),
            ProcedureStep(
                "Register the typed owner",
                "Add the typed owner in `backend/src/eneo/flows/infrastructure/flow_jsonb_ownership.py` with version, corruption behavior, and relational-candidate rationale.",
            ),
            ProcedureStep(
                "Validate at the boundary",
                "Parse and validate the envelope at the application or API boundary that first accepts the value.",
            ),
            ProcedureStep(
                "Test corruption behavior",
                "Add corruption and migration behavior tests, then run `make docs:regen` and the Flow docs contract test.",
            ),
        ),
    ),
    _route(
        slug="error-code",
        change_type="FlowApiErrorCode or failure path",
        start_here="Start at the enum, then follow metadata, translations, and callers.",
        proof="Prove the consumer sees a stable code, localized text, and recovery action.",
        source_refs=(
            _source(
                "Error-code enum",
                "backend/src/eneo/flows/flow_api_error_code.py",
            ),
            _source(
                "Failure taxonomy",
                "backend/src/eneo/flows/flow_error_taxonomy.py",
            ),
            _source(
                "Frontend messages",
                "frontend/apps/web/messages/en.json",
            ),
        ),
        procedure_title="Add an error code",
        procedure_steps=(
            ProcedureStep(
                "Add the public code",
                "Add the public code in `backend/src/eneo/flows/flow_api_error_code.py`.",
            ),
            ProcedureStep(
                "Add recovery metadata",
                "Add metadata and recovery actions in `backend/src/eneo/flows/flow_error_taxonomy.py`.",
            ),
            ProcedureStep(
                "Update localizations",
                "Add or update localization in `frontend/apps/web/messages/en.json` and the matching Swedish message file.",
            ),
            ProcedureStep(
                "Test the failure path",
                "Prove the failure path with a behavior test, then run `make docs:regen` and the Flow docs contract test.",
            ),
        ),
    ),
    _route(
        slug="review-checkpoint",
        change_type="Review checkpoint lifecycle",
        start_here="Start at the checkpoint repository and service, then check run status effects.",
        proof="Prove revision guards, idempotency, resume behavior, and typed exceptions.",
        source_refs=(
            _source(
                "Checkpoint repository",
                "backend/src/eneo/flows/infrastructure/flow_run_review_checkpoint_repo.py",
            ),
            _source(
                "Checkpoint service",
                "backend/src/eneo/flows/application/flow_run_review_checkpoint_service.py",
            ),
            _source(
                "Checkpoint exceptions",
                "backend/src/eneo/flows/domain/review_checkpoint_exceptions.py",
            ),
        ),
    ),
    _route(
        slug="docs",
        change_type="Developer docs or guarded contract",
        start_here="Start at the generator, then inspect the parity test and rendered MDX.",
        proof="Prove the generated page matches source-owned records and still renders.",
        source_refs=(
            _source(
                "Docs contract tests",
                "backend/tests/unittests/flows/test_flow_docs_site_contract.py",
            ),
            _source(
                "Developer docs meta",
                "frontend/apps/docs-site/src/content/docs/flows-for-developers/_meta.ts",
            ),
        ),
    ),
)

FLOW_RUN_SPAN_DEBUG_SIGNALS: Final[tuple[str, ...]] = (
    FLOW_RUN_EXECUTE_SPAN_NAME,
    *tuple(sorted(FLOW_RUN_SPAN_ATTRIBUTE_KEYS)),
)
FLOW_STEP_SPAN_DEBUG_SIGNALS: Final[tuple[str, ...]] = (
    FLOW_STEP_EXECUTE_SPAN_NAME,
    *tuple(sorted(FLOW_STEP_SPAN_ATTRIBUTE_KEYS)),
)

REVIEWER_DEBUG_RUNBOOK_STEPS: tuple[ReviewerDebugRunbookStep, ...] = (
    _runbook_step(
        slug="start-from-run-contract",
        inspect="Start from `FlowRunPublic` in the API response or evidence export.",
        signals=(
            "FlowRunPublic.id",
            "FlowRunPublic.status",
            "FlowRunPublic.trace_id",
            "FlowRunPublic.revision",
        ),
        next_action="Use `trace_id` as the persisted Flow correlation token, not as the OpenTelemetry protocol trace id.",
        source_refs=(
            _source("Run API model", "backend/src/eneo/flows/api/flow_models.py"),
            _source(
                "Evidence export",
                "backend/src/eneo/flows/application/flow_run_export_json.py",
            ),
        ),
    ),
    _runbook_step(
        slug="queued-without-worker-span",
        inspect="If a queued run has no worker span, inspect dispatch and redispatch state first.",
        signals=(
            "can_request_redispatch",
            "flow_dispatch_failed",
            "redispatched_count",
        ),
        next_action="Redispatch only when the status-capability endpoint allows it and repeated dispatch failures are operator alerts.",
        source_refs=(
            _source(
                "Run service",
                "backend/src/eneo/flows/application/flow_run_service.py",
            ),
            _source("Runtime tasks", "backend/src/eneo/flows/runtime/tasks.py"),
            _source(
                "Status capabilities",
                "backend/src/eneo/flows/api/flow_run_status_capability_models.py",
            ),
        ),
    ),
    _runbook_step(
        slug="run-span-correlation",
        inspect="Find the worker-root run span or worker log by run id first, then by persisted trace token when present.",
        signals=FLOW_RUN_SPAN_DEBUG_SIGNALS,
        next_action="If the trace-token attribute is absent, the task failed before loading the run row; continue with the run-id attribute.",
        source_refs=(
            _source(
                "Runtime trace helpers",
                "backend/src/eneo/flows/runtime/flow_runtime_trace.py",
            ),
            _source("Runtime tasks", "backend/src/eneo/flows/runtime/tasks.py"),
            _source(
                "Trace tests",
                "backend/tests/unittests/flows/test_flow_runtime_trace.py",
            ),
        ),
    ),
    _runbook_step(
        slug="step-span-correlation",
        inspect="Inspect step spans when the run span reached execution but a step did not finish.",
        signals=FLOW_STEP_SPAN_DEBUG_SIGNALS,
        next_action="Use step id, order, attempt number, and result status to match the span to persisted step rows.",
        source_refs=(
            _source("Executor", "backend/src/eneo/flows/runtime/executor.py"),
            _source(
                "Executor trace tests",
                "backend/tests/unittests/flows/test_flow_executor_runtime.py",
            ),
        ),
    ),
    _runbook_step(
        slug="terminalization-event",
        inspect="Check terminalization logs only after the run reaches a terminal state.",
        signals=(
            FLOW_RUN_LIFECYCLE_LOG_MESSAGE,
            FLOW_RUN_LIFECYCLE_EVENT_NAME,
            FLOW_RUN_TERMINALIZATION_OPERATION,
            "trace_id",
            "error_code",
            "audit_outbox_id",
        ),
        next_action="Absence of this event means terminalization has not completed or logging dropped the structured extra fields.",
        source_refs=(
            _source(
                "Lifecycle events",
                "backend/src/eneo/flows/application/flow_run_lifecycle_events.py",
            ),
            _source(
                "Lifecycle event tests",
                "backend/tests/unittests/flows/test_flow_run_lifecycle_events.py",
            ),
        ),
    ),
    _runbook_step(
        slug="persisted-state-owner",
        inspect="Compare persisted run, step, review checkpoint, and rerun states before changing recovery code.",
        signals=(
            "FlowRunStatus",
            "FlowStepResultStatus",
            "FlowRunReviewCheckpointState",
            "FlowRunRerunOperationStatus",
            "steps_requiring_review",
        ),
        next_action="Change the module that owns the stale state, then prove terminalization or redispatch behavior with focused tests.",
        source_refs=(
            _source(
                "Run lifecycle docs",
                "frontend/apps/docs-site/src/content/docs/flows-for-developers/run-lifecycle.mdx",
            ),
            _source(
                "Run repository",
                "backend/src/eneo/flows/infrastructure/flow_run_repo.py",
            ),
            _source(
                "Checkpoint repository",
                "backend/src/eneo/flows/infrastructure/flow_run_review_checkpoint_repo.py",
            ),
            _source(
                "Rerun repository",
                "backend/src/eneo/flows/infrastructure/flow_run_rerun_repo.py",
            ),
        ),
    ),
    _runbook_step(
        slug="consumer-facing-error",
        inspect="End the investigation at the public error code and consumer recovery action.",
        signals=(
            "run.error.code",
            "flow_worker_stalled",
            "flow_task_failure",
            "flow_step_execution_failed",
        ),
        next_action="Update error taxonomy, localization, and consumer docs when the public recovery action changes.",
        source_refs=(
            _source(
                "Error taxonomy",
                "backend/src/eneo/flows/flow_error_taxonomy.py",
            ),
            _source(
                "Failure docs",
                "frontend/apps/docs-site/src/content/docs/flows-for-developers/when-things-fail.mdx",
            ),
        ),
    ),
)


REVIEWER_VALIDATION_COMMANDS: tuple[ReviewerValidationCommand, ...] = (
    _command(
        slug="docs-regen",
        label="Flow docs regeneration",
        command="make docs:regen",
        workdir="repo root",
        when_to_run="Run after changing Flow docs generators, source catalogs, schemas, error codes, lifecycle states, or guarded docs.",
        referenced_paths=("backend/scripts/generate_flow_docs.py",),
        requires_path_arguments=False,
    ),
    _command(
        slug="docs-contract",
        label="Developer docs contract",
        command="set -a; source .env.template; set +a; uv run pytest tests/unittests/flows/test_flow_docs_site_contract.py -q",
        workdir="backend",
        when_to_run="Run after changing guarded Flow developer docs, error codes, tables, lifecycle states, or modules.",
        referenced_paths=(
            "backend/tests/unittests/flows/test_flow_docs_site_contract.py",
        ),
    ),
    _command(
        slug="ruff",
        label="Python lint",
        command="uv run ruff check scripts/flow_developer_reviewer_guide_docs.py scripts/generate_flow_developer_reviewer_guide_docs.py tests/unittests/flows/test_flow_docs_site_contract.py",
        workdir="backend",
        when_to_run="Run after changing the reviewer-guide generator or docs contract tests.",
        referenced_paths=(
            "backend/scripts/flow_developer_reviewer_guide_docs.py",
            "backend/scripts/generate_flow_developer_reviewer_guide_docs.py",
            "backend/tests/unittests/flows/test_flow_docs_site_contract.py",
        ),
    ),
    _command(
        slug="pyright",
        label="Python type check",
        command="uv run pyright scripts/flow_developer_reviewer_guide_docs.py scripts/generate_flow_developer_reviewer_guide_docs.py tests/unittests/flows/test_flow_docs_site_contract.py",
        workdir="backend",
        when_to_run="Run after changing typed docs generator records or contract protocols.",
        referenced_paths=(
            "backend/scripts/flow_developer_reviewer_guide_docs.py",
            "backend/scripts/generate_flow_developer_reviewer_guide_docs.py",
            "backend/tests/unittests/flows/test_flow_docs_site_contract.py",
        ),
    ),
    _command(
        slug="docs-prettier",
        label="Docs-site format",
        command="bun prettier --check apps/docs-site/src/content/docs/flows-for-developers/reviewing-flows-code.mdx apps/docs-site/src/content/docs/flows-for-developers/_meta.ts",
        workdir="frontend",
        when_to_run="Run after changing the rendered reviewer guide page or docs-site section metadata.",
        referenced_paths=(
            "frontend/apps/docs-site/src/content/docs/flows-for-developers/reviewing-flows-code.mdx",
            "frontend/apps/docs-site/src/content/docs/flows-for-developers/_meta.ts",
        ),
    ),
    _command(
        slug="targeted-pytest",
        label="Focused Flow tests",
        command="set -a; source .env.template; set +a; uv run pytest tests/unittests/flows/test_flow_docs_site_contract.py tests/unittests/flows/test_flow_package_layout.py -q",
        workdir="backend",
        when_to_run="Run for Flow docs, package layout, module ownership, or boundary changes.",
        referenced_paths=(
            "backend/tests/unittests/flows/test_flow_docs_site_contract.py",
            "backend/tests/unittests/flows/test_flow_package_layout.py",
        ),
    ),
    _command(
        slug="import-boundary",
        label="Import boundary",
        command="uv run lint-imports --no-cache",
        workdir="backend",
        when_to_run="Run after changing Flow package layout or dependencies across the engine and AI Builder boundary.",
        referenced_paths=("backend/.importlinter",),
        requires_path_arguments=False,
    ),
)


def validate_reviewer_guide_catalog(
    topics: Sequence[ReviewerChecklistTopic] | None = None,
    routes: Sequence[ReviewerRoute] | None = None,
    commands: Sequence[ReviewerValidationCommand] | None = None,
    runbook_steps: Sequence[ReviewerDebugRunbookStep] | None = None,
) -> None:
    selected_topics = tuple(REVIEWER_CHECKLIST_TOPICS if topics is None else topics)
    selected_routes = tuple(REVIEWER_ROUTES if routes is None else routes)
    selected_commands = tuple(
        REVIEWER_VALIDATION_COMMANDS if commands is None else commands
    )
    selected_runbook_steps = tuple(
        REVIEWER_DEBUG_RUNBOOK_STEPS if runbook_steps is None else runbook_steps
    )
    _validate_slug_order(
        "review checklist topics",
        tuple(topic.slug for topic in selected_topics),
        REVIEWER_CHECKLIST_TOPIC_SLUGS,
    )
    _validate_slug_order(
        "review routes",
        tuple(route.slug for route in selected_routes),
        REVIEWER_ROUTE_SLUGS,
    )
    _validate_slug_order(
        "review validation commands",
        tuple(command.slug for command in selected_commands),
        REVIEWER_VALIDATION_COMMAND_SLUGS,
    )
    _validate_slug_order(
        "debug runbook steps",
        tuple(step.slug for step in selected_runbook_steps),
        REVIEWER_DEBUG_RUNBOOK_STEP_SLUGS,
    )

    for topic in selected_topics:
        _validate_slug(topic.slug)
        _validate_short_sentence(topic.slug, "check", topic.check)
        _validate_short_sentence(topic.slug, "reject", topic.reject)
        _validate_source_refs(topic.slug, topic.source_refs)

    for route in selected_routes:
        _validate_slug(route.slug)
        _validate_short_sentence(route.slug, "start_here", route.start_here)
        _validate_short_sentence(route.slug, "proof", route.proof)
        _validate_source_refs(route.slug, route.source_refs)
        _validate_route_procedure(route)

    for command in selected_commands:
        _validate_slug(command.slug)
        _validate_short_sentence(command.slug, "when_to_run", command.when_to_run)
        _validate_validation_command(command)

    for step in selected_runbook_steps:
        _validate_slug(step.slug)
        _validate_short_sentence(step.slug, "inspect", step.inspect)
        _validate_short_sentence(step.slug, "next_action", step.next_action)
        _validate_source_refs(step.slug, step.source_refs)
        _validate_runbook_signals(step)
    _validate_runbook_span_attribute_coverage(selected_runbook_steps)


def render_flow_developer_reviewer_guide_docs_page() -> str:
    validate_reviewer_guide_catalog()
    parts = [
        'import { Cards, Steps } from "nextra/components";',
        "",
        "# Reviewing Flows code",
        "",
        "Use this page before reviewing or authoring a Flow PR. It gives the files to open, defects to reject, and commands that prove the change.",
        "",
        "## Review route",
        "",
        _render_review_route_diagram(),
        "",
        "Use the diagram first, then use the table for the exact source owner.",
        "",
        "## Where to start",
        "",
        _render_routes_table(),
        "",
        "## Common changes",
        "",
        *_render_common_change_procedures(),
        "## Review checklist",
        "",
        _render_checklist_table(),
        "",
        "## Validation commands",
        "",
        _render_validation_commands_table(),
        "",
        "## Debugging a stuck run",
        "",
        "Flow runtime spans and worker logs are worker-root signals. Correlate by searchable Flow attributes, especially the persisted Flow `trace_id` exposed as `flow.run.trace_id`, not by OpenTelemetry trace-id navigation.",
        "",
        _render_debug_runbook_table(),
        "",
        "## Source guards",
        "",
        "- Source references are repo-relative file paths only, not line-number citations.",
        "- Validation commands must name the checked file paths unless the tool reads its own config.",
        "- Add or update this page when a Flow PR changes guarded modules, errors, statuses, schemas, or docs contracts.",
        "",
        "## Related",
        "",
        render_flow_docs_related_nextra_cards(
            (
                FlowDocsRelatedNextraCard(
                    "How Flows is built",
                    "/docs/flows-for-developers/how-built",
                ),
                FlowDocsRelatedNextraCard(
                    "The data schema",
                    "/docs/flows-for-developers/data-schema",
                ),
            )
        ),
        "",
    ]
    return "\n".join(parts)


def write_flow_developer_reviewer_guide_docs_page(
    output_path: Path = FLOW_DEVELOPER_REVIEWER_GUIDE_DOCS_OUTPUT_PATH,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        render_flow_developer_reviewer_guide_docs_page(),
        encoding="utf-8",
    )


def _validate_slug_order(
    label: str,
    actual_slugs: tuple[str, ...],
    expected_slugs: tuple[str, ...],
) -> None:
    if len(actual_slugs) != len(expected_slugs):
        raise ValueError(f"Flow reviewer guide must contain all {label}")
    if len(set(actual_slugs)) != len(actual_slugs):
        raise ValueError(f"Flow reviewer guide {label} must not contain duplicates")
    if actual_slugs != expected_slugs:
        raise ValueError(f"Flow reviewer guide {label} must use the required order")


def _validate_slug(slug: str) -> None:
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
        raise ValueError(f"Flow reviewer guide slug is invalid: {slug}")


def _validate_short_sentence(slug: str, field_name: str, value: str) -> None:
    if "\n" in value or len(value) > _MAX_FIELD_LENGTH:
        raise ValueError(
            f"Flow reviewer guide {slug} {field_name} must be one short sentence"
        )
    if "|" in value:
        raise ValueError(
            f"Flow reviewer guide {slug} {field_name} must not contain table pipes"
        )
    if len(_SENTENCE_END_PATTERN.findall(value)) != 1:
        raise ValueError(
            f"Flow reviewer guide {slug} {field_name} must be one short sentence"
        )


def _validate_source_refs(
    slug: str, source_refs: tuple[ReviewerGuideSourceRef, ...]
) -> None:
    if not source_refs:
        raise ValueError(f"Flow reviewer guide {slug} needs source refs")
    for source_ref in source_refs:
        _validate_repo_file_path(slug, "source ref", source_ref.path)


def _validate_validation_command(command: ReviewerValidationCommand) -> None:
    if "::" in command.command:
        raise ValueError(
            f"Flow reviewer guide validation command {command.slug} must not use pytest node ids"
        )
    if not command.referenced_paths:
        raise ValueError(
            f"Flow reviewer guide validation command {command.slug} needs referenced paths"
        )
    for path in command.referenced_paths:
        _validate_repo_file_path(command.slug, "command ref", path)
        if (
            command.requires_path_arguments
            and _command_path_token(path, command.workdir) not in command.command
        ):
            raise ValueError(
                f"Flow reviewer guide validation command {command.slug} must include checked path {path}"
            )


def _validate_route_procedure(route: ReviewerRoute) -> None:
    has_title = route.procedure_title is not None
    has_steps = bool(route.procedure_steps)
    if has_title != has_steps:
        raise ValueError(
            f"Flow reviewer guide route {route.slug} must define procedure title and steps together"
        )
    if route.procedure_title is None:
        return

    if "|" in route.procedure_title:
        raise ValueError(
            f"Flow reviewer guide route {route.slug} procedure title must not contain table pipes"
        )
    if len(route.procedure_steps) < 3:
        raise ValueError(
            f"Flow reviewer guide route {route.slug} procedure needs at least three steps"
        )
    for step in route.procedure_steps:
        _validate_procedure_step(route.slug, step)


def _validate_procedure_step(slug: str, step: ProcedureStep) -> None:
    if "\n" in step.title or "\n" in step.body:
        raise ValueError(
            f"Flow reviewer guide route {slug} procedure step must not contain newlines"
        )
    if len(step.title) > 64:
        raise ValueError(
            f"Flow reviewer guide route {slug} procedure step title is too long"
        )
    if len(step.body) > 260:
        raise ValueError(f"Flow reviewer guide route {slug} procedure step is too long")
    if "|" in step.title or "|" in step.body:
        raise ValueError(
            f"Flow reviewer guide route {slug} procedure step must not contain table pipes"
        )
    if "`" in step.title:
        raise ValueError(
            f"Flow reviewer guide route {slug} procedure step title must not contain backticked paths"
        )
    if step.title == step.body:
        raise ValueError(
            f"Flow reviewer guide route {slug} procedure step title must not duplicate body"
        )


def _validate_runbook_signals(step: ReviewerDebugRunbookStep) -> None:
    if not step.signals:
        raise ValueError(
            f"Flow reviewer guide debug runbook step {step.slug} needs signals"
        )
    if len(set(step.signals)) != len(step.signals):
        raise ValueError(
            f"Flow reviewer guide debug runbook step {step.slug} has duplicate signals"
        )
    for signal in step.signals:
        if not signal or "\n" in signal or "|" in signal:
            raise ValueError(
                f"Flow reviewer guide debug runbook step {step.slug} has invalid signal"
            )
        if signal not in _ALLOWED_DEBUG_SIGNALS:
            raise ValueError(
                f"Flow reviewer guide debug runbook step {step.slug} has unknown signal: {signal}"
            )
        if signal.startswith("flow.") and signal not in _FLOW_SIGNAL_TRUTH:
            raise ValueError(
                f"Flow reviewer guide debug runbook step {step.slug} has unknown flow signal: {signal}"
            )


def _validate_runbook_span_attribute_coverage(
    steps: tuple[ReviewerDebugRunbookStep, ...],
) -> None:
    rendered_signals = {signal for step in steps for signal in step.signals}
    missing_run_keys = FLOW_RUN_SPAN_ATTRIBUTE_KEYS - rendered_signals
    missing_step_keys = FLOW_STEP_SPAN_ATTRIBUTE_KEYS - rendered_signals
    if missing_run_keys or missing_step_keys:
        raise ValueError(
            "Flow reviewer guide debug runbook span attribute coverage drift"
        )
    if FLOW_RUN_EXECUTE_SPAN_NAME not in rendered_signals:
        raise ValueError("Flow reviewer guide debug runbook missing run span name")
    if FLOW_STEP_EXECUTE_SPAN_NAME not in rendered_signals:
        raise ValueError("Flow reviewer guide debug runbook missing step span name")


def _validate_repo_file_path(slug: str, label: str, path: str) -> None:
    if ":" in path:
        raise ValueError(
            f"Flow reviewer guide {slug} {label} must be a file path without line numbers"
        )
    if not path.startswith(_PATH_PREFIXES):
        raise ValueError(
            f"Flow reviewer guide {slug} {label} must point inside backend, docs, or frontend"
        )
    # The generated MDX cannot exist before the first render; tests prove it exists after generation.
    if _is_generated_output_path(path):
        return
    if not (REPO_ROOT / path).is_file():
        raise ValueError(
            f"Flow reviewer guide {slug} {label} file does not exist: {path}"
        )


def _is_generated_output_path(path: str) -> bool:
    return REPO_ROOT / path == FLOW_DEVELOPER_REVIEWER_GUIDE_DOCS_OUTPUT_PATH


def _command_path_token(path: str, workdir: ReviewGuideWorkdir) -> str:
    if workdir == "backend" and path.startswith("backend/"):
        return path.removeprefix("backend/")
    if workdir == "frontend" and path.startswith("frontend/"):
        return path.removeprefix("frontend/")
    return path


def _render_review_route_diagram() -> str:
    return render_flow_docs_mermaid_block(
        "flowchart LR",
        '  pr["Flow PR"] --> api["API/router"]',
        '  pr --> runtime["Runtime/executor"]',
        '  pr --> handlers["Step handler"]',
        '  pr --> uploads["Runtime file/upload"]',
        '  pr --> schema["Schema/migration"]',
        '  pr --> errors["Error-code"]',
        '  pr --> review["Review checkpoint"]',
        '  pr --> docs["Docs"]',
        '  api --> owner["Canonical owner"]',
        "  runtime --> owner",
        "  handlers --> owner",
        "  uploads --> owner",
        "  schema --> owner",
        "  errors --> owner",
        "  review --> owner",
        "  docs --> owner",
        '  owner --> checklist["Checklist"]',
        '  checklist --> validation["Validation"]',
    )


def _render_routes_table() -> str:
    rows = tuple(
        (
            route.change_type,
            route.start_here,
            route.proof,
            _render_source_refs(route.source_refs),
        )
        for route in REVIEWER_ROUTES
    )
    return _render_markdown_table(
        ("Change type", "Start here", "Proof", "Source refs"),
        rows,
    )


def _render_common_change_procedures() -> list[str]:
    parts: list[str] = [
        "These procedures are attached to the change-type routes above, so the reviewer guide has one owner for where a Flow change starts and how to prove it.",
        "",
    ]
    for route in REVIEWER_ROUTES:
        if route.procedure_title is None:
            continue
        # Raw h4 keeps Nextra Steps numbering without adding page TOC entries.
        parts.extend(
            [
                f"### {route.procedure_title}",
                "",
                "<Steps>",
                "",
            ]
        )
        for step in route.procedure_steps:
            parts.extend(
                [
                    f"<h4>{step.title}</h4>",
                    "",
                    step.body,
                    "",
                ]
            )
        parts.extend(["</Steps>", ""])
    return parts


def _render_checklist_table() -> str:
    rows = tuple(
        (
            topic.title,
            topic.check,
            topic.reject,
            _render_source_refs(topic.source_refs),
        )
        for topic in REVIEWER_CHECKLIST_TOPICS
    )
    return _render_markdown_table(
        ("Topic", "Check", "Reject", "Source refs"),
        rows,
    )


def _render_validation_commands_table() -> str:
    rows = tuple(
        (
            command.label,
            f"`{command.workdir}`",
            f"`{command.command}`",
            _render_path_refs(command.referenced_paths),
            command.when_to_run,
        )
        for command in REVIEWER_VALIDATION_COMMANDS
    )
    return _render_markdown_table(
        ("Category", "Workdir", "Command", "Checked refs", "When"),
        rows,
    )


def _render_debug_runbook_table() -> str:
    rows = tuple(
        (
            str(index),
            step.inspect,
            _render_signal_tokens(step.signals),
            step.next_action,
            _render_source_refs(step.source_refs),
        )
        for index, step in enumerate(REVIEWER_DEBUG_RUNBOOK_STEPS, start=1)
    )
    return _render_markdown_table(
        ("Step", "Inspect", "Signals", "Next", "Source refs"),
        rows,
    )


def _render_markdown_table(
    headers: tuple[str, ...],
    rows: tuple[tuple[str, ...], ...],
) -> str:
    column_widths = tuple(
        max(len(headers[index]), *(len(row[index]) for row in rows))
        for index in range(len(headers))
    )

    def render_row(cells: tuple[str, ...]) -> str:
        return (
            "| "
            + " | ".join(
                cell.ljust(column_widths[index]) for index, cell in enumerate(cells)
            )
            + " |"
        )

    separator = (
        "| " + " | ".join("-" * column_width for column_width in column_widths) + " |"
    )
    return "\n".join(
        (render_row(headers), separator, *(render_row(row) for row in rows))
    )


def _render_source_refs(source_refs: tuple[ReviewerGuideSourceRef, ...]) -> str:
    return ", ".join(
        f"{source_ref.label}: `{source_ref.path}`" for source_ref in source_refs
    )


def _render_signal_tokens(signals: tuple[str, ...]) -> str:
    return ", ".join(f"`{signal}`" for signal in signals)


def _render_path_refs(paths: tuple[str, ...]) -> str:
    return ", ".join(f"`{path}`" for path in paths)
