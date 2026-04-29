TL;DR:
1. Flow runtime already has useful CAS/idempotency primitives, but the canonical lifecycle owner is split across `FlowRunService`, `FlowRunExecutor`, repositories, Celery tasks, router background tasks, and frontend status helpers.
2. The top runtime reliability risk is terminalization: stale-running reconciliation fails the run but does not finish in-flight attempts or audit the terminal state consistently.
3. The top maintainability risk is duplicated lifecycle state: run/result/attempt statuses are copied through enums, DB constraints, backend helper sets, generated TypeScript, frontend literal unions, and inline checks.
4. The highest-ROI refactor is not a new abstraction layer; it is one explicit runtime lifecycle contract: typed execution command, typed terminalization command, and a small `execute` loop over named phases.
5. Pause/resume, step rerun, and pause-and-edit are currently feature gaps that require a backend state-machine/data-model expansion before frontend affordances can be honest.

# Agent B - Flow Runtime Review

Scope reviewed: `backend/src/intric/flows/runtime/**`, `FlowRunService`, `FlowRunRepository`, Celery flow execution and reconciliation, flow run routers, runtime frontend components, generated client runtime calls, and runtime-focused tests.

Standards used:

| Standard | Relevant rule | Application in this review |
|---|---|---|
| `docs/engineering/maintainability-standards.md:11` | Every important concept needs one canonical home. | Runtime lifecycle/status/terminalization must stop living in parallel helper sets and caller-specific branches. |
| `docs/engineering/maintainability-standards.md:149-152` | Runtime state must be persisted and public runtime transitions must be idempotent and auditable. | Reconciliation must terminalize runs, step results, attempts, and audit state through one owner. |
| `docs/engineering/api-design-standard.md:3` | Routers are HTTP adapters, not business logic owners. | `flow_run_execution_router.py` should remain dispatch/audit adapter; lifecycle rules belong in application/runtime. |
| `docs/engineering/testing-standard.md:8-12` | Worker/runtime tests cover retries, duplicate starts, crash recovery, and terminalization. | Existing tests cover many unit behaviors but miss the complete crash-recovery terminalization invariant. |
| `docs/engineering/frontend-state-standard.md:3` | Frontend state must have one owner. | Active/terminal status logic should not be duplicated across progress, focus, table, and presentation helpers. |

## Current Lifecycle

| Phase | Current owner | Evidence | Review note |
|---|---|---|---|
| Create API request | `flow_run_execution_router.create_flow_run` | `backend/src/intric/flows/api/flow_run_execution_router.py:106-204` | Router enforces scope, calls service, writes created audit event, and schedules background dispatch. This is mostly an adapter, but dispatch is hidden in FastAPI background task semantics. |
| Validate published version/input | `FlowRunService.create_run` | `backend/src/intric/flows/application/flow_run_service.py:325-431` | Service validates published version, inline input, step files, idempotency fingerprint, and payload size. The accepted payload shape is still `dict[str, Any]`. |
| Persist run and preseed results | `FlowRunRepository.create` | `backend/src/intric/flows/infrastructure/flow_run_repo.py:46-99` | Repository creates a queued run and pre-seeds pending `FlowStepResults`. This is the right persistence owner, but JSON payload types remain broad. |
| Enqueue run | Router background task -> `dispatch_flow_run_after_commit` -> `CeleryFlowExecutionBackend` | `backend/src/intric/flows/api/flow_run_execution_router.py:199-203`, `backend/src/intric/flows/application/flow_dispatch.py:15-63`, `backend/src/intric/flows/runtime/celery_execution_backend.py:29-81` | Dispatch is split across three owners and fallback `user_id` compatibility branches. |
| Claim run | `FlowRunExecutor.execute` via `FlowRunRepository.mark_running_if_claimable` | `backend/src/intric/flows/runtime/executor.py:331-351`, `backend/src/intric/flows/infrastructure/flow_run_repo.py:420-431` | Good CAS primitive: only queued runs transition to running. |
| Validate execution snapshot | `FlowRunExecutor.execute` | `backend/src/intric/flows/runtime/executor.py:370-425` | Checksum, runtime step parsing, persisted-result state, and assistant snapshot drift handling live inside the long executor method. |
| Execute step | `FlowRunExecutor.execute` + `step_execution_runtime` + input resolution | `backend/src/intric/flows/runtime/executor.py:430-709`, `backend/src/intric/flows/runtime/executor.py:733-809`, `backend/src/intric/flows/runtime/step_input_resolution.py:54-388`, `backend/src/intric/flows/runtime/step_execution_runtime.py:738-888` | Step orchestration, input/file resolution, LLM execution, failure handling, and webhook delivery are partially extracted but still coordinated by one large loop. |
| Resolve inputs and files | `step_input_resolution.resolve_step_input` | `backend/src/intric/flows/runtime/step_input_resolution.py:84-160`, `backend/src/intric/flows/runtime/step_input_resolution.py:213-310`, `backend/src/intric/flows/runtime/step_input_resolution.py:391-428` | Canonical runtime file resolution exists here, while API submission validation lives in `flow_run_step_inputs.py`. This is acceptable if the boundary contract is typed. |
| Persist step result and attempt | `FlowRunExecutor._persist_successful_step` and repository | `backend/src/intric/flows/runtime/executor.py:938-973`, `backend/src/intric/flows/infrastructure/flow_run_repo.py:509-603` | Attempt creation uses an upsert and finish is idempotent. Success persistence crosses `flow_repo.save_step_result` and `flow_run_repo.finish_attempt`, so transaction checkpoints need names. |
| Persist evidence/artifacts | Step result payload and evidence bundle/export modules | `backend/src/intric/flows/flow_run_evidence_bundle.py:20-39`, `backend/src/intric/flows/flow_run_evidence.py:67-130`, `backend/src/intric/flows/flow_run_export_json.py:340-390` | Evidence reads step attempts and step result payloads. Orphan `STARTED` attempts are visible in evidence/debug export duration calculations. |
| Handle typed/generic error | `FlowRunExecutor` failure handlers | `backend/src/intric/flows/runtime/executor.py:568-637`, `backend/src/intric/flows/runtime/executor.py:866-930`, `backend/src/intric/flows/runtime/step_attempt_runtime.py:99-137` | Typed failures and generic failures have separate plans, but broad catches still collapse multiple operational classes. |
| Pause/resume | No current runtime owner | `backend/src/intric/flows/enums.py:64-85`, `backend/src/intric/database/tables/flow_tables.py:397-400` | No persisted paused/review state exists. Treat pause/resume as future lifecycle design, not UI-only work. |
| Terminalize | `FlowRunExecutor`, `FlowRunService`, repository, Celery reconciliation | `backend/src/intric/flows/runtime/executor.py:716-731`, `backend/src/intric/flows/runtime/executor.py:1047-1068`, `backend/src/intric/flows/application/flow_run_service.py:655-688`, `backend/src/intric/flows/runtime/tasks.py:322-358` | This is the weakest ownership boundary: normal execution, cancellation, service reconciliation, and Celery beat reconciliation do different subsets of terminalization. |

