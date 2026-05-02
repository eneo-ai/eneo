# Batch 9 — Human Review Pause/Edit/Resume Plan

TL;DR:
1. Batch 9 implements durable human review as runtime lifecycle state, not UI-only state and not Celery waiting.
2. The canonical owners are `flow_runs.status`, `flow_run_review_checkpoints`, `FlowRunService`, `FlowRunRepository`, and the existing Flow executor/task boundary.
3. `awaiting_review` is neither active nor terminal; it is cancellable and excluded from concurrency limits.
4. Runtime review checkpoints are separate from `care_data_policy`, because that policy describes outside-flow governance metadata.
5. Implementation must proceed in small slices: state/data model, checkpoint command, pause/yield, API/resume, evidence, frontend.

## Relevant Standards

| Standard | Section | Batch 9 application |
|---|---|---|
| `docs/engineering/maintainability-standards.md` | Canonical Ownership Rule; Delete-First Refactoring | Add one checkpoint owner and avoid generic run-control abstractions. |
| `docs/engineering/comment-and-readability-standard.md` | Comment Standard: Why, Not What | Do not add comments that narrate pause/resume mechanics; names and tests must carry the readable path. |
| `docs/engineering/api-design-standard.md` | API Consumer Standard; API Maintainer Standard | Add explicit review/resume endpoints, typed request/response schemas, and named 409 errors. |
| `docs/engineering/testing-standard.md` | Worker/runtime tests; API contract tests | Protect pause/yield/resume behavior, duplicate resume, stale edit, and frontend state derivation. |

## Problem

Flow runs currently move from queued/running to terminal states. Batch 9 needs a persisted human wait state so a step can complete, produce output for review, release the Celery worker, and later resume through an explicit API command. The implementation must avoid worker waits, generic action endpoints, optional JSON flags, and compatibility branches for unshipped Flow behavior.

## Current State Evidence

| Area | Evidence | Problem | Canonical home |
|---|---|---|---|
| Run status enum | `backend/src/intric/flows/enums.py:81-87` defines `queued`, `running`, `completed`, `failed`, `cancelled`. | No persisted status can represent a run that yielded to human review. | `FlowRunStatus` plus status predicate sets in the same module. |
| Status predicates | `backend/src/intric/flows/enums.py:104-122` classifies only active, terminal, and cancellable states. | `awaiting_review` needs explicit classification or status-aware code will drift. | `ACTIVE_FLOW_RUN_STATUSES`, `TERMINAL_FLOW_RUN_STATUSES`, `CANCELLABLE_FLOW_RUN_STATUSES`. |
| DB status constraint | `backend/src/intric/database/tables/flow_tables.py:420-423` rejects any run status outside the five existing values. | Runtime cannot persist a wait state without a migration and model update. | `FlowRuns.status` check constraint plus Alembic migration. |
| Revision token | `backend/src/intric/database/tables/flow_tables.py:374-380` already documents revision as rerun/resume CAS token. | Resume should reuse this token rather than introduce a second run revision path. | `FlowRuns.revision`. |
| Execution claim time | `backend/src/intric/flows/infrastructure/flow_run_repo.py:998-1009` claims queued runs and writes `started_at=datetime.now(...)`. | Resume re-queues the existing execution task; a resumed worker claim must not erase the original run start time. | `mark_running_if_claimable`. |
| Concurrency limiter | `backend/src/intric/flows/infrastructure/flow_run_repo.py:522-529` counts statuses from `_ACTIVE_STATUSES`. | Review waits must not occupy tenant run slots while a human is offline. | `FlowRunRepository.count_active_runs`. |
| Stale-running reconciler | `backend/src/intric/flows/infrastructure/flow_run_repo.py:592-608` and `backend/src/intric/flows/runtime/tasks.py:324-355` reconcile `running` runs only. | The reconciler must remain a running-worker repair, not a review-expiry owner. | `list_stale_running_runs` plus terminalizer. |
| Executor entry | `backend/src/intric/flows/runtime/executor.py:344-364` skips terminal runs and claims only queued runs. | Redelivered pre-pause tasks must skip `awaiting_review`; resumed runs must re-enter by first moving the run back to `queued`. | Executor entry claim plus the Batch 9 resume service command. |
| Step loop | `backend/src/intric/flows/runtime/executor.py:670-743` persists successful steps, appends state, and terminalizes after all steps. | There is no checkpoint/yield branch after successful step output. | A named review checkpoint command invoked after persisted step success. |
| Review/resume permissions | `backend/src/intric/flows/flow_access_policy.py:34-35` defines actions; `:155-166` keeps them unimplemented. | Routes can be added without inventing new permission helpers, but gates must be flipped with tests only when endpoints exist. | `FlowApiAction.REVIEW` and `FlowApiAction.RESUME`. |
| Permission pins | `backend/tests/unittests/flows/test_flow_access_policy.py:55-74` asserts coarse permissions do not grant unimplemented review/resume. | Batch 9 must update these pins only in the slice that ships review/resume routes. | `test_flow_access_policy.py`. |
| Terminal audit outbox | `backend/src/intric/database/tables/flow_tables.py:1075-1104` keys outbox rows by `(flow_run_id, run_revision)` and constrains `description = action || ':' || source`. | Review edit/approve/reject mutate checkpoint revision, not run revision, so review outbox rows need checkpoint-revision ownership. | `flow_run_audit_outbox` constraints and repository insert methods. |
| Terminal source naming | `backend/src/intric/flows/enums.py:143-156` defines `FlowRunTerminalSource`; `rg` finds 56 references across source and tests. | Adding review lifecycle sources under terminal-only naming would make review events look like terminalization-only events. | Separate mechanical rename before the checkpoint data model slice. |
| Current rerun endpoint pattern | `backend/src/intric/flows/api/flow_run_execution_router.py:389-465` uses a thin route, service command, and recoverable dispatch. | Review/resume should follow explicit endpoint shape, not a generic run-control endpoint. | `flow_run_execution_router.py` plus service command. |
| Current run response | `backend/src/intric/flows/api/flow_models.py:500-523` exposes run revision/status but no active review checkpoint. | Frontend cannot render a review wait state or allowed actions without a typed checkpoint projection. | `FlowRunPublic` and/or active checkpoint response model. |
| Authoring step shape | `backend/src/intric/database/tables/flow_tables.py:112-168` and `backend/src/intric/flows/api/flow_models.py:269-298` contain no review policy field. | A pause trigger must be an explicit new step policy, not hidden in unrelated JSON. | Future `FlowStepReviewPolicy` contract, added in a dedicated slice. |
| Runtime step shape | `backend/src/intric/flows/runtime/models.py:22-40` contains executable step fields but no review policy. | Executor cannot know which output needs review yet. | `RuntimeStep` parsed from published definition. |
| Outbound output modes | `backend/src/intric/flows/enums.py:63-67` owns `FlowOutputMode`; `backend/src/intric/flows/runtime/step_attempt_runtime.py:162` currently treats `http_post` as webhook delivery. | Review policy must reject any outbound side-effecting output mode, not only one string literal in one parser branch. | A predicate co-located with `FlowOutputMode`. |
| Published definition | `backend/src/intric/flows/published_definition.py:47-63` owns versioned definition JSON snapshots. | Review policy must be persisted in the published snapshot so resume uses the run's original version. | Published definition builder/parser. |
| Care-data policy | `backend/src/intric/flows/flow_care_data_policy.py:8-18` names `single_reviewer_outside_flow`. | This is sensitive-flow governance metadata, not an in-flow checkpoint trigger. | Keep `flow_care_data_policy.py` separate; do not reuse as runtime checkpoint owner. |
| Frontend active status | `frontend/apps/web/src/lib/features/flows/components/flowRunProgress.ts:42-47` treats only queued/running as active. | Frontend status derivations need a generated/central value for paused runs. | Flow run progress/status primitives. |
| Frontend run list polling | `frontend/apps/web/src/lib/features/flows/components/FlowRunsTable.svelte:189-192` polls only queued/running runs. | Awaiting-review runs need a deliberate polling/notification decision, not accidental inactivity. | Flow run table state owner. |

