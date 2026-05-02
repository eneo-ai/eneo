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
| Terminal audit outbox is one row per run. | `backend/src/intric/database/tables/flow_tables.py:759-821` defines `flow_run_audit_outbox` and `backend/src/intric/database/tables/flow_tables.py:795` enforces `UNIQUE(flow_run_id)`. | Rerun operation rows are the canonical rerun audit owner in Batch 8; do not widen the terminal outbox or add a shared audit action for rerun. |
| Docker validation is still blocked in this Codex process. | `docker ps --format '{{.Names}}' \| sort` was rejected before execution with `approval required by policy, but AskForApproval is set to Never`. | Keep Docker as canonical validation in the plan, but record local fallback if the same blocker persists. |

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
- `backend/src/intric/flows/api/flow_run_steps_router.py`
  - Add the rerun endpoint under the step-owned runtime route.
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
- `backend/alembic/versions/<new>_flow_run_rerun_operations.py`
  - Create operation and invalidated-step tables.
  - Add attempt columns and indexes.
  - Down revision should follow `20260430_flow_step_file_mappings` unless another migration lands first.
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
- Migration backfills completed rows with `current_attempt_no = 1`; if a non-production environment has no completed rows, the same SQL is still harmless.
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

`flow_run_rerun_operations` is also the Batch 8 audit owner for rerun requests. Do not add `ActionType.FLOW_RUN_RERUN_REQUESTED`, do not call `audit_service.log_async` from the rerun endpoint, and do not widen `flow_run_audit_outbox`; that outbox remains one terminalization row per run.

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
- `flow_run_rerun_step_incomplete` when the root step has no completed current result
- `flow_run_rerun_step_inputs_invalid` for step input payloads outside the rerun root
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
