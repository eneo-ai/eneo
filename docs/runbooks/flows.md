# Flows Operations Runbook

## Runtime health endpoint

`GET /api/healthz/flows` is an operator diagnostic endpoint, not a public
liveness probe. It requires the configured Eneo super API key and does not
accept ordinary user, tenant API, service, or super-duper credentials. Keep the
key in the deployment secret manager and invoke the endpoint without printing
the value:

```bash
curl --fail-with-body --silent --show-error \
  --header "X-API-Key: ${ENEO_SUPER_API_KEY}" \
  "${ENEO_BASE_URL}/api/healthz/flows" | jq .
```

The response combines bounded database diagnostics with a bounded Celery
control inspection. `UNKNOWN` means the database query timed out or failed.
`MAINTENANCE_QUEUE_CONSUMER_UNAVAILABLE` means no responding worker reported
consuming the configured Flow maintenance queue; broker/control failure and an
inspection timeout are deliberately treated as unavailable. Verify the broker,
Flow worker process, worker queue subscription, and worker logs, then restart or
correct the worker deployment and repeat the check.

Recovery and health use the same staleness predicate for running runs. A stale
run with a pending or claimed webhook delivery is excluded from both surfaces:
the webhook worker still owns an external effect whose outcome may be in
progress. Do not terminalize it manually. Resolve or let the bounded webhook
claim/retry lifecycle converge, then repeat the health check.

### Health flags, effective thresholds, and recovery

Timing values are returned in `thresholds`; code-owned defaults are shown below.
Any positive count triggers a flag unless an age condition is stated.

| Flag | Effective threshold | Recovery action |
| --- | --- | --- |
| `MAINTENANCE_QUEUE_CONSUMER_UNAVAILABLE` | The 1-second Celery inspection finds no live worker consuming the configured maintenance queue, including unavailable broker/control replies. | Restore broker/control connectivity and a Flow worker subscribed to the maintenance queue, then repeat the endpoint check. |
| `STALE_QUEUED_RUNS` | A queued run remains dispatch-pending for at least `stale_queued_after_seconds` (30 seconds). | Verify broker and execution-worker health; allow bounded redispatch to converge and inspect dispatch diagnosis if it does not. |
| `ACCEPTED_DISPATCH_EXHAUSTED` | At least one queued run has exhausted dispatch after broker acceptance or an outcome-unknown send. | Check for delayed claims, then use the generation-fenced redispatch operation described below; never clear fields with SQL. |
| `STALE_RUNNING_RUNS` | A recovery-eligible running run is at least `stale_running_after_seconds` old (task timeout plus 60 seconds) but has not exceeded the unhealthy threshold. | Verify the execution worker and wait for the maintenance reconciler; investigate if the age keeps increasing. |
| `STALE_RUNNING_RECONCILER_LAG` | The oldest recovery-eligible running run exceeds `stale_running_unhealthy_after_seconds` (task timeout plus 180 seconds). | Restore the maintenance consumer and broker, inspect reconciler errors, and confirm the run terminalizes through normal recovery. |
| `EXPIRED_REVIEW_CHECKPOINTS` | A reconcilable checkpoint is expired, but its age has not exceeded `review_expiry_unhealthy_after_seconds` (120 seconds). | Verify the maintenance consumer and allow review-expiry reconciliation to terminalize the checkpoint. |
| `REVIEW_EXPIRY_RECONCILER_LAG` | The oldest reconcilable expired checkpoint is more than 120 seconds past expiry. | Restore the maintenance consumer, inspect review-expiry task failures, and verify the checkpoint reaches its normal terminal state. |
| `TERMINAL_RUNS_WITH_OPEN_ATTEMPTS` | Any terminal run updated in the 24-hour integrity lookback still has an open attempt. | Stop further mutation, preserve evidence, and investigate terminalization transaction ownership before repairing through the canonical lifecycle owner. |
| `TERMINAL_RUNS_WITH_ACTIVE_STEP_RESULTS` | Any terminal run updated in the 24-hour integrity lookback still has an active step result. | Stop further mutation, preserve evidence, and investigate terminalization transaction ownership before repairing through the canonical lifecycle owner. |
| `AUDIT_OUTBOX_DELIVERY_BACKLOG` | A pending audit row is still eligible after the 300-second backlog grace. | Restore audit storage and the maintenance consumer; let bounded delivery retry and verify the backlog clears. |
| `AUDIT_OUTBOX_DEAD_LETTERS` | Any lifecycle-audit delivery exhausted its bounded attempts. | Follow the generation-fenced audit dead-letter redrive procedure below after restoring audit storage. |
| `WEBHOOK_OUTBOX_DELIVERY_BACKLOG` | An unclaimed or sufficiently expired pending webhook delivery remains eligible beyond the 300-second grace. | Restore destination connectivity and the maintenance consumer; inspect sanitized delivery diagnosis and let bounded retry converge. |
| `WEBHOOK_OUTBOX_EXPIRED_CLAIMS` | Any pending webhook claim has reached `claim_expires_at`. | Verify the former worker is gone or no longer owns the effect, then let the maintenance delivery loop reclaim it. |
| `WEBHOOK_OUTBOX_DEAD_LETTERS` | Any webhook delivery exhausted its five-attempt budget. | Inspect the sanitized failure and destination contract; preserve the dead letter for operator diagnosis rather than editing it with SQL. |

