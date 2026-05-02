# Batch 10 — Operability, Cleanup, And Docs Plan

## TL;DR

1. Batch 9 is committed at `02292fe3`; Batch 10 is the next official batch.
2. The first implementation slice is Flow run lifecycle events, not audit-outbox delivery state, because the outbox currently has no consumer and delivery/dead-letter semantics require a separate runtime/data-model approval gate.
3. The canonical owner for run terminal state remains `FlowRunTerminalizer`; lifecycle events observe that boundary without creating a second terminalization path.
4. AI Builder observability remains separate from Flow runtime observability.
5. Unrelated dirty files remain out of scope: `scripts/run_codex_review.sh` and `PRODUCT.md`.

## Current Repository State

| Item | Evidence | Decision |
|---|---|---|
| Current branch | `git status --short --branch` reports `feature/refactor-flows-flowai` ahead of origin. | Continue on this branch only. |
| Current HEAD | `02292fe3 flows: add review checkpoint frontend state`. | Batch 9 is complete; Batch 10 starts here. |
| Staged files | `git diff --cached --name-only` returned empty. | Safe to plan. |
| Known unrelated dirty files | `scripts/run_codex_review.sh`, `PRODUCT.md`. | Do not touch, stage, format, or commit. |
| Additional untracked local scratch | `docs/refactor/goals.md`. | Treat as local scratch unless the user explicitly promotes it. |
| Docker validation | `docker exec eneo-41ae93-eneo-1 true` is blocked by this Codex process policy: `approval required by policy, but AskForApproval is set to Never`. | Record fallback and use local validation. |

## Batch 10 Source Requirements

`docs/refactor/implementation-order.md` defines Batch 10 as:

- PRDs: PRD-009 full operability, PRD-007/008 cleanup, PRD-010 docs
- Expected result: runbooks, dashboards/metrics, dead test deletion, readability cleanup, ADRs updated
- Validation: full targeted backend/frontend suites; docs diff review

Relevant acceptance criteria:

- PRD-009:
  - `RunObservabilityRecorder` or equivalent emits metrics from lifecycle/task boundaries.
  - Terminal audit outbox behavior is tested.
  - Flow runtime health probe exists.
  - Runbooks exist and alert metrics link to them.
  - AI Builder turn metrics are separate from flow run metrics.
- PRD-008:
  - Delete true dead code/tests and stale compatibility only after owning behavior coverage exists.
  - Comments explain intent, constraint, invariant, or trade-off; no restating comments.
- PRD-010:
  - Runtime runbooks document idempotency, retries, crash recovery, and rollback/recovery.

## Current Owner Inventory

| Concept | Current locations | Problem | Canonical home | Batch 10 decision |
|---|---|---|---|---|
| Terminal state transition | `backend/src/intric/flows/application/flow_run_terminalization.py:85-223` | Owns run CAS, attempt/result closure, checkpoint cancellation, rerun closure, and audit outbox insert. | `FlowRunTerminalizer` remains canonical. | Observe here; do not move terminalization. |
| Terminal audit outbox row | `backend/src/intric/database/tables/flow_tables.py:1218-1317`; `backend/src/intric/flows/infrastructure/flow_run_repo.py:1520-1599`; `rg "FlowRunAuditOutbox" backend/src` finds only the table and repo inserts. | Durable write exists, but there is no backend source consumer, delivery status, retry count, next retry, delivered timestamp, or dead-letter state. | `flow_run_audit_outbox` remains canonical lifecycle audit row. | Delivery/dead-letter is a delivery-model decision, not only a migration; do not add in Slice 10.1. |
| Terminal audit fail-closed behavior | `backend/tests/integration/flows/test_flow_terminalization_contract.py:401-459` | Insert failure rolls back terminal state; behavior is pinned. | `FlowRunTerminalizer` transaction boundary. | Preserve; add observability around outcomes without weakening fail-closed. |
| Dispatch failure terminalization | `backend/src/intric/flows/application/flow_dispatch.py:47-92` | Dispatch failure logs a free-form exception and terminalizes. | Dispatch adapter owns dispatch failure observation; terminalizer owns state write. | May emit a failure event in a later slice; not first implementation unless needed by terminalizer event contract. |
| Celery task timeout/missing principal | `backend/src/intric/flows/runtime/tasks.py:152-171`, `:202-257`, `:281-290` | Logs are not a stable metric/event contract. | Celery task adapter owns task-boundary events. | Later Batch 10 slice after lifecycle event contract. |
| AI Builder failure events | `backend/src/intric/flows/ai_builder/ai_builder_planner.py:1601-1626`; tests under `backend/tests/unittests/flows/ai_builder/test_ai_builder_failure_events.py`. | Separate event contract exists for AI Builder failures. | AI Builder planner observability remains separate. | Reuse shape/language, but do not route Flow lifecycle through AI Builder. |
| Existing generic failure event helper | `backend/src/intric/observability/failure_events.py`. | It is explicitly failure-event focused, not lifecycle metric focused. | Shared observability package. | Do not overload it for normal lifecycle success/no-op events; keep failure taxonomy reuse available for a later failure-event slice. |
| Tool-call evidence | `backend/src/intric/flows/flow_run_provenance.py:61` owns `llm.tool_calls`; `backend/src/intric/flows/runtime/models.py:52-66` carries transient execution output metadata before provenance capture. | The old result-row duplicate created a second evidence path after attempt provenance became canonical. | Attempt provenance remains canonical persisted evidence; runtime execution output remains transient input to provenance. | Slice 10.4 removes the persisted result-row field and evidence export guard instead of preserving a compatibility path. |

## Dead Code / Compatibility Inventory For This Slice

| Concept | Current locations | Shipped/persisted data need? | Keep/delete/rewrite | Canonical owner | Deletion condition |
|---|---|---|---|---|---|
| `tool_calls_metadata` result-row duplicate | `FlowStepResults`, `FlowStepResult`, retention service, evidence bundle guard | No shipped Flow consumers; live result writes stored NULL after provenance became canonical. | Delete in Slice 10.4. | `FlowAttemptProvenance` for persisted evidence; `StepExecutionOutput` for transient runtime metadata before provenance capture. | Completed by `20260502_drop_result_tool_calls`; no legacy field, deprecated schema member, or export exclusion remains. |
| Flow audit outbox without delivery state | `FlowRunAuditOutbox` table and repo inserts | Yes, rows are current lifecycle audit records. | Keep and plan delivery-state migration separately. | `flow_run_audit_outbox`. | Data-model approval for delivery/retry/dead-letter columns and worker contract. |
| AI Builder failure event comments | `ai_builder_planner.py:1567-1577` | Active diagnostics contract. | Keep. | AI Builder planner observability. | None in Batch 10. |
| Flow dispatch docstrings | `flow_dispatch.py:57`, `:105` | Active behavior description. | Keep unless source implementation narrows ownership. | Dispatch adapter. | None in Slice 10.1. |

