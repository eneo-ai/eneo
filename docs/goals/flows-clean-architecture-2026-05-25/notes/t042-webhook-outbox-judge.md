# T042 Webhook Outbox Judge

## TL;DR

- Decision: approve a ref-only durable webhook outbox as the first Worker; do not materialize resolved URL, headers, or body in this tranche.
- Delivery remains coupled to run success: pending webhook delivery keeps the run non-terminal; delivery success completes the run; dead-letter fails it.
- The first Worker must fix the stale-running interaction with an explicit `NOT EXISTS` exclusion and supporting partial index. A run with a pending webhook delivery row must not be failed by the generic stale-running reconciler while the webhook outbox is the recovery owner.
- Rerun/resume while webhook delivery is pending stays blocked by the existing `running` run status. Cancellation must prevent future claims from delivering rows for a terminal run.
- The first Worker must include enqueue, worker delivery, idempotency alignment, and deletion of inline executor webhook delivery in one reviewable slice.

## Decision

Choose **ref-only pending-run reconstruction** for the first Worker.

The materialized encrypted snapshot path is not approved yet. It would store resolved webhook URL, headers, timeout, and request body after interpolation and header decryption. That is a new sensitive storage surface, and T041 already established that `step_config_secrets.py` decrypts runtime headers before delivery. Without an explicit data/security decision for encryption, redaction, retention, and access policy, materialized request snapshots must remain blocked.

The ref-only path stores the durable delivery intent and enough identifiers to reconstruct from persisted Flow runtime state:

- `FlowRuns.input_payload_json` remains available while the run is non-terminal.
- `FlowRuns.flow_version` points at the published version used by execution.
- Published runtime steps can be parsed from `FlowVersion.definition_json`.
- Prior and current step outputs can be read from persisted `FlowStepResults`.
- `build_run_execution_state(...)` already rebuilds `prior_results` and `step_names_by_order` from persisted results and published steps.

The Worker must call or deepen the existing HTTP owners (`deliver_webhook_orchestrated` and `FlowHttpRuntimeHelper`) and must not instantiate `FlowRunExecutor` or reimplement the HTTP request path.

## Terminalization Semantics

Use coupled run semantics for the first Worker:

| Event | Run state decision |
|---|---|
| Executor completes an HTTP-post step | Persist completed step result and pending webhook row in one transaction; keep the run `running`. |
| Webhook worker delivery succeeds | Mark delivery row delivered, project `webhook_delivered=True` into the step result, then terminalize the run `completed` when this delivery gates the final run outcome. |
| Retryable delivery failure | Keep delivery row pending with backoff; keep the run `running`. |
| Delivery dead-letter | Mark delivery row dead-lettered, project sanitized error into the step result, and terminalize the run `failed`. |
| Run is cancelled before a row is claimed | Worker claim must not deliver rows for terminal runs. |
| Run becomes terminal after a row is claimed | Worker must not complete a now-terminal run; the post-send compare-and-set must fail unless the run is still `running` and the delivery row is still owned by the claim token. |

Do not introduce a new public run status in the first Worker. A new `pending_delivery` status would be a wider public contract change and should be a separate Judge/product decision if needed later.

## Table Shape And Lifecycle States

Create `flow_run_webhook_deliveries` as the canonical webhook delivery lifecycle owner. It should mirror the `FlowRunAuditOutbox` delivery vocabulary instead of inventing a second one:

- Reuse lifecycle columns: `delivery_status`, `delivery_attempts`, `next_delivery_at`, `delivered_at`, `dead_lettered_at`, and `delivery_last_error`.
- Reuse lifecycle states: `pending`, `delivered`, and `dead_lettered`.
- Do not add a separate persisted `in_progress` state in the first Worker. A claim is represented by claim metadata on a `pending` row, not by a fourth lifecycle status.
- Add webhook-specific identity columns: `flow_run_id`, `tenant_id`, `flow_id`, `step_id`, `attempt_no`, `idempotency_key`, and an opaque `payload_ref`.
- `payload_ref` must remain opaque. Do not parse `"flow_run:{id}:step:{id}:attempt:{n}"` back into state; the structured columns own identity.
- Omit audit-only columns and constraints: `action`, `source`, `description`, `entity_type`, `entity_id`, `actor_*`, `target_status`, review checkpoint fields, and audit description/source checks.
- Add claim metadata for no-HTTP-under-lock delivery: `claim_token`, `claim_expires_at`, and `claimed_at`.
- Add database checks for `length(idempotency_key) > 0`, `attempt_no >= 1`, `delivery_attempts >= 0`, pending rows with null `delivered_at`/`dead_lettered_at`, delivered rows with `delivered_at`, and dead-lettered rows with `dead_lettered_at`.
- Add unique `(flow_run_id, step_id, attempt_no)` and a uniqueness/check invariant for non-empty `idempotency_key`.

