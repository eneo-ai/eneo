# T044 Judge: Next Safe Task After Durable Webhook Outbox

## Decision

Choose `T045`: `refactor(flows-runtime): centralize outbox delivery status vocabulary`.

The first safe task after `T043` should not mix timing tests, audit best-effort behavior, lifecycle-source changes, and status typing. Claude's T044 plan gate found one valid blocker: adding a webhook-specific `FlowRunLifecycleSource` is not safe without an Alembic constraint migration because audit outbox sources are DB-constrained. Therefore T044 narrows the next Worker to one no-migration consolidation slice: centralize the shared `pending` / `delivered` / `dead_lettered` outbox delivery status vocabulary used by both Flow audit outbox and Flow webhook outbox paths.

## Current Evidence

| Topic | Source evidence | Judge assessment |
|---|---|---|
| Existing DB status values | `backend/src/intric/database/tables/flow_tables.py:95-104` defines duplicate audit and webhook delivery-status tuples with the same three strings. | Canonical owner should be the database table vocabulary because these values back DB check constraints. |
| Audit outbox status literals | `backend/src/intric/flows/infrastructure/flow_run_audit_outbox_repo.py:152`, `:182`, `:184`, `:203`, and `:207` repeat raw status strings. | Duplicated status policy in a persistence owner. |
| Webhook outbox status literals | `backend/src/intric/flows/infrastructure/flow_run_webhook_delivery_repo.py:88`, `:149`, `:151`, `:175`, `:180`, and `:182` repeat raw status strings. | Duplicated status policy in the new webhook persistence owner. |
| Runtime health status literals | `backend/src/intric/flows/runtime/flow_runtime_health.py:534`, `:543`, and `:559` query raw audit outbox status strings. | Health checks should use the same vocabulary as persistence checks. |
| Stale-running webhook exclusion | `backend/src/intric/flows/infrastructure/flow_run_repo.py:1657` checks pending webhook deliveries with a raw string. | This is part of the webhook outbox status vocabulary and belongs in T045. |
| Flow audit outbox retention cleanup | `backend/src/intric/data_retention/infrastructure/data_retention_service.py:186` checks delivered audit outbox rows with a raw string. | This is a directly coupled Flow audit outbox status read and belongs in T045. |
| Lifecycle-source migration blocker | `backend/src/intric/database/tables/flow_tables.py:70` derives `FLOW_RUN_LIFECYCLE_SOURCE_VALUES` from `FlowRunLifecycleSource`; `backend/src/intric/database/tables/flow_tables.py:1554-1557` uses it for `ck_flow_run_audit_outbox_source`; `backend/alembic/versions/20260514_review_expiry.py:139-142` creates the existing DB check. | Adding a new lifecycle source requires a migration and is not part of T045. |
| Audit best-effort behavior risk | `backend/src/intric/flows/runtime/flow_webhook_delivery.py:153-166` force-dead-letters all `ValueError`s raised while preparing delivery; `_prepare_delivery_payload` raises `ValueError` for both invariant failures and audit actor reconstruction failures. | Best-effort audit actor lookup must be its own Worker with a typed exception/logging contract, not folded into status typing. |

## Candidate Classification

| Candidate | Classification | Reason |
|---|---|---|
| Centralize audit/webhook outbox delivery statuses | `safe_now` | No behavior or migration needed. Reduces duplicate string vocabulary in Flow persistence and health paths. |
| Name webhook wrapper timeout and add deterministic deadline-guard tests | `follow_up` | Safe, but separate from status typing. Should be a small later Worker using `flow_webhook_delivery_policy.py` as owner. |
| Make webhook audit actor lookup best-effort | `needs_preflight` | Requires typed exception boundary and explicit warning/observability contract because current `ValueError` funnel also represents hard runtime invariants. |
| Add webhook-specific lifecycle source | `needs_preflight` | Requires Alembic migration for the existing audit outbox source check constraint. Not a no-migration hardening task. |
| Remove `cast(Any)` for executor template asset DI | `follow_up` | Valuable typed cleanup, but unrelated to outbox status vocabulary. |
| Deployment smoke/check instructions for webhook beat task | `follow_up` | Useful operational doc, not the next implementation blocker. |
| Runtime input retention | `blocked_on_decision` | Product/data decision-gated. |
| Service-key identity/review/rerun matrix | `blocked_on_decision` | Product/API decision-gated. |
| Schema migration or runtime file lifecycle changes | `blocked_on_decision` or `needs_preflight` | Requires explicit data/schema preflight and task approval. |