## Slice 10.1 — Flow Run Lifecycle Event Contract

### Problem

Flow runtime now has durable lifecycle state and audit outbox writes, but operators still lack a stable log-event contract at the Flow lifecycle boundary. Current terminalization code returns structured results but emits no stable lifecycle event; task/dispatch logs are free-form and not enough for dashboards/runbooks.

### Why This Slice First

- It is implementation work and avoids another docs-only pass.
- It does not require a migration.
- It is the smallest safe foundation for PRD-009 runbooks and future dashboard counters.
- It keeps the source-of-truth owner clear: lifecycle events observe `FlowRunTerminalizer`; they do not become a second lifecycle owner.
- It closes only the structured event/log half of PRD-009 lifecycle observability. Metrics backend selection, counters, and dashboards remain later Batch 10 work.

### Proposed Canonical Owner

Create one narrow application-layer module:

```text
backend/src/intric/flows/application/flow_run_lifecycle_events.py
```

This module owns only the Flow run lifecycle log-event schema and the terminalization emit function. It must not own terminal state changes, audit outbox insertion, Celery dispatch, evidence export, AI Builder turns, metrics backend selection, or audit durability.

Required shape:

- `FLOW_RUN_LIFECYCLE_EVENT_SCHEMA_VERSION`
- one `TypedDict` for the log payload shape
- one `emit_flow_run_terminalization_event(...)` function with `outcome: Literal["transitioned", "noop_already_terminal", "noop_lost_race"]`
- module docstring that states the event is a best-effort observability signal and is not a substitute for the durable `flow_run_audit_outbox` row
- schema-version bump rule copied from the existing failure-event discipline: bump only for breaking shape changes

The event fields should be low-cardinality and safe:

- `event="flow_run.lifecycle"`
- `schema_version`
- `operation="terminalize_run"`
- `outcome`: `transitioned` / `noop_already_terminal` / `noop_lost_race`
- `tenant_id`
- `flow_id`
- `run_id`
- `trace_id` from the persisted `FlowRun.trace_id`, not request context plumbing
- `source`
- `target_status`
- `previous_status`
- `run_revision`
- `audit_outbox_id` when available
- `error_code` when available

### Implementation Constraints

- Do not create a generic observability manager.
- Do not add a fake interface, Protocol, ABC, factory, or backend abstraction.
- Do not add a metrics backend.
- Do not add or modify migrations.
- Do not add audit-outbox delivery/dead-letter columns in this slice.
- Do not alter terminalization transaction semantics.
- Do not weaken `test_terminalization_rolls_back_when_audit_outbox_insert_fails`.
- Do not emit a misleading success lifecycle event before `insert_terminal_audit_outbox` succeeds.
- Do not route AI Builder events through this module.
- Do not touch unrelated dirty files.

### Expected Files To Change

Source:

- `backend/src/intric/flows/application/flow_run_lifecycle_events.py`
- `backend/src/intric/flows/application/flow_run_terminalization.py`

Tests:

- `backend/tests/unittests/flows/test_flow_run_lifecycle_events.py`
- `backend/tests/integration/flows/test_flow_terminalization_contract.py`

Docs:

- `docs/refactor/execution/batch-10-operability-cleanup-docs/plan.md`
- `docs/refactor/execution/batch-10-operability-cleanup-docs/journal.md`
- `docs/refactor/execution/batch-10-operability-cleanup-docs/retrospective-1.md`
- `docs/refactor/execution/batch-10-operability-cleanup-docs/claude-reconciliation-1.md`

### Behavior Pins Before Source Change

Before changing terminalizer behavior, add/confirm tests that pin:

- terminalization success emits exactly one stable lifecycle event with target status, source, run id, tenant id, trace id, revision, and audit outbox id
- duplicate terminalization/no-op emits exactly one `noop_already_terminal` event with the current run status and no audit outbox id
- lost CAS race emits exactly one `noop_lost_race` event with the current run status and no audit outbox id
- outbox insert failure still rolls back terminal state and does not produce a `transitioned` event
- invariant failure for completing with active work remains a raised `FlowRunTerminalizationInvariantError`
- event assertions use `caplog.records` filtered by `record.event == "flow_run.lifecycle"`; no recorder fake or injected test-only interface

### Validation Commands

Backend local fallback commands:

```bash
cd backend && uv run pytest \
  tests/unittests/flows/test_flow_run_lifecycle_events.py \
  tests/integration/flows/test_flow_terminalization_contract.py \
  -q
```

```bash
cd backend && uv run pyright \
  src/intric/flows/application/flow_run_lifecycle_events.py \
  src/intric/flows/application/flow_run_terminalization.py \
  tests/unittests/flows/test_flow_run_lifecycle_events.py \
  tests/integration/flows/test_flow_terminalization_contract.py
```

```bash
cd backend && uv run ruff check \
  src/intric/flows/application/flow_run_lifecycle_events.py \
  src/intric/flows/application/flow_run_terminalization.py \
  tests/unittests/flows/test_flow_run_lifecycle_events.py \
  tests/integration/flows/test_flow_terminalization_contract.py
```

```bash
cd backend && uv run ruff format --check \
  src/intric/flows/application/flow_run_lifecycle_events.py \
  src/intric/flows/application/flow_run_terminalization.py \
  tests/unittests/flows/test_flow_run_lifecycle_events.py \
  tests/integration/flows/test_flow_terminalization_contract.py
```

```bash
cd backend && uv run lint-imports --no-cache
```

