# Batch 10 — Operability, Cleanup, And Docs Journal

## Status

IN PROGRESS

## Starting Point

- Branch: `feature/refactor-flows-flowai`
- HEAD: `02292fe3 flows: add review checkpoint frontend state`
- Previous completed batch: Batch 9 Human Review Pause/Edit/Resume
- Staged files at start: none
- Known unrelated dirty files:
  - `scripts/run_codex_review.sh`
  - `PRODUCT.md`
- Additional untracked local scratch:
  - `docs/refactor/goals.md`
- Batch 10 directory: `docs/refactor/execution/batch-10-operability-cleanup-docs/`
- Docker status: `docker exec eneo-41ae93-eneo-1 true` is blocked by Codex process policy before host execution with `approval required by policy, but AskForApproval is set to Never`; local validation fallback is required.

## Iteration Log

### Iteration 1 — Plan Draft

- Plan: `docs/refactor/execution/batch-10-operability-cleanup-docs/plan.md`
- Chosen first slice: Flow lifecycle operability event contract.
- Rationale: current audit outbox delivery/dead-letter state is absent from the table shape and needs a data-model approval gate; lifecycle events are implementation work that improves operability without adding migrations or a second terminalization owner.
- Validation: not run yet.
- Claude review: `.codex/artifacts/claude-peer-loop-batch-10-flow-lifecycle-operability-plan-20260502T195817Z.md`
- Claude verdict: `changes_required`, `GREEN_LIGHT: no`, `MIN_SCORE: 7`.

### Iteration 1 Reconciliation

Accepted findings:

| Claude finding | Decision |
|---|---|
| `flow_run_operability.py` is too generic. | Rename the proposed owner to `backend/src/intric/flows/application/flow_run_lifecycle_events.py`. |
| Three emit functions and an optional dataclass shape are shallow. | Use one `TypedDict` plus one `emit_flow_run_terminalization_event(...)` function with a typed `outcome`. |
| Module placement at `flows/` root is ambiguous. | Place the event contract under `flows/application/` because the first caller is the application terminalizer. |
| Event/audit boundary was not explicit enough. | The module contract must state lifecycle events are best-effort observability, not audit durability; `flow_run_audit_outbox` remains canonical. |
| `trace_id` source was undeclared. | Use persisted `FlowRun.trace_id`, already present on `FlowRun`. |
| Audit outbox delivery was understated. | `rg "FlowRunAuditOutbox" backend/src` shows only the table and repo inserts; Slice 10.3 is a delivery-model and worker decision, not just a migration. |
| 10.1 does not close metrics. | Plan now states 10.1 only closes the structured event/log half; metrics remain later Batch 10 work. |
| Test mechanism was not pinned. | Use `caplog.records` filtered by `record.event == "flow_run.lifecycle"`; no fake recorder or interface. |
| Bespoke anti-slippage regex was noisy. | Use existing `./scripts/gate-local/anti_slippage.sh --worktree`. |

## Carry-Forward From Prior Batches

| Risk | Source | Batch 10 handling |
|---|---|---|
| Flow audit outbox has durable insert semantics but no consumer, delivery/retry state, or dead-letter state. | `FlowRunAuditOutbox` table has lifecycle/audit columns but no delivery columns; `rg "FlowRunAuditOutbox" backend/src` finds only the table and inserts. | Defer to a delivery-model/data-model-approved slice after lifecycle event contract. |
| `tool_calls_metadata` remains on result rows after attempt provenance became canonical. | Batch 7A carry-forward and current source reads/writes. | Defer to a migration/count-proof cleanup slice. |
| Broad frontend app check has unrelated baseline failures. | Batch 9 reconciliation. | Do not touch frontend in Slice 10.1. |

### Iteration 2 — Slice 10.1 Implementation

Changed files:

- `backend/src/intric/flows/application/flow_run_lifecycle_events.py`
- `backend/src/intric/flows/application/flow_run_terminalization.py`
- `backend/tests/unittests/flows/test_flow_run_lifecycle_events.py`
- `backend/tests/integration/flows/test_flow_terminalization_contract.py`
- `docs/refactor/execution/batch-10-operability-cleanup-docs/plan.md`
- `docs/refactor/execution/batch-10-operability-cleanup-docs/journal.md`
- `docs/refactor/execution/batch-10-operability-cleanup-docs/claude-reconciliation-1.md`

Implementation summary:

- Added one narrow lifecycle event module under `flows/application`.
- Kept `FlowRunTerminalizer` as the canonical owner for terminal state and audit outbox insertion.
- Emitted `transitioned` only after `insert_terminal_audit_outbox` returns an id.
- Emitted `noop_already_terminal` for duplicate terminalization and `noop_lost_race` for failed CAS/no-update outcomes.
- Kept invariant failure and audit-outbox insert failure paths free of misleading success events.
- Used `FlowRun.trace_id` from the persisted run; no request-context plumbing.
- Kept the event contract as structured logging only; durable recovery/audit remains `flow_run_audit_outbox`.

Validation:

| Command | Result |
|---|---|
| `cd backend && uv run ruff check src/intric/flows/application/flow_run_lifecycle_events.py src/intric/flows/application/flow_run_terminalization.py tests/unittests/flows/test_flow_run_lifecycle_events.py tests/integration/flows/test_flow_terminalization_contract.py` | Passed |
| `cd backend && uv run ruff format --check src/intric/flows/application/flow_run_lifecycle_events.py src/intric/flows/application/flow_run_terminalization.py tests/unittests/flows/test_flow_run_lifecycle_events.py tests/integration/flows/test_flow_terminalization_contract.py` | Passed |
| `cd backend && uv run pyright src/intric/flows/application/flow_run_lifecycle_events.py src/intric/flows/application/flow_run_terminalization.py tests/unittests/flows/test_flow_run_lifecycle_events.py tests/integration/flows/test_flow_terminalization_contract.py` | Passed |
| `cd backend && uv run pytest tests/unittests/flows/test_flow_run_lifecycle_events.py tests/integration/flows/test_flow_terminalization_contract.py -q` | Passed: `8 passed, 16 warnings` |
| `cd backend && uv run lint-imports --no-cache` | Passed: `3 kept, 0 broken` |
| `git diff --check -- ...` for touched source/test/doc paths | Passed |
| `./scripts/gate-local/anti_slippage.sh --worktree` | Passed: `anti-slippage: worktree clean` |
| `docker exec eneo-41ae93-eneo-1 true` | Blocked by current Codex process policy before host execution: `approval required by policy, but AskForApproval is set to Never` |

### Iteration 5 — Slice 10.3 Plan Review

- Chosen slice: Flow audit outbox delivery/retry/dead-letter model and worker.
- Claude artifact: `.codex/artifacts/claude-peer-loop-batch-10-flow-audit-outbox-delivery-plan-20260502T205958Z.md`
- Claude verdict: `changes_required`
- Claude green light: `no`
- Claude minimum score: `5`

Accepted findings:

| Claude finding | Decision |
|---|---|
| Copying the outbox `description` into `audit_logs.description` would leak the `action:source` idempotency string into human audit logs. | Keep the outbox description constraint, but synthesize human-readable audit log descriptions during delivery and preserve the outbox string in metadata. |
| Delivery idempotency was under-specified. | Use `flow_run_audit_outbox.id` as the delivered `audit_logs.id`; existing audit rows with the same id are treated as already delivered. |
| A bad row must not roll back unrelated deliveries. | Process each row through a nested transaction and test a mixed valid/invalid batch. |
| Deterministic audit-domain validation errors should not consume transient retry slots. | Dead-letter domain validation failures immediately; reserve bounded retry for unexpected delivery failures. |
| Adding delivery and health methods to `FlowRunRepository` would deepen the wrong owner. | Add a dedicated `FlowRunAuditOutboxRepository` and move outbox insert ownership there instead of adding more methods to `FlowRunRepository`. |
| Delivery bypasses tenant audit feature-flag gating and needs an explicit product rationale. | Document that Flow lifecycle audit is part of the PRD-003 durable runtime state and intentionally bypasses `AuditService._should_log_action`. |
| Retry/backlog policy values were magic numbers. | Add `flow_run_audit_outbox_policy.py` for interval, batch size, max attempts, backoff, and backlog grace. |

