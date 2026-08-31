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

The supported recovery path is the narrow deployment-shell command below. It
requires deployment or Kubernetes access through the authenticated operations
wrapper for that environment. Deployments must provide an access-controlled,
deployment-owned launcher that invokes only this module and injects
`ENEO_OPERATOR_IDENTITY` from its authenticated operator context. The CLI
cannot authenticate a human inside the application container; it fails closed
when the launcher does not provide an identity. Do not set or forward that
variable from an untrusted shell or command argument; do not expose this path
as a generic privileged shell. There is no public or tenant-facing redrive
endpoint and no bulk redrive command.

```bash
# The deployment-owned launcher must pass the subcommand and arguments exactly.
/usr/local/sbin/eneo-flow-audit-outbox -- list --limit 50
```

Use the `dead_lettered_at` value from the bounded list as the generation token.
Inspect one row without changing it, then redrive only that row after the audit
store, database, and platform maintenance worker are healthy:

```bash
export FLOW_AUDIT_OUTBOX_ID="<outbox-id-from-list>"
export FLOW_AUDIT_DEAD_LETTERED_AT="<dead-lettered-at-from-list>"
/usr/local/sbin/eneo-flow-audit-outbox -- dry-run "${FLOW_AUDIT_OUTBOX_ID}" \
  --expected-dead-lettered-at "${FLOW_AUDIT_DEAD_LETTERED_AT}"
/usr/local/sbin/eneo-flow-audit-outbox -- redrive "${FLOW_AUDIT_OUTBOX_ID}" \
  --expected-dead-lettered-at "${FLOW_AUDIT_DEAD_LETTERED_AT}" \
  --reason "Audit storage recovered; normal delivery can resume."
```

The command uses the existing generation-fenced delivery service and records
the operator identity, bounded reason, previous attempt count, and prior
generation in the tenant-scoped audit row. A stale generation or concurrent
delivery returns a nonzero conflict exit; list the row again before retrying.
Do not delete, resolve, reset attempts, or alter lifecycle fields with SQL. A
pending or dead-lettered row remains a retention blocker until the canonical
delivery owner records success.

Exit status `10` means the row was not found, `11` means it is no longer
dead-lettered, `12` means the generation is stale, `20` means configuration or
database bootstrap failed, and `21` means the audit operation or sink failed.

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
