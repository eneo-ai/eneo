# Batch 8 — Step Rerun Plan (Iteration 2)

TL;DR:
1. Batch 8 adds a real rerun lifecycle, not a redispatch alias: endpoint, command, operation rows, attempt lineage, template-aware DAG invalidation, evidence lineage, and frontend status behavior.
2. The canonical runtime owner remains `FlowRunService` plus `FlowRunRepository`; routers stay HTTP adapters and the worker reloads rerun state from the database.
3. `flow_run_rerun_operations` is the durable rerun request/audit owner, with deterministic fingerprint idempotency, child invalidation rows, and nullable attempt lineage on `flow_step_attempts`.
4. Rerun uses the run's published definition snapshot to compute dependency edges from `input_source` plus every runtime-interpolated template surface; live `flow_step_dependencies` remains an authoring projection unless it becomes version-scoped later.
5. No deprecated, legacy, or backwards-compatible Flow rerun path is allowed because Flow / Flow AI Builder is unreleased.

## Starting Evidence

| Signal | Evidence | Batch 8 implication |
|---|---|---|
| Rerun has no endpoint or operation table. | Scoped search finds only `FlowApiAction.RERUN`, a frontend error-code mapping, and redispatch paths; no `flow_run_rerun_operations` owner exists. | Create the canonical owner instead of extending redispatch. |
| Redispatch is queue repair, not step rerun. | `backend/src/intric/flows/api/flow_run_execution_router.py:376-455` routes stale queued redispatch and returns `redispatched_count`; `backend/src/intric/flows/application/flow_run_service.py:690-757` claims stale queued runs. | Do not reuse redispatch for rerun semantics. |
| The existing dispatch-after-commit helper is create-run behavior, not rerun recovery behavior. | `backend/src/intric/flows/api/flow_run_execution_router.py:212-216` uses `common.dispatch_flow_run_after_commit` for create-run dispatch; `backend/src/intric/flows/application/flow_dispatch.py:47-66` terminalizes the run as failed when dispatch fails. | Rerun needs a recoverable dispatch path that leaves the queued run and active operation for stale queued redispatch, or the helper must be generalized with explicit behavior. |
| Rerun permission action exists but is fail-closed. | `backend/src/intric/flows/flow_access_policy.py:34-36` defines `REVIEW`, `RESUME`, and `RERUN`; `backend/src/intric/flows/flow_access_policy.py:167-172` marks rerun `implemented=False`; `backend/tests/unittests/flows/test_flow_access_policy.py:54-75` pins future actions denied. | Batch 8 must intentionally enable rerun, with tests proving `FLOWS_RUN` and run ownership are insufficient. |
| Terminalization/outbox prerequisite exists. | `backend/src/intric/flows/application/flow_run_terminalization.py:33-198` owns idempotent terminalization and durable terminal audit; `backend/src/intric/database/tables/flow_tables.py:759-821` defines `FlowRunAuditOutbox`. | Rerun must not add a new ARQ-backed lifecycle audit path. |
| Current step results are current-only. | `backend/src/intric/database/tables/flow_tables.py:455-532` has one `FlowStepResults` row per `(flow_run_id, step_id)`. | Historical rerun evidence must live on attempts and rerun operation rows before current results are cleared. |
| Attempts are historical but do not yet carry rerun lineage or output snapshots. | `backend/src/intric/database/tables/flow_tables.py:535-606` stores attempt metadata/provenance only; `backend/src/intric/flows/domain/flow.py:177-202` mirrors the same shape. | Add nullable rerun lineage and output/input snapshot fields to attempts. |
| Attempt numbering is currently tied to Celery retry count. | `backend/src/intric/flows/runtime/executor.py:524-535` sets `attempt_no = retry_count + 1`. | Replace this for Flow runtime attempts with persisted allocation from run/step history. |
| Per-step input and result file rows are available. | `backend/src/intric/database/tables/flow_tables.py:609-756` defines `FlowRunStepInputFiles` and `FlowRunStepResultFiles`; `backend/src/intric/flows/flow_run_step_inputs.py:71-229` normalizes/validates/serializes `step_inputs`. | Rerun can persist attempt-scoped input files and evidence rows instead of mutating worker memory. |
| Evidence export now has row-backed artifacts. | `backend/src/intric/flows/flow_run_evidence_bundle.py:96-117` builds evidence with result files; `backend/src/intric/flows/flow_run_export_json.py:85-149` hashes the returned bundle. | Add rerun operation and attempt lineage into the hashed evidence bundle/export. |
| Current graph helper is API-shaped and order-derived. | `backend/src/intric/flows/api/flow_graph.py:6-123` builds nodes/edges for UI from step order and `input_source`. | Add a domain/runtime rerun graph module instead of reusing API dict output. |
| Runtime dependencies are not only `input_source`. | `backend/src/intric/flows/runtime/step_input_resolution.py:163-201` interpolates `input_bindings.question`; `backend/src/intric/flows/runtime/http_orchestration.py:129-155` and `backend/src/intric/flows/runtime/http_orchestration.py:296-328` interpolate HTTP input/output URL, headers, and bodies; `backend/src/intric/flows/runtime/template_fill_runtime.py:402-431` resolves template-fill bindings; `backend/src/intric/flows/runtime/step_execution_runtime.py:666-675` interpolates assistant prompt text. | Rerun graph must scan all runtime-interpolated published snapshot fields before invalidating current results. |
| `FlowStepDependencies` exists only as live authoring state. | `backend/src/intric/database/tables/flow_tables.py:193-235` defines live parent/child rows; scoped search found no repository/runtime writer or reader. | Batch 8 computes DAG from the published definition snapshot; do not trust live authoring dependencies for historical runs. |
| Current result files are attached to the current step-result row. | `backend/src/intric/database/tables/flow_tables.py:526-528` keeps one `FlowStepResults` row per run/step, while `backend/src/intric/database/tables/flow_tables.py:695-697` attaches result files to that row. | Batch 8 must prevent old attempt files from rendering as current after a result row is reset. |
| Run `updated_at` is not a stable compare-and-swap token. | `backend/src/intric/database/tables/base_class.py:35-39` sets `updated_at` with `onupdate=func.now()`. | Add a monotonic `FlowRuns.revision` lifecycle token and use `expected_run_revision` in rerun requests. |
| Terminal audit outbox must support rerun terminalization. | `backend/src/intric/database/tables/flow_tables.py:759-821` defines `flow_run_audit_outbox`; rerun reuses the same run id and increments `FlowRuns.revision`. | Key terminal audit rows by `(flow_run_id, run_revision)` so each terminal revision is auditable, while rerun request actor/reason details stay on `flow_run_rerun_operations`. |
| Direct non-interactive Docker calls are blocked in this Codex process, but the plain shell session can run Docker. | `docker ps --format '{{.Names}}' \| sort` was rejected before execution through the direct tool path; the same Docker commands run through the plain shell session. | Keep Docker as canonical validation and record whether each command used the plain shell session. |

## Canonical Ownership Map

| Concept | Current owner | Problem | Batch 8 canonical owner | Add / change / delete path |
|---|---|---|---|---|
| Rerun request and audit fact | None | No durable actor/reason/idempotency owner. | New `FlowRunRerunOperations` table and domain projection. | Add operation rows with actor user, reason, deterministic request fingerprint, status, root step, root attempt number, and timestamps. Do not add a shared audit action in Batch 8. |
| Invalidated steps | None | Downstream invalidation would otherwise be hidden in status updates. | New `FlowRunRerunInvalidatedSteps` rows. | Add one row per root/downstream step with role, step id/order, prior result, and prior attempt links. |
| Run revision | `FlowRuns.updated_at` only | Timestamp precision and unrelated updates make stale-write detection brittle. | `FlowRuns.revision` monotonic lifecycle token. | Add integer revision, return it in public run payloads, require `expected_run_revision` for rerun, and bump on rerun acceptance plus lifecycle transitions touched by Batch 8. |
| Attempt lineage | `FlowStepAttempts` without rerun fields | Attempts are historical but cannot explain supersession. | `FlowStepAttempts` nullable rerun/predecessor/supersession fields. | Add `rerun_operation_id`, `predecessor_attempt_id`, `superseded_by_attempt_id`, and indexes. |
| Historical attempt output evidence | Current `FlowStepResults` only | Clearing current result rows would erase old output payload from export. | `FlowStepAttempts` snapshots. | Add nullable `input_payload_json`, `output_payload_json`, and `flow_step_execution_hash` to attempts; populate on finish. |
| Current artifact visibility | `FlowRunStepResultFiles.step_result_id` only | Old attempt files remain attached to the current result row after an update reset. | `FlowStepResults.current_attempt_no` plus attempt-scoped file rows. | Add nullable `current_attempt_no`; current APIs return files only for the current completed attempt, while evidence/export can still include all attempt-scoped rows. |
| Rerun command transaction | None | Router-only rerun would mix HTTP, permissions, DAG, idempotency, persistence, and dispatch. | `FlowRunService.rerun_step(...)` plus repository transaction methods. | Router validates HTTP and calls service; service coordinates graph, idempotency, invalidation, operation row, and dispatch request. |
| Rerun DAG | API graph helper | API graph output is not a runtime invalidation contract and misses template-derived references. | New `flow_run_rerun_graph.py` narrow runtime module. | Build typed edges from published `RuntimeStep` definitions using `input_source` and static scans of runtime-interpolated fields; return root/downstream IDs in topological order with dependency reasons. |
| Rerun worker behavior | `FlowRunExecutor.execute` | Executor only knows full-run queued execution and uses retry count for attempts. | Executor reads active rerun operation from DB. | Normal executor skips unaffected completed steps, reruns pending invalidated subgraph, uses operation-owned root attempt allocation and repository-owned downstream allocation, and marks operation terminal. |
| Rerun API contract | None | Consumers cannot safely request, retry, or inspect reruns. | `flow_models.py` request/response models and generated client aliases. | Add `POST /flows/{id}/runs/{run_id}/steps/{step_id}/rerun/`, OpenAPI pins, generated schemas, and client wrapper. |
| Rerun frontend status | Existing step/public run projections | UI has no rerun affordance and no invalidated-step status pin. | Existing Flow run/evidence/progress views using generated types. | Add focused rerun confirmation/status behavior without creating frontend-only rerun state. |

