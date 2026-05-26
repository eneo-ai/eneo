# T045 Outbox Delivery Status Worker

## Objective

Centralize the shared audit/webhook outbox delivery-status vocabulary without a migration, storage-shape change, API/router change, lifecycle-source change, audit best-effort change, webhook timing change, or service-key/retention product decision.

## Implementation

- Added `FlowOutboxDeliveryStatus(str, Enum)` in `backend/src/intric/database/tables/flow_tables.py`, next to the DB check-constraint status value owner.
- Derived both `FLOW_RUN_AUDIT_OUTBOX_DELIVERY_STATUS_VALUES` and `FLOW_RUN_WEBHOOK_DELIVERY_STATUS_VALUES` from that enum.
- Kept raw status literals only in the existing SQL text check/index clauses in `flow_tables.py`.
- Changed audit outbox, webhook outbox, stale-running, runtime-health, and Flow audit-retention status comparisons/writes to use `FlowOutboxDeliveryStatus.*.value`.
- Updated outbox delivery tests to use the same vocabulary.
- Added architecture guards that:
  - assert the enum and both table value tuples stay in lockstep;
  - assert SQL text expressions that actually reference `delivery_status` match the enum;
  - derive source scan targets from AST references to `FlowOutboxDeliveryStatus`, `FlowRunAuditOutbox`, or `FlowRunWebhookDeliveries`, then reject raw `"pending"`, `"delivered"`, or `"dead_lettered"` literals in those files.
- Added the local `_sqlalchemy_affected_row_count(result: object)` boundary in `data_retention_service.py` because strict pyright otherwise exposed pre-existing SQLAlchemy `rowcount` unknown-type debt while T045 touched that file.
- Kept table-specific value tuple names with a short reason comment because each SQL CHECK constraint belongs to one table while the enum owns the shared vocabulary.

## Consolidation Effect

- Reused existing owner: `flow_tables.py` as the DB check-constraint vocabulary owner, plus existing outbox repositories, stale-running query, runtime health query, and Flow audit retention cleanup.
- Logic moved from: raw delivery-status literals in outbox repositories, stale-running reconciliation, runtime health, retention cleanup, and tests.
- Logic deleted: duplicated hand-written raw status literals in bounded Flow source paths.
- Duplicate path removed: audit and webhook outbox delivery statuses no longer have independent Python tuple definitions or caller literals.
- New code added: `FlowOutboxDeliveryStatus(str, Enum)`, architecture guards, and a local SQLAlchemy rowcount boundary needed for strict pyright on the touched retention file.
- Why existing owners were insufficient: the table file already owned the DB status value tuples, but it did not expose a typed Python vocabulary, so callers repeated raw strings.
- Guard/test preventing duplicate logic from returning: `test_flow_outbox_delivery_status_vocabulary_is_canonical`, `test_flow_outbox_delivery_status_sql_text_matches_vocabulary`, and `test_flow_outbox_delivery_status_literals_use_canonical_vocabulary`.
- Net Flow logic surface area: reduced.
- If increased, why the increase is necessary: N/A.

## Naming Gate

- `FlowOutboxDeliveryStatus` is domain-specific: it names the Flow outbox delivery lifecycle vocabulary used by both audit and webhook outboxes.
- It would appear clearly in `docs/flows/architecture.md` and the future "where to change X" table under webhook/audit outbox delivery status vocabulary.
- `_sqlalchemy_affected_row_count` is local to the data retention infrastructure file and names the exact SQLAlchemy boundary it adapts. It is not a generic Flow helper or shared utility.

## Specialist Review Notes

- Complexity guidance: no algorithmic rewrite was introduced; status lookups remain constant-value comparisons, and the guard scans a small bounded file list in tests only.
- SQLAlchemy/Postgres guidance: no migration, new constraint, index, or query-shape change was introduced. Existing partial-index SQL text remains unchanged and is now checked against the canonical enum.
- Maintainability rule: this change reduces places to debug delivery-status vocabulary drift without creating a generic outbox base class, manager, processor, or event abstraction.

## Verification

- `cd backend && uv run pytest tests/integration/flows/test_flow_audit_outbox_delivery.py tests/integration/flows/test_flow_webhook_outbox_delivery.py tests/integration/flows/test_flow_runtime_health.py tests/integration/test_flow_runtime_retention_cleanup.py tests/unittests/flows/test_flow_runtime_health.py tests/unittests/flows/test_flow_architecture_guards.py -q`
  - Result: pass, `43 passed, 16 warnings in 46.33s`.