Claim contract:

- Enqueue uses `INSERT ... ON CONFLICT DO NOTHING` on `(flow_run_id, step_id, attempt_no)`.
- Claim uses `UPDATE ... WHERE delivery_status = 'pending' AND (next_delivery_at IS NULL OR next_delivery_at <= now) AND (claim_expires_at IS NULL OR claim_expires_at <= now) RETURNING ...`, setting `claim_token`, `claimed_at`, and `claim_expires_at`, then commits before external HTTP.
- Post-send success/failure uses a compare-and-set update that checks the row id, claim token, and current `delivery_status = 'pending'`.
- Final run completion/failure must also check that the run is still non-terminal. A worker must not complete a run that was cancelled or otherwise terminalized after the row was claimed.

## Stale-Running Reconciler Decision

The generic stale-running reconciler currently treats old `running` runs as failed:

- `flow_run_repo.py:1640` loads `running` runs older than `updated_at <= stale_before`.
- `flow_run_service.py:607` sends those runs to `terminalize_stale_running_run(...)`.
- `flow_run_terminalization.py:72` terminalizes them as `failed`.
- `runtime/tasks.py:345` runs the same reconciliation across all tenants.
- `flow_run_recovery_policy.py:16` sets the stale threshold to task timeout plus grace.

Therefore the Worker is not safe if it only leaves webhook-gated runs in `running`. The Worker must make the webhook outbox row the recovery owner for runs whose only remaining work is outbound webhook delivery.

First Worker requirement:

- `list_stale_running_runs(...)` must exclude runs with pending webhook delivery rows that are still eligible for webhook recovery.
- The webhook worker must own retries, dead-lettering, and final terminalization for those rows.
- The webhook outbox must expose enough tests to prove such rows are not falsely failed by the generic stale-running reconciler.

Exact predicate:

```sql
NOT EXISTS (
  SELECT 1
  FROM flow_run_webhook_deliveries webhook_delivery
  WHERE webhook_delivery.flow_run_id = flow_runs.id
    AND webhook_delivery.tenant_id = flow_runs.tenant_id
    AND webhook_delivery.delivery_status = 'pending'
)
```

Supporting index:

```sql
CREATE INDEX ix_flow_run_webhook_deliveries_pending_run_tenant
ON flow_run_webhook_deliveries (flow_run_id, tenant_id)
WHERE delivery_status = 'pending';
```

The stale-running reconciler remains owner for stalled executor work; the webhook outbox becomes owner for pending outbound delivery.

Do not add a `FlowRuns.updated_at` heartbeat to hide webhook-gated runs from stale-running recovery. Pending webhook rows hold the run out of stale scope through the `NOT EXISTS` predicate; timestamp freshness stays display/recovery metadata for normal run execution.

## Rerun, Resume, And Cancel Policy

- Rerun/resume while webhook delivery is pending: blocked by existing `running` status. Do not add a special rerun compatibility path.
- Duplicate delivery: not allowed. Enforce one row per `(flow_run_id, step_id, attempt_no)`.
- Retry of the same row: reuse the same outgoing `Idempotency-Key`.
- Legitimate rerun after a terminal state: creates a new attempt and therefore a new delivery key.
- Cancel while pending: a pending row must not be claimable after the run is terminal. Do not deliver a webhook after cancellation unless it was already in the external HTTP send window.

## Idempotency Decision

Use the handler-produced attempt-aware key as the producer invariant:

- Producer key: `WebhookDeliveryIntent.idempotency_key`, semantically `(flow_run_id, step_id, attempt_no, webhook)`.
- Database invariant: unique `(flow_run_id, step_id, attempt_no)` and non-empty `idempotency_key`.
- Outgoing header: derive `sha256(idempotency_key).hexdigest()` from the stored producer key.
- Do not recompute from only `run.id:step.step_id` inside `http_orchestration.py`; that currently ignores attempt number and disagrees with `HttpPostStepHandler`.