## Canonical Ownership Map

| Concept | Current owner | Batch 9 canonical owner | Delete/merge path |
|---|---|---|---|
| Run lifecycle status | `backend/src/intric/flows/enums.py`; `FlowRuns.status` | Same owner, adding `AWAITING_REVIEW`. | Do not add string literals in routers, executor, frontend tests, or generated clients. |
| Review checkpoint state | None | New `flow_run_review_checkpoints` table, `FlowRunReviewCheckpoint` domain model, repository methods. | Do not store active checkpoint as ad hoc `flow_runs.output_payload_json` or `input_payload_json` flags. |
| Review output payloads | Step result/attempt payload JSON exists | Checkpoint row owns original and current review payload snapshots; step result remains the current output projection. | Evidence/export reads checkpoints for review lineage instead of overloading step result fields. |
| Resume CAS | `FlowRuns.revision` for rerun | Same run revision plus checkpoint revision/state CAS. | Do not introduce `updated_at` or a second untyped token as resume concurrency control. |
| Runtime review trigger | None | Explicit step review policy in authoring/public/runtime step contracts. | Do not reuse `care_data_policy`; it is outside-flow metadata. |
| Review/resume permissions | `FlowApiAction.REVIEW` and `FlowApiAction.RESUME` disabled | Same policy matrix, enabled with `FLOWS_MANAGE` when routes ship. | Do not leave `required_permissions=()` when flipping `implemented=True`. |
| Worker re-entry | `flows.execute` task and executor claim | Resume CASes run `awaiting_review -> queued`, then dispatches the existing execution task with IDs only. | Do not pass edited payloads through Celery or add a second execution task path. |
| Lifecycle audit outbox | Existing `flow_run_audit_outbox` is terminal-run-revision keyed | Same table, with terminal rows keyed by run revision and review checkpoint rows keyed by checkpoint revision. | Do not put checkpoint edit/approve/reject rows under the terminal-only unique key. |
| Outbound side-effect classification | `FlowOutputMode.HTTP_POST` is currently the only webhook delivery mode | `flow_output_mode_has_outbound_delivery(mode)` co-located with `FlowOutputMode`. | Do not scatter `mode == "http_post"` review-policy rejection checks. |
| API contract | `flow_run_execution_router.py` | Dedicated review-checkpoint endpoints under the run. | Do not add generic `RunControl(action=...)`. |
| Frontend review state | None | Generated OpenAPI types plus one Flow run detail/review component state owner. | Do not duplicate manual backend types. |