## Runtime State Ownership

| State | Current owner(s) | Problem | Proposed canonical home | Merge/delete path |
|---|---|---|---|---|
| Run status lifecycle | `FlowRunStatus`, DB check constraint, `FlowRunService._TERMINAL_STATUSES`, `FlowRunExecutor._TERMINAL_STATUSES`, frontend sets and inline checks | Lifecycle rules are copied across backend and frontend. Adding `paused`, `waiting_for_review`, or `rerun_requested` will require scattered edits. | `FlowRunStatus` as semantic owner, plus generated DB/API/frontend representations. | Add enum methods/projections, derive DB constraint text, delete duplicated backend sets and frontend literal sets. |
| Step result lifecycle | `FlowStepResultStatus`, DB check constraint, `claim_step_result`, frontend progress helpers | Pending/running/completed/failed/cancelled are copied and interpreted differently in progress stats. | `FlowStepResultStatus` plus a runtime lifecycle projection used by API/frontend. | Centralize active/terminal classification and update progress helpers to use generated/central status utilities. |
| Attempt lifecycle | `FlowStepAttemptStatus`, DB check constraint, `create_or_get_attempt_started`, `finish_attempt`, evidence exporters | Crash recovery can leave `started`/`retried` attempts unfinished for terminal failed runs. | Runtime terminalization service/repository method owns attempt closure. | Add `terminalize_open_attempts_for_run` as part of one terminalization transaction; delete caller-specific partial reconciliation. |
| Execution command | `FlowRunService.build_dispatch_request`, `FlowRunService.redispatch_stale_queued_runs`, `CeleryFlowExecutionBackend.dispatch`, `tasks.execute_flow_run` | User/service-key dispatch branches and `user_id` legacy shim are repeated. | `FlowRunExecutionCommand` in runtime/application boundary. | Build from `FlowPrincipal.from_run`, serialize once to Celery kwargs, parse once in task, delete `user_id` task compatibility path if no non-test callers remain. |
| Runtime input/file contract | `FlowRunCreateRequest`, `flow_run_step_inputs.py`, `step_input_resolution.py`, `FlowRunDialog.svelte`, `flowRunContract.ts`, `intric-js` JSDoc | Backend validates step input IDs and frontend builds matching objects manually. | API schema generated to `intric-js` plus a narrow frontend intent builder. | Keep `flowRunContract.ts` as UI intent adapter, but make its types generated and delete broad `Record<string, unknown>` where owned fields exist. |
| Evidence/attempt projection | `flow_run_evidence_bundle.py`, `flow_run_evidence.py`, `flow_run_export_json.py`, `FlowRunEvidence.svelte` | Evidence payloads and attempts are exposed as dicts/records; frontend groups attempts through `Record<string, unknown>`. | Evidence bundle schema/API model owns public evidence shape. | Add typed attempt/evidence projection in API/client; update frontend evidence code to consume generated types. |

## Findings

### 1. Terminalization Has No Single Owner

| Field | Detail |
|---|---|
| Problem | Normal completion, cancellation, dispatch failure, timeout failure, service reconciliation, and Celery beat reconciliation each terminalize different parts of the run lifecycle. |
| Why it matters | Worker-crash recovery can leave `FlowStepAttempts` in `started`/`retried` with `finished_at IS NULL`, while the parent run is failed. Evidence and debug export consume attempts and duration from these rows. |
| Evidence | Celery beat reconciliation cancels pending/running step results and fails the run at `backend/src/intric/flows/runtime/tasks.py:322-358`, but never calls `finish_attempt`. Service-level reconciliation only calls `fail_stale_running_run` at `backend/src/intric/flows/application/flow_run_service.py:655-675`, so it does not even cancel pending/running step results. Attempt rows are exposed through evidence at `backend/src/intric/flows/flow_run_evidence_bundle.py:20-39` and grouped/exported at `backend/src/intric/flows/flow_run_evidence.py:83-126` and `backend/src/intric/flows/flow_run_export_json.py:346-390`. |
| Current owner | Split between `FlowRunExecutor._mark_run_failed`, `FlowRunService.cancel_run`, `FlowRunService.reconcile_stale_running_runs`, `tasks._reconcile_stale_running_runs_all_tenants`, and repository status methods. |
| Proposed canonical home | A runtime application method, for example `terminalize_run(command: FlowRunTerminalizationCommand) -> FlowRun`, backed by repository methods that update run, step results, open attempts, and audit in one explicit transaction boundary. |
| Merge/delete path | Merge `FlowRunService.reconcile_stale_running_runs` and Celery beat reconciliation into the same terminalization path. Delete partial reconciliation logic that only flips run status. |
| Acceptance criteria | Any transition to completed/failed/cancelled has one code path; terminalization updates `FlowRuns.finished_at`, pending/running `FlowStepResults`, open `FlowStepAttempts`, and audit behavior consistently; repeated terminalization is idempotent. |
| Tests required | Worker/runtime integration test: create running run with running step result and started attempt, simulate stale reconciliation, assert run failed, step cancelled/failed by policy, attempt terminal with `finished_at`, and audit event behavior. Repository test: double terminalization returns existing terminal state without mutating completed evidence. API test: cancellation remains idempotent for already terminal runs. |
| Risk/trade-off | Must preserve existing evidence for completed steps when a later step or worker fails. The transaction may touch several tables, so lock ordering should be explicit. |
| Human reviewability impact | Reviewers can approve runtime failure behavior by inspecting one terminalization command instead of reconstructing four caller-specific paths. |
| Confidence | High. |