```bash
git diff --check -- \
  backend/src/intric/flows/application/flow_run_lifecycle_events.py \
  backend/src/intric/flows/application/flow_run_terminalization.py \
  backend/tests/unittests/flows/test_flow_run_lifecycle_events.py \
  backend/tests/integration/flows/test_flow_terminalization_contract.py \
  docs/refactor/execution/batch-10-operability-cleanup-docs
```

Source guards:

```bash
./scripts/gate-local/anti_slippage.sh --worktree
```

Expected: no planning vocabulary in code diffs; docs are excluded by the existing guard.

Docker preferred command, if policy allows later:

```bash
docker exec -w /workspace/backend eneo-41ae93-eneo-1 uv run pytest \
  tests/unittests/flows/test_flow_run_lifecycle_events.py \
  tests/integration/flows/test_flow_terminalization_contract.py \
  -q
```

Current Codex process blocks Docker execution before the host can run it; local fallback is the active validation path.

## Slice 10.2 — Flow Runtime Health Probe And Runbook

### Problem

Operators can see coarse backend and crawler health, but Flow runtime readiness still requires manually reading `flow_runs`, Celery logs, reconciliation code, and terminalization tests. PRD-009 requires a Flow runtime health probe and runbooks before Flows can be treated as production-supportable.

### Canonical Owner

| Concept | Current owner | Slice 10.2 decision |
|---|---|---|
| Global health endpoints | `backend/src/intric/server/main.py` owns `/api/healthz` and `/api/healthz/crawler`. | Register `/api/healthz/flows` on the same global health surface. Do not add an authenticated `/api/v1/flows` diagnostics route. |
| Flow stale-run thresholds | `FlowRunService` and Flow Celery tasks currently encode stale queued/running timing. | Centralize in `backend/src/intric/flows/application/flow_run_recovery_policy.py` before publishing threshold values in the health response. |
| Flow runtime DB health contract | No current owner. | Add `backend/src/intric/flows/runtime/flow_runtime_health.py` for typed response models, DB snapshot loading, and pure health classification. |
| Flow runtime runbook | No current operator runbook. | Add `docs/runbooks/flows.md`; `docs/TROUBLESHOOTING.md` only links to it. |

### Source Shape

`flow_runtime_health.py` must keep three boundaries visible:

- `load_flow_runtime_health_snapshot(...)`: SQL snapshot only, no status policy.
- `classify_flow_runtime_health(...)`: pure classification from snapshot, policy, and probe result.
- `FlowRuntimeHealthResponse`: response model consumed by `server/main.py`.

The response is aggregate-only because the endpoint is unauthenticated. It must not expose tenant IDs, flow IDs, run IDs, trace IDs, audit outbox IDs, prompts, payloads, evidence, or raw database errors.

### Status Rules

| Signal | Health status |
|---|---|
| DB query timeout/error | `UNKNOWN` |
| `TERMINAL_RUNS_WITH_OPEN_ATTEMPTS` | `UNHEALTHY` |
| `TERMINAL_RUNS_WITH_ACTIVE_STEP_RESULTS` | `UNHEALTHY` |
| `STALE_RUNNING_RECONCILER_LAG` | `UNHEALTHY` |
| `STALE_RUNNING_RUNS` inside reconciler grace | `DEGRADED` |
| `STALE_QUEUED_RUNS` | `DEGRADED` |
| No flags and DB query succeeds | `HEALTHY` |

Important adjustment from Claude: stale running count alone is not an unhealthy signal because the scheduled reconciler is expected to see stale running rows briefly. The unhealthy signal is stale running age beyond the reconciler grace window.

### Query Constraints

- Use existing DB state only; do not inspect Celery broker state in this slice.
- Keep the route timeout at 2 seconds, matching the crawler diagnostics responsiveness guard.
- Bound terminal-run open-work checks to the recent operator-actionable window (`24h`) so historical corruption cannot make the probe permanently slow or permanently unhealthy.
- Use closed enum values for status flags; do not create open-ended string flags or value-encoded flags.
- Do not add metrics backend, migrations, audit delivery columns, or delivery workers in this slice.

### Expected Files To Change

Source:

- `backend/src/intric/flows/application/flow_run_recovery_policy.py`
- `backend/src/intric/flows/application/flow_run_service.py`
- `backend/src/intric/flows/runtime/celery_app.py`
- `backend/src/intric/flows/runtime/tasks.py`
- `backend/src/intric/flows/runtime/flow_runtime_health.py`
- `backend/src/intric/server/main.py`

Tests:

- `backend/tests/unittests/flows/test_flow_runtime_health.py`
- `backend/tests/integration/flows/test_flow_runtime_health.py`
- `backend/tests/unit/test_api_key_contract_matrix.py`

Docs:

- `docs/runbooks/flows.md`
- `docs/TROUBLESHOOTING.md`
- Batch 10 plan/journal/reconciliation/retrospective docs.

### Validation Commands

```bash
cd backend && uv run pytest \
  tests/unittests/flows/test_flow_runtime_health.py \
  tests/integration/flows/test_flow_runtime_health.py \
  tests/unit/test_api_key_contract_matrix.py \
  -q
```

```bash
cd backend && uv run pyright \
  src/intric/flows/application/flow_run_recovery_policy.py \
  src/intric/flows/application/flow_run_service.py \
  src/intric/flows/runtime/celery_app.py \
  src/intric/flows/runtime/tasks.py \
  src/intric/flows/runtime/flow_runtime_health.py \
  src/intric/server/main.py \
  tests/unittests/flows/test_flow_runtime_health.py \
  tests/integration/flows/test_flow_runtime_health.py \
  tests/unit/test_api_key_contract_matrix.py
```

```bash
cd backend && uv run ruff check \
  src/intric/flows/application/flow_run_recovery_policy.py \
  src/intric/flows/application/flow_run_service.py \
  src/intric/flows/runtime/celery_app.py \
  src/intric/flows/runtime/tasks.py \
  src/intric/flows/runtime/flow_runtime_health.py \
  src/intric/server/main.py \
  tests/unittests/flows/test_flow_runtime_health.py \
  tests/integration/flows/test_flow_runtime_health.py \
  tests/unit/test_api_key_contract_matrix.py
```