## Human Reviewability

The batch is sliced so reviewers can evaluate the lifecycle-source rename, schema and CAS rules, review policy parsing, runtime pause behavior, API/resume semantics, evidence lineage, and frontend state ownership separately. Runtime behavior changes must stay separate from mechanical renames where possible.

## Runtime State Model

### Run Status Classification

| Status | Active for concurrency | Terminal | Cancellable | Executor behavior |
|---|---:|---:|---:|---|
| `queued` | yes | no | yes | Claim to `running`. |
| `running` | yes | no | yes | Execute or reconcile if stale. |
| `awaiting_review` | no | no | yes | Skip normal execution; resume path must first CAS the checkpoint and run back to `queued`. |
| `completed` | no | yes | no | Skip. |
| `failed` | no | yes | no | Skip. |
| `cancelled` | no | yes | no | Skip. |

### Checkpoint State Classification

| Checkpoint state | Meaning | Allowed next states |
|---|---|---|
| `awaiting_review` | Step output is ready for review. | `approved`, `rejected`, `cancelled`. |
| `edited` | Reviewer changed the checkpoint payload. | `approved`, `rejected`, `cancelled`. |
| `approved` | Reviewer accepted the current payload; run may be resumed. | `resumed`, `cancelled`. |
| `rejected` | Reviewer rejected the checkpoint and the run must not continue. | none. |
| `resumed` | Resume command accepted and dispatched. | none. |
| `cancelled` | Run cancellation closed the active checkpoint. | none. |

Run status and active checkpoint state deliberately use the same `awaiting_review` spelling. That invariant lets logs, API responses, and tests grep for one review-wait term instead of carrying near-synonyms.

Slice 9.1 adds these enums and tables before any code produces active checkpoints. Route and executor slices then make the states reachable.

### Revision And Idempotency Rules

| Operation | Required client token | Persisted CAS owner | Idempotency owner | Revision effect |
|---|---|---|---|---|
| Open checkpoint | none | Run row locked in `running`; `(run_id, step_id, attempt_no)` unique key | Duplicate open returns existing checkpoint | Run revision increments; checkpoint starts at revision 1. |
| Edit checkpoint | `expected_checkpoint_revision` | Checkpoint revision/state | none | Checkpoint revision increments; run revision does not change. |
| Approve checkpoint | `expected_checkpoint_revision` | Checkpoint revision/state | none | Checkpoint revision increments; run revision does not change. |
| Reject checkpoint | `expected_checkpoint_revision` | Checkpoint revision/state plus terminalizer | none | Checkpoint revision increments; terminalizer closes the run. |
| Resume checkpoint | `expected_checkpoint_revision` and idempotency key | Checkpoint revision/state plus run `awaiting_review -> queued` CAS | `flow_run_review_checkpoints.resume_idempotency_key`, unique per `(tenant_id, flow_run_id, resume_idempotency_key)` when non-null | Checkpoint revision increments; run revision increments. |

Rerun and resume both use `FlowRuns.revision` for run-level concurrency. Rerun is rejected with `flow_run_rerun_invalid_transition` while run status is `awaiting_review`; once the run is terminal, Batch 8's latest-run-revision rule applies. Review edit/approve/reject use checkpoint revision because they mutate the active checkpoint, not the whole run lifecycle.

Resume sequencing:
1. In one transaction, CAS checkpoint `approved -> resumed`, store `resume_idempotency_key`, insert the checkpoint outbox row, bump run revision, and set run status `queued`.
2. After commit, dispatch the existing `flows.execute` task with IDs only.
3. The worker claims `queued -> running`; this claim must preserve the original `flow_runs.started_at`.

`mark_running_if_claimable` should set `started_at = COALESCE(started_at, now)` so the first claim records the original run start and a resumed claim does not erase it. Resume timing belongs on the review checkpoint (`resumed_at`) and in review evidence, not on a second run-level start timestamp.

### Lifecycle Audit Outbox Rules

The existing terminal audit outbox stays the durable lifecycle audit owner, but Batch 9 must make the row key match the lifecycle being recorded:

| Event family | Outbox key | Entity fields | Description format | Target status |
|---|---|---|---|---|
| Run terminalization | unique `(flow_run_id, run_revision)` where `review_checkpoint_id IS NULL` | `entity_type=FLOW_RUN`, `entity_id=run.id` | `action.value + ":" + source.value` | Run terminal status. |
| Review checkpoint lifecycle | unique `(review_checkpoint_id, checkpoint_revision)` where `review_checkpoint_id IS NOT NULL` | `entity_type=FLOW_RUN_REVIEW_CHECKPOINT`, `entity_id=checkpoint.id` | `action.value + ":" + source.value` | Checkpoint state after the transition. |

The migration must add nullable `review_checkpoint_id` and `checkpoint_revision` columns, replace the current single unique constraint with the two partial unique indexes above, keep the `description = action || ':' || source` invariant, and widen `target_status` and `source` constraints only to the values required by terminalization and review checkpoints. Review outbox rows still populate `run_revision` with the current run revision for debugging context, but their uniqueness is checkpoint-revision keyed because edit/approve/reject/resume do not all bump `FlowRuns.revision`.