## Evidence export controls (D5)

Raw evidence export remains exceptional. It keeps the existing explicit
non-default reason gate and the audit-before-response contract: if the audit
write or commit fails, export fails closed before protected response bytes are
returned. Raw evidence export also requires active encryption. Enforcement of
that encryption precondition is owned by M2.9; this runbook does not create a
second policy owner. Until M2.9 enforcement is active and verified in the
deployment, do not enable or perform raw export. Redacted export remains the
default. Never place encryption keys, super API keys, or exported evidence in
incident tickets or command history.

## Stored HTTP credential inventory (M2.9)

Authored HTTP credentials are encrypted before they are stored, and both saving
a step and publishing a version refuse a credential that cannot be protected.
Rows written before that enforcement can still hold an unprotected value, and a
published version keeps whatever the draft held when it was published.

```bash
python backend/scripts/flow_http_secret_inventory.py
```

The scan is read-only across every tenant. It reports each draft step and each
published version whose declared credential fields are unprotected, and exits
non-zero when it finds anything. It never rewrites, re-encrypts, or deletes a
row: what to do about a reported row is an operator decision.

Two findings are possible. `UNPROTECTED` names the credential fields; the value
is never printed. `UNREADABLE` means the config declares the authored HTTP
shape but no longer parses, so nothing can be said about the credentials in it.

Confirm `ENCRYPTION_KEY` is configured first — without an active key every
stored credential is reported, because none of them can be recognized as
protected. Then re-enter the credentials on the reported draft steps and publish
a new version. Published versions are immutable: an affected version has to be
retired rather than edited, and the credential it carried must be rotated at the
destination, because it was readable in the snapshot.

## Accepted Flow Dispatch Exhaustion

A queued run with `dispatch_exhausted_at` set remains queued when at least one
delivery was broker-accepted or the process stopped before it could persist the
broker receipt. A delayed delivery may still claim it. `GET /api/healthz/flows` reports
`ACCEPTED_DISPATCH_EXHAUSTED`, an `UNHEALTHY` status, the affected count, and
the oldest age. This is distinct from never-accepted exhaustion, which remains
a terminal `failed` run with the sanitized `flow_dispatch_failed` error.

First verify worker and broker health and check whether a delayed worker claims
the run. If every accepted delivery was lost, an authorized run owner may call
`POST /api/v1/flows/{flow_id}/runs/{run_id}/redispatch/` with the observed
`dispatch_exhausted_at` in `expected_dispatch_exhausted_at`. For an accepted
exhausted run, that audited action atomically rearms exactly that epoch and
attempts its first dispatch. Concurrent or retried requests cannot rearm a later
exhausted epoch; automatic maintenance never resets the budget. Confirm
`redispatched_count: 1`, then poll the run. A zero count means either another
actor or worker already converged the run or broker acceptance was
outcome-unknown; poll the returned run because bounded server recovery remains
authoritative. The existing
`flow_run_redispatched` audit action records every authorized request and
whether that request rearmed an exhausted epoch. Never clear exhaustion fields
with SQL.

## Lifecycle Audit Outbox Dead Letters

Flow terminal and review transitions write a durable lifecycle-audit outbox.
Undelivered rows are required audit state: both `pending` and `dead_lettered`
rows block run-history purge. Do not delete, resolve, or update these rows with
SQL.

### Diagnose