```bash
cd backend && uv run ruff format --check \
  src/intric/flows/application/flow_run_recovery_policy.py \
  src/intric/flows/application/flow_run_service.py \
  src/intric/flows/runtime/celery_app.py \
  src/intric/flows/runtime/tasks.py \
  src/intric/flows/runtime/flow_runtime_health.py \
  src/intric/server/main.py \
  tests/unittests/flows/test_flow_runtime_health.py \
  tests/integration/flows/test_flow_runtime_health.py \
  tests/unit/test_api_key_contract_matrix.py
```

## Slice 10.3 — Flow Audit Outbox Delivery

### Problem

`flow_run_audit_outbox` now records terminal and review-checkpoint lifecycle facts in the same transaction as the runtime state change, but rows stop there. PRD-003 requires delivery to keep terminal state, retry, and alert; PRD-009 requires retry/delivery state and operational visibility.

### Source Evidence

| Concept | Evidence | Decision |
|---|---|---|
| Durable lifecycle write | `backend/src/intric/database/tables/flow_tables.py:1218-1317` owns `FlowRunAuditOutbox`; `backend/src/intric/flows/infrastructure/flow_run_repo.py:1520-1599` inserts terminal and review-checkpoint rows. | Keep the relational outbox as the canonical lifecycle audit fact. |
| No consumer | `rg "FlowRunAuditOutbox\|flow_run_audit_outbox" backend/src/intric` finds only the table and insert paths. | Add a Flow-owned Celery delivery task; do not use ARQ. |
| Generic audit write boundary | `backend/src/intric/audit/infrastructure/audit_log_repo_impl.py:84-111` writes `AuditLog` rows directly. | Delivery uses the existing `AuditLogRepository` contract, not `AuditService.log_async`. |
| Audit feature flags | `backend/src/intric/audit/application/audit_service.py:129-132` can skip audit logs through tenant/config gating. | Flow lifecycle audit bypasses tenant audit feature flags by design because PRD-003 treats it as part of durable runtime state, not best-effort product telemetry. |
| Existing audit description field | `flow_run_audit_description(...)` returns `action:source`; `ck_flow_run_audit_outbox_description` enforces that shape. | Keep the outbox idempotency key as-is, but synthesize human-readable `audit_logs.description` during delivery. |

### Canonical Owners

| Concept | Canonical home | Why |
|---|---|---|
| Outbox row insert, claim, delivery state | `backend/src/intric/flows/infrastructure/flow_run_audit_outbox_repo.py` | The outbox table has its own lifecycle and should not add more methods to `FlowRunRepository`. |
| Row-to-audit projection and retry policy application | `backend/src/intric/flows/application/flow_run_audit_outbox_delivery.py` | Application layer owns delivery decisions and the transformation into the platform audit domain. |
| Retry/backlog constants | `backend/src/intric/flows/application/flow_run_audit_outbox_policy.py` | Keeps retry, beat, and health thresholds in one place. |
| Aggregate health response | `backend/src/intric/flows/runtime/flow_runtime_health.py` | Existing health module owns DB snapshots and pure classification. |
| Celery task and schedule | `backend/src/intric/flows/runtime/tasks.py`; `backend/src/intric/flows/runtime/celery_app.py` | Existing Flow Celery runtime owns scheduled Flow runtime maintenance. |

### Data Model

Add a migration after `20260502_flow_step_review_policy`:

- `delivery_status`: `pending`, `delivered`, or `dead_lettered`; default `pending`.
- `delivery_attempts`: integer, default `0`, constrained `>= 0`.
- `next_delivery_at`: timezone timestamp, default `now()`.
- `delivered_at`: timezone timestamp, nullable.
- `dead_lettered_at`: timezone timestamp, nullable.
- `delivery_last_error`: text, nullable.

Do not add `audit_log_id`. Delivery creates the final audit log with `audit_logs.id == flow_run_audit_outbox.id`, so the outbox primary key is also the idempotency key for the audit row. This avoids a second identifier, avoids dangling FKs when audit retention deletes old audit rows, and makes duplicate delivery safe.

Status constraints:

- `pending`: `delivered_at IS NULL AND dead_lettered_at IS NULL`.
- `delivered`: `delivered_at IS NOT NULL AND dead_lettered_at IS NULL`.
- `dead_lettered`: `delivered_at IS NULL AND dead_lettered_at IS NOT NULL`.

Indexes:

- pending delivery index on `next_delivery_at, created_at` where `delivery_status = 'pending'`.
- dead-letter index on `dead_lettered_at` where `delivery_status = 'dead_lettered'`.

Retention decision: delivered/dead-lettered outbox retention is a follow-up for Slice 10.5 because delivered rows are operational lifecycle records, not a blocker for adding durable delivery. The model intentionally avoids an `audit_logs` FK so audit-log retention cannot break Flow outbox rows.

### Delivery Contract

Policy values live in `flow_run_audit_outbox_policy.py`:

- `FLOW_AUDIT_OUTBOX_DELIVERY_INTERVAL_SECONDS = 60`
- `FLOW_AUDIT_OUTBOX_DELIVERY_BATCH_SIZE = 100`
- `FLOW_AUDIT_OUTBOX_MAX_ATTEMPTS = 5`
- `FLOW_AUDIT_OUTBOX_RETRY_BACKOFF_SECONDS = (60, 300, 900, 3600)`
- `FLOW_AUDIT_OUTBOX_BACKLOG_GRACE_SECONDS = 300`

Delivery loop:

1. Load due pending rows with `FOR UPDATE SKIP LOCKED`.
2. Process each row in its own nested transaction so one bad row cannot roll back unrelated deliveries.
3. Build `AuditLog(id=outbox.id, ...)`.
4. Call `AuditLogRepository.create_if_absent(...)`, implemented with `INSERT ... ON CONFLICT (id) DO NOTHING`, so an existing audit row with the outbox id is treated as already delivered.
5. Mark the outbox `delivered` in the same transaction.
6. Domain validation failures dead-letter immediately because retry cannot repair the row.
7. Unexpected delivery failures schedule bounded retry until max attempts; max attempts dead-letters.

### Audit Projection

The delivered audit log description is synthesized from lifecycle state instead of copying the outbox's `action:source` idempotency string:

| Outbox row | Delivered `audit_logs.description` |
|---|---|
| `action=flow_run_completed`, `source=executor_completed` | `Flow run completed by executor_completed.` |
| `action=flow_run_failed`, `source=task_timeout` | `Flow run failed by task_timeout.` |
| `action=flow_run_review_checkpoint_approved`, `source=review_checkpoint_approved` | `Flow run review checkpoint approved by review_checkpoint_approved.` |