### Payload Projection Rules

| Payload | Owner | Mutability | Runtime effect |
|---|---|---|---|
| Original reviewed output | `flow_run_review_checkpoints.original_payload_json` | Immutable after checkpoint open | Evidence provenance only. |
| Current reviewed output | `flow_run_review_checkpoints.current_payload_json` | Mutated by review edit | Source of truth for the reviewed step's current result projection. |
| Current step result output | `flow_step_results.output_payload_json` | Updated to match `current_payload_json` on review edit | Used by `previous_step`, `all_previous_steps`, final run output, webhook decisions, and evidence current-result views. |
| Attempt output | `flow_step_attempts.output_payload_json` | Immutable after attempt completion | Preserves actual model/tool output before human edit. |
| Execution hash | `flow_step_results.flow_step_execution_hash` | Immutable during review edits | Represents the model/tool execution, not the human-edited projection. |

## Review Policy Boundary

Do not use `metadata_json.care_data_policy.approval_mode = "single_reviewer_outside_flow"` as the runtime trigger. That value intentionally describes a governance process outside Flow execution. Batch 9 should add an explicit step-scoped review policy when it implements the pause trigger, for example:

The Slice 9.2 wire shape is:

```json
{
  "review_policy": {
    "mode": "edit"
  }
}
```

`mode` accepts `view` or `edit`; absence of `review_policy` means no runtime review checkpoint. This avoids two booleans for three states. The published flow definition snapshot must carry the trigger because resumed execution must use the run's original version, not the mutable draft.

Review policy is incompatible with outbound side-effecting output modes until reviewed delivery exists. Implement this through `flow_output_mode_has_outbound_delivery(mode)` next to `FlowOutputMode`, and unit-test that every `FlowOutputMode` value is classified. Today the predicate returns true for `HTTP_POST`; future outbound modes must be classified before they can compile.

## Slice Plan

### Slice 9.0a — Lifecycle Source Rename

Problem: review-specific lifecycle sources should not be added under terminal-only naming.

Files expected:
- `backend/src/intric/flows/enums.py`
- `backend/src/intric/database/tables/flow_tables.py`
- `backend/src/intric/flows/application/flow_run_terminalization.py`
- `backend/src/intric/flows/application/flow_dispatch.py`
- `backend/src/intric/flows/application/flow_run_service.py`
- `backend/src/intric/flows/infrastructure/flow_run_repo.py`
- `backend/src/intric/flows/runtime/executor.py`
- `backend/src/intric/flows/runtime/tasks.py`
- Existing tests that import `FlowRunTerminalSource`

Acceptance criteria:
- [ ] Rename `FlowRunTerminalSource -> FlowRunLifecycleSource` across all references; no compatibility alias.
- [ ] Keep existing enum string values unchanged in this slice; no DB string-value drift and no source-value migration.
- [ ] Rename `FLOW_RUN_TERMINAL_SOURCE_VALUES -> FLOW_RUN_LIFECYCLE_SOURCE_VALUES` together with the enum.
- [ ] No run status, checkpoint table, route, or runtime behavior changes land in the rename commit.

Tests required:
- Existing terminalization, executor, Celery runtime, repository, and service tests that compile against the renamed enum.
- `rg -n "FlowRunTerminalSource" backend/src/intric backend/tests` returns no references.

Risk/trade-off:
- This is a mechanical rename across many files. Keeping it separate preserves reviewability for the data-model slice.

### Slice 9.1 — Status And Checkpoint Data Model

Problem: runtime cannot persist human-waiting state or checkpoint facts.

Files expected:
- `backend/src/intric/flows/enums.py`
- `backend/src/intric/audit/domain/action_types.py`
- `backend/src/intric/audit/domain/entity_types.py`
- `backend/src/intric/audit/domain/category_mappings.py`
- `backend/src/intric/database/tables/flow_tables.py`
- `backend/src/intric/flows/domain/flow.py`
- `backend/src/intric/flows/flow_factory.py`
- `backend/src/intric/flows/infrastructure/flow_run_repo.py`
- `backend/alembic/versions/20260502_review_checkpoints.py`
- `backend/tests/unittests/flows/test_flow_run_status_predicates.py`
- `backend/tests/unittests/flows/test_flow_review_checkpoint_data_model.py`
- `backend/tests/integration/flows/test_flow_run_review_checkpoint_repository.py`

