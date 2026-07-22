# Flows Operations Runbook

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