Delivered metadata keys:

- `flow_id`
- `flow_run_id`
- `run_revision`
- `source`
- `target_status`
- `review_checkpoint_id`
- `checkpoint_revision`
- `error_code`
- `outbox_description`

Only `FLOW_RUN_FAILED` maps to `Outcome.FAILURE`; all other lifecycle rows are successful audit records of the lifecycle operation. Failure audit logs use the outbox `error_message`, then `error_code`, then `action:source` to guarantee the audit domain receives a non-empty failure message.

### Health Contract

Extend `/api/healthz/flows` aggregate response with `audit_outbox` counts only:

- `pending_count`
- `delivery_backlog_count`
- `dead_lettered_count`
- `oldest_delivery_backlog_age_seconds`
- `oldest_dead_lettered_age_seconds`

Flags:

- `AUDIT_OUTBOX_DELIVERY_BACKLOG`: `DEGRADED` when pending rows are older than `FLOW_AUDIT_OUTBOX_BACKLOG_GRACE_SECONDS`.
- `AUDIT_OUTBOX_DEAD_LETTERS`: `UNHEALTHY` when any dead-lettered row exists.

The public health response must not expose tenant ids, flow ids, run ids, checkpoint ids, outbox ids, audit ids, prompts, payloads, evidence, or raw database errors.

### Expected Files To Change

Source:

- `backend/src/intric/database/tables/flow_tables.py`
- `backend/alembic/versions/20260502_flow_audit_outbox_delivery.py`
- `backend/src/intric/flows/infrastructure/flow_run_audit_outbox_repo.py`
- `backend/src/intric/flows/infrastructure/flow_run_repo.py`
- `backend/src/intric/flows/application/flow_run_audit_outbox_policy.py`
- `backend/src/intric/flows/application/flow_run_audit_outbox_delivery.py`
- `backend/src/intric/flows/application/flow_run_terminalization.py`
- `backend/src/intric/flows/application/flow_run_service.py`
- `backend/src/intric/flows/runtime/celery_app.py`
- `backend/src/intric/flows/runtime/executor.py`
- `backend/src/intric/flows/runtime/tasks.py`
- `backend/src/intric/flows/runtime/flow_runtime_health.py`
- `backend/src/intric/main/container/container.py`

Tests:

- `backend/tests/unittests/flows/test_flow_audit_outbox_delivery.py`
- `backend/tests/unittests/flows/test_flow_review_checkpoint_data_model.py`
- `backend/tests/unittests/flows/test_celery_runtime.py`
- `backend/tests/unittests/flows/test_flow_runtime_health.py`
- `backend/tests/integration/flows/test_flow_audit_outbox_delivery.py`
- `backend/tests/integration/flows/test_flow_runtime_health.py`
- `backend/tests/integration/flows/test_flow_run_repository.py`
- targeted review/terminalization contract tests that currently call `FlowRunRepository.insert_*_audit_outbox`.

Docs:

- Batch 10 plan/journal/reconciliation/retrospective.
- `docs/runbooks/flows.md`

### Tests Required

- Delivery creates one `audit_logs` row with `id == outbox.id` and marks the outbox delivered.
- Re-running delivery for an outbox whose audit log already exists marks delivered without creating a second audit log.
- In a multi-row batch, a deterministic invalid row dead-letters and valid neighboring rows deliver.
- Unexpected repository failure schedules retry, then dead-letters at `FLOW_AUDIT_OUTBOX_MAX_ATTEMPTS`.
- Check constraints reject impossible delivery status/timestamp combinations, unsupported delivery statuses, and negative delivery attempts.
- Celery app routes and schedules `flows.deliver_audit_outbox` on the Flow queue.
- Health classification degrades on aged backlog and becomes unhealthy on dead letters.
- Terminalization still rolls back when outbox insert fails before terminal state change.

### Validation Commands

```bash
cd backend && uv run pytest \
  tests/unittests/flows/test_flow_audit_outbox_delivery.py \
  tests/unittests/flows/test_flow_review_checkpoint_data_model.py \
  tests/unittests/flows/test_celery_runtime.py \
  tests/unittests/flows/test_flow_runtime_health.py \
  tests/integration/flows/test_flow_audit_outbox_delivery.py \
  tests/integration/flows/test_flow_runtime_health.py \
  tests/integration/flows/test_flow_terminalization_contract.py \
  tests/integration/flows/test_flow_run_review_checkpoint_repository.py \
  tests/integration/flows/test_flow_run_repository.py \
  -q
```

```bash
cd backend && uv run pyright \
  src/intric/flows/infrastructure/flow_run_audit_outbox_repo.py \
  src/intric/flows/infrastructure/flow_run_repo.py \
  src/intric/flows/application/flow_run_audit_outbox_policy.py \
  src/intric/flows/application/flow_run_audit_outbox_delivery.py \
  src/intric/flows/application/flow_run_terminalization.py \
  src/intric/flows/application/flow_run_service.py \
  src/intric/flows/runtime/celery_app.py \
  src/intric/flows/runtime/executor.py \
  src/intric/flows/runtime/tasks.py \
  src/intric/flows/runtime/flow_runtime_health.py \
  src/intric/main/container/container.py \
  tests/unittests/flows/test_flow_audit_outbox_delivery.py \
  tests/unittests/flows/test_flow_review_checkpoint_data_model.py \
  tests/unittests/flows/test_celery_runtime.py \
  tests/unittests/flows/test_flow_runtime_health.py \
  tests/integration/flows/test_flow_audit_outbox_delivery.py \
  tests/integration/flows/test_flow_runtime_health.py \
  tests/integration/flows/test_flow_terminalization_contract.py \
  tests/integration/flows/test_flow_run_review_checkpoint_repository.py \
  tests/integration/flows/test_flow_run_repository.py
```