Acceptance criteria:
- [ ] `FlowRunStatus.AWAITING_REVIEW` exists.
- [ ] `awaiting_review` is excluded from active and terminal statuses.
- [ ] `awaiting_review` is cancellable.
- [ ] `flow_runs.status` check constraint accepts `awaiting_review`.
- [ ] `ActionType` includes review lifecycle actions: checkpoint opened, edited, approved, rejected, and resumed.
- [ ] `EntityType` includes `FLOW_RUN_REVIEW_CHECKPOINT`, and each new `FLOW_RUN_REVIEW_*` action is mapped to `user_actions` in `backend/src/intric/audit/domain/category_mappings.py`.
- [ ] `FlowRunLifecycleSource` adds review lifecycle values needed for checkpoint opened, edited, approved, rejected, and resumed events.
- [ ] `flow_run_audit_outbox` supports terminal rows keyed by `(flow_run_id, run_revision)` and review checkpoint rows keyed by `(review_checkpoint_id, checkpoint_revision)`.
- [ ] `flow_run_audit_outbox.description = action || ':' || source` remains true for terminal and review rows.
- [ ] `flow_run_audit_outbox.target_status` allows terminal run statuses and review checkpoint states, without allowing unrelated strings.
- [ ] Review checkpoint outbox rows use `entity_type=FLOW_RUN_REVIEW_CHECKPOINT`, `entity_id=checkpoint.id`, and populate `run_revision` with the current run revision for context.
- [ ] `flow_run_review_checkpoints` owns checkpoint state, revision, schema version, tenant/run/flow/step, attempt number, original payload, current payload, `requester_user_id`, `requester_principal_type`, `decided_by_user_id`, `decided_by_principal_type`, decision timestamps, and next-step pointer.
- [ ] The checkpoint table stores `resume_idempotency_key` with a partial unique index on `(tenant_id, flow_run_id, resume_idempotency_key)` when the key is non-null.
- [ ] Only one active checkpoint can exist per run.
- [ ] Repository methods can create/fetch active checkpoint and perform checkpoint CAS without executor code.
- [ ] Rerun remains blocked by status while a run is `awaiting_review`; no rerun-specific waiting branch is added.
- [ ] `mark_running_if_claimable` preserves existing `started_at` with `COALESCE(started_at, now)`.

Tests required:
- Status predicate unit tests.
- Data model unit test for enum/checkpoint values and constraint strings.
- Repository integration test for one active checkpoint per run, stale revision CAS, checkpoint outbox uniqueness, mixed terminal/review outbox rows, and `started_at` preservation on resumed claim.
- Permission policy test continues to prove disabled review/resume actions do not grant access in Slice 9.1.
- Alembic compile check.

Risk/trade-off:
- This slice changes public run status enum before the frontend renders the state. The table/enums can land first because no producer sets the new status until Slice 9.3, but the generated client update must land before frontend code depends on the value.

### Slice 9.2 — Review Policy Contract And Checkpoint Open Command

Problem: executor needs a typed decision for whether a completed step should pause.

Files expected:
- `backend/src/intric/flows/enums.py`
- `backend/src/intric/flows/domain/flow.py`
- `backend/src/intric/flows/api/flow_models.py`
- `backend/src/intric/database/tables/flow_tables.py`
- `backend/src/intric/flows/runtime/models.py`
- `backend/src/intric/flows/runtime/step_definition_parser.py`
- `backend/src/intric/flows/published_definition.py`
- `backend/src/intric/flows/flow_review_policy.py`
- `backend/src/intric/flows/infrastructure/flow_run_repo.py`
- `backend/tests/unittests/flows/test_flow_review_policy.py`
- `backend/tests/integration/flows/test_flow_review_checkpoint_repository.py`

Acceptance criteria:
- [ ] Step review policy is explicit, typed, and present in published definition snapshots.
- [ ] Parser rejects malformed review policy with named error code.
- [ ] Parser rejects `review_policy` when `flow_output_mode_has_outbound_delivery(step.output_mode)` is true.
- [ ] `flow_output_mode_has_outbound_delivery` classifies every `FlowOutputMode` value.
- [ ] Checkpoint open command locks the run, validates `running`, creates a checkpoint, sets run `awaiting_review`, increments run revision, and inserts exactly one checkpoint-revision-keyed outbox row.
- [ ] Duplicate checkpoint open for the same `(run_id, step_id, attempt_no)` returns the existing checkpoint without duplicate state.
- [ ] Checkpoint open copies the completed step result payload into `original_payload_json` and `current_payload_json`.
- [ ] Pausing for review does not add `awaiting_review` to `flow_step_results.status`; the reviewed step remains `completed`.
- [ ] No `care_data_policy` dependency is introduced.

Tests required:
- Step schema/parser tests for valid and invalid review policy.
- Parser test proving review policy and outbound delivery output modes cannot be combined.
- Enum coverage test proving every `FlowOutputMode` value is classified for outbound delivery.
- Repository command integration tests for checkpoint open, duplicate open, and checkpoint-revision outbox insertion.
- Lifecycle audit outbox test for single checkpoint-open event when a transition happens.

Risk/trade-off:
- The parser now owns both review-policy shape and outbound-delivery incompatibility. Keep the side-effect predicate next to `FlowOutputMode` so future output modes cannot bypass review safety by missing a string literal check.

### Slice 9.3 — Executor Pause/Yield

Problem: successful step execution always continues or terminalizes.

Files expected:
- `backend/src/intric/flows/runtime/executor.py`
- `backend/src/intric/flows/runtime/step_attempt_runtime.py`
- `backend/src/intric/flows/infrastructure/flow_run_repo.py`
- `backend/tests/integration/flows/test_flow_runtime_worker_contract.py`
- `backend/tests/integration/flows/test_flow_terminalization_contract.py`