### 2. Status Lifecycle Is Duplicated Across Backend, DB, Generated Types, And Frontend

| Field | Detail |
|---|---|
| Problem | Run/result/attempt statuses are closed and copied through multiple owners instead of derived from one semantic source. |
| Why it matters | Pause/resume, human review, step rerun, and more precise retry states all require coordinated enum, DB constraint, index, API, generated-client, and frontend changes. The current shape makes drift likely. |
| Evidence | Runtime enums live at `backend/src/intric/flows/enums.py:64-85`; DB constraints hardcode run/result/attempt values at `backend/src/intric/database/tables/flow_tables.py:397-400`, `backend/src/intric/database/tables/flow_tables.py:502-506`, and `backend/src/intric/database/tables/flow_tables.py:569-572`; backend terminal sets are duplicated at `backend/src/intric/flows/application/flow_run_service.py:88-92` and `backend/src/intric/flows/runtime/executor.py:239-243`; repository `_ACTIVE_STATUSES` at `backend/src/intric/flows/infrastructure/flow_run_repo.py:40` is another lifecycle tuple that should be derived or deleted; frontend generated schema has `FlowRunStatus` at `frontend/packages/intric-js/src/types/schema.d.ts:12923-12927`, but feature code recreates active/terminal sets at `frontend/apps/web/src/lib/features/flows/components/flowRunProgress.ts:40-48`, `frontend/apps/web/src/lib/features/flows/components/flowRunsFocus.ts:6-30`, and inline checks in `frontend/apps/web/src/lib/features/flows/components/FlowRunsTable.svelte:191`, `frontend/apps/web/src/lib/features/flows/components/FlowRunsTable.svelte:548-568`, and `frontend/apps/web/src/lib/features/flows/components/FlowRunsTable.svelte:655-678`. |
| Current owner | No single owner. `FlowRunStatus` is the closest source, but lifecycle semantics live in helper sets and callers. |
| Proposed canonical home | `FlowRunStatus`, `FlowStepResultStatus`, and `FlowStepAttemptStatus` should own lifecycle semantics (`active`, `terminal`, `cancellable`, `redispatchable`) and produce DB/API/frontend projections. |
| Merge/delete path | Add backend semantic helpers/projections; generate DB check text from enum values or move to PostgreSQL enum with migration discipline; update frontend helpers to consume generated `FlowRunStatus`; delete duplicate sets and inline checks. |
| Acceptance criteria | Adding a new run status has one backend semantic owner and one generated frontend type path; all UI active/terminal/control decisions import one helper; DB constraints and indexes are updated from the same declared lifecycle map. |
| Tests required | Backend unit tests for status semantic helpers; migration/SQL tests that constraint values match enum values; frontend unit tests for one status helper, with table/progress/focus tests importing it rather than asserting duplicate string sets. |
| Risk/trade-off | DB constraint generation must stay migration-reviewable; do not hide schema diffs behind runtime code. |
| Human reviewability impact | Future status changes become obvious, small, and reviewable instead of scattered string edits. |
| Confidence | High. |

### 3. `FlowRunExecutor.execute` Mixes Lifecycle Phases And Transaction Checkpoints

| Field | Detail |
|---|---|
| Problem | `FlowRunExecutor.execute` coordinates claim, snapshot validation, security gates, step claims, attempt lifecycle, step execution, failure handling, webhook delivery, outcome calculation, audit, and commits in one long method. |
| Why it matters | The code has good pieces, but reviewers must mentally simulate a long control flow and many `commit` checkpoints to understand retry, cancellation, and partial failure behavior. |
| Evidence | `execute` spans `backend/src/intric/flows/runtime/executor.py:316-731`; it claims the run at `backend/src/intric/flows/runtime/executor.py:331-351`, validates flow/version state at `backend/src/intric/flows/runtime/executor.py:353-425`, loops over steps at `backend/src/intric/flows/runtime/executor.py:430-709`, handles success at `backend/src/intric/flows/runtime/executor.py:657-707`, and terminalizes at `backend/src/intric/flows/runtime/executor.py:709-731`. Existing extracted helpers include `resolve_step_claim` at `backend/src/intric/flows/runtime/claim_resolution.py:21-54`, `build_step_gate_decision` at `backend/src/intric/flows/runtime/step_attempt_runtime.py:50-96`, and `determine_run_outcome` at `backend/src/intric/flows/runtime/run_outcome.py:18-51`. |
| Current owner | `FlowRunExecutor` is the runtime mechanics owner. |
| Proposed canonical home | Keep `FlowRunExecutor` as owner, but split `execute` into named phases that return typed outcomes. Do not create an interface or port for the executor. |
| Merge/delete path | Extract phase methods inside the same module; preserve existing pure helper modules where they are deep; delete restating comments such as `backend/src/intric/flows/runtime/executor.py:682`. |
| Acceptance criteria | `execute` reads as claim -> prepare snapshot -> iterate steps -> finalize; every phase names inputs, outputs, commit boundary, and failure outcome; no new one-method interface is introduced. |
| Tests required | Keep existing executor behavior tests, then add phase-level tests through public executor behavior for duplicate worker, cancellation between steps, failure after attempt start, webhook failure, and terminal outcome. Avoid tests that assert private helper calls. |
| Risk/trade-off | Mechanical extraction can accidentally change transaction timing. Preserve checkpoints first, then simplify after tests prove behavior. |
| Human reviewability impact | Reviewers can review lifecycle phases independently and see transaction boundaries without reading a 400-line method. |
| Confidence | High. |

#### Proposed `FlowRunExecutor.execute` Phase Split

Do not introduce a fake executor interface. Use concrete internal types:

```python
@dataclass(frozen=True)
class PreparedRunExecution:
    run: FlowRun
    version: FlowVersion
    steps: list[RuntimeStep]
    state: RunExecutionState
    version_metadata: dict[str, Any] | None

@dataclass(frozen=True)
class StepIterationOutcome:
    kind: Literal["continue", "return"]
    result: dict[str, str] | None = None
    completed_result: FlowStepResult | None = None

async def _claim_run_for_execution(
    self, *, run_id: UUID, flow_id: UUID, tenant_id: UUID
) -> FlowRun | dict[str, str]:
    """Consumes run id; persists running claim; returns run or idempotent skip."""

async def _prepare_run_execution(
    self, *, run: FlowRun, flow_id: UUID, tenant_id: UUID
) -> PreparedRunExecution | dict[str, str]:
    """Consumes claimed run; validates active flow, checksum, snapshot, assistant drift."""

async def _execute_runtime_step(
    self,
    *,
    prepared: PreparedRunExecution,
    step: RuntimeStep,
    celery_task_id: str | None,
    retry_count: int,
) -> StepIterationOutcome:
    """Consumes prepared run and one step; owns step claim, attempt start, step execution, webhook, and checkpoint."""

async def _finalize_run_execution(
    self, *, prepared: PreparedRunExecution
) -> dict[str, str]:
    """Consumes final persisted step results; delegates to canonical terminalization."""
```

Transaction boundaries should remain explicit:

| Phase | Current checkpoint evidence | Future checkpoint name |
|---|---|---|
| Run claim | `await self._commit()` after `mark_running_if_claimable` at `backend/src/intric/flows/runtime/executor.py:342-347` | `commit_run_claim` |
| Flow deleted before start | Update/cancel then commit at `backend/src/intric/flows/runtime/executor.py:353-368` | `commit_pre_execution_cancellation` |
| Snapshot validation failures | Status update commits at `backend/src/intric/flows/runtime/executor.py:375-425` | `commit_snapshot_validation_failure` |
| Step claim | Claim then commit at `backend/src/intric/flows/runtime/executor.py:479-484` | `commit_step_claim` |
| Attempt start | Attempt upsert then commit at `backend/src/intric/flows/runtime/executor.py:532-545` | `commit_attempt_started` |
| Successful step | Save result and finish attempt then commit at `backend/src/intric/flows/runtime/executor.py:938-973` | `commit_step_success` |
| Cancel detected after step execution | Finish cancelled attempt then commit at `backend/src/intric/flows/runtime/executor.py:639-655` | `commit_mid_step_cancellation` |
| Terminal outcome | Update status/audit then commit at `backend/src/intric/flows/runtime/executor.py:716-731` | `commit_run_terminalization` |

### 4. Celery Execution Payloads Are Loose And Dispatch Principal Branches Are Repeated

| Field | Detail |
|---|---|
| Problem | Flow execution command shape is represented as a partial `TypedDict`, Celery kwargs, and repeated user/service-key dispatch branches. |
| Why it matters | A missing or conflicting principal can be accepted until task runtime. Retry/redispatch code must repeat branch logic, increasing the chance of service-key behavior drift. |
| Evidence | Dispatch request is a `TypedDict(total=False)` and built by branch at `backend/src/intric/flows/application/flow_run_service.py:75-83` and `backend/src/intric/flows/application/flow_run_service.py:299-312`; stale redispatch repeats the branch at `backend/src/intric/flows/application/flow_run_service.py:620-640`; execution backend maps optional fields into Celery kwargs at `backend/src/intric/flows/runtime/celery_execution_backend.py:29-81`; task accepts loose strings and legacy `user_id` at `backend/src/intric/flows/runtime/tasks.py:178-220`. Grep found no production caller of the task `user_id` shim outside these compatibility branches; tests still cover it. |
| Current owner | Split between `FlowRunService`, `CeleryFlowExecutionBackend`, and `tasks.execute_flow_run`. |
| Proposed canonical home | `FlowRunExecutionCommand` in the application/runtime boundary, built from `FlowPrincipal.from_run`, with `to_celery_kwargs()` and `from_celery_kwargs()` methods. |
| Merge/delete path | Replace `FlowRunDispatchRequest`; make backend dispatch accept `FlowRunExecutionCommand`; remove task `user_id` compatibility after updating tests. |
| Acceptance criteria | There is one serializer/deserializer for Celery payloads; invalid principal combinations fail before dispatch or at task parse with a domain-specific error; redispatch uses the same command builder as initial dispatch. |
| Tests required | Unit tests for command serialization for user and service-key principals; task parse test for invalid payload; redispatch test proving it uses the command builder; remove tests that preserve the legacy `user_id` task kwarg. |
| Risk/trade-off | Existing queued tasks with old kwargs could fail if deployed mid-queue. Because this is pre-production, deletion is preferred; if rollout safety is needed, document a short-lived drain window and deletion point. |
| Human reviewability impact | Runtime dispatch becomes one typed contract instead of three branches and a task shim. |
| Confidence | High. |

### 5. Broad Runtime Catches Need A Failure Taxonomy

| Field | Detail |
|---|---|
| Problem | Runtime catches broad `Exception` in many places, mixing deterministic validation failures, transient infrastructure failures, optional best-effort probes, webhook failures, and audit failures. |
| Why it matters | Retry policy, terminalization, user-visible error messages, and alerting should differ by failure class. Broad catches make runtime behavior harder to reason about during incidents. |
| Evidence | Core broad catches: attempt start at `backend/src/intric/flows/runtime/executor.py:545`, generic step failure at `backend/src/intric/flows/runtime/executor.py:624`, webhook delivery at `backend/src/intric/flows/runtime/executor.py:693`, audit swallow at `backend/src/intric/flows/runtime/executor.py:1102`, task failure at `backend/src/intric/flows/runtime/tasks.py:303`, dispatch failure at `backend/src/intric/flows/application/flow_dispatch.py:46`, and redispatch failure at `backend/src/intric/flows/application/flow_run_service.py:642`. Runtime package scan also finds broad catches in RAG retrieval, transcription, template fill, document rendering, preflight, HTTP audit, and shutdown paths. |
| Current owner | No taxonomy owner; each module decides locally. |
| Proposed canonical home | Runtime failure taxonomy under `backend/src/intric/flows/runtime/`, used by executor, task boundary, dispatch/reconciliation, and evidence/audit reporting. |
| Merge/delete path | Keep best-effort optional probes where appropriate, but wrap them in named outcomes. Replace catch-all terminalization with typed categories. |
| Acceptance criteria | Every broad catch is classified as deterministic contract violation, policy/auth failure, transient infrastructure failure, external provider failure, webhook delivery failure, best-effort telemetry failure, or unexpected internal failure; each category states retry, terminalization, audit, and user-message behavior. |
| Tests required | Behavior tests for typed IO no-retry failure, transient provider retry/terminalization path, webhook connect failure vs HTTP non-2xx behavior, audit failure policy, and task timeout behavior. |
| Risk/trade-off | A taxonomy can become ceremony if it only wraps exceptions. It must change behavior or reviewability: retry/no-retry, audit, and public error shape. |
| Human reviewability impact | Reviewers can approve failure behavior by category instead of reading every catch. |
| Confidence | Medium-high. Some broad catches in optional helpers may be acceptable once documented. |

