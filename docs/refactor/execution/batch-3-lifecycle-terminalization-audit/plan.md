# Batch 3 - Lifecycle Terminalization Audit Plan

## Status

Loop Iteration 1 `/plan` complete. No source, test, migration, or
frontend implementation changes have been made yet.

## Gate Check

- Branch: `feature/refactor-flows-flowai`.
- Latest commit: `39b8652b flows: define access and published definition contracts`.
- Staged files: none.
- Known unrelated dirty files that must remain untouched:
  - `frontend/packages/ui/src/icons/types.d.ts`
  - `scripts/run_codex_review.sh`
  - `PRODUCT.md`

## Batch Scope

Batch 3 covers the lifecycle foundation and terminal audit subset from
PRD-003 and PRD-009.

In scope:

- canonical Flow run status predicate owner
- duplicated status predicate sweep for current statuses
- one idempotent terminalization command for terminal run transitions
- stale-running reconciliation through terminalization
- task timeout / missing-principal / task-failure paths through terminalization
- executor terminal paths through terminalization
- durable Flow lifecycle audit outbox row written in the terminalization transaction
- behavior tests for runtime worker, stale reconciliation, task timeout,
  duplicate terminalization, and audit outbox behavior

Explicitly out of scope:

- Batch 4 per-step file mapping and top-level `file_ids` deletion
- Batch 5 generated frontend type migration or package naming
- Batch 6 AI Builder contract split
- Batch 8 step rerun
- Batch 9 human review pause/edit/resume and `waiting_for_review`
- Flow runtime health endpoint, dashboards, alerting, and full runbooks
  beyond terminal outbox policy
- opportunistic `intric.*` to `eneo.*` package/import renames
- parallel `eneo.*` namespace or compatibility re-export modules
- non-lifecycle Flow audit migration unless the touched lifecycle path
  currently uses it

## Acceptance Criteria Restated From PRDs

From `docs/refactor/prd/PRD-003-runtime-reliability-and-feature-gaps.md`:

- [ ] All terminal transitions go through one command.
- [ ] Stale-running reconciliation closes open attempts and emits durable audit.
- [ ] `FlowRunCreateRequest` no longer exposes top-level `file_ids`.
- [ ] Rerun returns DAG-derived `invalidated_step_ids`.
- [ ] Human review persists checkpoint and exits worker.
- [ ] Resume re-dispatches a fresh task and validates expected revision.
- [ ] Evidence distinguishes original vs edited review output.

Batch 3 will satisfy the first two criteria. The remaining five are
explicitly deferred to Batches 4, 8, and 9.

From `docs/refactor/prd/PRD-009-observability-and-operability.md`:

- [ ] `RunObservabilityRecorder` or equivalent emits metrics from lifecycle/task boundaries.
- [ ] Terminal audit outbox behavior is tested.
- [ ] Flow runtime health probe exists.
- [ ] Runbooks exist and alert metrics link to them.
- [ ] AI Builder turn metrics are separate from flow run metrics.
- [ ] Local `celerybeat-schedule` hygiene is tracked as a small follow-up outside the core operability PR unless it blocks clean review.

Batch 3 will satisfy terminal audit outbox behavior and leave a
terminalization result shape that can feed metrics. Full recorder,
health probe, alerting, runbooks, and AI Builder metrics remain Batch 10
operability work unless Claude identifies a concrete Batch 3 blocker.

## Current Source-Of-Truth Owners