## Behavior Pins To Add Or Rewrite BEFORE Deletion / Destructive State Changes

- [ ] Add rerun graph unit tests before state mutation code:
  - root step returns all transitive dependents
  - `previous_step` invalidates only chain dependents
  - `all_previous_steps` invalidates every step that consumes the root
  - `input_bindings.question` invalidates binding-only dependents
  - HTTP input/output URL, header, `body_template`, and `body_json` references invalidate dependents
  - template-fill `output_config.bindings` and assistant snapshot instructions invalidate dependents
  - unrelated later steps remain outside `invalidated_step_ids`
  - rerun graph code has no dependency on live `FlowStepDependencies`
- [ ] Add repository migration/model tests before service implementation:
  - `flow_run_rerun_operations` persists actor, reason, request fingerprint, root step, root attempt number, and status
  - invalidation child rows link prior step result and prior attempt
  - attempt lineage fields are nullable for pre-rerun historical attempts and indexed for evidence lookup
  - `FlowRuns.revision` is present and rerun acceptance bumps it exactly once
  - `FlowStepResults.current_attempt_no` hides prior attempt files from current step responses after invalidation
- [ ] Add API/OpenAPI pins before router implementation:
  - path `/api/v1/flows/{id}/runs/{run_id}/steps/{step_id}/rerun/`
  - operation ID `rerun_flow_run_step`
  - request model requires `expected_run_revision` and reason
  - response model returns `operation_id`, `run`, `rerun_step_id`, `new_attempt_no`, and `invalidated_step_ids`
  - error contracts include stale revision, invalid transition, incomplete root step, invalid root step inputs, and permission denial
- [ ] Add permission matrix tests before enabling `FlowApiAction.RERUN`:
  - `FLOWS_MANAGE` may rerun
  - `FLOWS_RUN`, `FLOWS_VIEW`, and original-run ownership alone may not rerun
  - service-key principals remain denied until a separate explicit service-key rerun capability exists
- [ ] Add service/runtime behavior tests before destructive result clearing:
  - identical deterministic rerun request fingerprint returns the same operation and root attempt number
  - same stale revision with a different request returns `flow_run_rerun_stale_revision`
  - stale expected run revision returns `flow_run_rerun_stale_revision` without mutating rows when no matching operation exists
  - rerun marks root and downstream current result projections pending and clears current output/error fields
  - unaffected completed step rows remain current and are reused by the executor
  - rerun dispatch failure after command commit leaves a queued run and active operation that stale queued redispatch can recover
  - stale queued redispatch of a queued rerun run dispatches exactly once and the executor reads the active rerun operation from DB
- [ ] Add evidence pins before clearing current rows:
  - evidence export includes rerun operations and invalidated step lineage
  - old attempts are marked superseded by the new attempt after rerun succeeds
  - current step results cannot make invalidated downstream output look current
  - historical result files remain in evidence/export but are absent from current step responses until a new attempt completes
- [ ] Add frontend status/component tests before wiring UI:
  - rerun confirmation calls the generated client with reason and expected revision
  - returned invalidated steps render as pending/queued instead of completed
  - rerun API errors use the runtime error mapping, with no frontend-only rerun state source.

## Files To Change

### Tier A — Source-Only / Runtime Code

- `backend/src/intric/flows/flow_run_rerun_graph.py`
  - New narrow runtime/domain module for published-definition DAG traversal.
  - Existing candidates checked: `flow_graph.py` is API-shaped; `step_lineage.py` resolves upstream orders for evidence/prompt lineage, not full invalidation.
- `backend/src/intric/flows/flow_run_rerun_request.py`
  - New narrow domain value objects for deterministic rerun request fingerprints and operation replay decisions.
  - Existing candidates checked: create-run idempotency lives inside `FlowRunService`; rerun needs its own endpoint-specific fingerprint because its canonical owner is the operation row.
- `backend/src/intric/flows/application/flow_run_service.py`
  - Add `rerun_step()` command, idempotency handling, run revision check, step input validation reuse, operation creation, and dispatch request return.
- `backend/src/intric/flows/infrastructure/flow_run_repo.py`
  - Add repository methods for operation creation/lookup, invalidation rows, persisted attempt number allocation, step-result invalidation, active rerun context lookup, and operation terminal status.
- `backend/src/intric/flows/runtime/executor.py`
  - Replace retry-count attempt allocation for Flow runtime with persisted allocation.
  - Read rerun operation context from DB and attach operation/predecessor lineage when creating/finishing attempts.
- `backend/src/intric/flows/flow_run_evidence_bundle.py`
  - Add operation/invalidation/attempt-lineage rows to evidence bundle payload.
- `backend/src/intric/flows/flow_run_export_json.py`
  - Add rerun lineage summary and ensure manifest/export content hash covers the lineage payload.
- `backend/src/intric/flows/api/flow_run_execution_router.py`
  - Add the step-scoped rerun endpoint under the run-lifecycle router because rerun mutates run state.
- `backend/src/intric/flows/api/flow_models.py`
  - Add `FlowRunStepRerunRequest`, `FlowRunStepRerunResponse`, and public rerun lineage models.
- `backend/src/intric/flows/api/flow_assembler.py`
  - Add explicit response assembly for `FlowRunStepRerunResponse` so the router does not shape nested run fields by hand.
- `backend/src/intric/flows/flow_access_policy.py`
  - Enable `FlowApiAction.RERUN` with `FLOWS_MANAGE` as the explicit current equivalent; keep service keys denied.
- `frontend/packages/intric-js/src/endpoints/flows.js`
  - Add generated-client-adjacent rerun wrapper under the existing flow run route owner.
- `frontend/packages/intric-js/src/types/resources.d.ts`
  - No handwritten rerun resource alias in Batch 8; use the generated schema type names unless existing package exports fail validation.
- `frontend/apps/web/src/lib/features/flows/flowRuntimeErrorMapping.ts`
  - Replace the current unsupported-code-only mapping with real stale-revision, invalid-transition, step-input, and permission messages where user-facing errors are needed.
- `frontend/apps/web/src/lib/features/flows/components/FlowRunEvidenceStepCard.svelte`
  - Add the rerun affordance as a thin UI caller of generated/client state.
- `frontend/apps/web/src/lib/features/flows/components/flowRunProgress.ts`
  - Ensure pending invalidated steps render from backend step status, not local rerun flags.

### Tier B — Persisted / Public Contract

- `backend/src/intric/database/tables/flow_tables.py`
  - Add `FlowRunRerunOperations`.
  - Add `FlowRunRerunInvalidatedSteps`.
  - Add nullable attempt lineage/snapshot columns to `FlowStepAttempts`.
  - Add `FlowRuns.revision`.
  - Add `FlowStepResults.current_attempt_no`.
  - Do not add a live `FlowSteps` FK for operation root step id; the published snapshot is the historical owner and live step rows can change after the run.
- `backend/alembic/versions/20260502_rerun_ops.py`
  - Create operation and invalidated-step tables.
  - Add attempt columns and indexes.
  - Down revision should follow `20260430_flow_step_file_mappings` unless another migration lands first.
- `backend/alembic/versions/20260502_rerun_runtime_lineage.py`
  - Add active-rerun uniqueness and terminal audit outbox revision keying as a forward migration.
- `frontend/packages/intric-js/src/types/schema.d.ts`
  - Update generated Flow rerun API contract after OpenAPI is stable.
- `frontend/apps/web/messages/en.json`
- `frontend/apps/web/messages/sv.json`
  - Add rerun UI/error strings together if UI text is added.

### Tests

- `backend/tests/unittests/flows/test_flow_rerun_graph.py`
- `backend/tests/unittests/flows/test_flow_rerun_architecture.py`
- `backend/tests/integration/flows/test_flow_rerun_contract.py`
- `backend/tests/integration/flows/test_flow_runtime_worker_contract.py`
- `backend/tests/unittests/flows/test_flow_run_service.py`
- `backend/tests/unittests/flows/test_flow_router.py`
- `backend/tests/unittests/flows/test_flow_access_policy.py`
- `backend/tests/unit/test_flow_openapi_contract.py`
- `backend/tests/integration/flows/test_flow_evidence_api_contracts.py`
- `frontend/packages/intric-js/src/endpoints/flows.test.js`
- `frontend/apps/web/src/lib/features/flows/components/flowRunProgress.test.ts`
- `frontend/apps/web/src/lib/features/flows/components/FlowRunEvidenceStepCard.test.ts`