## Approved T045 Worker

Objective: replace duplicated Flow audit/webhook outbox delivery-status string literals with one `FlowOutboxDeliveryStatus(str, Enum)` vocabulary at the table-constraint owner, without changing persisted values or behavior.

Allowed files:

- `docs/goals/flows-clean-architecture-2026-05-25/state.yaml`
- `docs/goals/flows-clean-architecture-2026-05-25/notes/t045-outbox-delivery-status.md`
- `backend/src/intric/database/tables/flow_tables.py`
- `backend/src/intric/data_retention/infrastructure/data_retention_service.py`
- `backend/src/intric/flows/infrastructure/flow_run_audit_outbox_repo.py`
- `backend/src/intric/flows/infrastructure/flow_run_repo.py`
- `backend/src/intric/flows/infrastructure/flow_run_webhook_delivery_repo.py`
- `backend/src/intric/flows/runtime/flow_runtime_health.py`
- `backend/tests/integration/flows/test_flow_audit_outbox_delivery.py`
- `backend/tests/integration/flows/test_flow_webhook_outbox_delivery.py`
- `backend/tests/integration/flows/test_flow_runtime_health.py`
- `backend/tests/integration/test_flow_runtime_retention_cleanup.py`
- `backend/tests/unittests/flows/test_flow_runtime_health.py`
- `backend/tests/unittests/flows/test_flow_architecture_guards.py`

Non-goals:

- No Alembic migration, schema-shape change, new table, new DB constraint, or lifecycle-source change.
- No router, API schema, OpenAPI, frontend, Flow AI Builder, retention, service-key identity, or runtime file lifecycle edits.
- No audit best-effort behavior change.
- No webhook worker timing/clock/deadline changes.
- No new shared helper, manager, processor, service locator, event bus, outbox base class, or generic retry abstraction.

Acceptance criteria:

- Define `class FlowOutboxDeliveryStatus(str, Enum)` next to the existing DB check-constraint value tuples in `flow_tables.py`.
- Derive both `FLOW_RUN_AUDIT_OUTBOX_DELIVERY_STATUS_VALUES` and `FLOW_RUN_WEBHOOK_DELIVERY_STATUS_VALUES` from the typed vocabulary so the DB constraint owner remains the single source of truth. Keep both tuple names because the table constraints are named per outbox table.
- Replace raw delivery-status literals in both outbox repositories, `FlowRunRepository` stale-running webhook exclusion, Flow runtime health queries, Flow audit outbox retention cleanup, and listed tests with `FlowOutboxDeliveryStatus.<STATUS>.value`.
- Keep SQLAlchemy column storage as strings; do not change persisted values or migration state.
- Prefer `server_default=FlowOutboxDeliveryStatus.PENDING.value` for the audit and webhook outbox `delivery_status` columns if SQLAlchemy accepts it; preserve raw strings only inside SQL text where Python enum attributes cannot be used.
- Preserve unavoidable DDL literal strings in `CheckConstraint(...)` and `postgresql_where=sa.text(...)` in `flow_tables.py`; do not try to interpolate Python enum members into SQL text.
- Add or update tests/guards that fail if audit and webhook outbox status tuples drift apart, if enum values stop matching the DB constraint vocabulary, if enum values drift from the hand-coded SQL text in `CheckConstraint(...)` / `postgresql_where=sa.text(...)`, or if raw outbox status strings return in repository/health/retention paths.
- Architecture guard must scan the touched Flow roots plus `src/intric/data_retention/infrastructure/data_retention_service.py`, and allow raw status literals only in `flow_tables.py` DDL constraint/index SQL text and unrelated Celery result payload keys.

Required verification:

- Watchdog before starting implementation and before committing.
- Claude plan gate before source edits; Claude commit gate after implementation with `--timeout-seconds 1200`, `--require-green`, and `--required-min-score 8`.
- Antigravity only if Claude and Codex disagree on a runtime/data/ownership blocker.
- `cd backend && uv run pytest tests/integration/flows/test_flow_audit_outbox_delivery.py tests/integration/flows/test_flow_webhook_outbox_delivery.py tests/integration/flows/test_flow_runtime_health.py tests/integration/test_flow_runtime_retention_cleanup.py tests/unittests/flows/test_flow_runtime_health.py tests/unittests/flows/test_flow_architecture_guards.py -q`
- `cd backend && uv run ruff check src/intric/database/tables/flow_tables.py src/intric/data_retention/infrastructure/data_retention_service.py src/intric/flows/infrastructure/flow_run_audit_outbox_repo.py src/intric/flows/infrastructure/flow_run_repo.py src/intric/flows/infrastructure/flow_run_webhook_delivery_repo.py src/intric/flows/runtime/flow_runtime_health.py tests/integration/flows/test_flow_audit_outbox_delivery.py tests/integration/flows/test_flow_webhook_outbox_delivery.py tests/integration/flows/test_flow_runtime_health.py tests/integration/test_flow_runtime_retention_cleanup.py tests/unittests/flows/test_flow_runtime_health.py tests/unittests/flows/test_flow_architecture_guards.py`
- `cd backend && uv run pyright src/intric/database/tables/flow_tables.py src/intric/data_retention/infrastructure/data_retention_service.py src/intric/flows/infrastructure/flow_run_audit_outbox_repo.py src/intric/flows/infrastructure/flow_run_repo.py src/intric/flows/infrastructure/flow_run_webhook_delivery_repo.py src/intric/flows/runtime/flow_runtime_health.py tests/integration/flows/test_flow_audit_outbox_delivery.py tests/integration/flows/test_flow_webhook_outbox_delivery.py tests/integration/flows/test_flow_runtime_health.py tests/integration/test_flow_runtime_retention_cleanup.py tests/unittests/flows/test_flow_runtime_health.py tests/unittests/flows/test_flow_architecture_guards.py`
- `git diff --check`
- staged-scope check before commit:
  - `git diff --cached --name-only --diff-filter=ACMRTUXB`
  - every staged path must match the T045 `allowed_files`;
  - `git diff --cached --name-only --diff-filter=A` must not include unrelated untracked files such as `.devcontainer/devcontainer-lock.json`, `PRODUCT.md`, `FLOWS_*`, `flows-clean-architecture-2026-05-25/`, or `utvecklingssamtal.mp3`;
  - unstaged unrelated dirty files are preserved and excluded from the commit.

Consolidation effect:

- Reused existing owner: `flow_tables.py` as the DB check-constraint vocabulary owner, plus the existing audit/webhook outbox repositories, stale-running query, runtime health query, and Flow audit retention cleanup.
- Logic moved from: duplicated raw delivery-status strings in audit outbox repo, webhook outbox repo, stale-running query, runtime health queries, retention cleanup, and tests into one typed vocabulary.
- Logic deleted: duplicate literal status values in persistence/health paths.
- Duplicate path removed: audit and webhook outbox status vocabularies stop drifting as independent raw tuples.
- New code added: one narrow `FlowOutboxDeliveryStatus(str, Enum)` at the persistence constraint owner; no new service/helper abstraction.
- Why existing owners were insufficient: the current owner stores two identical tuples and callers still repeat raw strings, so the concept has no typed Python access point.
- Guard/test preventing duplicate logic from returning: status vocabulary guard plus repository/health tests using the typed values.
- Net Flow logic surface area: reduced.

## Deferred Follow-Ups

| Follow-up | Required gate before Worker |
|---|---|
| Name webhook wrapper timeout and add deterministic deadline-guard tests | Small Judge/Worker after T045; use `flow_webhook_delivery_policy.py` as owner and avoid real-time sleeps. |
| Make webhook audit actor lookup best-effort | Judge must approve typed exception boundary, structured warning fields, and observability stance. |
| Add webhook-specific lifecycle source | Alembic/Postgres preflight and migration approval required. |
| Remove `cast(Any)` in Flow executor task DI | Typed-boundary cleanup task; do not drive-by in T045. |

## Peer Review

- Claude T044 plan gate artifact: `.codex/artifacts/claude-peer-loop-t044-choose-next-safe-webhook-hardening-task-20260526T114554Z.md`
- Valid concerns addressed in this revision:
  - Dropped lifecycle-source enum change from no-migration T045.
  - Split audit best-effort behavior out of T045.
  - Chose the DB check-constraint vocabulary owner for status typing.
  - Added worktree/staged-scope hygiene requirements.
- Disagreement: none. The migration and audit-boundary blockers are valid.