#### Broad `except Exception` Inventory

| Location | Current behavior | Desired category |
|---|---|---|
| `backend/src/intric/flows/runtime/executor.py:545` | Attempt-start failure delegates to generic failure plan after rollback. | Persistence/internal failure; terminalize via canonical terminalization. |
| `backend/src/intric/flows/runtime/executor.py:624` | Any step exception marks step/run failed. | Split deterministic contract/provider/transient/unexpected. |
| `backend/src/intric/flows/runtime/executor.py:693` | Any webhook delivery exception fails run. | Separate webhook HTTP non-2xx, network/transient, auth/config. |
| `backend/src/intric/flows/runtime/executor.py:1102` | Audit failure is warning-only. | Explicit audit durability policy; observability reviewer should decide fail-open/fail-closed. |
| `backend/src/intric/flows/runtime/tasks.py:303` | Any task exception marks run failed. | Task-boundary unexpected failure; use terminalization and alert. |
| `backend/src/intric/flows/application/flow_dispatch.py:46` | Dispatch failure marks run failed before execution. | Broker/dispatch failure; consider queued redispatch policy before hard fail. |
| `backend/src/intric/flows/application/flow_run_service.py:642` | Redispatch failure logged; batch continues except run-scoped calls re-raise. | Transient dispatch failure with clear API/beat behavior. |
| `backend/src/intric/flows/runtime/rag_retrieval.py:110`, `backend/src/intric/flows/runtime/rag_retrieval.py:169` | RAG failures are downgraded into metadata/diagnostics. | External optional retrieval; fail soft only if product policy says RAG is optional. |
| `backend/src/intric/flows/runtime/transcription_runtime.py:142`, `backend/src/intric/flows/runtime/transcription.py:163` | Transcription failures normalize to typed IO failures. | External provider/typed input failure; no retry unless provider transient is identified. |
| `backend/src/intric/flows/runtime/template_fill_runtime.py:145`, `backend/src/intric/flows/runtime/template_fill_runtime.py:174`, `backend/src/intric/flows/runtime/template_fill_runtime.py:187`, `backend/src/intric/flows/runtime/template_fill_runtime.py:288`, `backend/src/intric/flows/runtime/template_fill_runtime.py:297`, `backend/src/intric/flows/runtime/template_fill_runtime.py:366` | Template fill failures are converted locally. | Deterministic document/template errors vs renderer infra errors. |
| `backend/src/intric/flows/runtime/document_rendering/service.py:72`, `backend/src/intric/flows/runtime/document_rendering/service.py:100` | Renderer fallback/translation. | Renderer capability/fallback policy with explicit degradation. |
| `backend/src/intric/flows/runtime/step_execution_runtime.py:41`, `backend/src/intric/flows/runtime/step_execution_runtime.py:226`, `backend/src/intric/flows/runtime/step_execution_runtime.py:836`, `backend/src/intric/flows/runtime/step_execution_runtime.py:874` | Defensive import/probe/model-call fallback. | Keep import/probe as best-effort; split model call rejection from provider failure. |
| `backend/src/intric/flows/runtime/http_audit.py:87`, `backend/src/intric/flows/runtime/http_runtime.py:207`, `backend/src/intric/flows/runtime/celery_preflight.py:49`, `backend/src/intric/flows/runtime/celery_app.py:66` | Local best-effort audit/preflight/shutdown behavior. | Keep as outer-boundary best effort, but document observability impact. |

### 6. Runtime JSON Contracts Are Too Broad At Owned Boundaries

| Field | Detail |
|---|---|
| Problem | Runtime input, output, artifacts, attempts, and evidence payloads are exposed or persisted as broad dict/record bags even where the system owns the shape. |
| Why it matters | Arbitrary output JSON may remain flexible, but owned sub-fields like `step_inputs`, `artifacts`, `generated_file_ids`, attempt provenance, and run outcome should be typed so API and frontend do not drift. |
| Evidence | `FlowRunCreateRequest.input_payload_json` is `dict[str, Any]` at `backend/src/intric/flows/api/flow_models.py:431-434`; `FlowRunPublic` exposes input/output payload JSON as broad dicts at `backend/src/intric/flows/api/flow_models.py:445-463`; `FlowRunStepPublic` exposes payloads, model parameters, tool metadata, and diagnostics as dict/list bags at `backend/src/intric/flows/api/flow_models.py:498-523`; runtime models use `dict[str, Any]` for step bindings/config/contracts and output metadata at `backend/src/intric/flows/runtime/models.py:22-40` and `backend/src/intric/flows/runtime/models.py:50-79`; frontend run dialog stores input/form/runtime file state as `Record<string, unknown>` at `frontend/apps/web/src/lib/features/flows/components/FlowRunDialog.svelte:67-83`; evidence frontend uses `Record<string, unknown>` for attempts at `frontend/apps/web/src/lib/features/flows/components/FlowRunEvidence.svelte:45-50` and `frontend/apps/web/src/lib/features/flows/components/FlowRunEvidence.svelte:167-180`. |
| Current owner | Mixed between API models, runtime models, evidence bundle/export, generated client, and frontend adapters. |
| Proposed canonical home | Typed API boundary models for owned runtime envelopes; typed runtime dataclasses for owned projections; leave truly arbitrary downstream model output as JSON. |
| Merge/delete path | Type `FlowRunCreateRequest.step_inputs`, `RunOutcome`, artifacts, generated file ids, diagnostics, and attempts first. Do not attempt a full type model for arbitrary `output_payload_json` in this phase. |
| Acceptance criteria | Owned sub-fields have named schemas and generated frontend types; free-form JSON is explicitly isolated and documented as user/model output; evidence frontend no longer treats attempts as `Record<string, unknown>`. |
| Tests required | API contract tests for run creation schema, step input serialization, evidence attempt shape, artifact shape, and generated client typing. Frontend unit tests for `buildFlowRunIntent` and evidence grouping using generated attempt types. |
| Risk/trade-off | Over-typing arbitrary model output would be expensive and brittle. Scope typing to owned envelopes and projections. |
| Human reviewability impact | Contract changes become visible model diffs rather than implicit JSON key conventions. |
| Confidence | High for owned-field gaps; medium for exact schema split, which should be coordinated with API/data reviewers. |