Acceptance criteria:
- [ ] After successful step persistence, executor opens a checkpoint when review policy applies.
- [ ] Task returns `{"status": "awaiting_review"}` after the checkpoint commit and does not occupy a worker slot.
- [ ] Redelivered execution task skips runs already in `awaiting_review`.
- [ ] Stale-running reconciliation remains `running`-only; the existing repository predicate is preserved and pinned by test.
- [ ] Terminalization is not called for review waits.
- [ ] Review-policy steps cannot use any outbound delivery output mode; this avoids sending side effects before human approval.
- [ ] The current step result row remains `completed` while the run waits for review; checkpoint state is the only review lifecycle state.

Tests required:
- Worker integration test: run pauses after the review step, leaves completed step result and attempt closed, and returns awaiting review.
- Duplicate task delivery test: second execution does not create another checkpoint or rerun the step.
- Stale-running test: awaiting-review run is not queried by the running-run reconciler.

Risk/trade-off:
- The executor hot path adds a post-success review branch beside webhook delivery and final terminalization. Duplicate task delivery must prove the branch commits one checkpoint and then exits without re-running the step.

### Slice 9.4 — Review API, Edit/Approve/Reject, And Resume Dispatch

Problem: humans need typed endpoints to inspect, edit, decide, and resume checkpoints.

Files expected:
- `backend/src/intric/flows/api/flow_run_execution_router.py`
- `backend/src/intric/flows/api/flow_models.py`
- `backend/src/intric/flows/application/flow_run_service.py`
- `backend/src/intric/flows/infrastructure/flow_run_repo.py`
- `backend/src/intric/flows/application/flow_dispatch.py`
- `backend/src/intric/flows/flow_access_policy.py`
- `backend/tests/unittests/flows/test_flow_access_policy.py`
- `backend/tests/unittests/flows/test_flow_run_service.py`
- `backend/tests/unit/test_flow_openapi_contract.py`
- `backend/tests/integration/flows/test_flow_runtime_worker_contract.py`

Endpoint shape:
- `GET /api/v1/flows/{id}/runs/{run_id}/review-checkpoints/active/`
- `PATCH /api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/`
- `POST /api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/approve/`
- `POST /api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/reject/`
- `POST /api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/resume/`

Public schemas:
- `FlowRunReviewCheckpointPublic`
- `FlowRunReviewCheckpointEditRequest`
- `FlowRunReviewCheckpointApproveRequest`
- `FlowRunReviewCheckpointRejectRequest`
- `FlowRunReviewCheckpointResumeRequest`
- `FlowRunReviewCheckpointResumeResponse`

`FlowRunReviewCheckpointPublic` exposes `id`, `tenant_id`, `flow_id`, `flow_run_id`,
`step_id`, `step_order`, `attempt_no`, `state`, `revision`, `schema_version`,
`original_payload_json`, `current_payload_json`, `next_step_ids`, requester/decider
principal fields, decision timestamps, and row timestamps. It does not expose
`resume_idempotency_key`; that key is a replay token, not a public checkpoint fact.

Acceptance criteria:
- [ ] `GET .../review-checkpoints/active/` uses existing `FlowApiAction.VIEW` semantics and returns `200` with `FlowRunReviewCheckpointPublic | null`; `null` means the run currently has no active checkpoint.
- [ ] Service-key principals keep the same run-visibility boundary as run detail for the active checkpoint read: they may read only checkpoints on runs they own. Product can later narrow this to an evidence-view capability, but Slice 9.4 does not create a second service-key visibility model.
- [ ] Mutating review endpoints use `FlowApiAction.REVIEW`; resume uses `FlowApiAction.RESUME`.
- [ ] `FlowApiAction.REVIEW` and `FlowApiAction.RESUME` require `FLOWS_MANAGE` before `implemented=True` is set.
- [ ] Mutating review/resume routes stay user-principal only; service keys are denied.
- [ ] Every mutating review endpoint requires `expected_checkpoint_revision`.
- [ ] Resume idempotency uses the `Idempotency-Key` header, matching `create_flow_run`; missing or blank keys return `flow_review_idempotency_key_required`, and overlong keys return `flow_run_invalid_idempotency_key`.
- [ ] Edit uses checkpoint revision CAS, updates `current_payload_json`, updates the current step result projection to the same payload, does not update `flow_step_results.flow_step_execution_hash`, increments checkpoint revision, inserts a checkpoint-revision-keyed outbox row, and returns the full checkpoint.
- [ ] Review mutations lock the run row before the checkpoint row, matching terminalization and checkpoint-open ordering; edit then updates the current step result projection by `(run_id, step_id, current_attempt_no)`, and concurrent edits with the same expected revision produce one winner and one `flow_review_stale_revision`.
- [ ] Edited payload shape is reviewer-owned in Slice 9.4. The API requires a JSON object but does not validate it against `output_contract`; downstream typed-input validation remains the runtime safety net.
- [ ] Approve uses checkpoint revision CAS, transitions to `approved`, increments checkpoint revision, inserts a checkpoint-revision-keyed outbox row, and returns the full checkpoint.
- [ ] Resume requires approved checkpoint state, matching `expected_checkpoint_revision`, and an idempotency key.
- [ ] Resume CASes checkpoint `approved -> resumed`, stores `resume_idempotency_key`, inserts one checkpoint-revision-keyed outbox row, advances run revision, transitions run `awaiting_review -> queued`, commits, then dispatches the existing `flows.execute` task with IDs only.
- [ ] Idempotent resume replay with the same `Idempotency-Key` short-circuits before CAS/outbox insert/dispatch and returns the existing resumed checkpoint plus current run.
- [ ] Resume does not pre-check the tenant concurrency quota. Once the run is `queued`, it participates in the existing tenant active-run quota like any other queued run.
- [ ] If post-commit resume dispatch fails, the existing stale queued redispatch owner (`redispatch_stale_queued_runs`) remains the repair path.
- [ ] Duplicate resume with the same idempotency key returns the same accepted checkpoint/run response.
- [ ] Resume with a different idempotency key after resume returns `flow_review_already_resumed`.
- [ ] Resume error codes are state-specific: `flow_review_already_resumed` for `resumed`, `flow_review_rejected` for `rejected`, `flow_review_cancelled` for `cancelled`, and `flow_review_not_approved` for `awaiting_review` or `edited`.
- [ ] Reject CASes checkpoint to `rejected`, increments checkpoint revision, inserts a checkpoint-revision-keyed outbox row, and calls `terminalize_run(target=CANCELLED, source=REVIEW_REJECTED, error_code="flow_review_rejected")`.
- [ ] Reject runs in one transaction; if terminalization fails after checkpoint CAS, the checkpoint mutation and checkpoint outbox insert roll back together with the run terminalization.
- [ ] Reject requires a non-empty `reason` with the rerun reason length limit; missing/blank reason returns `flow_review_reject_reason_required`, and overlong reason returns `flow_review_reject_reason_too_long`.
- [ ] Rejection uses run status `cancelled`; `source=REVIEW_REJECTED` distinguishes reviewer rejection from user/admin cancellation.
- [ ] Cancelling a run with an active review checkpoint CASes the checkpoint to `cancelled`, increments checkpoint revision, and inserts a checkpoint-revision-keyed outbox row in the same transaction as run cancellation.
- [ ] Terminalizer checkpoint cancellation only fires when an active checkpoint exists at cancellation time; reject first transitions the checkpoint to `rejected`, so rejection writes exactly one checkpoint outbox row.
- [ ] Routers remain HTTP adapters; application service owns transaction orchestration.
- [ ] New OpenAPI operation IDs are pinned: `get_active_flow_run_review_checkpoint`, `edit_flow_run_review_checkpoint`, `approve_flow_run_review_checkpoint`, `reject_flow_run_review_checkpoint`, and `resume_flow_run_review_checkpoint`.