## Data Model Decision

### `flow_runs.revision`

`FlowRuns.revision` is the compare-and-swap token for rerun and Batch 9 resume.

- Add `revision INTEGER NOT NULL DEFAULT 1`.
- Include it in `FlowRun` and `FlowRunPublic`.
- Require `expected_run_revision` on rerun requests.
- Repository updates that accept a rerun bump `revision = revision + 1` in the same row-locked transaction.
- Batch 8 bumps revision on rerun acceptance and on the lifecycle writes it touches for queued-to-running, terminalization, and cancellation. Older write paths that Batch 8 does not touch must not be used as rerun compare tokens.

`updated_at` remains display metadata, not a revision contract.

### `flow_step_results.current_attempt_no`

`FlowStepResults` remains the current projection, while attempts and file rows hold history.

- Add nullable `current_attempt_no`.
- The migration default makes existing current rows read as first-attempt rows without a separate table-wide backfill update.
- Initial preseed rows use `1` for consistency with first-attempt input/result file rows.
- Rerun invalidation sets `current_attempt_no = NULL` on root/downstream current rows while clearing current output, error, prompt, token, execution hash, and display artifact fields.
- Successful step persistence sets `current_attempt_no = attempt_no`.
- Current step APIs include result files only when `FlowStepResults.status = completed` and `FlowRunStepResultFiles.attempt_no = FlowStepResults.current_attempt_no`.
- Evidence/export include all attempt-scoped result files so old artifacts remain auditable after current projection reset.

### `flow_run_rerun_operations`

The operation row is the canonical rerun request and audit fact.

Planned columns:

- `id`
- `tenant_id`
- `flow_id`
- `flow_run_id`
- `rerun_step_id`
- `rerun_step_order`
- `root_attempt_no`
- `root_attempt_id`
- `status`: `queued`, `running`, `completed`, `failed`, `cancelled`
- `request_fingerprint`
- `expected_run_revision`
- `accepted_run_revision`
- `reason`
- `input_payload_json`
- `step_inputs_json`
- `requested_by_principal_type`
- `requested_by_user_id`
- `failure_code`
- `failure_message`
- `started_at`
- `finished_at`
- normal `created_at` / `updated_at`

Constraints and indexes:

- composite FK `(flow_run_id, tenant_id)` to `flow_runs`
- composite FK `(flow_run_id, flow_id)` to `flow_runs`
- FK `tenant_id` to tenants and `flow_id` to flows
- check status values
- check actor identity by principal type; Batch 8 only writes user principals because service-key rerun is denied
- unique `(tenant_id, flow_run_id, request_fingerprint)`
- index `(flow_run_id, status)`
- index `(tenant_id, created_at)`
- index `(flow_run_id, rerun_step_id)`

The root `rerun_step_id` intentionally does not FK to live `flow_steps`. A rerun is version-pinned to `flow_versions.definition_json`; live authoring steps can be edited or deleted after the run, so a live-step FK would point at the wrong owner.

`flow_run_rerun_operations` is also the Batch 8 audit owner for rerun requests. Do not add `ActionType.FLOW_RUN_RERUN_REQUESTED` and do not call `audit_service.log_async` from the rerun endpoint. `flow_run_audit_outbox` remains the terminal lifecycle audit owner, keyed by `(flow_run_id, run_revision)` so the initial run and each rerun terminal revision can emit a terminal audit row without mixing rerun request fields into the outbox.

Terminalization closes active rerun operations. If the run is cancelled, active `queued` or `running` rerun operations become `cancelled`. If another terminalization path fails the run while a rerun is active, the operation becomes `failed` with `failure_code = "run_terminalized"`.

The repository allocates `root_attempt_no` while holding the run row lock and stores it on the operation row. The executor reads that value for the root step; it does not recompute root attempt numbers from Celery retry count or from current history. Downstream attempt numbers are allocated under the operation/run lock when the executor claims each downstream invalidated step and are written to `flow_run_rerun_invalidated_steps`.

Idempotency is deterministic. The request fingerprint is built from tenant, user principal, flow id, run id, rerun step id, expected run revision, prior root attempt id, normalized inline payload, and normalized root `step_inputs`. A replay with the same fingerprint returns the existing operation. A different request against an already advanced revision returns stale revision, not a separate compatibility branch.

### `flow_run_rerun_invalidated_steps`

Invalidated rows make downstream invalidation explicit and auditable.

Planned columns:

- `id`
- `operation_id`
- `tenant_id`
- `flow_id`
- `flow_run_id`
- `step_id`
- `step_order`
- `invalidation_order`
- `role`: `root` or `downstream`
- `dependency_sources_json`
- `prior_step_result_id`
- `prior_attempt_id`
- `new_attempt_no`
- `new_attempt_id`

Constraints and indexes:

- FK `operation_id` to `flow_run_rerun_operations`
- composite FKs back to run/tenant and run/flow
- nullable FK `prior_step_result_id` to `flow_step_results`
- nullable FK `prior_attempt_id` and `new_attempt_id` to `flow_step_attempts`
- unique `(operation_id, step_id)`
- unique `(operation_id, invalidation_order)`
- index `(flow_run_id, step_id)`
- index `(prior_attempt_id)` and `(new_attempt_id)`

`dependency_sources_json` stores a typed list rendered by `flow_run_rerun_graph.py`. It exists to make the invalidation reason reviewable in evidence exports; it is not used as executable graph state.

The allowed `RerunDependencyKind` values are:

- `input_source.previous_step`
- `input_source.all_previous_steps`
- `input_bindings.question`
- `input_config.url`
- `input_config.headers`
- `input_config.body_template`
- `input_config.body_json`
- `output_config.url`
- `output_config.headers`
- `output_config.body_template`
- `output_config.body_json`
- `output_config.bindings`
- `assistant_snapshot.instructions`
- `runtime_alias.previous_step`

### `flow_step_attempts` additions

Attempts become the historical owner for rerun output lineage.

Planned nullable columns:

- `rerun_operation_id`
- `predecessor_attempt_id`
- `superseded_by_attempt_id`
- `input_payload_json`
- `output_payload_json`
- `flow_step_execution_hash`

Indexes:

- `ix_flow_step_attempts_rerun_operation`
- `ix_flow_step_attempts_predecessor_attempt`
- `ix_flow_step_attempts_superseded_by_attempt`

These columns are nullable so existing pre-rerun attempts remain valid without a compatibility branch in code.

Attempt snapshots are the owner of the input/output data used for evidence after a current projection reset. For root rerun attempts, repository writes request `step_inputs` when supplied; when omitted, it copies prior root attempt input-file rows. For downstream invalidated attempts, repository copies prior attempt input-file rows before execution. Resolved input payloads are written to `FlowStepAttempts.input_payload_json` at finish/failure from the same payload persisted to the current result row.

## API Contract

Endpoint:

```text
POST /api/v1/flows/{id}/runs/{run_id}/steps/{step_id}/rerun/
operation_id: rerun_flow_run_step
```

Request:

```json
{
  "expected_run_revision": 7,
  "reason": "Corrected source transcript",
  "input_payload_json": {"case_id": "A-123"},
  "step_inputs": {
    "step-uuid": {"file_ids": ["file-uuid"]}
  }
}
```

Response:

```json
{
  "operation_id": "operation-uuid",
  "run": {},
  "rerun_step_id": "step-uuid",
  "new_attempt_no": 2,
  "invalidated_step_ids": ["downstream-step-uuid"],
  "status": "queued"
}
```

Error codes:

- `flow_run_rerun_stale_revision` for stale `expected_run_revision`
- `flow_run_rerun_invalid_transition` for queued/running/cancelled runs
- `flow_run_rerun_step_not_found` for a step absent from the run's published snapshot
- `flow_run_rerun_step_incomplete` when an invalidated current result row is missing or the root step has no completed current result
- `flow_run_rerun_reason_required` for empty or whitespace-only reason values
- `flow_run_rerun_step_inputs_invalid` for step input payloads outside the rerun root
- HTTP request validation errors (`422`) for structurally invalid rerun requests, including reason values over 1024 characters and `expected_run_revision < 1`
- existing permission errors from the Flow access policy

Concurrent reruns do not get a second public conflict code in Batch 8. A same-fingerprint replay returns the existing operation, while a different request after revision advancement returns `flow_run_rerun_stale_revision`.

## Rerun Algorithm

1. Router enforces flow scope with `FlowApiAction.RERUN`; service keys remain denied.
2. Service loads the run under tenant scope and checks `expected_run_revision`.
3. Service rejects active/cancelled runs. Completed and failed runs are eligible if the root step result is completed.
4. Service loads the run's published `FlowVersion.definition_json` and parses runtime steps.
5. Rerun graph computes transitive dependents from the root using published snapshot semantics:
   - `previous_step`: edge from previous order to current step
   - `all_previous_steps`: edges from every earlier step to current step
   - `flow_input`, `http_get`, `http_post`: no implicit step parent edge
   - static references in `input_bindings`, HTTP input/output config templates, template-fill bindings, and assistant snapshot instructions add explicit step parent edges