1. Check `GET /api/healthz/flows`. The
   `audit_outbox_dead_letters` flag and `audit_outbox.dead_lettered_count`
   indicate exhausted delivery. `audit_outbox_delivery_backlog` identifies old
   pending rows that have not exhausted retries.
2. Confirm the audit store and database are healthy before redrive. Redrive
   makes the row immediately eligible and restores its full five-attempt budget.
3. List dead letters through the operator API. It is available only with the
   configured Eneo super API key; ordinary user, tenant API, service, and super
   duper keys are not accepted.

Set the deployment URL and configured super-key header value:

```bash
export ENEO_BASE_URL="https://eneo.example.com"
export ENEO_SUPER_API_KEY="<super-api-key>"

curl --fail-with-body --silent --show-error \
  --header "X-API-Key: ${ENEO_SUPER_API_KEY}" \
  "${ENEO_BASE_URL}/api/v1/sysadmin/flows/audit-outbox/dead-letters/?limit=50&offset=0" \
  | jq .
```

The response is bounded to 200 rows per request. Advance `offset` while
`has_more` is true. Record the selected row's `outbox_id`, tenant and run ids,
failure text, and exact `dead_lettered_at` value. That timestamp is the
generation token, not merely diagnostic time.

### Redrive one generation

Use the exact token returned by the latest list response and a trimmed,
nonblank reason of at most 500 characters:

```bash
export OUTBOX_ID="<outbox-id>"
export DEAD_LETTERED_AT="<dead_lettered_at-from-list>"

curl --fail-with-body --silent --show-error \
  --request POST \
  --header "X-API-Key: ${ENEO_SUPER_API_KEY}" \
  --header "Content-Type: application/json" \
  --data "$(jq -n \
    --arg token "${DEAD_LETTERED_AT}" \
    --arg reason "Audit storage recovered and delivery was verified." \
    '{expected_dead_lettered_at: $token, reason: $reason}')" \
  "${ENEO_BASE_URL}/api/v1/sysadmin/flows/audit-outbox/${OUTBOX_ID}/redrive/" \
  | jq .
```

Successful redrive is one atomic transaction:

```text
dead_lettered(attempts exhausted, generation T)
  -> pending(attempts 0, eligible now, errors and terminal timestamps cleared)
  -> delivered(at most one lifecycle audit)
```

The transaction also commits one tenant-scoped SYSTEM audit action,
`flow_run_audit_delivery_redriven`, containing the reason and prior bounded
delivery diagnosis. There is no separate resolve operation.

### Conflicts and safe retry

- `404`: the outbox id does not exist. Recheck the environment and id; no state
  or audit changed.
- `409` with a non-dead-lettered state: another operator or the delivery worker
  already transitioned it. Verify current health rather than repeating blindly.
- `409` for a changed generation: the row dead-lettered again after it was
  listed. List again, investigate the new failure, and use the new
  `dead_lettered_at` token. An old token can never redrive a later generation.
- `422`: the reason/token contract is invalid. Supply an offset-aware timestamp
  and a trimmed reason of 1-500 characters.
- `5xx`: transition and operator audit roll back together. List again before
  retrying; do not repair with SQL.

Concurrent or repeated requests with the same token allow one transition and
one operator audit. Treat 409 from the losing request as expected convergence.

### Verify recovery

1. Repeat the dead-letter list. The row should no longer appear while pending
   or after delivery.
2. Check `/api/healthz/flows` until the dead-letter count and flag clear. A
   remaining backlog flag means delivery is still pending or failing.
3. Query the tenant audit surface and confirm both the original lifecycle audit
   and `flow_run_audit_delivery_redriven` operator audit exist. Idempotent
   delivery must not duplicate the lifecycle audit.
4. If the run is past its configured retention horizon, the next existing
   retention pass may purge it only after delivery reaches `delivered`. Pending
   and newly dead-lettered rows remain purge blockers.

### Rollback and recovery

To roll back the release, stop issuing redrives and revert the application
version. Do not reverse rows already changed to `pending`: the normal worker can
safely finish their idempotent delivery, and reverting them with SQL would lose
the generation and operator-audit contract. If the delivery dependency remains
unhealthy, pause the audit delivery worker to preserve attempt budget, restore
the dependency, resume the worker, then list and redrive only rows that reached
`dead_lettered`. A failed redrive request is transactionally safe to retry after
re-listing.