This preserves the existing opaque 64-character header shape but intentionally changes the header value because `attempt_no` now contributes. Source search found tests asserting only presence/length/stability, not a published external contract for the old `sha256(run.id:step.step_id)` value.

## First Worker

Title: `fix(flows-runtime): deliver webhooks through durable ref-only outbox`

Objective:

Implement the first durable outbound webhook slice using a ref-only `flow_run_webhook_deliveries` owner. Persist the completed step result and pending delivery row together, deliver through a worker outside the claim transaction, remove direct executor webhook delivery, and keep stale-running reconciliation from failing runs whose pending work is owned by the webhook outbox.

The success-plan handoff must carry the typed `WebhookDeliveryIntent` to the enqueue site. Do not preserve `StepSuccessPlan.should_deliver_webhook` as the only signal and re-derive row identity later.

Allowed files:

- `docs/goals/flows-clean-architecture-2026-05-25/state.yaml`
- `docs/goals/flows-clean-architecture-2026-05-25/notes/t043-webhook-outbox-worker.md`
- `backend/alembic/versions/*flow_run_webhook_deliveries*.py`
- `backend/src/intric/database/tables/flow_tables.py`
- `backend/src/intric/main/container/container.py`
- `backend/src/intric/flows/runtime/celery_app.py`
- `backend/src/intric/flows/runtime/tasks.py`
- `backend/src/intric/flows/runtime/executor.py`
- `backend/src/intric/flows/runtime/http_orchestration.py`
- `backend/src/intric/flows/runtime/step_attempt_runtime.py`
- `backend/src/intric/flows/runtime/step_execution_result.py`
- `backend/src/intric/flows/runtime/step_result_builder.py`
- `backend/src/intric/flows/runtime/step_handlers/http_post.py`
- `backend/src/intric/flows/runtime/flow_webhook_delivery.py`
- `backend/src/intric/flows/application/flow_webhook_delivery_policy.py`
- `backend/src/intric/flows/infrastructure/flow_run_repo.py`
- `backend/src/intric/flows/infrastructure/flow_run_webhook_delivery_repo.py`
- `backend/tests/integration/flows/test_flow_webhook_outbox_repository.py`
- `backend/tests/integration/flows/test_flow_webhook_outbox_delivery.py`
- `backend/tests/integration/flows/test_flow_runtime_worker_contract.py`
- `backend/tests/unittests/flows/test_flow_runtime_step_handlers.py`
- `backend/tests/unittests/flows/test_step_attempt_runtime.py`
- `backend/tests/unittests/flows/test_http_orchestration.py`
- `backend/tests/unittests/flows/test_celery_runtime.py`
- `backend/tests/unittests/flows/test_flow_architecture_guards.py`

Verification commands:

```bash
cd backend && uv run pytest tests/integration/flows/test_flow_webhook_outbox_repository.py -q
cd backend && uv run pytest tests/integration/flows/test_flow_webhook_outbox_delivery.py -q
cd backend && uv run pytest tests/integration/flows/test_flow_runtime_worker_contract.py::test_webhook_delivery_success_uses_handler_intent_for_fresh_sessions tests/integration/flows/test_flow_runtime_worker_contract.py::test_webhook_delivery_failure_persists_failed_state_for_fresh_sessions -q
cd backend && uv run pytest tests/unittests/flows/test_flow_runtime_step_handlers.py tests/unittests/flows/test_step_attempt_runtime.py tests/unittests/flows/test_http_orchestration.py tests/unittests/flows/test_celery_runtime.py tests/unittests/flows/test_flow_architecture_guards.py -q
cd backend && uv run ruff check src/intric/flows src/intric/database/tables/flow_tables.py src/intric/main/container/container.py tests/integration/flows tests/unittests/flows
cd backend && uv run pyright src/intric/flows src/intric/database/tables/flow_tables.py src/intric/main/container/container.py tests/integration/flows tests/unittests/flows
```

Required red tests before implementation:

- Stale-running skip: a `running` run older than the stale threshold is not terminalized by `reconcile_stale_running_runs` when it has a pending webhook delivery row.
- Duplicate enqueue: inserting or enqueuing the same `(flow_run_id, step_id, attempt_no)` twice creates one row and does not create a second delivery path.
- Cancel race: a run cancelled between enqueue and worker claim is not delivered by the webhook worker.
- Claim transaction boundary: the worker commits the claim before external HTTP send, then records success/failure in a separate compare-and-set update.
- Wire idempotency: the sent `Idempotency-Key` equals `sha256(intent.idempotency_key).hexdigest()` and retries of the same row reuse it.