6. Service normalizes and validates rerun `step_inputs` against the root step only. It reuses the existing step-input validator and rejects downstream step inputs.
7. Repository creates or replays the deterministic operation row by `request_fingerprint`. If creating, it holds the run row lock, checks the expected revision, allocates `root_attempt_no`, writes the operation, writes invalidation rows in topological order, bumps the run revision, and resets current projections.
8. Repository writes invalidated-step rows for root plus downstream steps, linking prior current result and prior latest completed attempt where present.
9. Repository marks root and downstream current result projections pending, sets `current_attempt_no = NULL`, and clears current output/error/current artifact display fields so stale downstream output cannot read as current.
10. Repository sets the run back to queued and clears terminal output/error/finished fields.
11. Router schedules the normal Flow execution backend with IDs only through a rerun-aware dispatch-after-commit path. The existing create-run helper terminalizes on dispatch failure, so Batch 8 must either add a rerun-specific helper or generalize that helper with explicit recoverable-dispatch behavior.
12. Executor reloads the active operation and invalidated-step rows from DB. It uses `root_attempt_no` from the operation and repository-allocated downstream attempt numbers; it does not use Celery retry count or in-memory rerun lineage from the task payload.
13. Executor skips unaffected completed steps, executes pending invalidated steps, writes attempt lineage/input/output snapshots, and fills `new_attempt_no`/`new_attempt_id` on invalidated-step rows.
14. On successful replacement, repository sets the prior attempt's `superseded_by_attempt_id`.
15. If dispatch fails before execution starts, the run and operation stay queued so stale queued redispatch can recover them. The redispatch integration test must prove dispatch failure, queued operation recovery, active-operation reload, and single execution of the invalidated subgraph.
16. Terminalization closes active rerun operations using the status rule defined above.
17. Evidence bundle/export includes operations, invalidated steps, and attempt predecessor/supersession fields.

## Slice 8.5 Repository Command Contract

The repository command is the canonical writer for rerun operation acceptance. It runs inside the caller's existing unit-of-work session; operation insert, invalidated-step inserts, run reset, revision bump, and current-result resets commit together or roll back together. No operation row may commit without the matching run/result mutation.

Fresh operation insertion uses the same idempotent insert pattern as `FlowRunRepository.create_or_get_attempt_started`: PostgreSQL `INSERT ... ON CONFLICT DO NOTHING` against `uq_flow_run_rerun_operations_request_fingerprint`, followed by a select fallback. Concurrent identical rerun requests must both observe the same operation row. Different requests after a revision bump return `flow_run_rerun_stale_revision`.

Replay happens before state-transition checks. A same-fingerprint replay returns:

- the current persisted operation row, including its current status
- the latest persisted run row
- all persisted invalidated-step rows for the operation

The repository does not hide executor progress from callers; API assembly decides how to expose the latest operation/run state.

### Rerun Versus Retry Boundary

Batch 8 rerun replaces a previously completed step output and invalidates downstream outputs. Every invalidated step must already have a current-result row because rerun updates the current projection instead of creating a second current path. A root step whose current result is `failed`, `pending`, `running`, or `cancelled` is not eligible for rerun. Failed current steps require retry/recovery semantics, not rerun semantics, because they do not have a completed current output to supersede. The stable error code is `flow_run_rerun_step_incomplete`.

### Operation Row Insert Values

The command requires these caller inputs:

| Input | Stored column / use |
|---|---|
| `tenant_id` | `flow_run_rerun_operations.tenant_id` and tenant-scoped queries |
| `flow_id` | `flow_run_rerun_operations.flow_id` and flow-scoped queries |
| `flow_run_id` | `flow_run_rerun_operations.flow_run_id` |
| `rerun_step_id` | `flow_run_rerun_operations.rerun_step_id` |
| `rerun_step_order` | `flow_run_rerun_operations.rerun_step_order` |
| `request_fingerprint` | `flow_run_rerun_operations.request_fingerprint` idempotency key |
| `expected_run_revision` | `flow_run_rerun_operations.expected_run_revision` |
| `reason` | `flow_run_rerun_operations.reason`; required non-empty API input |
| `input_payload_json` | `flow_run_rerun_operations.input_payload_json`; nullable |
| `step_inputs_json` | `flow_run_rerun_operations.step_inputs_json`; nullable |
| `requested_by_principal_type` | `flow_run_rerun_operations.requested_by_principal_type`; Batch 8 writes only `user` |
| `requested_by_user_id` | `flow_run_rerun_operations.requested_by_user_id` |

On fresh insert:

| Column | Value |
|---|---|
| `status` | `queued` |
| `started_at` | `NULL` |
| `finished_at` | `NULL` |
| `failure_code` | `NULL` |
| `failure_message` | `NULL` |
| `expected_run_revision` | requester-supplied CAS value |
| `accepted_run_revision` | the run revision observed under lock; equal to `expected_run_revision` on the fresh path |
| `root_attempt_no` | `max(flow_step_attempts.attempt_no for root step) + 1`, with `0 + 1` when no prior attempt row exists |
| `root_attempt_id` | `NULL` until the executor creates the root attempt |

The run row is locked before allocating `root_attempt_no`; `uq_flow_step_attempts_run_step_attempt` remains the structural backstop when the executor later creates the attempt row. The command does not pre-create `flow_step_attempts` rows.

### Rejection Order And Error Codes

After replay lookup misses, the fresh path rejects in this order:

1. Lock run by `flow_run_id`, `flow_id`, and `tenant_id`; missing row surfaces as `not_found`.
2. `expected_run_revision != FlowRuns.revision` returns `flow_run_rerun_stale_revision`.
3. `FlowRuns.status` outside `completed` or `failed` returns `flow_run_rerun_invalid_transition`.
4. `rerun_step_id` absent from the run's published runtime step list returns `flow_run_rerun_step_not_found`.
5. Any invalidated step without a current `FlowStepResults` row returns `flow_run_rerun_step_incomplete`.
6. Root current `FlowStepResults.status != completed` returns `flow_run_rerun_step_incomplete`.

### Run Reset Values

On fresh acceptance, update only these `FlowRuns` columns:

| Column | New value |
|---|---|
| `status` | `queued` |
| `revision` | `accepted_run_revision + 1` |
| `output_payload_json` | `NULL` |
| `error_message` | `NULL` |
| `started_at` | `NULL` |
| `finished_at` | `NULL` |
| `cancelled_at` | `NULL` |

Do not change `trace_id`, original create-run `idempotency_key`, original create-run `request_fingerprint`, principal columns, `flow_id`, `flow_version`, `input_payload_json`, or `job_id`.

### Step Result Reset Values

On fresh acceptance, reset the root and downstream current `FlowStepResults` rows using one canonical reset map:

| Column | New value |
|---|---|
| `status` | `pending` |
| `current_attempt_no` | `NULL` |
| `input_payload_json` | `NULL` |
| `output_payload_json` | `NULL` |
| `effective_prompt` | `NULL` |
| `model_parameters_json` | `NULL` |
| `num_tokens_input` | `NULL` |
| `num_tokens_output` | `NULL` |
| `error_message` | `NULL` |
| `flow_step_execution_hash` | `NULL` |
| `tool_calls_metadata` | `NULL` |
| `started_at` | `NULL` |
| `finished_at` | `NULL` |

Do not change row identity, run/flow/tenant IDs, `step_id`, `step_order`, `assistant_id`, or `created_at`.

### Invalidated Step Rows

`flow_run_rerun_invalidated_steps` rows are deterministic:

- `invalidation_order` is contiguous, starts at `1`, and follows `step_order` ascending.
- The root row uses `role = root` and `dependency_sources_json = []`.
- Downstream rows use `role = downstream` and persist the graph's `RerunDependencyKind.value` strings from `RerunInvalidatedStep.dependency_kinds`.
- `prior_step_result_id` links the current result row that was reset.
- `prior_attempt_id` links the latest completed attempt for the step, if any.
- `new_attempt_no` and `new_attempt_id` remain `NULL` until the executor claims that invalidated step.

### Slice 8.5 Tests

- Fresh operation acceptance writes operation, invalidated-step rows, run reset, revision bump, and step-result resets in one transaction.
- Rolling back the caller transaction after command execution leaves no rerun operation or invalidated rows.
- Same-fingerprint concurrent requests both observe one operation row through the `ON CONFLICT DO NOTHING` pattern.
- Stale revision returns `flow_run_rerun_stale_revision` and does not mutate rows.
- Cancelled/running/queued runs return `flow_run_rerun_invalid_transition`.
- A failed root step result returns `flow_run_rerun_step_incomplete`; completed roots are eligible.
- A missing current-result row for any invalidated step returns `flow_run_rerun_step_incomplete`.
- A rerun step absent from the published definition snapshot returns `flow_run_rerun_step_not_found`.
- Invalidated rows pin root/downstream roles, contiguous invalidation order, and `dependency_sources_json`, including the `föregående_steg` runtime-alias dependency from the graph.
- Tenant filters are present on lock and mutation queries.

### Slice 8.5 Validation Commands

Run these for the repository-command slice before Claude implementation review:

```bash
docker exec -w /workspace/backend eneo-41ae93-eneo-1 .venv/bin/pytest tests/integration/flows/test_flow_run_rerun_repository.py tests/unittests/flows/test_flow_rerun_graph.py tests/unittests/flows/test_flow_rerun_architecture.py tests/unittests/flows/test_flow_access_policy.py -q
docker exec -w /workspace/backend eneo-41ae93-eneo-1 .venv/bin/ruff check src/intric/flows/infrastructure/flow_run_repo.py src/intric/flows/flow_factory.py tests/integration/flows/test_flow_run_rerun_repository.py
docker exec -w /workspace/backend eneo-41ae93-eneo-1 .venv/bin/pyright --pythonpath .venv/bin/python src/intric/flows/infrastructure/flow_run_repo.py src/intric/flows/flow_factory.py tests/integration/flows/test_flow_run_rerun_repository.py
```

Local fallback commands use the same paths with `uv run pytest`, `uv run ruff check`, and `uv run pyright`.

## Slice 8.6 Service Command Contract

The service command is the application boundary for rerun acceptance. It does not add the HTTP route, executor behavior, evidence export, or frontend UI. Those slices call this command after the application contract is pinned.

### Canonical Owner

`FlowRunService.rerun_step(...)` owns:

- loading the tenant-scoped run
- loading the run's immutable `FlowVersion.definition_json`
- parsing published runtime steps
- computing the rerun invalidation graph
- validating the rerun reason and inline payload
- accepting only root-step `step_inputs`
- computing the deterministic rerun request fingerprint
- calling `FlowRunRepository.accept_or_replay_rerun_operation(...)`

`FlowRunRepository` remains the canonical writer for operation rows, invalidated rows, run revision changes, and current-result resets. The service must not duplicate repository mutation logic.

### Service Inputs

Add this keyword-only application method:

```python
async def rerun_step(
    *,
    flow_id: UUID,
    run_id: UUID,
    rerun_step_id: UUID,
    expected_run_revision: int,
    reason: str,
    input_payload_json: dict[str, Any] | None = None,
    step_inputs: dict[UUID, dict[str, list[UUID]]] | None = None,
) -> FlowRunRerunCommandResult: ...
```

The service returns the repository command result for now. The API response assembler slice can map it into a public model without adding a second service DTO in this slice.

`flow_id` stays in the service signature because the route contains both flow and run identifiers; the service uses it when loading the run so a mismatched run id is invisible under the requested flow.

### Validation And Rejection

- `reason` is trimmed with `strip()`, must be non-empty after trimming, and is capped at 1024 characters. Empty or whitespace-only `reason` returns `flow_run_rerun_reason_required`; too-long `reason` returns `flow_run_rerun_reason_too_long`.
- Service-key denial is owned by `FlowAccessPolicy` from Slice 8.4. The service does not add a duplicate principal gate; router tests must keep proving service-key rerun is denied before this command is called.
- `input_payload_json` is normalized with the flow definition snapshot metadata only when supplied. Omitted payload means "reuse existing run input"; it must not trigger required-form-field validation.
- Supplied `input_payload_json` is a complete replacement payload for the rerun operation. If it is missing required form fields in the published snapshot, existing payload validation errors propagate; the service does not merge it with the original run input.
- Reserved orchestration keys remain rejected through the existing `_reject_reserved_input_payload_keys(...)`.
- `step_inputs` is normalized through `normalize_step_inputs_payload(...)`.
- Any `step_inputs` key other than the rerun root `rerun_step_id` returns `flow_run_rerun_step_inputs_invalid`.
- Root `step_inputs` validation reuses `validate_submitted_step_inputs(...)` with only the root step's runtime input spec, so downstream required inputs do not block a root rerun.
- A root absent from the published definition returns `flow_run_rerun_step_not_found`.

### Fingerprint Inputs

The service builds `FlowRunRerunRequestFingerprintInput` with:

- tenant id
- requesting user id
- flow id
- run id
- root step id
- expected run revision
- latest completed root attempt id, if any
- normalized inline payload, if supplied
- normalized root step input file ids, if supplied

The latest completed root attempt id comes from `FlowRunRepository.get_latest_completed_attempt_id_for_step(...)`. Do not list all attempts in the service just to derive one id.

### Repository Call

The service passes to `accept_or_replay_rerun_operation(...)`:

- tenant, flow, run, root step id, root step order
- deterministic fingerprint
- expected run revision
- normalized reason
- normalized inline payload
- serialized root step inputs or `None`
- requesting user id
- graph invalidated steps

`rerun_step_order` is derived from the published runtime step whose `step_id == rerun_step_id`; the service must not hardcode the order.

The service must not dispatch work in this slice. The router/dispatch slice will decide when to enqueue based on `result.created` and will use a rerun-aware recoverable dispatch helper.

### Slice 8.6 Tests

Add focused unit tests in `backend/tests/unittests/flows/test_flow_run_service.py`:

- service builds a published-snapshot graph and passes root/downstream invalidation rows to the repository command
- deterministic fingerprint includes latest completed root attempt id and is stable across equivalent root input ordering
- deterministic fingerprint uses `None` when there is no completed root attempt
- same repository replay result is returned without additional mutation logic
- empty or whitespace-only reason returns `flow_run_rerun_reason_required`
- a 1024-character reason is accepted
- reason values over 1024 characters return `flow_run_rerun_reason_too_long`
- root step absent from the published definition returns `flow_run_rerun_step_not_found`
- explicit empty root `step_inputs` are preserved as a distinct fingerprint and serialized payload
- downstream `step_inputs` are rejected with `flow_run_rerun_step_inputs_invalid`
- omitted inline payload does not require form fields from the published snapshot
- supplied inline payload rejects reserved orchestration keys
- service-key denial remains covered by the Slice 8.4 access-policy tests, not a duplicate service test

Add one repository integration test in `backend/tests/integration/flows/test_flow_run_rerun_repository.py`:

- `get_latest_completed_attempt_id_for_step(...)` returns the latest completed root attempt by highest completed `attempt_no`, ignores attempts outside the requested flow, ignores higher failed attempts, and returns `None` when the scoped row does not exist.

### Slice 8.6 Validation Commands

Run these for the service-command slice before Claude implementation review:

```bash
docker exec -w /workspace/backend eneo-41ae93-eneo-1 .venv/bin/pytest tests/unittests/flows/test_flow_run_service.py -k 'rerun_step' -q
docker exec -w /workspace/backend eneo-41ae93-eneo-1 .venv/bin/pytest tests/integration/flows/test_flow_run_rerun_repository.py -k 'latest_completed_attempt' -q
docker exec -w /workspace/backend eneo-41ae93-eneo-1 .venv/bin/pytest tests/unittests/flows/test_flow_run_service.py tests/integration/flows/test_flow_run_rerun_repository.py -q
docker exec -w /workspace/backend eneo-41ae93-eneo-1 .venv/bin/ruff check src/intric/flows/application/flow_run_service.py src/intric/flows/infrastructure/flow_run_repo.py tests/unittests/flows/test_flow_run_service.py tests/integration/flows/test_flow_run_rerun_repository.py
docker exec -w /workspace/backend eneo-41ae93-eneo-1 .venv/bin/pyright --pythonpath .venv/bin/python src/intric/flows/application/flow_run_service.py src/intric/flows/infrastructure/flow_run_repo.py tests/unittests/flows/test_flow_run_service.py tests/integration/flows/test_flow_run_rerun_repository.py
git diff --check
```

The focused test names may be adjusted only if the final names remain service-command-specific and are recorded in the journal.

## Slice 8.7 API Contract And Recoverable Dispatch

The API slice exposes the service command without moving rerun ownership into the router. It also adds the recoverable dispatch path required by the Batch 8 algorithm: dispatch failure after the repository command commits must leave the run queued so stale queued redispatch can recover it.

### Canonical Owners

| Concept | Canonical owner | Decision |
|---|---|---|
| Public rerun request/response schemas | `backend/src/intric/flows/api/flow_models.py` | Add narrow `FlowRunStepRerunRequest` and `FlowRunStepRerunResponse` models next to the existing runtime API schemas. Reuse `StepRunInput` for root step file inputs. |
| Rerun response assembly | `backend/src/intric/flows/api/flow_assembler.py` | Add a typed assembler method so the router does not hand-shape nested run fields or invalidated-step IDs. |
| Rerun HTTP endpoint | `backend/src/intric/flows/api/flow_run_execution_router.py` | Add `POST /api/v1/flows/{id}/runs/{run_id}/steps/{step_id}/rerun/` under the run-lifecycle router. The path remains step-scoped, but the file owner is the execution router because rerun mutates run lifecycle state. |
| Recoverable dispatch-after-commit | `backend/src/intric/flows/application/flow_dispatch.py` | Add a recoverable dispatch wrapper that shares a private dispatch core with the create-run helper. The wrappers differ only in failure policy: create-run terminalizes, rerun logs and leaves queued state recoverable. |
| Application dispatch export | `backend/src/intric/flows/application/__init__.py` | Re-export the recoverable dispatch helper through the existing lazy application export pattern so import-safety tests pin the canonical path. |
| Flow run revision token | `FlowRunPublic` in `flow_models.py` | Expose `revision` because API consumers need the compare token for `expected_run_revision`. `updated_at` remains display metadata. Add a field description making clear that the current public consumer is the rerun endpoint. |

### Request Contract

Add:

```python
class FlowRunStepRerunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_run_revision: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=1024)
    input_payload_json: dict[str, Any] | None = None
    step_inputs: dict[UUID, StepRunInput] | None = None
```