| Concept | Current owner/evidence | Problem | Batch 3 canonical owner |
|---|---|---|---|
| Run status enum and predicates | `backend/src/intric/flows/enums.py:64` defines `FlowRunStatus`. | Enum values exist, but active/terminal predicates are duplicated by callers. | Keep enum values and add run-status predicate constants/functions in `backend/src/intric/flows/enums.py` so status rules live next to the enum. |
| Active run counting | `backend/src/intric/flows/infrastructure/flow_run_repo.py:40` and `:155` use `_ACTIVE_STATUSES`. | Active semantics are repository-local. | `enums.py` provides `ACTIVE_FLOW_RUN_STATUSES`. Repository imports it. |
| Terminal status checks | `backend/src/intric/flows/application/flow_run_service.py:91`, `backend/src/intric/flows/runtime/executor.py:240`, and `backend/src/intric/flows/runtime/step_attempt_runtime.py:58` duplicate terminal sets. | New states would drift across service, executor, and step gate logic. | `enums.py` provides `TERMINAL_FLOW_RUN_STATUSES` and `is_terminal_flow_run_status`. |
| Terminal run update | `backend/src/intric/flows/infrastructure/flow_run_repo.py:293` owns a generic `update_status`, while direct terminal callers exist in service, executor, dispatch, and tasks. | Terminalization does not consistently close attempts/results or audit. | New application command, planned as `backend/src/intric/flows/application/flow_run_terminalization.py`, owns terminal transitions. |
| Step result closure | `backend/src/intric/flows/infrastructure/flow_run_repo.py:483` only marks pending/running step results cancelled. | Failure reconciliation and timeout need failed result closure, not always cancelled. | Terminalization command delegates to repository methods that close active step results according to target status. |
| Step attempt closure | `backend/src/intric/flows/infrastructure/flow_run_repo.py:552` can finish one known attempt only. | Reconciler/task timeout cannot close unknown open attempts. | Repository adds a run-scoped open-attempt closure used only by terminalization. |
| Terminal audit | `backend/src/intric/flows/runtime/executor.py:1071` calls `audit_service.log_async`; `backend/src/intric/audit/application/audit_service.py:234` enqueues ARQ work. | Lifecycle audit is best-effort/ARQ-backed and can duplicate on no-op terminal updates. | Terminalization writes a relational lifecycle audit outbox row in the same transaction as the terminal state change. |
| Principal actor fields | `backend/src/intric/flows/principal.py:100` owns audit actor mapping. | Keep this owner; do not copy actor mapping into terminalization callers. | Terminalization uses `FlowPrincipal.from_run(...).audit_actor_fields()` or an explicit command principal. |

## Duplicated Status Predicate Inventory

| Predicate | Current locations | Batch 3 action |
|---|---|---|
| Run terminal statuses | `flow_run_service.py:91`, `executor.py:240`, `step_attempt_runtime.py:58`, `flow_run_repo.py:312`, tests in `test_flow_run_service.py:2534` | Move reusable predicate/set to status predicate owner; keep DB constraints and enum value definition in place. |
| Run active statuses | `flow_run_repo.py:40`; active count at `flow_run_repo.py:155`; stale queued/running methods at `flow_run_repo.py:200` and `:225` | Move reusable active set to status predicate owner; stale methods stay explicit by state. |
| Terminal from-status CAS defaults | `flow_run_repo.py:319` defaults to queued/running for terminal statuses. | Terminalization command supplies valid source statuses; delete the generic terminal `update_status` method after all callers move. |
| Step active result statuses | `mark_pending_steps_cancelled` uses pending/running at `flow_run_repo.py:495`. | Add lifecycle/result predicate or repository-local tuple for active step results; use target status mapping from terminalization. |
| Step open attempt statuses | `finish_attempt` updates started/retried at `flow_run_repo.py:578`. | Add run-scoped open-attempt closure using the same started/retried set. |

## Behavior Pins Before Destructive Runtime Cleanup

The first implementation step will add or rewrite tests before replacing
terminalization call sites.