Boundary notes:

- `flow_webhook_delivery_policy.py` may exist only for retry/dead-letter constants and pure retry-delay calculation, mirroring `flow_run_audit_outbox_policy.py`. Use the audit-outbox retry shape unless source evidence justifies different values: max attempts `5`, backoff seconds `(60, 300, 900, 3600)`. If it becomes a pass-through wrapper over the repository or worker, remove it from the slice.
- `step_result_builder.py` is allowed only to keep the public projection coherent: `webhook_delivered` should remain the step result projection (`False` before delivery, `True` after success, sanitized error after dead-letter) while retry/dead-letter lifecycle lives in the webhook delivery row.
- Celery task name: `flows.deliver_webhook_outbox`.
- Queue: reuse the existing Flow execution queue for the first slice; do not create queue topology work in this task.

Stop if:

- Implementation needs to persist resolved URL, headers, body, decrypted secret values, or request snapshots.
- The Worker would keep inline executor webhook delivery and outbox delivery live without deleting the inline path in the same slice.
- The Worker would hold a database transaction or row lock during external HTTP.
- The Worker would import or instantiate `FlowRunExecutor` to deliver a webhook row.
- The Worker would add a generic outbox base class, event bus, plugin system, manager, processor, or one-implementation port.
- The Worker cannot prove stale-running reconciliation skips runs whose pending work is owned by webhook delivery.
- The Worker cannot make `flow_webhook_delivery_policy.py` a real pure policy boundary.
- The Worker needs router/API/OpenAPI changes.
- The Worker needs retention, service-key identity, Flow AI Builder, frontend state cleanup, or broad schema hardening outside webhook delivery.

## Consolidation Effect

- Reused existing owner: `WebhookDeliveryIntent` remains the producer boundary; `http_orchestration` and `FlowHttpRuntimeHelper` remain the HTTP request behavior owners; stale-running reconciliation remains the owner for stalled executor work.
- Logic moved from: webhook context/request/delivery orchestration moves out of `FlowRunExecutor` into a narrow webhook delivery owner.
- Logic deleted: direct executor helpers `_deliver_step_webhook`, `_handle_webhook_delivery_failure`, `_mark_webhook_delivery_success`, and tests that only assert inline delivery behavior.
- Duplicate path removed: after the Worker there is one delivery lifecycle owner, the webhook delivery outbox, instead of executor inline branches plus step-result payload flags acting as hidden state.
- New code added: webhook-specific table/repository/pure retry policy/worker because audit outbox constraints and in-DB delivery loop do not fit external HTTP side effects.
- Why existing owners were insufficient: audit outbox owns lifecycle audit delivery, not external webhook effects; `http_orchestration` sends requests but does not own durable delivery lifecycle; executor should not own external side-effect retries.
- Guard/test preventing duplicate logic from returning: architecture guard forbids direct executor webhook send; integration tests assert enqueue-before-worker, no HTTP under claim transaction, stale-running exclusion, and one row per run/step/attempt.
- Net Flow logic surface area: reduced after the slice. Before: executor inline delivery branch, three executor helper methods, step-result payload lifecycle flags, and attempt-blind orchestration idempotency. After: one webhook delivery lifecycle table/repository/worker owns retries and terminalization, while step result stores only the public projection.

## Peer-Review Disposition

Claude T041 approved the read-only preflight with `GREEN_LIGHT yes` and required explicit reconstruction proof, typed intent handoff, no HTTP under DB locks, and a Judge decision before Worker implementation.

Antigravity T041 rejected ref-only as a target and recommended materialized encrypted snapshots. The first Worker chooses ref-only because:

- pending delivery keeps the run non-terminal, so retention does not purge needed runtime evidence;
- stale-running reconciliation must delegate pending webhook rows to the webhook outbox owner;
- the worker must reconstruct only from persisted run/version/result state and current encrypted config, not from mutable draft state or executor internals.

The storage-shape concern is valid, but the recommended snapshot cannot proceed without a data/security decision because it stores resolved request state. This is a source-backed disagreement with Antigravity's preferred storage shape, not a dismissal of the risk.