Plan revision:

- Added Slice 10.3 to this plan with source evidence, owners, data model, delivery contract, exact audit description examples, metadata keys, health flags, expected files, tests, and validation commands.

Notes:

- The first targeted test run failed because the integration logging setup bypassed pytest root capture for the lifecycle logger. The final tests still assert real `logging.LogRecord` payloads through `caplog.records`; the test helper attaches pytest's capture handler directly to the lifecycle logger for the action window and restores the logger afterward.
- `docker exec` remains unavailable in this Codex process despite normal command usage and no escalation request. Local fallback validation completed.

### Iteration 2 Claude Verification

- Claude artifact: `.codex/artifacts/claude-peer-loop-batch-10-flow-lifecycle-operability-implementation-20260502T201432Z.md`
- Claude verdict: `green`
- Claude green light: `yes`
- Claude minimum score: `8`

Accepted non-blocking cleanup from Claude before commit:

- Tightened `previous_status` from `FlowRunStatus | str` to `FlowRunStatus`.
- Removed the status normalization helper.
- Added a module-docstring rationale for excluding free-form failure text from the lifecycle event.
- Added unit pins for `noop_already_terminal` and `noop_lost_race` payloads.

Verification answers:

| Question | Answer |
|---|---|
| Is `FlowRun.trace_id` non-null at domain and DB levels? | Yes. `FlowRun.trace_id` is required on the domain model and `FlowRuns.trace_id` is `nullable=False` with a default. |
| Does `flow_run_lifecycle_events.py` have only one source importer? | Yes. `rg "flow_run_lifecycle_events\\|emit_flow_run_terminalization_event" backend/src backend/tests` shows the only source importer is `flow_run_terminalization.py`; other references are tests. |
| Is the module earned beyond Slice 10.1? | Yes for the current slice because it owns a stable event schema separate from terminalization logic. Revisit in later Batch 10 slices if new lifecycle events need a different module shape. |
| Is `_capture_flow_lifecycle_logs` duplicated elsewhere? | No. Current references are limited to `test_flow_terminalization_contract.py`. |

### Iteration 3 — Slice 10.2 Plan Review

- Chosen slice: Flow runtime health/readiness probe and runbook.
- Claude artifact: `.codex/artifacts/claude-peer-loop-batch-10-flow-runtime-health-plan-20260502T202644Z.md`
- Claude verdict: `changes_required`
- Claude green light: `no`
- Claude minimum score: `6`

Accepted findings:

| Claude finding | Decision |
|---|---|
| `stale_running_count > 0 => UNHEALTHY` would flap while the reconciler is expected to recover runs. | Classify stale running rows as `DEGRADED` until oldest stale-running age exceeds the reconciler grace window; only then emit `STALE_RUNNING_RECONCILER_LAG` / `UNHEALTHY`. |
| Terminal open-work checks need a recency bound. | Bound terminal-run open-attempt and active-step-result checks to a 24-hour operator-actionable window. |
| Stale queued/running thresholds would become three sources of truth. | Add `flow_run_recovery_policy.py` and make `FlowRunService`, Flow Celery beat/task code, and the health probe share it. |
| The SQL snapshot and pure classification boundaries needed to be explicit. | `flow_runtime_health.py` exposes `load_flow_runtime_health_snapshot(...)` and `classify_flow_runtime_health(...)` separately. |
| `status_flags: list[str]` invites drift. | Use closed `FlowRuntimeHealthFlag` enum values. |
| DB query flags duplicated probe fields. | Keep DB query state under `probe`; do not add `DB_QUERY_OK`/`DB_QUERY_ERROR` status flags. |
| Placeholder broker/beat fields are hedge prose. | The response declares `probe.scope=db_only` and omits placeholder queue/beat liveness fields. |
| Runbook canonical home should be one place. | Add `docs/runbooks/flows.md`; `docs/TROUBLESHOOTING.md` links to it only. |