```bash
cd backend && uv run ruff check \
  src/intric/flows/infrastructure/flow_run_audit_outbox_repo.py \
  src/intric/flows/infrastructure/flow_run_repo.py \
  src/intric/flows/application/flow_run_audit_outbox_policy.py \
  src/intric/flows/application/flow_run_audit_outbox_delivery.py \
  src/intric/flows/application/flow_run_terminalization.py \
  src/intric/flows/application/flow_run_service.py \
  src/intric/flows/runtime/celery_app.py \
  src/intric/flows/runtime/executor.py \
  src/intric/flows/runtime/tasks.py \
  src/intric/flows/runtime/flow_runtime_health.py \
  src/intric/main/container/container.py \
  tests/unittests/flows/test_flow_audit_outbox_delivery.py \
  tests/unittests/flows/test_flow_review_checkpoint_data_model.py \
  tests/unittests/flows/test_celery_runtime.py \
  tests/unittests/flows/test_flow_runtime_health.py \
  tests/integration/flows/test_flow_audit_outbox_delivery.py \
  tests/integration/flows/test_flow_runtime_health.py \
  tests/integration/flows/test_flow_terminalization_contract.py \
  tests/integration/flows/test_flow_run_review_checkpoint_repository.py \
  tests/integration/flows/test_flow_run_repository.py
```

```bash
cd backend && uv run ruff format --check \
  src/intric/flows/infrastructure/flow_run_audit_outbox_repo.py \
  src/intric/flows/infrastructure/flow_run_repo.py \
  src/intric/flows/application/flow_run_audit_outbox_policy.py \
  src/intric/flows/application/flow_run_audit_outbox_delivery.py \
  src/intric/flows/application/flow_run_terminalization.py \
  src/intric/flows/application/flow_run_service.py \
  src/intric/flows/runtime/celery_app.py \
  src/intric/flows/runtime/executor.py \
  src/intric/flows/runtime/tasks.py \
  src/intric/flows/runtime/flow_runtime_health.py \
  src/intric/main/container/container.py \
  tests/unittests/flows/test_flow_audit_outbox_delivery.py \
  tests/unittests/flows/test_flow_review_checkpoint_data_model.py \
  tests/unittests/flows/test_celery_runtime.py \
  tests/unittests/flows/test_flow_runtime_health.py \
  tests/integration/flows/test_flow_audit_outbox_delivery.py \
  tests/integration/flows/test_flow_runtime_health.py \
  tests/integration/flows/test_flow_terminalization_contract.py \
  tests/integration/flows/test_flow_run_review_checkpoint_repository.py \
  tests/integration/flows/test_flow_run_repository.py
```

```bash
cd backend && uv run lint-imports --no-cache
./scripts/gate-local/anti_slippage.sh --worktree
```

## Slice 10.4 — Remove Result-Row Tool-Call Metadata

### Problem

Batch 7A made Flow attempt provenance the canonical owner for LLM evidence, but the old result-row `tool_calls_metadata` field remained in the database model, domain result model, repository writes, retention cleanup, and evidence export guard. Because Flows are not released, preserving the duplicate as a deprecated or backwards-compatible result field would create dead architecture before launch.

### Source Evidence

| Concept | Evidence | Decision |
|---|---|---|
| Persisted result row | `backend/src/intric/database/tables/flow_tables.py:498-542` owns `FlowStepResults`; the duplicate column is removed by this slice. | Result rows no longer persist tool-call metadata. |
| Domain result model | `backend/src/intric/flows/domain/flow.py:165-180` owns `FlowStepResult`; the duplicate field is removed. | API/evidence result records cannot accidentally expose the old field. |
| Canonical persisted evidence | `backend/src/intric/flows/flow_run_provenance.py:61` owns `llm.tool_calls`. | Attempt provenance remains the only persisted Flow tool-call evidence path. |
| Transient runtime metadata | `backend/src/intric/flows/runtime/models.py:52-66` owns `StepExecutionOutput.tool_calls_metadata`. | Keep this transient carrier because step execution still needs to move LLM adapter metadata into attempt provenance. |
| Evidence export guard | `backend/src/intric/flows/flow_run_evidence_bundle.py:300-301` now dumps result records directly. | Delete the omission guard because the result model no longer contains the field. |
| Retention cleanup | `backend/src/intric/data_retention/infrastructure/data_retention_service.py` no longer selects, counts, or clears the result field. | Retention follows the remaining persisted evidence owners only. |

### Canonical Owners

| Concept | Canonical home | What must not be preserved |
|---|---|---|
| Persisted LLM tool-call evidence | `FlowAttemptProvenance.llm.tool_calls` | No `FlowStepResult.tool_calls_metadata`, ORM result column, deprecated schema field, or evidence export exclusion. |
| Runtime adapter metadata before provenance capture | `StepExecutionOutput.tool_calls_metadata` | Do not move transient execution metadata into result rows. |
| Result-row persistence | `FlowRepository.save_step_result` | Do not write NULL placeholders for removed fields. |
| Rerun reset state | `FlowRunRepository._RERUN_STEP_RESULT_RESET_VALUES` | Do not reset columns that no longer exist. |

### Implementation Shape

Add migration `20260502_drop_result_tool_calls` after `20260502_flow_audit_delivery`:

- upgrade drops `flow_step_results.tool_calls_metadata`
- downgrade recreates the nullable JSONB column for schema reversibility only
- downgrade does not restore data because live Flow result writes already stored this field as NULL before removal

Delete the field from:

- `FlowStepResults`
- `FlowStepResult`
- `intric.flows.flow` re-export
- `FlowRepository.save_step_result`
- rerun result reset values
- retention cleanup select/update/count logic
- evidence bundle exclusion guard
- tests that protected the now-deleted result-level field

Keep:

- completion model and assistant tool-call metadata outside Flow result persistence
- `StepExecutionOutput.tool_calls_metadata`
- attempt provenance tool-call preview and tests

### Tests Required

- Result repository tests should build and persist `FlowStepResult` without a result-level tool-call field.
- Evidence API/export tests should keep proving attempt provenance is present; do not add a vacuous negative schema test for a field that no longer exists in any Flow result owner.
- Rerun repository tests should reset active result state without referencing removed columns.
- Retention cleanup tests should tombstone remaining persisted debug fields without the deleted column.
- Runtime tests should still pass transient `StepExecutionOutput.tool_calls_metadata` through attempt provenance.

### Validation Commands