| Pin | Failure mode protected | Test file |
|---|---|---|
| Status predicate owner pin | A future status is added without updating active/terminal/cancellable predicates. | New `backend/tests/unittests/flows/test_flow_run_status_predicates.py`. |
| Duplicate terminalization pin | A second terminalization call changes output/error/audit or emits a duplicate audit row. | New `backend/tests/integration/flows/test_flow_terminalization_contract.py`. |
| Audit fail-closed pin | If terminal audit outbox insert fails, the run must remain non-terminal. | New `backend/tests/integration/flows/test_flow_terminalization_contract.py`. |
| Completion worker contract pin | Happy-path execution reaches terminal state, closes attempts/results, and writes an outbox event instead of using ARQ `audit_service.log_async`. | Update `backend/tests/integration/flows/test_flow_runtime_worker_contract.py`. |
| Stale-running reconciliation pin | Reconciler terminalizes stale runs, closes pending/running step results, closes open attempts, and emits exactly one durable audit row. | Update `backend/tests/unittests/flows/test_flow_run_service.py` and `backend/tests/unittests/flows/test_celery_runtime.py`; add integration coverage in `test_flow_terminalization_contract.py` if fixture setup is tractable. |
| Task timeout pin | Celery task timeout calls terminalization and does not manually flip status. | Update `backend/tests/unittests/flows/test_celery_runtime.py`. |
| Missing-principal/task-failure pin | Celery wrapper terminalizes failure sources through the same command. | Update `backend/tests/unittests/flows/test_celery_runtime.py` if the existing coverage can be tightened without broad setup. |
| Public task-wrapper pin | Batch 0 carry-forward: direct executor contract is not enough; add an eager Celery/task-wrapper contract or document fixture gap. | Prefer `backend/tests/unittests/flows/test_celery_runtime.py`; add integration only if Docker/session fixtures allow. |

No deletion or terminal call-site replacement happens before these pins
exist.

## Terminalization Command Design

Canonical owner: `backend/src/intric/flows/application/flow_run_terminalization.py`.

The command is a concrete application-layer owner, not an interface or
test-only seam. It earns its file because the transaction crosses run
status, step results, step attempts, and lifecycle audit outbox.

Planned public shape:

```text
terminalize_run(
    run_id,
    tenant_id,
    target_status,
    source,
    error_code=None,
    error_message=None,
    output_payload_json=None,
    cancelled_at=None,
    principal=None,
) -> FlowRunTerminalizationResult
```

`FlowRunTerminalizationResult` will include:

- `run`
- `did_transition: bool`
- `target_status`
- `source`
- `audit_outbox_id: UUID | None`

Rules:

- Valid target statuses are `TERMINAL_FLOW_RUN_STATUSES` from
  `backend/src/intric/flows/enums.py`.
- Source CAS uses `queued` and `running`. If the run is already
  terminal, return `did_transition=false` without touching rows.
- The command writes the outbox row before or within the same transaction
  as the terminal status update. If outbox insert fails, the terminal
  state change must not commit.
- Duplicate calls on an already terminal run return
  `did_transition=false` and do not close rows again or write a second
  outbox row.
- `completed` with active step results still outstanding raises a
  terminalization invariant error. Successful completion must come from
  `determine_run_outcome` over completed rows, not from silently closing
  active rows.
- `failed` maps active step results and open attempts to failed.
- `cancelled` maps active step results and open attempts to cancelled
  and records `cancelled_at`.
- Terminal audit source values are a closed `FlowRunTerminalSource`
  enum defined in `backend/src/intric/flows/enums.py` and mirrored by a
  DB CHECK constraint. Initial values:
  `executor_completed`, `executor_failed`, `flow_deleted`,
  `definition_checksum_mismatch`, `invalid_flow_definition`,
  `assistant_snapshot_drift`, `step_missing`, `task_timeout`,
  `task_failure`, `missing_principal`, `stale_running_reconciler`,
  `user_cancel`, and `dispatch_failure`.

Call sites to retarget:

- `backend/src/intric/flows/application/flow_dispatch.py:54`
- `backend/src/intric/flows/application/flow_run_service.py:670`
- `backend/src/intric/flows/application/flow_run_service.py:680`
- `backend/src/intric/flows/application/flow_run_service.py:699`
- `backend/src/intric/flows/application/flow_run_service.py:707`
- `backend/src/intric/flows/runtime/executor.py:361`
- `backend/src/intric/flows/runtime/executor.py:379`
- `backend/src/intric/flows/runtime/executor.py:391`
- `backend/src/intric/flows/runtime/executor.py:418`
- `backend/src/intric/flows/runtime/executor.py:464`
- `backend/src/intric/flows/runtime/executor.py:509`
- `backend/src/intric/flows/runtime/executor.py:717`
- `backend/src/intric/flows/runtime/executor.py:1055`
- `backend/src/intric/flows/runtime/tasks.py:161`
- `backend/src/intric/flows/runtime/tasks.py:294`
- `backend/src/intric/flows/runtime/tasks.py:341`

