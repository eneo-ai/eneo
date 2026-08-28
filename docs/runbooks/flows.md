# Flows operations runbook

## Runtime health

`GET /api/healthz/flows` is an operator diagnostic endpoint. It requires the
configured Eneo super API key; ordinary user, tenant API, service, and
super-duper credentials are rejected. Keep the key in the deployment secret
manager and never print it in logs or tickets.

```bash
curl --fail-with-body --silent --show-error \
  --header "X-API-Key: ${ENEO_SUPER_API_KEY}" \
  "${ENEO_BASE_URL}/api/healthz/flows" | jq .
```

The response combines bounded database diagnostics with platform worker
readiness for execution and maintenance. `UNKNOWN` means a diagnostic query
failed or timed out. Missing or expired ARQ health keys and Redis probe failures
fail closed.

Health and recovery use the same staleness predicate for running runs. A stale
run with a pending or claimed webhook delivery is excluded from both surfaces
because the webhook worker may still own an external effect. Let the bounded
claim/retry lifecycle converge before repeating the health check.

Production has two Flow-related platform processes:

- `task-execution-worker` executes queued runs;
- `task-maintenance-worker` reconciles stale work, expires review checkpoints,
  redispatches queued work, and delivers audit/webhook outboxes.

There is no Flow-private worker, beat process, or scheduler.

## Health flags and recovery

Timing values are returned in `thresholds`; code-owned defaults are shown below.
Any positive count triggers a flag unless an age condition is stated.

| Flag | Effective threshold | Recovery action |
| --- | --- | --- |
| `EXECUTION_WORKER_UNAVAILABLE` | The platform execution worker health key is missing or the one-second Redis readiness probe failed. | Restore Redis and `task-execution-worker`, then repeat the health check. |
| `MAINTENANCE_WORKER_UNAVAILABLE` | The platform maintenance worker health key is missing or the one-second Redis readiness probe failed. | Restore Redis and `task-maintenance-worker`, then repeat the health check. |
| `STALE_QUEUED_RUNS` | A queued run remains dispatch-pending for at least `stale_queued_after_seconds` (30 seconds). | Verify broker and execution health; allow bounded redispatch to converge. |
| `ACCEPTED_DISPATCH_EXHAUSTED` | At least one queued run has exhausted dispatch after broker acceptance or an outcome-unknown send. | Check for a delayed claim before using the authorized generation-fenced redispatch endpoint. Never clear fields with SQL. |
| `STALE_RUNNING_RUNS` | A recovery-eligible run is at least `stale_running_after_seconds` old (task timeout plus 60 seconds) but has not crossed the unhealthy threshold. | Restore worker capacity and allow the stale-running reconciler to terminalize through normal ownership. |
| `STALE_RUNNING_RECONCILER_LAG` | The oldest recovery-eligible run exceeds `stale_running_unhealthy_after_seconds` (task timeout plus 180 seconds). | Restore maintenance capacity and inspect sanitized reconciler errors. |
| `EXPIRED_REVIEW_CHECKPOINTS` | A reconcilable checkpoint is expired but no more than `review_expiry_unhealthy_after_seconds` (120 seconds) past expiry. | Allow review-expiry reconciliation to terminalize the checkpoint. |
| `REVIEW_EXPIRY_RECONCILER_LAG` | The oldest reconcilable checkpoint is more than 120 seconds past expiry. | Restore maintenance capacity and inspect expiry-task failures. |
| `TERMINAL_RUNS_WITH_OPEN_ATTEMPTS` | Any terminal run updated within the 24-hour integrity lookback still has an open attempt. | Stop mutation, preserve evidence, and investigate terminalization ownership. |
| `TERMINAL_RUNS_WITH_ACTIVE_STEP_RESULTS` | Any terminal run updated within the 24-hour integrity lookback still has an active step result. | Stop mutation, preserve evidence, and investigate terminalization ownership. |
| `AUDIT_OUTBOX_DELIVERY_BACKLOG` | A pending audit row remains eligible after the 300-second backlog grace. | Restore audit storage and maintenance capacity; let bounded delivery retry. |
| `AUDIT_OUTBOX_DEAD_LETTERS` | Any lifecycle-audit delivery exhausted its bounded attempts. | Preserve the row, restore dependencies, and follow the fail-closed dead-letter guidance below. |
| `WEBHOOK_OUTBOX_DELIVERY_BACKLOG` | An unclaimed or sufficiently expired pending webhook delivery remains eligible beyond the 300-second grace. | Restore destination connectivity and maintenance capacity; inspect sanitized diagnosis. |
| `WEBHOOK_OUTBOX_EXPIRED_CLAIMS` | Any pending webhook claim has reached `claim_expires_at`. | Verify the former worker no longer owns the effect, then allow bounded reclaim. |
| `WEBHOOK_OUTBOX_DEAD_LETTERS` | Any webhook delivery exhausted its five-attempt budget. | Preserve the row and inspect its sanitized failure and destination contract. |

A stale running run with a pending or claimed webhook delivery may still have an
external effect in progress. Do not terminalize it manually. Let the bounded
claim/retry lifecycle converge first.

## Accepted dispatch exhaustion

A queued run whose `dispatch_exhausted_at` is set can still have a delayed
broker-accepted delivery. First verify broker and worker health and wait for a
possible claim. If delivery was lost, an authorized run owner may call the run
redispatch endpoint with the observed `dispatch_exhausted_at` generation token.
The audited compare-and-swap re-arms only that generation; concurrent requests
cannot re-arm a later epoch. Poll the returned run after either a successful or
no-op response. Automatic maintenance never resets an exhausted budget.

## Lifecycle audit outbox dead letters

Terminal and review transitions write durable lifecycle-audit outbox rows.
Both `pending` and `dead_lettered` rows are required audit state and block
run-history purge.

The final core release exposes no public or sysadmin manual-redrive API. When a
dead letter appears:

1. restore the audit store, database, and platform maintenance worker;
2. preserve the row and its bounded failure diagnosis;
3. confirm the health endpoint and normal delivery loop after recovery;
4. do not delete, resolve, reset attempts, or alter lifecycle fields with SQL;
5. escalate for an audited application change if the row cannot converge.

This fail-closed policy avoids creating an unreviewed cross-tenant operator
surface. A pending or dead-lettered row remains a retention blocker until the
canonical delivery owner records success.

## Evidence export

Raw evidence export is exceptional. It requires the explicit non-default reason
gate and an audit-before-response transaction. If audit or commit fails,
protected bytes are not returned. Active encryption enforcement belongs to
M2.9; until that enforcement is active and verified in the deployment, do not
enable or perform raw evidence export. Redacted export remains the default.
Never put encryption keys, API keys, or exported evidence in tickets or command
history.

## Stored HTTP credentials

Authored HTTP credentials are encrypted before storage, and save/publish refuses
values that cannot be protected. Legacy rows must be reviewed through an
approved tenant-scoped support procedure. Do not automatically rewrite,
re-encrypt, or delete them. Re-enter affected draft credentials, publish a new
immutable version, retire the affected old version, and rotate the destination
credential.

An `UNPROTECTED` finding identifies fields, never values. `UNREADABLE` means the
stored configuration no longer proves its expected shape. Confirm the active
encryption key before interpreting either result.