Tests required:
- API contract tests for route paths, operation IDs, response models, and error shapes.
- Permission tests convert `REVIEW` and `RESUME` from unimplemented negative pins to positive `FLOWS_MANAGE` and coarse `FLOWS` grants; service-key principals remain denied for mutating review/resume endpoints.
- Service tests for stale edit, edit-then-approve revision, duplicate resume replay, already resumed with another key, rejected checkpoint, cancelled checkpoint, reject reason validation, and service-key denial.
- Repository integration test for concurrent edit CAS: two edits with the same expected revision produce one persisted edit and one stale-revision failure.
- Terminalization integration test for cancelling a run with an active checkpoint: run cancellation and checkpoint cancellation outbox rows commit together, and reject writes exactly one checkpoint outbox row.
- Service or integration test for concurrent reject versus cancel: one terminal transition wins, and persisted audit rows contain one terminal outbox row plus one checkpoint outbox row.
- Runtime integration test for approve/resume from awaiting review to completed.
- Runtime integration test proving edit + approve + resume feeds the edited payload to the next step's `previous_step` input source.
- Permission matrix for user, service key, tenant admin, space admin, space owner, run owner, `FLOWS_VIEW`, `FLOWS_MANAGE`, `FLOWS_RUN`, and coarse `FLOWS` behavior.

Risk/trade-off:
- The read endpoint exposes current checkpoint payload through normal flow-view semantics. The response schema must apply the same visibility policy as run detail until product defines a narrower review-view permission.
- Slice 9.4 intentionally adds checkpoint cancellation inside the terminalizer because terminalization is the canonical run-state transition owner. The test suite must pin that the branch is limited to active checkpoints and does not double-write checkpoint audit rows after reject.

### Slice 9.5 — Evidence And Export Lineage

Problem: evidence must distinguish original step output from current reviewed output.

Files expected:
- `backend/src/intric/flows/flow_run_evidence_bundle.py`
- `backend/src/intric/flows/flow_run_export_json.py`
- `backend/src/intric/flows/flow_run_evidence_export_manifest.py`
- `backend/src/intric/flows/infrastructure/flow_run_repo.py`
- `backend/tests/unittests/flows/test_flow_run_export_json.py`
- `backend/tests/unittests/flows/test_flow_run_evidence_bundle.py`

Acceptance criteria:
- [x] Evidence bundle includes review checkpoints for the run.
- [x] Export manifest schema bumps to `flow-evidence-export.v5`.
- [x] Export shows original payload, current reviewed payload, decision, reviewer identity fields allowed by policy, checkpoint revision, and resume linkage.
- [x] Redacted export keeps sensitive reviewed payloads within existing evidence policy.
- [x] No deleted or unreviewed payload is silently treated as final output.

Tests required:
- [x] Export JSON test for original vs current reviewed output.
- [x] Redaction test for sensitive review payloads.
- [x] Manifest version test if export schema changes.

