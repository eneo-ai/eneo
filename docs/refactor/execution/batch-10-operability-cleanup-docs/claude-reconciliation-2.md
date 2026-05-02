# Claude Reconciliation 2 — Flow Runtime Health

## TL;DR

1. Claude rejected the first Slice 10.2 plan because the health status rules and threshold ownership would create noisy alerts and drift.
2. The accepted design keeps `/api/healthz/flows` on the existing global health surface and moves Flow-specific logic into `flows/runtime/flow_runtime_health.py`.
3. Stale running rows are `DEGRADED` while they are still inside the reconciler grace window; `UNHEALTHY` requires reconciler lag.
4. Terminal-run open-work checks are bounded to a recent 24-hour window.
5. DB query failures live in `probe`, while health flags are closed enum values for operator conditions only.

## Claude Artifact

`.codex/artifacts/claude-peer-loop-batch-10-flow-runtime-health-plan-20260502T202644Z.md`

Verdict: `changes_required`  
Green light: `no`  
Minimum score: `6`

## Accepted Findings

| Finding | Decision | Source impact |
|---|---|---|
| Stale running count alone would mark the system unhealthy during normal beat recovery. | Use an age-based split: `STALE_RUNNING_RUNS` is degraded; `STALE_RUNNING_RECONCILER_LAG` is unhealthy. | `flow_runtime_health.py` classification. |
| Terminal open-attempt query needs a recency bound. | Limit terminal open-attempt and active-step-result integrity checks to 24 hours. | `flow_runtime_health.py` SQL snapshot. |
| Stale-run thresholds were duplicated. | Add `flow_run_recovery_policy.py` and reuse it from `FlowRunService`, Flow Celery beat/task code, and health. | `flow_run_service.py`, `celery_app.py`, `tasks.py`, `flow_runtime_health.py`. |
| SQL and classification boundaries were not pinned. | Expose separate `load_flow_runtime_health_snapshot(...)` and `classify_flow_runtime_health(...)` functions. | Unit tests can cover classification; integration tests can cover DB shape. |
| Open string flags invite drift. | Use `FlowRuntimeHealthFlag` enum values. | Response model and tests. |
| DB query status was duplicated across flags and probe fields. | Keep DB query state under `probe`; reserve flags for runtime conditions. | Response model. |
| Placeholder queue/beat fields would be hedge payload. | Use `probe.scope = "db_only"` and defer broker/beat liveness to a later slice. | Response model and runbook. |
| Two doc locations would drift. | Put operational detail in `docs/runbooks/flows.md`; link from `docs/TROUBLESHOOTING.md`. | Docs only. |

## Rejected Or Deferred

| Suggestion | Decision | Reason |
|---|---|---|
| Run `EXPLAIN ANALYZE` for the terminal open-attempt query before merge. | Deferred unless local validation shows query/runtime issues. | The current local environment does not provide a representative populated production dataset; the query is bounded to 24 hours and covered by integration tests. |
| Add Celery broker/beat liveness now. | Deferred to a later operability slice. | This slice is intentionally no-migration and DB-observable only. Beat heartbeat persistence requires a runtime contract. |
| Remove `status_reason`. | Kept as one canonical sentence per status. | Existing health endpoints expose a human-readable reason; the new response constrains it rather than concatenating arbitrary strings. |
| Put logic under `flows/application`. | Adjusted to `flows/runtime`. | The probe is operational runtime diagnostics and imports SQLAlchemy tables; keeping it out of application services avoids making the application layer own adapter-specific health queries. |

## Verification Questions

| Question | Answer |
|---|---|
| Does the probe expose tenant IDs, flow IDs, run IDs, trace IDs, or audit IDs? | No. The response is aggregate-only. |
| Does the route create a parallel Flow API diagnostics surface? | No. It is registered next to `/api/healthz` and `/api/healthz/crawler`, not under `/api/v1/flows`. |
| Does the probe rely on Celery broker-specific APIs? | No. `probe.scope` is `db_only`; broker/beat checks are deferred. |
| Are health flags closed? | Yes. `FlowRuntimeHealthFlag` is an enum. |

## Verification

Artifact: `.codex/artifacts/claude-peer-loop-batch-10-flow-runtime-health-implementation-20260502T204202Z.md`

Verdict: `green`  
Green light: `yes`  
Minimum score: `8`

Accepted post-green cleanup:

| Finding | Change |
|---|---|
| Active status counts should not group all historical terminal runs. | `_load_run_status_counts` now filters to `queued`, `running`, and `awaiting_review`. |
| Probe failure enum values were lower-case while health status/flags were upper-case. | `FlowRuntimeProbeFailure` values are now `TIMEOUT` and `ERROR`. |
| Success and failure paths used different response timestamps. | The route captures one timestamp and passes it through all outcomes. |
| Recovery policy constants had implicit beat coupling. | Added a module docstring explaining the coupling. |

## Confidence

High after validation and green verification. The accepted findings directly shaped the implementation, and the remaining risks are non-blocking operability follow-ups.
