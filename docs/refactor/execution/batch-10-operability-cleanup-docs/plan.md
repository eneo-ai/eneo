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
| `tool_calls_metadata` cleanup | `backend/src/intric/data_retention/infrastructure/data_retention_service.py:471`, `:494`, `:525`, `:796`; `backend/src/intric/flows/runtime/executor.py:197-198`; `backend/src/intric/flows/flow_run_evidence_bundle.py:26`. | Still a duplicated result-row field after provenance became canonical. | Attempt provenance should remain canonical. | Needs migration/delete sweep; defer until explicit data-model approval or combine with an approved cleanup slice. |

## Dead Code / Compatibility Inventory For This Slice

| Concept | Current locations | Shipped/persisted data need? | Keep/delete/rewrite | Canonical owner | Deletion condition |
|---|---|---|---|---|---|
| `tool_calls_metadata` result-row duplicate | `FlowStepResults`, executor, retention service, evidence bundle guard | Possible persisted rows until migration proof/backfill; Batch 7A kept it as carry-forward. | Keep in Slice 10.1. | `FlowAttemptProvenance` for evidence; DB result row until migration. | Human-approved data-model cleanup with migration/count proof. |
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

## Deferred Batch 10 Slices

| Slice | Scope | Gate |
|---|---|---|
| 10.3 | Audit outbox delivery/retry/dead-letter model and worker | Requires explicit delivery-model and data-model approval because `FlowRunAuditOutbox` has no consumer or delivery columns today. |
| 10.4 | `tool_calls_metadata` cleanup | Requires migration/count proof and generated schema impact review. |
| 10.5 | Evidence/export/runbook/docs cleanup | After event and health signals exist. |
| 10.6 | Branding/namespace ADR/backlog closure | No package rename; update docs/backlog only unless separately approved. |

## Stop Conditions For This Batch

Stop before source changes if the revised lifecycle-event contract still looks like a shallow module after reconciliation. Stop before implementation if the event contract requires a migration, metrics backend selection, or broad telemetry platform decision.

Stop during implementation if:

- any source/test diff touches unrelated frontend files, package naming, migrations, Celery queue semantics, or data model
- terminalization fail-closed behavior changes
- validation fails for a product regression outside the planned slice
- Claude returns accepted/partial findings after two fix rounds
