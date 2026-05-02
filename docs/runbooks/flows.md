# Flow Runtime Runbook

## Scope

This runbook covers Flow run execution signals exposed by:

```bash
curl http://localhost:8123/api/healthz/flows
```

The endpoint is an unauthenticated operator diagnostic probe. It reports aggregate DB-derived runtime state only. It intentionally does not expose tenant IDs, flow IDs, run IDs, trace IDs, prompts, payloads, evidence, or audit details.

Use `/api/healthz` for coarse backend/worker liveness. Use `/api/healthz/flows` when Flow runs appear stuck, slow, or inconsistent.

## Health Contract

| Field | Meaning |
|---|---|
| `status` | `HEALTHY`, `DEGRADED`, `UNHEALTHY`, or `UNKNOWN`. |
| `probe.scope` | `db_only`; broker and Celery beat liveness are not inferred from Redis in this slice. |
| `probe.db_query_ok` | Whether the API server could read Flow runtime state within the probe timeout. |
| `runs.queued_count` | Current queued Flow runs. |
| `runs.running_count` | Current running Flow runs. |
| `runs.awaiting_review_count` | Runs paused for human review; these are not active worker slots. |
| `runs.stale_queued_count` | Queued runs older than the redispatch threshold. |
| `runs.stale_running_count` | Running runs older than the stale-running reconciliation threshold. |
| `data_integrity.terminal_runs_with_open_attempts_count` | Recently terminal runs that still have open step attempts. |
| `data_integrity.terminal_runs_with_active_step_results_count` | Recently terminal runs that still have pending/running step results. |
| `audit_outbox.pending_count` | Flow audit outbox rows that still need delivery. |
| `audit_outbox.delivery_backlog_count` | Pending outbox rows older than the audit outbox backlog grace threshold. |
| `audit_outbox.dead_lettered_count` | Outbox rows that exhausted delivery or failed deterministic projection. |
| `audit_outbox.oldest_delivery_backlog_age_seconds` | Age of the oldest pending row beyond the backlog grace threshold. |
| `audit_outbox.oldest_dead_lettered_age_seconds` | Age of the oldest dead-lettered row. |

Status flags are closed values:

| Flag | Severity | Meaning |
|---|---|---|
| `STALE_QUEUED_RUNS` | `DEGRADED` | Runs are queued beyond the redispatch threshold. |
| `STALE_RUNNING_RUNS` | `DEGRADED` | Runs are stale but still inside the reconciler grace window. |
| `STALE_RUNNING_RECONCILER_LAG` | `UNHEALTHY` | A stale running run remained stale beyond the reconciler grace window. |
| `TERMINAL_RUNS_WITH_OPEN_ATTEMPTS` | `UNHEALTHY` | Terminalization did not close all open attempts for a recent terminal run. |
| `TERMINAL_RUNS_WITH_ACTIVE_STEP_RESULTS` | `UNHEALTHY` | Terminalization did not close all active step-result projections for a recent terminal run. |
| `AUDIT_OUTBOX_DELIVERY_BACKLOG` | `DEGRADED` | Pending audit outbox rows are older than the delivery backlog grace threshold. |
| `AUDIT_OUTBOX_DEAD_LETTERS` | `UNHEALTHY` | At least one audit outbox row is dead-lettered. |

## Triage

1. Capture the health payload:

```bash
curl -s http://localhost:8123/api/healthz/flows | jq
```

2. Check coarse service health:

```bash
curl -s http://localhost:8123/api/healthz | jq
docker compose ps
docker compose logs --tail=100 backend
docker compose logs --tail=100 worker
```

3. Check Flow Celery worker logs for task receipt, timeout, and reconciliation:

```bash
docker compose logs --tail=200 worker | grep -E "flows\\.execute|flows\\.reconcile_running|flow_executor|flow_task"
```

4. Check whether stale running reconciliation is moving runs to terminal state:

```bash
docker compose logs --tail=200 worker | grep -E "stale_running_reconciler|flow_worker_stalled|flow_run_lifecycle_event"
```

## Recovery

### `UNKNOWN`

Likely cause: the API server could not query Flow runtime tables within the probe timeout.

Actions:

1. Check database connectivity and connection pool saturation.
2. Check backend logs for `DB query timeout in flow runtime health check` or `DB query error in flow runtime health check`.
3. Do not manually update Flow run rows. Restore database availability first.

Escalate to the platform/database owner if the probe remains `UNKNOWN` after backend restart and database connectivity is healthy.