Rules:

- `expected_run_revision` is required and must be `>= 1`. Malformed compare tokens are `422`; honest stale compare tokens remain `flow_run_rerun_stale_revision`.
- `reason` is required and must be at most 1024 characters at the HTTP boundary.
- The service still strips the reason and returns `flow_run_rerun_reason_required` for whitespace-only values. Its too-long check remains a defensive application-layer guard for non-HTTP callers, not the primary public HTTP surface.
- `step_inputs` may include only the rerun root step. The service owns root-only validation because it has the published snapshot.
- Unknown top-level request keys are rejected by `extra="forbid"`. Do not add a `file_ids`-specific removed-field validator because rerun never shipped that request shape.

### Response Contract

Add:

```python
class FlowRunStepRerunResponse(BaseModel):
    operation_id: UUID
    run: FlowRunPublic
    rerun_step_id: UUID
    new_attempt_no: int
    invalidated_step_ids: list[UUID]
    status: FlowRunRerunOperationStatus
```

`new_attempt_no` is the root operation's allocated root attempt number. Downstream attempt numbers are executor-owned and remain absent until the worker claims each invalidated step.

On idempotent replay, `result.run` reflects the current persisted run row, including any revision bumps from worker progress after the original acceptance. `result.created` is `false`, and `operation.status` reflects the current operation status.

`FlowRunStepRerunResponse.run` must have an OpenAPI description explaining that it is the current persisted run state; on idempotent replay, `run.revision` may have advanced past the request's `expected_run_revision`. `FlowRunPublic.revision` must be required in the OpenAPI component.

### Endpoint Contract

Add to `flow_run_execution_router.py`:

- path: `/{id}/runs/{run_id}/steps/{step_id}/rerun/`
- method: `POST`
- status: `202 Accepted`
- operation ID: `rerun_flow_run_step`
- permission: `FlowApiAction.RERUN`
- service-key principals: denied by `FlowAccessPolicy`
- response model: `FlowRunStepRerunResponse`
- response status: `202` for both created operations and idempotent replays. The endpoint description must explain that `202` means the rerun request was accepted or replayed; operation lifecycle is reported by the response `status` field.

Router behavior:

1. Enforce flow scope with `FlowApiAction.RERUN`.
2. Convert `step_inputs` from `StepRunInput` models to plain Python data.
3. Call `FlowRunService.rerun_step(...)`.
4. If `result.created` is true, schedule the recoverable dispatch helper with `run_service.build_dispatch_request(result.run)`.
5. If `result.created` is false, return the replayed operation and do not schedule another dispatch.
6. Return the assembler-built response.

The router must not call `audit_service.log_async` for rerun. `flow_run_rerun_operations` is the Batch 8 audit fact and owns actor/reason/idempotency.

### Recoverable Dispatch Contract

Add `dispatch_flow_run_recoverably_after_commit(...)` next to `dispatch_flow_run_after_commit(...)`.

- It dispatches through the normal `FlowExecutionBackend`.
- It accepts the same ID/principal payload as `dispatch_flow_run_after_commit(...)`.
- Both public helpers share one private dispatch core so dispatch payload assembly has one owner.
- On dispatch failure, it logs and returns without terminalizing the run.
- It does not mark the rerun operation failed. A queued run plus active queued operation is recoverable by stale queued redispatch.
- It is exposed through `flow_router_common.py` for router scheduling, matching the current create-run dispatch import pattern.
- It is also re-exported from `intric.flows.application` through the existing lazy export pattern and covered by startup import tests.

Do not duplicate backend dispatch payload assembly between helpers. Keep the different failure policies explicit in the public helper names.

### OpenAPI / Consumer Contract Pins

Update `backend/tests/unit/test_flow_openapi_contract.py` to prove:

- required path `/api/v1/flows/{id}/runs/{run_id}/steps/{step_id}/rerun/`
- operation ID `rerun_flow_run_step`
- request schema `FlowRunStepRerunRequest`
- response schema `FlowRunStepRerunResponse` under status `202`
- required error responses: `400`, `403`, `404`, `422`
- `FlowRunPublic` exposes `revision`
- `FlowRunPublic.revision` is required in the component schema
- rerun request requires `expected_run_revision` and `reason`
- rerun request schema has `expected_run_revision >= 1`, `reason` max length 1024, and rejects unknown top-level keys
- `FlowRunPublic.revision` has a description that scopes Batch 8 compare-token use to rerun
- `FlowRunStepRerunResponse.run` documents current persisted run state and replay revision advancement

### Router And Dispatch Tests

Add focused tests in `backend/tests/unittests/flows/test_flow_router.py`:

- router calls `rerun_step(...)` with path IDs, `expected_run_revision`, reason, optional inline payload, and step input file IDs
- created rerun schedules `dispatch_flow_run_recoverably_after_commit(...)` once using `build_dispatch_request(result.run)`
- replayed rerun response does not schedule dispatch
- stale revision from `rerun_step(...)` propagates and does not schedule dispatch
- endpoint permission matrix rejects `FLOWS_VIEW`, `FLOWS_RUN`, original-run ownership alone, and service-key principals before calling `rerun_step(...)`; `FLOWS_MANAGE` is accepted
- response includes `operation_id`, nested run with `revision`, root `new_attempt_no`, invalidated step IDs, and operation status
- recoverable dispatch helper dispatches successfully without terminalization
- recoverable dispatch helper logs dispatch failure and does not terminalize the run
- shared dispatch core test spies on the private core and asserts both public wrappers call it with equivalent dispatch kwargs for the same input
- startup import tests assert the recoverable dispatch helper is available through the canonical application package export without changing import side effects

### Slice 8.7 Validation Commands

Run these before Claude implementation review:

```bash
docker exec -w /workspace/backend eneo-41ae93-eneo-1 .venv/bin/pytest tests/unittests/flows/test_flow_router.py -k 'rerun_flow_run_step or recoverably_after_commit or dispatch_after_commit_wrappers_share_dispatch_core' -q
docker exec -w /workspace/backend eneo-41ae93-eneo-1 .venv/bin/pytest tests/unit/test_flow_openapi_contract.py -k 'rerun or revision' -q
docker exec -w /workspace/backend eneo-41ae93-eneo-1 .venv/bin/pytest tests/unit/test_server_startup_imports.py -q
docker exec -w /workspace/backend eneo-41ae93-eneo-1 .venv/bin/ruff check src/intric/flows/api/flow_models.py src/intric/flows/api/flow_assembler.py src/intric/flows/api/flow_run_execution_router.py src/intric/flows/api/flow_router_common.py src/intric/flows/application/__init__.py src/intric/flows/application/flow_dispatch.py tests/unittests/flows/test_flow_router.py tests/unit/test_flow_openapi_contract.py tests/unit/test_server_startup_imports.py
docker exec -w /workspace/backend eneo-41ae93-eneo-1 .venv/bin/pyright --pythonpath .venv/bin/python src/intric/flows/api/flow_models.py src/intric/flows/api/flow_assembler.py src/intric/flows/api/flow_run_execution_router.py src/intric/flows/api/flow_router_common.py src/intric/flows/application/__init__.py src/intric/flows/application/flow_dispatch.py tests/unittests/flows/test_flow_router.py tests/unit/test_flow_openapi_contract.py tests/unit/test_server_startup_imports.py
git diff --check
```

Run this guard before commit:

```bash
git diff -- backend/src/intric/flows backend/tests/unittests/flows/test_flow_router.py backend/tests/unit/test_flow_openapi_contract.py backend/tests/unit/test_server_startup_imports.py | rg '^\+.*(deprecated|legacy|backwards compat|backward compat|compatibility shim|rerun.*redispatch|redispatch.*rerun)' || true
```

## Slice 8.9 Evidence Rerun Lineage

This slice completes the backend evidence contract for Batch 8. It makes rerun
operation rows and invalidated-step rows visible through the same canonical
evidence bundle/export path that already owns step results, step attempts, and
result files.

### Canonical Owners

| Concept | Canonical owner | Decision |
|---|---|---|
| Rerun request/audit fact in evidence | `flow_run_rerun_operations` via `FlowRunRepository` | Add a tenant-scoped run query and expose rows as typed evidence payload, not as an ad hoc debug-only dict. |
| Rerun invalidation lineage in evidence | `flow_run_rerun_invalidated_steps` via `FlowRunRepository` | Add a tenant-scoped run query ordered by operation and invalidation order. |
| Attempt predecessor/supersession lineage | `FlowStepAttempts` | Already included in `step_attempts`; keep it there and do not duplicate attempt lineage into a second summary owner. |
| Evidence/export payload shape | `flow_run_evidence_bundle.py` | Add `rerun_operations` and `rerun_invalidated_steps` beside `step_attempts` and `result_files` so raw/redacted export shapes stay identical. |
| Debug export timestamp inside hashed bundle | `flow_run_evidence.py` | Derive `debug_export.generated_at` from persisted evidence timestamps so repeated exports of unchanged evidence keep a stable `content_hash`; manifest `exported_at` remains the wall-clock export time. |
| Export summary | `flow_run_export_json.py` | Add a narrow rerun lineage summary derived from the bundle payload. The bundle remains the source of truth. |
| Public evidence schema | `flow_models.py` | Add typed public models for rerun operation and invalidated-step rows, then add them to `FlowRunEvidenceResponse`. |
| Export schema version | `flow_run_evidence_export_manifest.py` | Bump `flow-evidence-export.v3` to `flow-evidence-export.v4` because the hashed bundle gains two top-level arrays and the summary gains rerun lineage. |
| Generated client contract | `frontend/packages/intric-js/src/types` | Refresh generated schema/types after the backend OpenAPI shape changes and pin rerun lineage in the package type-smoke file. |