Deletion after retargeting:

- Delete `FlowRunRepository.update_status`; verified current callers
  only write terminal statuses.
- Delete `FlowRunRepository.cancel`.
- Delete `FlowRunRepository.fail_stale_running_run`.
- Delete `FlowRunExecutor._mark_run_failed`.
- Delete `intric.flows.runtime.tasks._mark_run_failed`.
- Delete `FlowRunExecutor._audit_run_terminal_state` and its two call
  sites at executor completion/failure; the terminal audit outbox
  replaces this ARQ-backed lifecycle audit path.
- Delete `FlowRunRepository.mark_pending_steps_cancelled` if all callers
  move to the terminalization command and no non-terminal owner remains.

No source-only compatibility bridge is kept for direct terminal status
updates. If a direct terminal update remains after implementation, the
plan must be revised before validation.

## Durable Audit / Outbox Policy

Planned data owner: `flow_run_audit_outbox`.

Minimum table shape for Batch 3:

- `id`
- `tenant_id`
- `flow_id`
- `flow_run_id`
- `description`
- `action`
- `entity_type`
- `entity_id`
- `actor_id`
- `actor_type`
- `actor_api_key_id`
- `source`
- `target_status`
- `error_code`
- `error_message`
- `created_at` / `updated_at`
- `UNIQUE (flow_run_id)` for Batch 3 terminal-only lifecycle audit

Batch 3 inserts one outbox row for each real terminal transition. It
does not add delivery-state columns or a delivery worker; Batch 10 owns
delivery status, retries, alerts, runbooks, and any schema migration
needed for non-terminal lifecycle events. For terminal-only Batch 3,
`UNIQUE (flow_run_id)` is the dedupe rule. Batches 8 and 9 must replace
that constraint if review/rerun introduce multiple lifecycle events per
run.

`description` is deterministic text derived from `(action, source)`;
callers do not pass free-form audit descriptions.

Outbox FK policy:

- `tenant_id`: `ON DELETE CASCADE`, matching tenant-scoped data cleanup.
- `flow_id`: `ON DELETE RESTRICT`, because an undelivered lifecycle audit
  row should not disappear because a flow is deleted.
- `flow_run_id`: `ON DELETE RESTRICT`, because the terminal audit outbox
  row is the durable audit handoff for that run. If retention needs to
  delete runs before audit delivery exists, Batch 10 must add a delivery
  and retention policy instead of silently cascading rows away.

No generic `metadata_json` column is added in Batch 3. The row stores
the explicit terminal audit fields needed for delivery; any future
metadata envelope must have a schema/version owner.

Terminal audit coverage delta:

- Current code audits only executor `completed` and executor `failed`
  paths through `audit_service.log_async`.
- Current cancel, dispatch failure, task timeout, task failure,
  missing-principal, and stale-running reconciliation paths emit no
  lifecycle audit.
- After Batch 3, every real terminal transition emits exactly one
  relational outbox row, and duplicate terminalization emits none.

Non-lifecycle Flow audit callers stay on existing `audit_service.log_async`
for now. They are not migrated opportunistically in this batch.

## Data Model / Migration Impact

Batch 3 is expected to add one Alembic migration and one SQLAlchemy
table mapping for `flow_run_audit_outbox`.

Migration requirements:

- create the outbox table with tenant/run/flow FKs
- enforce low-cardinality status/action/source strings with checks or
  code-side enums plus table constraints
- add a run audit lookup index and `UNIQUE (flow_run_id)`
- avoid touching unrelated audit tables
- no `waiting_for_review` status migration in Batch 3
- run `cd backend && uv run alembic heads`; if there is more than one
  head, stop before writing the migration

Rollback:

- migration downgrade drops only the outbox table/indexes/constraints
- source rollback can retarget terminalization call sites back to
  repository methods, but that is an emergency rollback, not a
  compatibility path to preserve

## Expected Files To Change

Docs/artifacts:

- `docs/refactor/execution/batch-3-lifecycle-terminalization-audit/plan.md`
- `docs/refactor/execution/batch-3-lifecycle-terminalization-audit/journal.md`
- `docs/refactor/execution/batch-3-lifecycle-terminalization-audit/retrospective-1.md`
- `docs/refactor/execution/batch-3-lifecycle-terminalization-audit/retrospective-2.md`
- `docs/refactor/execution/batch-3-lifecycle-terminalization-audit/claude-reconciliation-1.md`
- `docs/refactor/execution/batch-3-lifecycle-terminalization-audit/claude-reconciliation-2.md`

Source:

- `backend/src/intric/flows/enums.py`
- `backend/src/intric/flows/application/flow_run_terminalization.py`
- `backend/src/intric/flows/application/flow_dispatch.py`
- `backend/src/intric/flows/application/flow_run_service.py`
- `backend/src/intric/flows/infrastructure/flow_run_repo.py`
- `backend/src/intric/flows/runtime/executor.py`
- `backend/src/intric/flows/runtime/tasks.py`
- `backend/src/intric/flows/runtime/step_attempt_runtime.py`
- `backend/src/intric/database/tables/flow_tables.py`
- `backend/src/intric/main/container/container.py`
- one new Alembic migration under `backend/alembic/versions/`

Tests:

- `backend/tests/unittests/flows/test_flow_run_status_predicates.py`
- `backend/tests/integration/flows/test_flow_terminalization_contract.py`
- `backend/tests/integration/flows/test_flow_runtime_worker_contract.py`
- `backend/tests/unittests/flows/test_celery_runtime.py`
- `backend/tests/unittests/flows/test_flow_executor_runtime.py`
- `backend/tests/unittests/flows/test_flow_run_service.py`
- `backend/tests/unittests/flows/test_step_attempt_runtime.py` if
  predicate import behavior changes the step gate
- `backend/tests/integration/flows/test_flow_run_repository.py` if
  repository-level terminalization/outbox behavior needs DB coverage

This list is intentionally narrow. If implementation needs other source
or test files, stop, update this plan, and re-run `/plan`.

## Validation Commands

`implementation-order.md` names these Batch 3 validation categories:
runtime worker contract, stale reconciliation, task timeout, duplicate
terminalization, and audit outbox tests.

Before validation, run and record:

```bash
docker ps --format '{{.Names}}'
```

```bash
cd backend && uv run alembic heads
```

Preferred Docker validation:

```bash
docker exec -w /workspace/backend eneo-41ae93-eneo-1 uv run pyright \
  src/intric/flows/enums.py \
  src/intric/flows/application/flow_run_terminalization.py \
  src/intric/flows/application/flow_dispatch.py \
  src/intric/flows/application/flow_run_service.py \
  src/intric/flows/infrastructure/flow_run_repo.py \
  src/intric/flows/runtime/executor.py \
  src/intric/flows/runtime/tasks.py \
  src/intric/flows/runtime/step_attempt_runtime.py \
  src/intric/database/tables/flow_tables.py \
  tests/unittests/flows/test_flow_run_status_predicates.py \
  tests/integration/flows/test_flow_terminalization_contract.py \
  tests/integration/flows/test_flow_runtime_worker_contract.py \
  tests/unittests/flows/test_celery_runtime.py \
  tests/unittests/flows/test_flow_executor_runtime.py \
  tests/unittests/flows/test_flow_run_service.py
```

```bash
docker exec -w /workspace/backend eneo-41ae93-eneo-1 uv run pytest \
  tests/unittests/flows/test_flow_run_status_predicates.py \
  tests/integration/flows/test_flow_terminalization_contract.py \
  tests/integration/flows/test_flow_runtime_worker_contract.py \
  tests/unittests/flows/test_celery_runtime.py \
  tests/unittests/flows/test_flow_executor_runtime.py \
  tests/unittests/flows/test_flow_run_service.py \
  -q
```