```bash
cd backend && uv run pytest \
  tests/unittests/flows/test_flow_run_evidence.py \
  tests/unittests/flows/test_step_attempt_runtime.py \
  tests/unittests/flows/test_flow_runtime_builders.py \
  tests/unittests/flows/test_step_execution_runtime.py \
  tests/unittests/flows/test_flow_executor_runtime.py \
  tests/unittests/flows/test_flow_claim_resolution.py \
  tests/unittests/flows/test_flow_run_outcome.py \
  tests/unittests/flows/test_variable_resolver.py \
  tests/unittests/flows/test_typed_io_executor.py \
  tests/unittests/flows/test_flow_run_service.py \
  tests/unittests/flows/test_template_fill_runtime.py \
  tests/unit/test_flow_openapi_contract.py \
  -q
```

Host note: the PDF artifact case in `test_typed_io_executor.py` requires WeasyPrint native libraries that are missing on this host. The local fallback validation reruns the same suite with only `tests/unittests/flows/test_typed_io_executor.py::test_document_outputs_generate_downloadable_artifacts[pdf-application/pdf-.pdf]` deselected and records the environment failure separately.

```bash
cd backend && uv run pytest \
  tests/integration/test_flow_runtime_retention_cleanup.py \
  tests/integration/flows/test_flow_repository.py \
  tests/integration/flows/test_flow_evidence_api_contracts.py \
  tests/integration/flows/test_flow_run_rerun_repository.py \
  tests/integration/flows/test_flow_step_file_mapping_contract.py \
  -q
```

```bash
cd backend && uv run pyright \
  src/intric/data_retention/infrastructure/data_retention_service.py \
  src/intric/database/tables/flow_tables.py \
  src/intric/flows/domain/flow.py \
  src/intric/flows/flow.py \
  src/intric/flows/flow_run_evidence_bundle.py \
  src/intric/flows/infrastructure/flow_repo.py \
  src/intric/flows/infrastructure/flow_run_repo.py \
  src/intric/flows/runtime/step_result_builder.py \
  tests/integration/test_flow_runtime_retention_cleanup.py \
  tests/integration/flows/test_flow_repository.py \
  tests/integration/flows/test_flow_evidence_api_contracts.py \
  tests/integration/flows/test_flow_run_rerun_repository.py \
  tests/integration/flows/test_flow_step_file_mapping_contract.py \
  tests/unittests/flows/test_flow_run_evidence.py \
  tests/unittests/flows/test_step_attempt_runtime.py \
  tests/unittests/flows/test_flow_runtime_builders.py \
  tests/unittests/flows/test_step_execution_runtime.py \
  tests/unittests/flows/test_flow_executor_runtime.py \
  tests/unittests/flows/test_flow_claim_resolution.py \
  tests/unittests/flows/test_flow_run_outcome.py \
  tests/unittests/flows/test_variable_resolver.py \
  tests/unittests/flows/test_typed_io_executor.py \
  tests/unittests/flows/test_flow_run_service.py \
  tests/unittests/flows/test_template_fill_runtime.py \
  tests/unit/test_flow_openapi_contract.py
```

```bash
cd backend && uv run ruff check ...
cd backend && uv run ruff format --check ...
cd backend && uv run lint-imports --no-cache
git diff --check -- ...
./scripts/gate-local/anti_slippage.sh --worktree
```

Ownership grep:

```bash
rg -n "tool_calls_metadata|ToolCallMetadata" \
  backend/src/intric/flows/domain \
  backend/src/intric/flows/flow.py \
  backend/src/intric/database/tables/flow_tables.py \
  backend/src/intric/flows/infrastructure \
  backend/src/intric/flows/flow_run_evidence_bundle.py \
  backend/src/intric/data_retention/infrastructure/data_retention_service.py
```

Expected: no output.

## Slice 10.5 — Delivered Audit Outbox Retention And Docs Cleanup

### Problem

Slice 10.3 made `flow_run_audit_outbox.id == audit_logs.id` the delivery idempotency key. After delivery, the platform audit log is the canonical audit record, but the delivered outbox row still contains the same audit facts. Audit retention hard-deletes old `audit_logs`; without a Flow-owned cleanup, delivered outbox rows can outlive their audit-log twins and become a hidden audit retention bypass.

The runbook also describes audit outbox triage without listing the existing `audit_outbox` health fields and flags, and the architecture map still documents the deleted result-level `tool_calls_metadata` field.

### Source Evidence

| Concept | Evidence | Decision |
|---|---|---|
| Delivered audit identity | `backend/src/intric/flows/application/flow_run_audit_outbox_delivery.py:149-166` builds `AuditLog(id=row.id, timestamp=row.created_at, ...)`. | The audit log is the delivered audit record; the delivered outbox row is delivery staging state. |
| Audit retention | `backend/src/intric/audit/infrastructure/audit_log_repo_impl.py:369-407` hard-deletes `audit_logs` older than tenant retention. | Delivered outbox cleanup should follow actual audit-log deletion, not duplicate tenant retention cutoff logic. |
| Flow outbox table | `backend/src/intric/database/tables/flow_tables.py:1218-1377` stores delivery state and audit facts. | Delete only rows with `delivery_status='delivered'` and no `audit_logs` twin. |
| Pending/dead-lettered rows | `backend/src/intric/flows/runtime/flow_runtime_health.py:42-49`, `:110-115`, `:287-294` expose backlog/dead-letter health. | Pending rows still need delivery; dead-lettered rows are unresolved audit incidents and must not be auto-deleted without replay/ack semantics. |
| Data retention worker | `backend/src/intric/data_retention/infrastructure/data_retention_worker.py:16-24`, `:124-148` reports Flow runtime cleanup counts. | Add a sibling cleanup transaction and a separate `flow_audit_outbox_delivered_rows` count. |
| Runbook drift | `docs/runbooks/flows.md:17-39` omits existing audit outbox health fields and flags. | Complete the health contract table before adding retention behavior. |
| Architecture doc drift | `docs/FLOWS_AND_AI_BUILDER_ARCHITECTURE.md:627`, `:645`, `:934` still mention result-level `tool_calls_metadata`. | Remove all current-architecture references and point tool-call evidence to attempt provenance. |

### Canonical Owners