### Source Scope

- `backend/src/intric/flows/infrastructure/flow_run_repo.py`
  - Add `list_rerun_operations_for_run(...)` with `tenant_id` and `flow_run_id` filters, empty-list no-rerun behavior, and deterministic ordering by `created_at ASC, id ASC`.
  - Add `list_rerun_invalidated_steps_for_run(...)` with `tenant_id` and `flow_run_id` filters, empty-list no-rerun behavior, and deterministic ordering by `operation_id ASC, invalidation_order ASC, id ASC`.
- `backend/src/intric/flows/application/flow_run_service.py`
  - Fetch rerun operations and invalidated rows in `_get_evidence_bundle(...)`.
- `backend/src/intric/flows/flow_run_evidence_bundle.py`
  - Extend `EvidenceBundle` and `RedactedEvidenceBundle`.
  - Include rerun rows in raw and redacted payloads.
  - Add the two tuple fields to `RedactedEvidenceBundle`, include them in `to_export_payload()`, and walk each row through the same redactor with paths `bundle.rerun_operations[{index}]` and `bundle.rerun_invalidated_steps[{index}]`.
  - Reuse a narrow internal section redaction helper if it reduces repeated redaction boilerplate without hiding the evidence section path.
  - Dump rerun rows with plain `model_dump(mode="json")`; no provenance enrichment hook is needed for these persisted audit rows.
- `backend/src/intric/flows/flow_run_evidence.py`
  - Make `debug_export.generated_at` deterministic from persisted evidence timestamps, including rerun operation and invalidated-step rows, so the hashed bundle does not drift between identical exports.
- `backend/src/intric/flows/flow_run_export_json.py`
  - Add `_build_rerun_lineage_summary(...)`.
  - Add `summary["rerun_lineage"]` with `operations_count`, `queued_operations_count`, `running_operations_count`, `completed_operations_count`, `failed_operations_count`, `cancelled_operations_count`, `active_operations_count`, `terminal_operations_count`, `invalidated_steps_count`, and `completed_replacement_count`.
  - Do not mirror rerun lineage into `debug_export`; `rerun_operations` and `rerun_invalidated_steps` are the canonical evidence channel.
- `backend/src/intric/flows/flow_run_evidence_export_manifest.py`
  - Bump `EVIDENCE_EXPORT_SCHEMA_VERSION` to `flow-evidence-export.v4`.
- `backend/src/intric/flows/api/flow_models.py`
  - Add `FlowRunRerunOperationPublic` and `FlowRunRerunInvalidatedStepPublic`.
  - Add `rerun_operations` and `rerun_invalidated_steps` to `FlowRunEvidenceResponse`.
  - Add `current_attempt_no` to `FlowRunStepPublic` so the typed evidence endpoint exposes the existing current-attempt projection already present in raw evidence records.
  - Expose the full persisted rerun operation evidence row: id, tenant/run/flow ids, root step id/order, root attempt number/id, status, request fingerprint, expected/accepted revision, reason, `input_payload_json`, `step_inputs_json`, requesting principal/user, failure fields, and timestamps.
  - Keep `request_fingerprint` public in evidence because it lets support and audit tooling correlate a replayed rerun request with the accepted operation row and invalidation lineage without reading database internals.
  - Expose the full persisted invalidated-step evidence row: id, operation/tenant/run/flow ids, step id/order, invalidation order, role, `dependency_sources_json: list[RerunDependencyKind]`, prior result/attempt ids, replacement attempt number/id, and timestamps.
- `backend/tests/integration/flows/test_flow_run_rerun_repository.py`
  - Pin the two new repository list methods for tenant scoping, empty-list behavior, deterministic ordering, and multi-tenant isolation.
- `backend/tests/integration/flows/test_flow_evidence_api_contracts.py`
  - Pin redacted evidence API/export payloads with rerun operation and invalidated-step rows.
- `backend/tests/unit/test_flow_openapi_contract.py`
  - Pin `FlowRunEvidenceResponse` OpenAPI schema additions and the v4 export schema literal.
- `backend/tests/unittests/flows/test_flow_models.py`
  - Pin typed evidence response parsing for the new nested models.
- `backend/tests/unittests/flows/test_flow_run_evidence.py`
  - Pin the deterministic debug-export timestamp used by evidence bundle hashing.
- `frontend/packages/intric-js/src/types/schema.d.ts`
  - Refresh from current backend OpenAPI.
- `frontend/packages/intric-js/src/types/resources.d.ts`
  - Export public aliases for rerun operation and invalidated-step evidence rows.
- `frontend/packages/intric-js/src/types/flow-resource-aliases.types.ts`
  - Add type-smoke fixtures for v4 evidence export and rerun lineage.
- `backend/src/intric/flows/ai_builder/ai_builder_domain_models.py`
  - Remove new generated-client wording that would introduce stale Flow/AI Builder release-state language into the refreshed OpenAPI output.

### Tests

- Evidence endpoint returns:
  - rerun operation id, root step id/order, root attempt number/id, status, reason, actor, expected/accepted revision, failure fields, and timestamps
  - invalidated-step role, dependency source values, prior result/attempt ids, and replacement attempt ids
  - step-attempt predecessor/supersession fields in the existing `step_attempts` array
- Evidence export returns the same rerun rows in `bundle`, hashes the bundle that contains them, and includes a derived rerun summary.
- Evidence export of the same terminal run twice returns the same `content_hash` when there are no intervening writes.
- Redaction preserves raw/redacted shape equality for rerun keys: `set(raw_bundle.keys()) == set(redacted_bundle.keys())`, rerun arrays have the same length, each row has the same key set, and sensitive inline rerun payload fields are redacted through the existing bundle redactor at manifest paths.
- Typed response model parses rerun rows through named public schemas; JSON payload columns remain explicit JSON object fields.
- `FlowRunStepResults.current_attempt_no` already serializes through `_dump_result_record(...)`; this slice must not add a duplicate attempt-currentness field elsewhere.
- The generated-client impact is visible in OpenAPI contract tests and the `@intric/intric-js` type smoke check.

### Validation Commands

Run these before Claude implementation review:

```bash
docker exec -w /workspace/backend eneo-41ae93-eneo-1 .venv/bin/pytest tests/integration/flows/test_flow_evidence_api_contracts.py -k 'rerun or evidence_export_returns_redacted_json_attachment' -q
docker exec -w /workspace/backend eneo-41ae93-eneo-1 .venv/bin/pytest tests/integration/flows/test_flow_run_rerun_repository.py -k 'evidence or list_rerun' -q
docker exec -w /workspace/backend eneo-41ae93-eneo-1 .venv/bin/pytest tests/unit/test_flow_openapi_contract.py -k 'evidence or export_schema' -q
docker exec -w /workspace/backend eneo-41ae93-eneo-1 .venv/bin/pytest tests/unittests/flows/test_flow_models.py -q
docker exec -w /workspace/backend eneo-41ae93-eneo-1 .venv/bin/pytest tests/unittests/flows/test_flow_run_evidence.py::test_build_debug_export_uses_latest_evidence_timestamp -q
docker exec -w /workspace/backend eneo-41ae93-eneo-1 .venv/bin/ruff check src/intric/flows/ai_builder/ai_builder_domain_models.py src/intric/flows/infrastructure/flow_run_repo.py src/intric/flows/application/flow_run_service.py src/intric/flows/flow_run_evidence.py src/intric/flows/flow_run_evidence_bundle.py src/intric/flows/flow_run_export_json.py src/intric/flows/flow_run_evidence_export_manifest.py src/intric/flows/api/flow_models.py tests/integration/flows/test_flow_evidence_api_contracts.py tests/integration/flows/test_flow_run_rerun_repository.py tests/unit/test_flow_openapi_contract.py tests/unittests/flows/test_flow_models.py tests/unittests/flows/test_flow_run_evidence.py
docker exec -w /workspace/backend eneo-41ae93-eneo-1 .venv/bin/pyright --pythonpath .venv/bin/python src/intric/flows/ai_builder/ai_builder_domain_models.py src/intric/flows/infrastructure/flow_run_repo.py src/intric/flows/application/flow_run_service.py src/intric/flows/flow_run_evidence.py src/intric/flows/flow_run_evidence_bundle.py src/intric/flows/flow_run_export_json.py src/intric/flows/flow_run_evidence_export_manifest.py src/intric/flows/api/flow_models.py tests/integration/flows/test_flow_evidence_api_contracts.py tests/integration/flows/test_flow_run_rerun_repository.py tests/unit/test_flow_openapi_contract.py tests/unittests/flows/test_flow_models.py tests/unittests/flows/test_flow_run_evidence.py
cd frontend/packages/intric-js && bun run check
git diff --check
```

Run this guard before commit:

```bash
git diff -- backend/src/intric/flows backend/tests/integration/flows/test_flow_evidence_api_contracts.py backend/tests/integration/flows/test_flow_run_rerun_repository.py backend/tests/unit/test_flow_openapi_contract.py backend/tests/unittests/flows/test_flow_models.py backend/tests/unittests/flows/test_flow_run_evidence.py frontend/packages/intric-js/src/types/flow-resource-aliases.types.ts frontend/packages/intric-js/src/types/resources.d.ts frontend/packages/intric-js/src/types/schema.d.ts | rg '^\+.*(deprecated|legacy|backwards compat|backward compat|compatibility shim|rerun.*redispatch|redispatch.*rerun)' || true
```

## Validation Commands

Canonical Docker commands from `implementation-order.md` for Batch 8, made executable for this plan:

```bash
docker exec -w /workspace/backend eneo-41ae93-eneo-1 uv run pytest tests/integration/flows/test_flow_rerun_contract.py tests/integration/flows/test_flow_runtime_worker_contract.py::test_flow_run_step_rerun_invalidates_dag_and_executes_worker -q
docker exec -w /workspace/backend eneo-41ae93-eneo-1 uv run pytest tests/unittests/flows/test_flow_rerun_graph.py tests/unittests/flows/test_flow_rerun_architecture.py tests/unittests/flows/test_flow_access_policy.py tests/unittests/flows/test_flow_router.py::test_flow_run_step_rerun_permission_matrix tests/unittests/flows/test_flow_run_service.py::test_rerun_step_replays_idempotent_operation tests/unit/test_flow_openapi_contract.py::test_openapi_flow_run_step_rerun_contract -q
docker exec -w /workspace/frontend eneo-41ae93-eneo-1 bun run test:unit -- src/lib/features/flows/components/flowRunProgress.test.ts src/lib/features/flows/components/FlowRunEvidenceStepCard.test.ts
docker exec -w /workspace/backend eneo-41ae93-eneo-1 uv run pyright
docker exec -w /workspace/backend eneo-41ae93-eneo-1 uv run ruff check src/intric/flows tests/unittests/flows tests/integration/flows tests/unit/test_flow_openapi_contract.py
docker exec -w /workspace/backend eneo-41ae93-eneo-1 uv run ruff format --check src/intric/flows tests/unittests/flows tests/integration/flows tests/unit/test_flow_openapi_contract.py
docker exec -w /workspace/frontend eneo-41ae93-eneo-1 bun run check
docker exec -w /workspace/frontend eneo-41ae93-eneo-1 bun run lint
git diff --check
```

If Docker remains blocked before execution in this Codex process, run the same checks locally and record the fallback in `journal.md`:

```bash
cd backend && uv run pytest tests/integration/flows/test_flow_rerun_contract.py tests/integration/flows/test_flow_runtime_worker_contract.py::test_flow_run_step_rerun_invalidates_dag_and_executes_worker -q
cd backend && uv run pytest tests/unittests/flows/test_flow_rerun_graph.py tests/unittests/flows/test_flow_rerun_architecture.py tests/unittests/flows/test_flow_access_policy.py tests/unittests/flows/test_flow_router.py::test_flow_run_step_rerun_permission_matrix tests/unittests/flows/test_flow_run_service.py::test_rerun_step_replays_idempotent_operation tests/unit/test_flow_openapi_contract.py::test_openapi_flow_run_step_rerun_contract -q
cd frontend/apps/web && bun run test:unit -- src/lib/features/flows/components/flowRunProgress.test.ts src/lib/features/flows/components/FlowRunEvidenceStepCard.test.ts
cd backend && uv run pyright
cd backend && uv run ruff check src/intric/flows tests/unittests/flows tests/integration/flows tests/unit/test_flow_openapi_contract.py
cd backend && uv run ruff format --check src/intric/flows tests/unittests/flows tests/integration/flows tests/unit/test_flow_openapi_contract.py
cd frontend && bun run check
cd frontend && bun run lint
git diff --check
```

Additional guard commands after implementation:

```bash
rg -n "deprecated|legacy|backwards compat|backward compat|compatibility shim|flow_run_rerun_step_inputs_unsupported" backend/src/intric/flows backend/tests/unittests/flows backend/tests/integration/flows frontend/apps/web/src/lib/features/flows frontend/packages/intric-js/src
rg -n "retry_count \\+ 1|rerun.*redispatch|redispatch.*rerun" backend/src/intric/flows backend/tests
```

Expected guard result: no new Flow rerun compatibility/deprecation paths, no executor attempt numbering from Celery retry count, and no rerun implementation through redispatch.

## Acceptance Criteria (Verbatim From PRD)

- [ ] Rerun endpoint starts from one completed step and names invalidated step IDs.
- [ ] Review checkpoint endpoints allow discover, edit, approve/reject, and resume. (Batch 9; no Batch 8 implementation.)
- [ ] `FlowRunExecutor.execute` is split by named phases without adding fake interfaces.
- [ ] `FlowRunService` is not split unless transaction ownership changes.
- [ ] Runtime status semantics come from one lifecycle projection.
- [ ] Terminalization closes open attempts and pending/running step results according to policy.
- [ ] Duplicate terminalization is idempotent.
- [ ] Worker crash, task timeout, duplicate task start, and reconciler behavior are tested.
- [ ] Human review never occupies a worker slot while waiting. (Batch 9; no Batch 8 implementation.)
- [ ] Rerun and resume have separate endpoints from redispatch.
- [ ] Idempotency scope is endpoint-specific.
- [ ] Errors include stale revision, already resumed, invalid transition, invalidated evidence, unauthorized review, and rerun conflict. (Batch 8 owns stale revision, invalid transition, and invalidated evidence. Batch 8 represents concurrent rerun conflict through deterministic replay or stale revision instead of adding a separate `flow_run_rerun_conflict` code. Batch 9 owns already resumed and unauthorized review.)
- [ ] Review checkpoints have schema version, reviewer, original output, edited output, decision, timestamps, and expected revision. (Batch 9; no Batch 8 implementation.)
- [ ] Rerun stores attempt lineage and invalidation/supersession metadata.
- [ ] UI controls render only when generated lifecycle state allows the action.
- [ ] Review UI has one state owner and does not reuse generic evidence viewer state as mutable review state. (Batch 9; no Batch 8 implementation.)
- [ ] API-plus-worker runtime happy path.
- [ ] Terminalization crash recovery.
- [ ] Per-step file mapping.
- [ ] DAG rerun.
- [ ] Review pause/edit/resume journey. (Batch 9; no Batch 8 implementation.)
- [ ] All terminal transitions go through one command.
- [ ] Stale-running reconciliation closes open attempts and emits durable audit.
- [ ] `FlowRunCreateRequest` no longer exposes top-level `file_ids`.
- [ ] Rerun returns DAG-derived `invalidated_step_ids`.
- [ ] Human review persists checkpoint and exits worker. (Batch 9; no Batch 8 implementation.)
- [ ] Resume re-dispatches a fresh task and validates expected revision. (Batch 9; no Batch 8 implementation.)
- [ ] Evidence distinguishes original vs edited review output. (Batch 9; no Batch 8 implementation.)

## Out Of Scope For Batch 8

- Human review pause/edit/resume state, endpoints, checkpoint tables, and frontend review UI.
- Generic `RunControl` action endpoint.
- Redispatch changes beyond proving rerun does not reuse redispatch.
- Compatibility support for JSON-only artifacts, top-level run `file_ids`, or never-shipped rerun request shapes.
- Service-key rerun support unless a separate explicit permission/capability is designed.
- `intric.*` to `eneo.*` Python namespace migration.
- A new workflow engine, Celery chain/chord human gate, or worker in-memory rerun lineage.

## Risk / Trade-Off

| Risk | Mitigation | Confidence |
|---|---|---|
| Historical output evidence could be lost when current result rows are cleared. | Add attempt snapshots before clearing current rows and include those attempts in evidence export. | High |
| Live authoring dependencies could disagree with the run's historical graph. | Compute DAG from the run's published definition snapshot; do not FK operation root step to live `FlowSteps`. | High |
| Attempt numbering could collide on rerun or worker retry. | Allocate from persisted `(run_id, step_id)` attempt history and test duplicate starts. | Medium |
| Rerun operation audit could drift from shared audit system. | Make operation rows durable actor/reason audit facts now; do not add ARQ audit calls. Decide later whether PRD-009 promotes them into a shared lifecycle outbox. | Medium |
| Frontend UI could invent local rerun state. | Use generated response and existing backend step statuses only; component tests assert status comes from API-shaped data. | Medium |
| Frontend cannot poll a standalone rerun operation endpoint. | Keep Batch 8 status ownership in run and step projections; a downstream rerun failure is shown as run/step failure, while operation details remain available through the rerun response and evidence/export. | Medium |

## Human Reviewability Impact

- Data-model changes are concentrated in one migration and `flow_tables.py`.
- Runtime graph logic is isolated in one narrow module with behavior tests.
- Router changes add one explicit endpoint and response model instead of a generic action switch.
- Service and repository changes keep transaction ownership in the application/repository layer.
- Evidence changes are append-only to the evidence bundle/export contract and are guarded by export tests.
- The diff should be reviewed in this order: migration/tables, graph tests/module, repository command, service command, router/OpenAPI, executor, evidence, frontend.