### 7. Frontend Runtime State Recreates Backend Lifecycle Semantics

| Field | Detail |
|---|---|
| Problem | Frontend runtime tables, progress views, focus behavior, and status presentation duplicate active/terminal status logic and manually shape run input payloads. |
| Why it matters | The frontend will drift when backend lifecycle expands; UI controls may appear for wrong statuses or fail to poll statuses that are active but not named `queued`/`running`. |
| Evidence | Generated type already includes `FlowRunStatus` at `frontend/packages/intric-js/src/types/schema.d.ts:12923-12927`, but feature code declares status filters manually at `frontend/apps/web/src/lib/features/flows/components/FlowRunsTable.svelte:47-67`, polls active runs with inline string checks at `frontend/apps/web/src/lib/features/flows/components/FlowRunsTable.svelte:189-209`, controls redispatch/cancel with inline status checks at `frontend/apps/web/src/lib/features/flows/components/FlowRunsTable.svelte:548-568` and `frontend/apps/web/src/lib/features/flows/components/FlowRunsTable.svelte:655-678`, and maintains separate active/terminal helper sets at `frontend/apps/web/src/lib/features/flows/components/flowRunProgress.ts:40-48` and `frontend/apps/web/src/lib/features/flows/components/flowRunsFocus.ts:6-30`. |
| Current owner | No single frontend lifecycle owner; `flowRunProgress.ts` is the closest helper but not canonical. |
| Proposed canonical home | A generated-type-backed frontend runtime status helper, aligned with backend enum semantics. |
| Merge/delete path | Move active/terminal/cancellable/redispatchable decisions into one helper; update table, progress, focus, and tests to import it; keep `flowRunContract.ts` as payload adapter but generated-type it. |
| Acceptance criteria | No inline `queued`/`running` status control logic remains in runtime components; status filter type comes from generated client or a central mapped type; pause/resume UI is not added until backend lifecycle state exists. |
| Tests required | Frontend unit tests for one status helper; table tests for queued/running/completed/failed/cancelled controls through helper behavior; generated-client type check once frontend baseline is healthy. |
| Risk/trade-off | Some presentation helpers may still accept unknown statuses for forward compatibility; that is fine if lifecycle decisions are canonical. |
| Human reviewability impact | Reviewers can evaluate frontend lifecycle behavior in one helper instead of scanning multiple components. |
| Confidence | High. |

### 8. Runtime Feature Gaps Are Data-Model/API/Runtime Gaps, Not UI Polish

| Feature | Current evidence | Required future design |
|---|---|---|
| Per-step file mapping | Backend has `step_inputs` schema and validation at `backend/src/intric/flows/api/flow_models.py:410-434` and `backend/src/intric/flows/flow_run_step_inputs.py:67-128`; frontend builds payload at `frontend/apps/web/src/lib/features/flows/flowRunContract.ts:40-68` and submits it at `frontend/apps/web/src/lib/features/flows/components/FlowRunDialog.svelte:819-835`. | Keep and type the canonical `step_inputs` path; delete top-level `file_ids` compatibility after the migration window unless a shipped API consumer needs it. |
| Step-level execution/rerun | Step result rows are unique by run/step at `backend/src/intric/database/tables/flow_tables.py:519-524`; attempts are unique by run/step/attempt at `backend/src/intric/database/tables/flow_tables.py:586-590`; executor runs the whole flow sequentially at `backend/src/intric/flows/runtime/executor.py:430-709`. | Add an explicit rerun command/state model: which upstream/downstream results are invalidated, which attempts remain evidence, and which run status is active. Do not fake rerun by redispatching the full run without invalidation rules. |
| Human-in-the-loop pause-and-edit | Run statuses are closed to queued/running/completed/failed/cancelled at `backend/src/intric/flows/enums.py:64-69` and `backend/src/intric/database/tables/flow_tables.py:397-400`; no pause/review statuses exist. | Add persisted states such as `paused_for_review` only with DB constraints, API controls, executor suspension/resume semantics, audit events, and frontend controls. |

## Idempotency And Crash Recovery

| Scenario | Current behavior | Gap | Proposed acceptance criteria |
|---|---|---|---|
| Retried create request | Idempotency key is validated at `backend/src/intric/flows/application/flow_run_service.py:314-323`, fingerprinted at `backend/src/intric/flows/application/flow_run_service.py:408-510`, and backed by DB unique indexes at `backend/src/intric/database/tables/flow_tables.py:417-438`. | Strong baseline. It still depends on broad `input_payload_json`. | Same key + same normalized request returns existing run; same key + different request returns conflict; tests continue at service/API/repository layers. |
| Duplicate task start | Run claim only updates queued to running at `backend/src/intric/flows/infrastructure/flow_run_repo.py:420-431`; executor skips if not claimable at `backend/src/intric/flows/runtime/executor.py:342-351`; tests exist for duplicate claim behavior at `backend/tests/integration/flows/test_flow_run_repository.py:802` and `backend/tests/unittests/flows/test_flow_executor_runtime.py:863`. | Good baseline. Ensure future status additions preserve this CAS property. | Only one worker can own a run execution phase; duplicates return an idempotent skip. |
| Duplicate attempt start | Attempt upsert uses unique run/step/attempt at `backend/src/intric/flows/infrastructure/flow_run_repo.py:509-550`; tests cover idempotent/concurrent attempt start at `backend/tests/integration/flows/test_flow_run_repository.py:1203` and `backend/tests/integration/flows/test_flow_run_repository.py:1298`. | Good baseline, but attempt number is `retry_count + 1` from Celery retries, so custom rerun/step retry needs a new attempt-number owner. | Attempt numbering is owned by persisted runtime command, not only Celery retry count. |
| Worker crash mid-step | Beat reconciliation marks stale running runs failed at `backend/src/intric/flows/runtime/tasks.py:322-358`. | Open attempts are not terminalized; audit is skipped; service and beat reconciliation differ. | Reconciliation invokes canonical terminalization for run, step results, attempts, and audit. |
| Timeout in task wrapper | Task timeout cancels future and marks run failed at `backend/src/intric/flows/runtime/tasks.py:284-302`. | Future cancellation may not stop already-running side effects; terminalization remains partial through `_mark_run_failed`. | Timeout path uses canonical terminalization and records task timeout as attempt/run provenance. |
| Double terminalization | Repository `update_status` defaults terminal transitions to queued/running only and returns existing row if CAS misses at `backend/src/intric/flows/infrastructure/flow_run_repo.py:293-343`; tests cover idempotent terminal update at `backend/tests/integration/flows/test_flow_run_repository.py:562`. | Good run-level baseline, but step/attempt/audit idempotency is not unified. | Double terminalization is idempotent across all runtime tables and audit policy. |