| Concept | Canonical home | What not to do |
|---|---|---|
| Delivered audit record | `audit_logs` | Do not keep delivered outbox rows as a second audit log after the audit log is hard-deleted. |
| Delivery staging state | `flow_run_audit_outbox` | Do not delete pending rows or unresolved dead letters. |
| Delivered outbox retention cleanup | `DataRetentionService.delete_old_delivered_flow_audit_outbox_rows` | Do not make shared audit retention import Flow infrastructure. |
| Data retention worker reporting | `data_retention_worker.DeletedCounts` | Do not mix audit-outbox hard deletes into `FlowRuntimeCleanupCounts`, which is for Flow debug/artifact tombstoning. |
| Health/runbook operator contract | `docs/runbooks/flows.md` | Do not document partial fields while the endpoint already returns audit outbox fields. |

### Revised Cleanup Policy

Use an anti-join on the delivered audit log twin:

```sql
DELETE FROM flow_run_audit_outbox outbox
WHERE outbox.delivery_status = 'delivered'
  AND NOT EXISTS (
    SELECT 1
    FROM audit_logs audit
    WHERE audit.id = outbox.id
  )
```

This keeps audit retention as the single source of truth. It is safe if cron order changes, if audit retention policy changes, or if a tenant's audit purge is skipped. The outbox row is deleted only after the audit row is gone.

Implementation requirements:

- Use `RETENTION_BATCH_SIZE` from `data_retention_service.py`; no new batching constant.
- Use the existing batched delete shape: `DELETE ... WHERE id IN (SELECT id ... LIMIT RETENTION_BATCH_SIZE)`, looped until `rowcount == 0`.
- Add `DataRetentionService.delete_old_delivered_flow_audit_outbox_rows() -> int`.
- Run it from `cleanup_old_data` in its own transaction after `cleanup_old_flow_runtime_data`.
- Report the count as `flow_audit_outbox_delivered_rows`.
- Do not add a generic retention strategy/base class.
- Do not import Flow infrastructure from audit retention.
- Do not delete `pending` or `dead_lettered` outbox rows in this slice.
- Record dead-letter retention as a future replay/ack contract, not a silent cleanup.

### Tests Required

- Old delivered outbox row without an `audit_logs` twin is deleted.
- Delivered outbox row with an `audit_logs` twin stays.
- Old pending row without an audit twin stays.
- Old dead-lettered row without an audit twin stays.
- Cleanup is idempotent.
- Batching uses `RETENTION_BATCH_SIZE`; patch the module constant in a test and prove more than one batch is processed.
- Data retention worker count and total include `flow_audit_outbox_delivered_rows`.

### Docs Required

- `docs/runbooks/flows.md` lists `audit_outbox.pending_count`, `delivery_backlog_count`, `dead_lettered_count`, and oldest-age fields.
- `docs/runbooks/flows.md` lists `AUDIT_OUTBOX_DELIVERY_BACKLOG` and `AUDIT_OUTBOX_DEAD_LETTERS`.
- `docs/runbooks/flows.md` states delivered outbox rows are removed only after the audit log twin is removed by audit retention.
- `docs/runbooks/flows.md` states unresolved dead letters stay visible until a replay/ack contract exists.
- `docs/FLOWS_AND_AI_BUILDER_ARCHITECTURE.md` removes all current-architecture `flow_step_results.tool_calls_metadata` references and bumps `Last reviewed`.
- Batch 10 plan, journal, reconciliation, and retrospective capture the accepted Claude findings.

### Validation Commands

```bash
cd backend && uv run pytest \
  tests/unittests/data_retention/test_data_retention_worker.py \
  tests/integration/test_flow_runtime_retention_cleanup.py \
  tests/unittests/flows/test_flow_audit_outbox_delivery.py \
  tests/unittests/flows/test_flow_runtime_health.py \
  -q
```

```bash
cd backend && uv run pyright \
  src/intric/data_retention/infrastructure/data_retention_service.py \
  src/intric/data_retention/infrastructure/data_retention_worker.py \
  tests/integration/test_flow_runtime_retention_cleanup.py \
  tests/unittests/data_retention/test_data_retention_worker.py
```

```bash
cd backend && uv run ruff check \
  src/intric/data_retention/infrastructure/data_retention_service.py \
  src/intric/data_retention/infrastructure/data_retention_worker.py \
  tests/integration/test_flow_runtime_retention_cleanup.py \
  tests/unittests/data_retention/test_data_retention_worker.py
```

```bash
cd backend && uv run ruff format --check \
  src/intric/data_retention/infrastructure/data_retention_service.py \
  src/intric/data_retention/infrastructure/data_retention_worker.py \
  tests/integration/test_flow_runtime_retention_cleanup.py \
  tests/unittests/data_retention/test_data_retention_worker.py
```

```bash
cd backend && uv run lint-imports --no-cache
git diff --check -- \
  backend/src/intric/data_retention/infrastructure/data_retention_service.py \
  backend/src/intric/data_retention/infrastructure/data_retention_worker.py \
  backend/tests/integration/test_flow_runtime_retention_cleanup.py \
  backend/tests/unittests/data_retention/test_data_retention_worker.py \
  docs/runbooks/flows.md \
  docs/FLOWS_AND_AI_BUILDER_ARCHITECTURE.md \
  docs/refactor/execution/batch-10-operability-cleanup-docs
./scripts/gate-local/anti_slippage.sh --worktree
```

## Remaining Batch 10 Slices

| Slice | Scope | Gate |
|---|---|---|
| 10.6 | Branding/namespace ADR/backlog closure | No package rename; update docs/backlog only unless separately approved. |

## Batch 10 Follow-Ups

| Item | Owner | Reason |
|---|---|---|
| Flow audit outbox delivered-row partial index | Flow data model | Measure the anti-join cleanup with a representative delivered-row volume before adding an index such as `created_at WHERE delivery_status='delivered'` or `id WHERE delivery_status='delivered'`. |
| Flow audit outbox dead-letter replay/ack contract | Flow operability | Dead-letter rows are unresolved audit incidents. They need explicit replay/ack semantics before any retention cleanup can delete them. |

## Stop Conditions For This Batch

Stop before source changes if the revised lifecycle-event contract still looks like a shallow module after reconciliation. Stop before implementation if the event contract requires a migration, metrics backend selection, or broad telemetry platform decision.

Stop during implementation if:

- any source/test diff touches unrelated frontend files, package naming, migrations, Celery queue semantics, or data model
- terminalization fail-closed behavior changes
- validation fails for a product regression outside the planned slice
- Claude returns accepted/partial findings after two fix rounds