### `STALE_QUEUED_RUNS`

Likely cause: dispatch lag, worker downtime, or a broker issue.

Actions:

1. Confirm the Flow worker process is running.
2. Check worker logs for `flows.execute` receipt.
3. If only one tenant or flow is affected, use the existing authenticated Flow run redispatch path from the application surface when available. Do not update `flow_runs.status` manually.
4. If all tenants are affected, treat it as worker/broker outage and restore worker capacity first.

Escalate if `runs.oldest_stale_queued_age_seconds` keeps increasing while workers are healthy.

### `STALE_RUNNING_RUNS`

Likely cause: a run exceeded the execution timeout and is waiting for the scheduled reconciler.

Actions:

1. Wait one reconciliation interval and re-check `/api/healthz/flows`.
2. Confirm worker logs include `flows.reconcile_running`.
3. Confirm lifecycle events include terminalization outcomes from `stale_running_reconciler`.

Escalate only if this becomes `STALE_RUNNING_RECONCILER_LAG` or the count keeps growing.

### `STALE_RUNNING_RECONCILER_LAG`

Likely cause: Celery beat is not scheduling `flows.reconcile_running`, the worker is not consuming the Flow queue, or reconciliation is failing.

Actions:

1. Restart the Flow worker/beat process if beat logs are absent.
2. Check logs for reconciliation exceptions.
3. Verify terminal audit outbox insert failures are not blocking terminalization.
4. Do not manually set runs to `failed`; terminalization must close step attempts/results and write the audit outbox row in the same lifecycle path.

Escalate to the Flow runtime owner if the same stale running run survives two worker restarts or if terminal audit outbox failures are present.

### Terminal Runs With Open Work

Likely cause: terminalization did not close all active attempts or step-result projections.

Actions:

1. Treat this as a data integrity incident.
2. Check recent lifecycle events for `operation=terminalize_run`.
3. Check terminal audit outbox insert errors and transaction rollback logs.
4. Do not run ad hoc SQL updates. Any repair must preserve run status, step attempts, step results, evidence export behavior, and audit outbox facts together.

Escalate to the Flow runtime owner. A repair script requires a targeted test fixture that reproduces the open-attempt/open-result shape before modifying data.

### Audit Outbox Delivery Backlog

Likely cause: `flows.deliver_audit_outbox` is not scheduled, the Flow worker is not consuming the Flow queue, or audit-log persistence is failing.

Actions:

1. Confirm Celery beat includes `deliver-flow-audit-outbox`.
2. Confirm worker logs include `flows.deliver_audit_outbox`.
3. Check recent `flow_run_audit_outbox.delivery_last_error` values without exposing prompts, payloads, or evidence.
4. Restart the Flow worker/beat process if delivery logs are absent.

Escalate if backlog remains after two delivery intervals or keeps growing while new runs terminalize.

### Audit Outbox Dead Letters

Likely cause: a deterministic audit row projection failure or repeated audit-log persistence failure after bounded retries.

Actions:

1. Treat this as an audit delivery incident.
2. Preserve the dead-lettered row; do not delete it to silence `/api/healthz/flows`.
3. Record the row id, delivery error, action, source, and target status in the incident ticket.
4. Replay or repair only through a reviewed script that keeps `flow_run_audit_outbox.id` equal to the delivered `audit_logs.id`.

Escalate to the Flow runtime owner. Manual SQL updates require a test fixture that reproduces the dead-letter shape before modifying production data.

### Audit Outbox Retention

Delivered outbox row lifetime follows `audit_logs` lifetime. The data retention worker deletes delivered Flow audit outbox rows only after audit retention has removed the matching `audit_logs.id` row.

Pending rows remain until delivery succeeds or dead-letters. Dead-lettered rows remain visible until a reviewed replay or acknowledgement contract exists. A large delivered-outbox table usually means audit logs are still retained for the same period; investigate audit retention volume before adding an outbox-specific cleanup rule.

## Rollback

If a new Flow runtime release causes repeated `UNHEALTHY` results:

1. Stop new run creation if product/support decides the risk is user-visible.
2. Roll back the application release.
3. Keep the database intact; do not roll back migrations unless the release introduced a migration and the rollback plan for that migration has been approved.
4. Re-check `/api/healthz/flows` after rollback.

## Non-Goals

- This endpoint does not prove Celery broker liveness.
- This endpoint does not deliver audit outbox rows.
- This endpoint does not inspect provider latency or AI Builder turn health.
- This runbook does not authorize manual database edits.
