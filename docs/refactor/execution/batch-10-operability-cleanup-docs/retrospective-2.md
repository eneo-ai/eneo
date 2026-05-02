# Retrospective 2 — Flow Runtime Health Probe

## TL;DR

1. Slice 10.2 added `GET /api/healthz/flows` on the existing global health surface.
2. The probe is DB-only and aggregate-only; it exposes no tenant, flow, run, trace, prompt, payload, evidence, or audit identifiers.
3. Stale-run timing now has one owner in `flow_run_recovery_policy.py`.
4. Health flags are closed enum values and distinguish recoverable stale runs from reconciler lag.
5. Claude gave green light after verification, and local validation passed.

## Outcome

Implemented a Flow runtime diagnostics contract with:

- shared stale-run recovery policy
- SQL snapshot loading separated from pure health classification
- `/api/healthz/flows` route with a 2-second DB timeout guard
- unit tests for classification
- integration tests for the DB snapshot and actual endpoint response
- unauthenticated route contract coverage
- `docs/runbooks/flows.md` linked from `docs/TROUBLESHOOTING.md`

## What Stayed Clean

| Area | Result |
|---|---|
| Health surface | Reused `/api/healthz/*`; did not add a parallel `/api/v1/flows` diagnostics route. |
| Runtime scope | DB-observable signals only; broker/beat liveness remains a later contract. |
| Data exposure | Aggregate counts only; no principal, tenant, flow, run, trace, prompt, payload, or evidence fields. |
| Status flags | Closed enum values, no value-encoded dynamic strings. |
| Threshold ownership | `FlowRunService`, Flow Celery beat/task code, and health probe share `flow_run_recovery_policy.py`. |
| Runbook ownership | Operational detail lives in `docs/runbooks/flows.md`; troubleshooting docs link to it. |

## Validation

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
| `docker exec eneo-41ae93-eneo-1 true` | Blocked before host execution by the active Codex process policy. |

## Claude Loop

| Iteration | Artifact | Verdict |
|---|---|---|
| Plan review | `.codex/artifacts/claude-peer-loop-batch-10-flow-runtime-health-plan-20260502T202644Z.md` | `changes_required`, `GREEN_LIGHT: no` |
| Implementation verification | `.codex/artifacts/claude-peer-loop-batch-10-flow-runtime-health-implementation-20260502T204202Z.md` | `green`, `GREEN_LIGHT: yes` |

Accepted plan-review changes:

- stale running is unhealthy only after the reconciler grace window expires
- terminal open-work checks are bounded to 24 hours
- stale-run timing has a canonical policy module
- status flags are closed enum values
- DB query state lives in `probe`, not status flags
- broker/beat placeholder fields were omitted

Accepted post-green cleanup:

- active status counts filter to queued/running/awaiting-review rows
- probe failure enum values use the health response casing convention
- the route captures one timestamp for success and failure paths
- recovery policy documents its Celery beat coupling

## Carry Forward

| Item | Owner | Next action |
|---|---|---|
| Celery broker and beat liveness | Flow runtime operability | Add only when beat heartbeat persistence or broker inspection contract is approved. |
| Audit outbox delivery/retry/dead-letter | `flow_run_audit_outbox` delivery model | Slice 10.3 after data-model approval. |
| Metrics backend/dashboard counters | PRD-009 observability | Add after platform metrics owner confirms backend and label conventions. |
| OpenAPI field descriptions for health response | API maintainer experience | Add if `/api/healthz/flows` becomes a generated-client surface rather than operator-only diagnostics. |
| Full historical terminal open-work audit | Runtime/data repair | Keep health probe bounded; use a dedicated repair/audit command for full-history inspection if needed. |

## Confidence

High. The DB snapshot is covered by integration tests, classification is covered by unit tests, the endpoint is called through the test client, and Claude green-lit the implementation after the accepted cleanup.