Implementation summary so far:

- Added `backend/src/intric/flows/application/flow_run_recovery_policy.py`.
- Added `backend/src/intric/flows/runtime/flow_runtime_health.py`.
- Placement note: the first plan named `flows/application/flow_runtime_health.py`, but the implementation uses `flows/runtime/flow_runtime_health.py` because the probe is operational diagnostics over runtime DB state and imports SQLAlchemy tables.
- Registered `GET /api/healthz/flows` under the existing global health surface.
- Added unit classification tests, integration DB snapshot tests, and the unauthenticated route contract test.
- Added the Flow runtime runbook and linked it from troubleshooting docs.

### Iteration 4 — Slice 10.2 Verification

- Claude artifact: `.codex/artifacts/claude-peer-loop-batch-10-flow-runtime-health-implementation-20260502T204202Z.md`
- Claude verdict: `green`
- Claude green light: `yes`
- Claude minimum score: `8`

Accepted post-green cleanup:

| Claude note | Change |
|---|---|
| Count only active run statuses in the status-count query. | `_load_run_status_counts` filters to `queued`, `running`, and `awaiting_review`. |
| Probe failure enum casing should match the health response convention. | `FlowRuntimeProbeFailure` values are uppercase. |
| Route success/failure timestamps should use one captured clock value. | `/api/healthz/flows` passes the route-entry timestamp to both success and failure responses. |
| Recovery policy constants need a short coupling note. | `flow_run_recovery_policy.py` documents the Celery beat coupling. |

Final validation:

| Command | Result |
|---|---|
| `cd backend && uv run ruff check ...` for Slice 10.2 source/tests | Passed |
| `cd backend && uv run ruff format --check ...` for Slice 10.2 source/tests | Passed |
| `cd backend && uv run pyright ...` for Slice 10.2 source/tests | Passed |
| `cd backend && uv run pytest tests/unittests/flows/test_flow_runtime_health.py tests/integration/flows/test_flow_runtime_health.py tests/unit/test_api_key_contract_matrix.py -q` | Passed: `69 passed, 16 warnings` |
| `cd backend && uv run pytest tests/unittests/flows/test_celery_runtime.py tests/unittests/flows/test_flow_run_service.py::test_reconcile_stale_running_runs_marks_stale_runs_failed tests/unittests/flows/test_flow_run_service.py::test_reconcile_stale_running_runs_skips_already_reconciled_runs -q` | Passed: `14 passed, 10 warnings` |
| `cd backend && uv run lint-imports --no-cache` | Passed: `3 kept, 0 broken` |
| `git diff --check -- ...` for touched source/test/doc paths | Passed |
| `./scripts/gate-local/anti_slippage.sh --worktree` | Passed |
| `docker exec eneo-41ae93-eneo-1 true` | Blocked by current Codex process policy before host execution: `approval required by policy, but AskForApproval is set to Never` |

### Iteration 6 — Slice 10.3 Implementation Verification

- Implemented Flow audit outbox delivery with retry, dead-letter state, idempotent audit-log projection, Celery beat wiring, and health/runbook coverage.
- Moved audit outbox persistence out of `FlowRunRepository` into `FlowRunAuditOutboxRepository`.
- Kept `flow_run_audit_outbox.id == audit_logs.id` as the idempotency key; `BasePublic` provides the server-generated `gen_random_uuid()` id.
- Tightened the post-green cleanup by making `FlowRunTerminalizer` require an explicit `FlowRunAuditOutboxRepository` dependency and by expanding delivery mapping/constraint coverage.

Claude artifacts:

| Pass | Artifact | Verdict |
|---|---|---|
| Plan review | `.codex/artifacts/claude-peer-loop-batch-10-flow-audit-outbox-delivery-plan-20260502T205958Z.md` | `changes_required`, `GREEN_LIGHT: no`, minimum score `5` |
| Plan verification | `.codex/artifacts/claude-peer-loop-batch-10-flow-audit-outbox-delivery-plan-verification-20260502T210456Z.md` | `green`, `GREEN_LIGHT: yes`, minimum score `8` |
| Implementation verification | `.codex/artifacts/claude-peer-loop-batch-10-flow-audit-outbox-delivery-implementation-verification-20260502T213041Z.md` | `green`, `GREEN_LIGHT: yes`, minimum score `8` |
| Final verification | `.codex/artifacts/claude-peer-loop-batch-10-flow-audit-outbox-delivery-final-contract-verification-20260502T214219Z.md` | `green`, `GREEN_LIGHT: yes`, minimum score `9` |

Accepted implementation findings:

| Finding | Change |
|---|---|
| Delivered audit rows need human-readable descriptions instead of `action:source`. | `FlowRunAuditOutboxDeliveryService` maps Flow audit actions to human audit descriptions and preserves the outbox string as metadata. |
| Delivery must be idempotent across retries and duplicate starts. | `AuditLogRepository.create_if_absent` writes with `INSERT ... ON CONFLICT (id) DO NOTHING`; the delivered audit log id is the outbox id. |
| One bad outbox row must not block neighboring rows. | Delivery uses per-row nested transactions around projection/write/failure handling. |
| Deterministic domain validation errors should not consume retry slots. | `ValueError` during projection/audit-domain construction dead-letters immediately. |
| Retry policy values should not be magic numbers. | `flow_run_audit_outbox_policy.py` owns interval, batch size, attempts, backoff, and backlog grace constants. |
| Optional terminalizer dependency fallback was dead production code. | `FlowRunTerminalizer` now requires explicit `audit_outbox_repo`; services, executor, container, and tests pass it directly. |
| Projection and constraints needed tighter tests. | Unit tests cover all Flow audit description mappings and failure-message fallback order; integration tests cover timestamp, invalid status, and negative-attempt constraints. |

Validation:

| Command | Result |
|---|---|
| `cd backend && uv run ruff check ...` for Slice 10.3 touched source/tests | Passed |
| `cd backend && uv run ruff format ...` for Slice 10.3 touched source/tests | Passed |
| `cd backend && uv run pytest tests/unittests/flows/test_flow_audit_outbox_delivery.py tests/unittests/flows/test_flow_review_checkpoint_data_model.py tests/unittests/flows/test_celery_runtime.py tests/unittests/flows/test_flow_runtime_health.py -q` | Passed: `40 passed, 10 warnings` |
| `cd backend && uv run pytest tests/integration/flows/test_flow_audit_outbox_delivery.py tests/integration/flows/test_flow_runtime_health.py tests/integration/flows/test_flow_terminalization_contract.py tests/integration/flows/test_flow_run_review_checkpoint_repository.py tests/integration/flows/test_flow_run_repository.py -q` | Passed: `50 passed, 16 warnings` |
| `cd backend && uv run pyright ...` for Slice 10.3 touched source/tests | Passed: `0 errors, 0 warnings, 0 informations` |
| `cd backend && uv run lint-imports --no-cache` | Passed: `3 kept, 0 broken` |
| `git diff --check -- ...` for Slice 10.3 touched paths | Passed |
| `./scripts/gate-local/anti_slippage.sh --worktree` | Passed: `anti-slippage: worktree clean` |

Verification answers:

| Question | Answer |
|---|---|
| Are outbox ids server-generated? | Yes. `FlowRunAuditOutbox` inherits `BasePublic`, whose `IdMixin` uses `server_default=func.gen_random_uuid()`. |
| Is `enable_autobegin_for_flow_task_session(session)` before explicit `session.begin()` acceptable in the delivery task? | Yes. Once `session.begin()` is active, autobegin is inert; the helper keeps Flow task discipline consistent while the explicit transaction owns the `FOR UPDATE SKIP LOCKED` lock lifetime. |
| Were integration tests run against real PostgreSQL? | Yes. The integration fixtures used testcontainers with `pgvector/pgvector:pg16`; the new partial indexes and check constraints were exercised against PostgreSQL. |