- `cd backend && uv run pyright src/intric/database/tables/flow_tables.py src/intric/data_retention/infrastructure/data_retention_service.py src/intric/flows/infrastructure/flow_run_audit_outbox_repo.py src/intric/flows/infrastructure/flow_run_repo.py src/intric/flows/infrastructure/flow_run_webhook_delivery_repo.py src/intric/flows/runtime/flow_runtime_health.py tests/integration/flows/test_flow_audit_outbox_delivery.py tests/integration/flows/test_flow_webhook_outbox_delivery.py tests/integration/flows/test_flow_runtime_health.py tests/integration/test_flow_runtime_retention_cleanup.py tests/unittests/flows/test_flow_runtime_health.py tests/unittests/flows/test_flow_architecture_guards.py`
  - Result: pass, `0 errors, 0 warnings, 0 informations`.
- `cd backend && uv run ruff check src/intric/database/tables/flow_tables.py src/intric/data_retention/infrastructure/data_retention_service.py src/intric/flows/infrastructure/flow_run_audit_outbox_repo.py src/intric/flows/infrastructure/flow_run_repo.py src/intric/flows/infrastructure/flow_run_webhook_delivery_repo.py src/intric/flows/runtime/flow_runtime_health.py tests/integration/flows/test_flow_audit_outbox_delivery.py tests/integration/flows/test_flow_webhook_outbox_delivery.py tests/integration/flows/test_flow_runtime_health.py tests/integration/test_flow_runtime_retention_cleanup.py tests/unittests/flows/test_flow_runtime_health.py tests/unittests/flows/test_flow_architecture_guards.py`
  - Result: pass, `All checks passed!`.
- `rg -n '"pending"|"delivered"|"dead_lettered"' backend/src/intric/data_retention/infrastructure/data_retention_service.py backend/src/intric/flows/infrastructure/flow_run_audit_outbox_repo.py backend/src/intric/flows/infrastructure/flow_run_repo.py backend/src/intric/flows/infrastructure/flow_run_webhook_delivery_repo.py backend/src/intric/flows/runtime/flow_runtime_health.py`
  - Result: pass, no matches.
- `git diff --check`
  - Result: pass.
- `cd backend && uv run pytest tests/unittests/flows/test_flow_architecture_guards.py::test_flow_outbox_delivery_status_vocabulary_is_canonical tests/unittests/flows/test_flow_outbox_delivery_status_sql_text_matches_vocabulary tests/unittests/flows/test_flow_outbox_delivery_status_literals_use_canonical_vocabulary -q`
  - Result: fail, command typo omitted the file path on the second and third node IDs.
- `cd backend && uv run pytest tests/unittests/flows/test_flow_architecture_guards.py::test_flow_outbox_delivery_status_vocabulary_is_canonical tests/unittests/flows/test_flow_architecture_guards.py::test_flow_outbox_delivery_status_sql_text_matches_vocabulary tests/unittests/flows/test_flow_architecture_guards.py::test_flow_outbox_delivery_status_literals_use_canonical_vocabulary -q`
  - Result: fail once after the guard tightening because non-check constraints do not expose `sqltext`; fixed by skipping constraints without `sqltext`.
- `cd backend && uv run pytest tests/unittests/flows/test_flow_architecture_guards.py::test_flow_outbox_delivery_status_vocabulary_is_canonical tests/unittests/flows/test_flow_architecture_guards.py::test_flow_outbox_delivery_status_sql_text_matches_vocabulary tests/unittests/flows/test_flow_architecture_guards.py::test_flow_outbox_delivery_status_literals_use_canonical_vocabulary -q`
  - Result: pass, `3 passed in 0.60s`.

## Peer Review

- Claude commit gate iteration 1: `.codex/artifacts/claude-peer-loop-t045-outbox-delivery-status-implementation-review-20260526T121924Z.md`
  - Verdict: `changes_required`, `GREEN_LIGHT: no`, `MIN_SCORE: 7`.
  - Valid concerns addressed:
    - SQL-text guard matched too broadly and could fail on unrelated partial indexes or constraints.
    - Source literal guard used a fixed five-file list and could miss future outbox table callers.
    - Two table-specific derived tuples needed either consolidation or an explicit reason for keeping table-specific names.
- Claude commit gate iteration 2: pending.