```bash
git diff --check -- \
  backend/src/intric/flows \
  backend/src/intric/database/tables/flow_tables.py \
  backend/src/intric/main/container/container.py \
  backend/alembic/versions \
  backend/tests/integration/flows \
  backend/tests/unittests/flows \
  docs/refactor/execution/batch-3-lifecycle-terminalization-audit
```

```bash
rg -n "FlowRunStatus\\.(COMPLETED|FAILED|CANCELLED)|_TERMINAL_STATUSES|_ACTIVE_STATUSES|mark_pending_steps_cancelled\\(|fail_stale_running_run\\(|update_status\\(|_audit_run_terminal_state\\(|_mark_run_failed\\(|flow_run_repo\\.cancel\\(|run_repo\\.cancel\\(|\\\"(completed|failed|cancelled)\\\"" \
  backend/src/intric/flows
```

The `rg` guard is expected to retain enum definitions, status predicate owner,
and non-terminal claim paths. It must not show direct terminal
transitions outside the terminalization command unless explicitly
classified in the retrospective.

Local fallback if Docker is blocked:

```bash
cd backend && uv run pyright \
  src/intric/flows/enums.py \
  src/intric/flows/application/flow_run_terminalization.py \
  src/intric/flows/application/flow_dispatch.py \
  src/intric/flows/application/flow_run_service.py \
  src/intric/flows/infrastructure/flow_run_repo.py \
  src/intric/flows/runtime/executor.py \
  src/intric/flows/runtime/tasks.py \
  src/intric/flows/runtime/step_attempt_runtime.py \
  src/intric/database/tables/flow_tables.py \
  tests/unittests/flows/test_flow_run_status_predicates.py \
  tests/integration/flows/test_flow_terminalization_contract.py \
  tests/integration/flows/test_flow_runtime_worker_contract.py \
  tests/unittests/flows/test_celery_runtime.py \
  tests/unittests/flows/test_flow_executor_runtime.py \
  tests/unittests/flows/test_flow_run_service.py
```

```bash
cd backend && uv run pytest \
  tests/unittests/flows/test_flow_run_status_predicates.py \
  tests/integration/flows/test_flow_terminalization_contract.py \
  tests/integration/flows/test_flow_runtime_worker_contract.py \
  tests/unittests/flows/test_celery_runtime.py \
  tests/unittests/flows/test_flow_executor_runtime.py \
  tests/unittests/flows/test_flow_run_service.py \
  -q
```

Optional but expected boundary checks after the targeted tests pass:

```bash
cd backend && uv run lint-imports --no-cache
```

```bash
cd backend && uv run ruff check \
  src/intric/flows \
  tests/integration/flows/test_flow_terminalization_contract.py \
  tests/integration/flows/test_flow_runtime_worker_contract.py \
  tests/unittests/flows/test_celery_runtime.py \
  tests/unittests/flows/test_flow_executor_runtime.py \
  tests/unittests/flows/test_flow_run_service.py \
  tests/unittests/flows/test_flow_run_status_predicates.py
```

## Do Not Touch

- `frontend/packages/ui/src/icons/types.d.ts`
- `scripts/run_codex_review.sh`
- `PRODUCT.md`
- package namespace/import migration from `intric.*` to `eneo.*`
- generated frontend clients or package names
- migrations unrelated to Flow lifecycle audit outbox
- frontend source

## Risks And Stop Conditions

- If Claude rejects the outbox table shape as under-specified, stop and
  revise the plan before source changes.
- If adding the outbox migration requires multiple heads or a merge
  migration, stop and inspect Alembic heads before proceeding.
- If the runtime worker integration fixtures cannot exercise the Celery
  wrapper without broad setup, keep the direct executor contract and add
  a unit-level Celery wrapper behavior pin, then record the fixture gap.
- If terminalization requires changing public API response shape,
  stop; public API changes are not planned for this batch.
- If any direct terminal update remains after implementation, classify it
  in the retrospective. Unclassified direct terminal writes fail the
  batch.