## Tests

Existing useful coverage:

| Area | Evidence | Notes |
|---|---|---|
| Create idempotency | `backend/tests/unittests/flows/test_flow_run_service.py:385`, `backend/tests/unittests/flows/test_flow_run_service.py:473`, `backend/tests/unittests/flows/test_flow_run_service.py:533`, `backend/tests/integration/flows/test_flow_run_repository.py:302` | Good service/repository behavior coverage. |
| Redispatch service/API | `backend/tests/unittests/flows/test_flow_run_service.py:1965-2211`, `backend/tests/unittests/flows/test_flow_router.py:1710-1819` | Good coverage of stale queued redispatch branches, including dispatch failure. |
| Reconciliation | `backend/tests/unittests/flows/test_flow_run_service.py:2221-2271`, `backend/tests/unittests/flows/test_celery_runtime.py:298-346` | Covers run failure count but not open attempt terminalization or audit. |
| Duplicate execution/claims | `backend/tests/unittests/flows/test_flow_executor_runtime.py:863`, `backend/tests/unittests/flows/test_flow_executor_runtime.py:938`, `backend/tests/integration/flows/test_flow_run_repository.py:802`, `backend/tests/integration/flows/test_flow_run_repository.py:877` | Strong CAS coverage. |
| Attempt lifecycle | `backend/tests/integration/flows/test_flow_run_repository.py:1203`, `backend/tests/integration/flows/test_flow_run_repository.py:1298`, `backend/tests/integration/flows/test_flow_run_repository.py:1504` | Good idempotent attempt start/finish baseline. |
| Cancellation during execution | `backend/tests/unittests/flows/test_flow_executor_runtime.py:1595`, `backend/tests/unittests/flows/test_flow_executor_runtime.py:1679`, `backend/tests/unittests/flows/test_flow_executor_runtime.py:1872` | Good behavior protection around mid-run cancellation. |
| Terminal audit | `backend/tests/unittests/flows/test_flow_executor_runtime.py:3456`, `backend/tests/unittests/flows/test_flow_executor_runtime.py:3550` | Normal executor paths covered; reconciliation terminal audit missing. |

Required high-ROI tests:

| Priority | Test | Layer | Failure mode protected |
|---:|---|---|---|
| 1 | Stale running run with started attempt reconciles through canonical terminalization. | Worker/runtime integration | Worker crash mid-step leaves attempt open and audit absent. |
| 2 | `FlowRunExecutionCommand` serializes/deserializes user and service-key principals and rejects invalid combinations. | Unit | Missing principal discovered only inside Celery task. |
| 3 | Run status helper contract matches enum and generated frontend type. | Backend + frontend unit | Lifecycle drift across DB/API/UI. |
| 4 | Webhook failure taxonomy distinguishes non-2xx, connect timeout, and invalid config. | Executor behavior | Broad webhook catch terminates all failure modes identically. |
| 5 | Evidence frontend consumes typed attempts and handles unfinished historical attempts gracefully during migration. | Frontend component/unit | Evidence duration/grouping breaks on orphan attempts. |

No new validation commands were run in this Agent B pass. Phase 0 already records the baseline: `cd backend && uv run pyright` is green, flow-scoped Ruff has import-order failures, and frontend checks have repo-wide failures.

## Deferred Reliability Watchlist

| Risk | Evidence | Verdict |
|---|---|---|
| Global Celery async loop lifecycle | `_get_flow_task_loop` owns a module-level loop/thread at `backend/src/intric/flows/runtime/tasks.py:33-59`, and task execution waits on `run_coroutine_threadsafe(...).result(...)` at `backend/src/intric/flows/runtime/tasks.py:261-283`. | Not a Phase 1 blocker, but Phase 2 implementation should verify Celery fork/restart behavior before changing task execution. If the loop is process-local and restarted after fork, document that invariant; otherwise move async execution to a safer worker boundary. |
| Audit durability policy | Terminal audit failures are swallowed with warning at `backend/src/intric/flows/runtime/executor.py:1089-1111`. | Leave the fail-open/fail-closed decision to the observability reviewer, but do not ship the failure taxonomy until this policy has an owner. |

## Ranked Work Items

| Rank | Work item | Scope | Acceptance criteria | Tests | Risk | Reviewability |
|---:|---|---|---|---|---|---|
| 1 | Make status lifecycle semantic and canonical. | Backend enums, DB constraints/migration policy, generated client, runtime frontend helpers. | One owner for active/terminal/cancellable/redispatchable semantics; DB check constraint values are generated from or mechanically checked against enum values; duplicate sets and dead lifecycle tuples are deleted. | Status helper tests, DB constraint parity tests, frontend helper tests. | Medium: DB migrations must be explicit. | High: status changes become localized. |
| 2 | Introduce canonical terminalization. | `FlowRunService`, `FlowRunRepository`, Celery reconciliation, executor failure paths, audit. | Run, step results, attempts, and audit terminalize through one idempotent path; terminalization metadata includes a typed source such as user cancel, timeout, beat reconciliation, dispatch failure, task failure, or normal completion. | Worker crash/reconciliation integration tests and double-terminalization tests. | Medium-high: touches runtime failure behavior. | Very high: incident behavior becomes inspectable in one place. |
| 3 | Add `FlowRunExecutionCommand`. | Dispatch service, execution backend, Celery task, redispatch. | One typed command serializer/parser; legacy `user_id` task kwarg removed or given deletion point. | Command unit tests and redispatch tests. | Low-medium: queued old payloads if deployment overlaps. | High: eliminates repeated principal branches. |
| 4 | Split `FlowRunExecutor.execute` into phases. | `runtime/executor.py` only, using existing helper modules. | Small top-level loop with named checkpoints and typed step outcomes. | Existing executor behavior tests plus checkpoint-sensitive scenarios. | Medium: transaction timing can change. | High: long-method review burden drops. |
| 5 | Type owned runtime/evidence projections. | API models, runtime models, evidence bundle/export, generated client, frontend evidence. | Owned envelopes typed; arbitrary model output remains JSON. | API contract and frontend evidence tests. | Medium: generated client churn. | Medium-high: schema drift becomes visible. |
| 6 | Define runtime failure taxonomy. | Executor, task boundary, RAG/transcription/template/webhook helpers, audit policy. | Broad catches are categorized with retry/terminalization/audit behavior. | Category behavior tests. | Medium-high: may change external failure behavior. | High: production failure review gets clearer. |
| 7 | Design pause/resume and step rerun as explicit lifecycle features. | Data model, API, executor, frontend. | Persisted states, API controls, audit events, and invalidation semantics exist before UI controls. | Contract/runtime/frontend tests for pause/resume/rerun. | High: feature-level architecture change. | High if staged after status/terminalization cleanup. |