Risk/trade-off:
- Export v5 must include both `original_payload_json` and `current_payload_json` as separate fields; never collapse them into a single output field.

### Slice 9.6 — Frontend Generated Types And Review UI State

Problem: frontend must display and operate review checkpoints from typed backend state.

Files expected:
- `frontend/packages/intric-js/src/types/schema.d.ts`
- `frontend/packages/intric-js/src/endpoints/flows.js`
- `frontend/apps/web/src/lib/features/flows/components/flowRunProgress.ts`
- `frontend/apps/web/src/lib/features/flows/components/flowRunStatusLabel.ts`
- `frontend/apps/web/src/lib/features/flows/components/flowRunStatusPresentation.ts`
- `frontend/apps/web/src/lib/features/flows/components/flowRunStatusSets.ts`
- `frontend/apps/web/src/lib/features/flows/components/FlowRunsTable.svelte`
- `frontend/apps/web/src/lib/features/flows/components/FlowRunReviewCheckpointPanel.svelte`
- `frontend/apps/web/messages/en.json`
- `frontend/apps/web/messages/sv.json`

Acceptance criteria:
- [ ] Generated schema includes `awaiting_review` and review checkpoint models.
- [ ] One frontend status module owns active/terminal/cancellable run status sets; progress, status badge, and run table import it instead of duplicating string sets.
- [ ] Status badge and run list render awaiting-review distinctly.
- [ ] Review UI owns editable checkpoint state in one component/service boundary.
- [ ] Resume/edit buttons use allowed backend state, not guessed frontend conditions.
- [ ] Translations are updated in English and Swedish together.

Tests required:
- Frontend status presentation tests for `awaiting_review`.
- Component tests for edit stale error, approve/resume success, and unavailable action state.
- Generated-client endpoint smoke test.

Risk/trade-off:
- Keep frontend UI focused on the new checkpoint surface. Do not reuse evidence viewer state as mutable review state.

## Acceptance Criteria From PRD-003

- [x] All terminal transitions go through one command. Completed before Batch 9.
- [x] Stale-running reconciliation closes open attempts and emits durable audit. Completed before Batch 9.
- [x] `FlowRunCreateRequest` no longer exposes top-level `file_ids`. Completed before Batch 9.
- [x] Rerun returns DAG-derived `invalidated_step_ids`. Completed in Batch 8.
- [ ] Human review persists checkpoint and exits worker.
- [ ] Resume re-queues the existing execution task and validates expected checkpoint revision plus run revision CAS.
- [ ] Evidence distinguishes original vs edited review output.

## Out Of Scope

- Generic workflow engine or `RunControl` endpoint.
- Celery chain/chord human gates.
- Periodic reconciliation as the primary resume path.
- Service-key review/resume unless product defines service-principal review semantics.
- Automatic checkpoint TTL cancellation; default is no auto-cancel until an ADR/product decision says otherwise.
- Reusing `care_data_policy` as a runtime review trigger.
- Preserving deprecated/legacy/backwards-compatible Flow review shapes.
- Separate `flows.resume` Celery task in Batch 9; resume intentionally re-queues the existing `flows.execute` path after database CAS. A wrapper task can be reconsidered only if it removes code, not if it creates a second execution path.

## Validation Commands

Use Docker unless the container is unavailable:

```bash
docker ps --format '{{.Names}}'
docker exec -w /workspace/backend eneo-41ae93-eneo-1 .venv/bin/pytest tests/unittests/flows/test_flow_run_status_predicates.py -q
docker exec -w /workspace/backend eneo-41ae93-eneo-1 .venv/bin/pytest tests/unittests/flows/test_flow_access_policy.py -q
docker exec -w /workspace/backend eneo-41ae93-eneo-1 .venv/bin/pytest tests/integration/flows/test_flow_runtime_worker_contract.py -q
docker exec -w /workspace/backend eneo-41ae93-eneo-1 .venv/bin/pytest tests/integration/flows/test_flow_terminalization_contract.py -q
docker exec -w /workspace/backend eneo-41ae93-eneo-1 .venv/bin/ruff check src/intric/flows src/intric/database/tables/flow_tables.py tests/unittests/flows tests/integration/flows
docker exec -w /workspace/backend eneo-41ae93-eneo-1 .venv/bin/pyright src/intric/flows tests/unittests/flows tests/integration/flows
```

Add slice-specific frontend validation in Slice 9.6:

```bash
pnpm -C frontend check
pnpm -C frontend --filter @intric/web test -- flowRunStatus
```

## Scoring Target

| Dimension | Target | Reason |
|---|---:|---|
| Maintainability | 9 | One persisted review owner, explicit lifecycle states, behavior tests. |
| Code Quality | 9 | Typed schemas, no unearned abstractions, no AI slop comments. |
| Clean Architecture | 9 | Routers stay thin; application/repository own transactions; executor owns runtime branch. |
| Separation of Concerns | 9 | Review checkpoint, evidence, frontend state, and permissions are sliced separately. |
| Single Source of Truth | 9 | One checkpoint table and one status enum. |
| Human Readability | 9 | Domain names reveal lifecycle without explanatory comments. |
| Human Reviewability | 9 | Slices isolate schema, runtime, API, evidence, and frontend. |

Overall target score: 9.