## Current Owner And Canonical Home Summary

| Concept | Current owner(s) | Proposed canonical home | Delete/merge path |
|---|---|---|---|
| Run lifecycle state | Enum, DB checks, service/executor sets, frontend sets/inline checks | Flow status lifecycle map derived from backend enum and generated to frontend | Delete duplicate sets in `FlowRunService`, `FlowRunExecutor`, `flowRunProgress.ts`, `flowRunsFocus.ts`, and table inline checks. |
| Execution dispatch payload | `FlowRunDispatchRequest`, execution backend kwargs, task kwargs | `FlowRunExecutionCommand` | Delete partial `TypedDict` and `user_id` compatibility shim. |
| Terminalization | Executor, service, repo, Celery task | Runtime terminalization command/use case | Merge service and beat reconciliation into one path. |
| Step execution phase | `FlowRunExecutor.execute` plus helper modules | `FlowRunExecutor` phase methods and existing pure helper modules | Keep useful helpers; avoid new executor interface. |
| Runtime file mapping | API `StepRunInput`, `flow_run_step_inputs.py`, frontend `flowRunContract.ts` | API schema plus generated frontend type and UI intent adapter | Delete top-level `file_ids` legacy path after decision. |
| Evidence attempts | Evidence bundle/export plus frontend records | Evidence API schema/generated client | Replace `Record<string, unknown>` attempts in frontend. |

## Risk And Trade-Off

The recommended path is intentionally staged. Status semantics and terminalization should come before feature expansion because they are the foundation for pause/resume, step rerun, and reliable recovery. The main trade-off is migration churn: making the lifecycle explicit touches enum semantics, DB constraints, API schemas, generated TypeScript, runtime workers, and tests. That churn is justified because the repository is pre-production and the current parallel lifecycle paths will become more expensive after shipping.

Avoid:

- Creating a new executor interface or factory; `FlowRunExecutor` has one real implementation and should be deepened, not abstracted.
- Fully typing arbitrary `output_payload_json`; type owned sub-fields and leave model/user output as JSON.
- Adding pause/resume buttons before the backend has persisted lifecycle states and executor suspension semantics.
- Preserving `user_id` Celery payload compatibility unless a real queued-task rollout need is documented.

## Claude Peer Review

Claude iteration 1 returned `VERDICT: changes_required`, `GREEN_LIGHT: no`, and `MIN_SCORE: 4`, primarily because the original direction underweighted status single-source-of-truth and terminalization/reconciliation. I accepted the peer-review corrections that were verified against source:

| Peer correction | Codex verification | Applied change |
|---|---|---|
| Prioritize status lifecycle duplication. | Verified duplicate backend sets and frontend sets/inline checks at the cited files, plus generated `FlowRunStatus`. | Finding 2 and work item 1 lead the maintainability recommendations. |
| Reconciliation has two paths with different semantics. | Verified service method is referenced only in tests/source definition, while Celery beat schedules `flows.reconcile_running`; semantics differ. | Finding 1 names terminalization as top runtime reliability risk and requires merge. |
| Open attempts after worker crash are user-visible. | Verified evidence bundle/export and frontend evidence consume step attempts. | Crash-recovery tests require attempt terminalization. |
| Do not over-type arbitrary output JSON. | Runtime payloads include arbitrary model/user output. | Finding 6 scopes typing to owned envelopes/projections. |
| Pause/resume is speculative without backend state. | DB and enum only permit queued/running/completed/failed/cancelled. | Feature gaps section frames pause/resume as lifecycle design work. |

Claude iteration 2 reviewed this document and returned `VERDICT: green`, `GREEN_LIGHT: yes`, and `MIN_SCORE: 7` for the Phase 1 deliverable. Non-blocking refinements from iteration 2 were folded into this document: the global Celery async-loop watchlist item, the dead repository active-status tuple, explicit DB constraint parity acceptance, and typed terminalization source metadata.

## Scorecard

| Dimension | Score | Why |
|---|---:|---|
| Maintainability | 4 | Runtime behavior has useful primitives, but lifecycle ownership is scattered across executor/service/repo/tasks/frontend. |
| Code Quality | 5 | Core code is typed enough for Pyright and has extracted helpers, but broad JSON, broad catches, and long control flow remain. |
| Clean Architecture | 5 | Routers are mostly adapters, but Celery/background dispatch and audit/terminalization boundaries are not cleanly owned. |
| Separation of Concerns | 4 | `FlowRunExecutor.execute` and terminalization paths mix phases and responsibilities. |
| Single Source of Truth | 3 | Status semantics and execution command shape are duplicated across backend, DB, task payloads, generated types, and frontend. |
| Human Readability | 5 | Domain names are mostly clear, but long executor flow and duplicated status helpers make week-one comprehension expensive. |
| Runtime Reliability | 3 | CAS and idempotency are good, but crash recovery/terminalization can leave attempts open and audit behavior inconsistent. |
| Testability | 6 | There is substantial behavior coverage, but the highest-risk crash-recovery invariant and status-source invariant are missing. |

Overall score: 3, because Single Source of Truth and Runtime Reliability both require refactor before further runtime feature work.
