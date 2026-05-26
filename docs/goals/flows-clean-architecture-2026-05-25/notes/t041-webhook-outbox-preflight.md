# T041 Durable Webhook Outbox Preflight

## TL;DR

- `HttpPostStepHandler` now emits a typed `WebhookDeliveryIntent`, but the executor still reduces it to `should_deliver_webhook` and sends the HTTP side effect inline.
- There is no durable outbound webhook outbox. Current durable outbox code is lifecycle audit only, and its table shape must not be reused for webhook delivery.
- The audit outbox is still useful as a pattern: partial indexes, retry/dead-letter counters, health summary, and worker scheduling. Its row-lock delivery loop is not enough for webhooks because external HTTP must not run while holding database locks.
- A safe webhook outbox design should keep `WebhookDeliveryIntent` as ingress, store one delivery row per run/step/attempt, claim rows with a short lease, and send outside the claim transaction.
- The next task should be a Judge task. It must choose the first Worker shape and explicitly close run terminalization, rerun-with-pending-delivery, and ref-only reconstruction before direct executor delivery is removed.

## Current Evidence

| Topic | Evidence | Finding |
|---|---|---|
| Handler intent | `backend/src/intric/flows/runtime/step_execution_result.py:14` defines `WebhookDeliveryIntent`; `backend/src/intric/flows/runtime/step_handlers/http_post.py:39` creates it. | The typed ingress exists and should remain the canonical producer boundary. |
| Intent projection | `backend/src/intric/flows/runtime/step_attempt_runtime.py:170` builds the success plan and `backend/src/intric/flows/runtime/step_attempt_runtime.py:193` sets `should_deliver_webhook=bool(result.delivery_intents)`. | The executor does not consume the intent contents yet. |
| Inline delivery | `backend/src/intric/flows/runtime/executor.py:862` calls `_deliver_step_webhook` inline after saving the step result in the current transaction. | The side effect is not durable before delivery. |
| Inline request building | `backend/src/intric/flows/runtime/executor.py:1579` builds webhook context; `backend/src/intric/flows/runtime/executor.py:1874` calls `deliver_webhook_orchestrated`. | Request construction is still executor-owned. |
| Inline failure | `backend/src/intric/flows/runtime/executor.py:1603` records delivery failure and `backend/src/intric/flows/runtime/executor.py:1627` terminalizes the run failed. | Current semantics treat webhook delivery as part of step/run success. |
| Inline success | `backend/src/intric/flows/runtime/executor.py:1642` writes `webhook_delivered=True`; `backend/src/intric/flows/runtime/executor.py:911` terminalizes the run after outcome calculation. | Current completion is coupled to webhook success. |
| HTTP idempotency | `backend/src/intric/flows/runtime/http_orchestration.py:331` hashes `run.id:step.step_id`; the handler intent uses `run_id:step_id:attempt_no:webhook` at `backend/src/intric/flows/runtime/step_handlers/http_post.py:44`. | The producer intent and outgoing header disagree about attempt/rerun semantics. |
| Secret handling | `backend/src/intric/flows/step_config_secrets.py:16` encrypts stored config headers; `backend/src/intric/flows/step_config_secrets.py:50` decrypts for runtime. | Persisting a materialized request snapshot would risk storing decrypted secrets unless explicitly encrypted. |
| Audit outbox table | `backend/src/intric/database/tables/flow_tables.py:1431` defines `FlowRunAuditOutbox`; constraints at `:1545`, `:1550`, and unique indexes at `:1501`/`:1508` are lifecycle-audit-specific. | The table is not a generic delivery outbox. |
| Audit delivery loop | `backend/src/intric/flows/infrastructure/flow_run_audit_outbox_repo.py:138` lists due rows with `FOR UPDATE SKIP LOCKED`; `backend/src/intric/flows/application/flow_run_audit_outbox_delivery.py:73` iterates rows. | Good pattern for short in-DB audit writes, but not for slow external HTTP under a transaction. |
| Audit health | `backend/src/intric/flows/runtime/flow_runtime_health.py:125` exposes audit outbox summary; `:526` loads pending/backlog/dead-letter counts. | Health/readiness pattern exists but is audit-specific. |
| Audit worker | `backend/src/intric/flows/runtime/tasks.py:479` delivers audit outbox; `backend/src/intric/flows/runtime/celery_app.py:62` schedules it. | Worker scheduling pattern exists. |
| Current tests | `backend/tests/integration/flows/test_flow_runtime_worker_contract.py:982` expects inline `_deliver_webhook` success and `:1027` expects inline failure terminalization. | Tests protect current direct-delivery behavior and must change in the same slice that removes it. |
| Runtime retention | `backend/src/intric/data_retention/infrastructure/data_retention_service.py:485` targets terminal runs; `:566` clears debug fields from step results. | Keeping runs non-terminal while webhook delivery is pending avoids current retention purging pending delivery inputs/results. |
| State reconstruction | `backend/src/intric/flows/runtime/executor.py:548` loads persisted results; `backend/src/intric/flows/runtime/execution_state_builder.py:8` rebuilds `RunExecutionState` and `:25` rebuilds `step_names_by_order`. | A ref-only worker can rebuild prior state from persisted run/version/results if pending deliveries keep the run non-terminal. |
| Webhook payload readers | Source search finds production `webhook_delivered` readers in `step_execution_runtime.py:502`, `step_result_builder.py:120`, `flow_run_export_json.py:935`, and generated type hints in `frontend/packages/intric-js/src/types/resources.d.ts:189`. | No current production router/UI branch was found that treats pending webhook delivery as a separate public run state. |

Source search command:

```bash
rg -n "webhook.*outbox|outbox.*webhook|WebhookOutbox|FlowWebhook|webhook_delivery|delivery_intent|WebhookDelivery" backend/src/intric backend/tests -g '*.py'
```

It found only handler intents, inline executor delivery, HTTP orchestration, tests, and audit names; no durable webhook outbox owner exists.

## Concept Inventory

| Concept | Current locations | Behavior differences | Canonical owner | Merge/delete path |
|---|---|---|---|---|
| Outbound delivery intent | `step_execution_result.py`, `step_handlers/http_post.py` | Intent includes run/step/attempt/idempotency/payload ref, but executor only uses a boolean. | `WebhookDeliveryIntent` remains ingress; future outbox enqueue service consumes it. | Replace `StepSuccessPlan.should_deliver_webhook` with `delivery_intents: tuple[WebhookDeliveryIntent, ...]` so the enqueue site gets typed data. |
| Payload reference | `WebhookPayloadRef(value=...)` in `http_post.py` | String reference is not enough to prove retention-safe delivery by itself. | Webhook outbox model/parser. | Either keep ref-only while run remains non-terminal until delivery, or add an encrypted typed request snapshot. |
| Request building | `executor._deliver_step_webhook`, `http_orchestration.deliver_webhook`, `FlowHttpRuntimeHelper` | Context assembly lives in executor; HTTP orchestration also computes idempotency. | A small webhook delivery application service plus `http_orchestration` request/delivery leaf functions. | Move context/request assembly out of executor when direct send is removed; do not copy it into a second implementation. |
| Delivery state | `webhook_delivered`/`webhook_error` in step result payload | Step result payload is used as delivery state and result payload at once. | Webhook delivery outbox row owns delivery lifecycle; step result can keep public projection after delivery. | Move retry/dead-letter/pending state to the outbox; keep step result payload as final public projection only. |
| Retry/dead-letter | Audit outbox policy/service/repo | Audit delivery is in-process DB work; webhook delivery is slow external HTTP. | Dedicated webhook delivery policy/service/repo. | Reuse retry constants pattern, not audit table or long lock pattern. |
| Idempotency | Handler intent includes attempt; HTTP header ignores attempt | Current header can collide across reruns of the same run/step. | Webhook outbox row stores producer key; HTTP delivery uses a stable derived header from that stored key. | Stop recomputing idempotency in `deliver_webhook`; pass the outbox/intent key into request construction. |
| Health/readiness | Audit-only summary in `flow_runtime_health.py` | No webhook pending/backlog/dead-letter signal. | Flow runtime health with separate webhook summary. | Add webhook summary once the table exists; do not overload audit names. |
| Audit outbox pattern | `FlowRunAuditOutbox`, repo, delivery service, Celery schedule | Audit row id is audit log id; lifecycle action/source constraints do not fit webhooks. | Audit code remains audit-only. | Copy only proven query/state patterns into a webhook-specific owner. |

## Audit Outbox Reuse Decision

Reuse as pattern only:

- delivery status counters and retry/dead-letter policy shape;
- partial indexes for filtered pending/dead-letter queries;
- Celery beat/task registration shape;
- health summary presentation shape;
- `SKIP LOCKED` style claim selection.

Do not reuse `flow_run_audit_outbox` table:

- It is constrained to lifecycle audit source/action/status values (`flow_tables.py:1545`, `:1550`, `:1557`).
- It has lifecycle uniqueness rules: one terminal row per run revision and one row per checkpoint revision (`flow_tables.py:1501`, `:1508`).
- The row id is reused as the delivered audit log id (`flow_tables.py:1432`), which is wrong for external webhook attempts.
- Data retention deletes delivered audit outbox mirrors only after matching audit logs are deleted (`data_retention_service.py:177`), which is unrelated to webhook delivery lifecycle.
- Webhook delivery needs many rows per run over time, request target state, retry/lease fields, HTTP response/error metadata, and idempotency semantics.

Do not copy audit delivery locking blindly:

- Audit delivery can hold a row lock while it writes an audit log in the same database.
- Webhook delivery must not hold a transaction/row lock across external HTTP. Use a short claim transaction with a lease, send outside the transaction, then mark success/failure with compare-and-set.

## Idempotency Model

Recommended model for Judge approval:

- Producer key: `WebhookDeliveryIntent.idempotency_key`, semantically `(flow_run_id, step_id, attempt_no, delivery_kind)`.
- Database uniqueness: unique `(flow_run_id, step_id, attempt_no)` plus a unique or checked non-empty `idempotency_key`.
- Consumer header: derive `Idempotency-Key` from the stored producer key, preferably `sha256(idempotency_key).hexdigest()` to preserve the existing opaque 64-character header contract from `test_http_orchestration.py:243`.
- Retry semantics: retrying the same outbox row reuses the same header.
- Rerun semantics: a new step attempt produces a new producer key/header.
- Current mismatch to fix in implementation: `http_orchestration.py:331` ignores attempt number while `http_post.py:44` includes it.

## Retention Coupling

Two viable designs:

1. Ref-only outbox, current semantics preserved:
   - Store IDs and payload ref only.
   - Keep the run non-terminal while delivery is pending.
   - Worker reconstructs context/request from persisted run, step result, published step snapshot, and encrypted runtime config.
   - Current retention targets terminal runs (`data_retention_service.py:485`), so pending delivery data remains available.
   - Delivery success terminalizes the run completed; dead-letter terminalizes failed.
   - Required reconstruction proof:
     - `run.input_payload_json` comes from the persisted run loaded by id.
     - `step.output_config`, `step.step_id`, `step.step_order`, and `step.user_description` come from `parse_published_runtime_steps(version.definition_json)` as in `executor.py:530`.
     - `state.prior_results` and `state.step_names_by_order` are rebuilt from `flow_run_repo.list_step_results(...)` plus published steps via `build_run_execution_state(...)`.
     - Current step `text` and `structured` values must be read from the persisted current step result payload before delivery.
     - This proof fails if a pending delivery can become terminal-retained before worker send; in that case use option 2 or block for retention policy.

2. Materialized request snapshot:
   - Store resolved URL, headers, timeout, and body in the outbox row.
   - This is retention-safe even if the run later becomes terminal.
   - It risks persisting decrypted secret headers unless the snapshot owner encrypts sensitive fields.
   - It requires an explicit security/data decision before implementation.

Scout recommendation: prefer option 1 for the first behavior switch because it preserves current semantics and avoids adding a new decrypted-secret storage surface. If Judge chooses option 2, block until the security/data owner decides how encrypted request snapshots are stored and retained.

## Rerun And Pending Delivery Policy

Judge must decide this before Worker implementation:

- Preferred coupled-semantics policy: an HTTP-post step with a pending webhook delivery keeps the run non-terminal, so review/rerun actions that require a terminal or reviewable run should not create a new attempt until delivery resolves.
- If rerun while pending is allowed anyway, the Worker must define whether it cancels the prior pending row, lets both rows deliver, or blocks the rerun. Letting both deliver is not acceptable by default because it can double-fire external side effects.
- The unique database invariant should still be one delivery row per `(flow_run_id, step_id, attempt_no)`.
- Retry of the same row uses the same idempotency key; a legitimately new attempt uses a new key.

## Crash-Window Analysis

Current inline path:

| Point | Current behavior | Risk |
|---|---|---|
| Attempt start | Attempt is started and committed before step execution (`executor.py:692`, `:703`). | Existing recovery can see a started attempt. |
| Step result save | Step result is saved before webhook delivery (`executor.py:833`). | It is not enough because external delivery still happens before durable delivery state exists. |
| Before HTTP send | No durable pending delivery row exists. | Crash can lose the side-effect intent or force ambiguous retry from step execution state. |
| After HTTP success before commit | HTTP side effect happened, but `webhook_delivered=True` may not commit. | Retry can redeliver. Current idempotency partially mitigates but does not include attempt number. |
| HTTP failure | Failure is persisted and run is terminalized failed (`executor.py:1603`). | No retry/dead-letter; a transient endpoint issue fails the whole run immediately. |

Desired outbox path:

| Point | Desired behavior | Guard |
|---|---|---|
| Step result + enqueue | Persist successful step result and pending webhook row in one transaction. | Integration test asserts both rows exist after executor returns and `_deliver_webhook` is not called. |
| Worker claim | Claim due rows with a short lease and commit before sending HTTP. | Repository test asserts no open transaction/lock is held during send; expired claims are reclaimable. |
| HTTP success | Mark outbox delivered, project `webhook_delivered=True`, and terminalize completed if this delivery gates final run completion. | Worker integration test asserts fresh-session completion and no duplicate audit/outbox rows. |
| Retryable failure | Increment attempts, record sanitized error, set `next_delivery_at`, return row to pending. | Retry-policy test asserts backoff and stable idempotency header. |
| Dead-letter | Mark dead-letter and terminalize failed if Judge preserves current coupled semantics. | Dead-letter test asserts visible health flag and run error code. |

## Tests And Verification For First Worker

Exact tests to add or update once Judge approves the first Worker:

- Migration/schema:
  - Create `flow_run_webhook_deliveries` with status/check constraints, unique `(flow_run_id, step_id, attempt_no)`, FK coverage, pending/dead-letter/expired-claim partial indexes.
  - Reject impossible states: delivered without `delivered_at`, dead-letter without `dead_lettered_at`, in-progress without `claim_token`/`claim_expires_at`, negative attempts, duplicate run/step/attempt.
- Repository:
  - Insert pending row from a real `WebhookDeliveryIntent` plus persisted `FlowStepResult.id`.
  - Claim due rows with `SKIP LOCKED`/lease behavior and return typed delivery rows.
  - Reclaim expired in-progress rows without holding locks across HTTP.
  - Mark success/failure/dead-letter with compare-and-set on id/claim token.
- Executor switch:
  - Existing `test_webhook_delivery_success_uses_handler_intent_for_fresh_sessions` should become: executor enqueues one pending row and does not call `_deliver_webhook`.
  - Crash-window test: after executor commit, fresh session sees completed step result plus pending delivery row.
  - Guard test: no direct `_deliver_step_webhook` path remains in executor after the switch slice.
- Worker delivery:
  - Successful worker delivery sends exactly one HTTP request, uses the stored/derived idempotency key, marks outbox delivered, updates step result projection, and terminalizes completed.
  - Retryable failure schedules retry and leaves run non-terminal/pending if coupled semantics are chosen.
  - Dead-letter marks outbox dead-lettered, exposes health/readiness, and terminalizes failed if coupled semantics are chosen.
- Health:
  - Pending backlog and dead-lettered webhook rows appear under webhook-specific health fields, not audit outbox fields.

Suggested verification commands:

```bash
cd backend && uv run pytest tests/integration/flows/test_flow_webhook_outbox_repository.py -q
cd backend && uv run pytest tests/integration/flows/test_flow_runtime_worker_contract.py::test_webhook_delivery_success_uses_handler_intent_for_fresh_sessions tests/integration/flows/test_flow_runtime_worker_contract.py::test_webhook_delivery_failure_persists_failed_state_for_fresh_sessions -q
cd backend && uv run pytest tests/unittests/flows/test_http_orchestration.py tests/unittests/flows/test_flow_runtime_step_handlers.py tests/unittests/flows/test_step_attempt_runtime.py -q
cd backend && uv run pytest tests/integration/flows/test_flow_runtime_health.py tests/unittests/flows/test_flow_runtime_health.py -q
cd backend && uv run ruff check src/intric/flows src/intric/database/tables/flow_tables.py tests/integration/flows tests/unittests/flows
cd backend && uv run pyright src/intric/flows src/intric/database/tables/flow_tables.py tests/integration/flows tests/unittests/flows
```

## Smallest Safe Worker Candidates

Candidate A: storage and claim owner only.

- Scope: add table/model/migration, repository, typed delivery row, policy constants, and tests.
- No executor behavior switch; no HTTP worker.
- Safe only if Judge accepts temporary unused groundwork because it does not create a live parallel path.
- Risk: increases code surface before behavior changes.
- Scout revision after peer review: do not activate this as a standalone Worker unless Judge documents why unused groundwork is safer than landing the behavior switch with deletion.

Candidate B: enqueue switch with no HTTP worker.

- Scope: add table/repo and change executor to enqueue pending rows instead of direct send.
- Leaves runs pending/non-terminal until a worker exists.
- Not safe alone because it changes observable runtime completion.

Candidate C1: enqueue + worker delivery + inline deletion.

- Scope: table/repo/service/worker, replace direct executor delivery with durable enqueue, consume typed intents, fix webhook idempotency to use attempt-aware producer key, and delete inline executor delivery helpers/tests in the same tranche.
- Include the worker claim lease so external HTTP is sent outside the claim transaction.
- Preserve current coupled semantics unless Judge decides otherwise: delivery success completes the run; dead-letter fails it.
- Broad but avoids unused parallel delivery paths.

Candidate C2: webhook health/readiness.

- Scope: add webhook-specific pending/backlog/dead-letter health fields after C1 creates real delivery state.
- Keep audit outbox health names audit-only.

Scout recommendation:

- Run a Judge task before Worker implementation.
- If Judge approves preserving current coupled semantics and ref-only reconstruction, prefer Candidate C1 first, then C2. This reduces duplicate runtime paths faster than standalone groundwork.
- If Judge requires decoupled completed-run-with-pending-delivery semantics or materialized request snapshots, stop for product/security/data decision before Worker implementation.

## Proposed Next Judge Task

Objective:

Choose the first T013 Worker from this preflight. Decide whether webhook delivery remains part of run success, whether the first Worker may add storage/claim groundwork without a live path, and whether request payloads are ref-only or materialized/encrypted.

Judge must answer:

- Is preserving current coupled semantics approved: pending webhook keeps run non-terminal; delivery success completes; dead-letter fails?
- Is a ref-only outbox acceptable because pending runs are not retention targets, or is the worker reconstruction complexity too high?
- Is a materialized request snapshot preferred, and if so who approves encrypted storage for resolved headers/body/URL data?
- What happens if rerun/resume is requested while a webhook delivery row is pending or in progress?
- Must the first Worker include enqueue + worker delivery + inline deletion to avoid an unused parallel path, or is standalone storage groundwork justified?
- Should the outgoing `Idempotency-Key` header use the stored producer key directly or a hash derived from it? Do not preserve the current 64-character test shape unless it is a real public contract.
- What exact allowed files, verification commands, and stop rules should the Worker receive?

## Consolidation Effect

- Reused existing owner: `WebhookDeliveryIntent` as producer ingress; `http_orchestration`/`FlowHttpRuntimeHelper` for HTTP request behavior; audit outbox only as a pattern.
- Logic moved from: future Worker should move webhook context/request/delivery lifecycle out of `FlowRunExecutor`.
- Logic deleted: future Worker should delete `_deliver_step_webhook`, `_handle_webhook_delivery_failure`, `_mark_webhook_delivery_success`, and direct-send tests in the same behavior switch.
- Duplicate path removed: target is one delivery state owner instead of step-result payload plus inline executor branches.
- New code added: a webhook-specific outbox storage/claim owner is necessary because audit outbox constraints and in-DB lock loop do not fit external HTTP.
- Why existing owners were insufficient: audit outbox owns lifecycle audit delivery, not external HTTP side effects; current HTTP orchestration owns request sending, not durable state.
- Guard/test preventing duplicate logic from returning: source guard for no direct executor webhook send after switch; repository/worker tests for one pending row per run/step/attempt, no transaction held during HTTP send, and stable attempt-aware idempotency.
- Net Flow logic surface area: likely increased if Candidate A lands alone; reduced after Candidate C1 deletes inline executor delivery.

## Peer Review Notes

Claude plan gate: `.codex/artifacts/claude-peer-loop-t041-webhook-outbox-preflight-20260526T091900Z.md`, `GREEN_LIGHT yes`, `MIN_SCORE 8`.

Valid concerns incorporated:

- Required explicit reconstruction proof for ref-only delivery.
- Required rerun-vs-pending-delivery policy before Worker.
- Tightened typed handoff from boolean to `WebhookDeliveryIntent` tuple.
- Reframed Candidate A as not recommended unless Judge proves it safer.
- Added no-lock-during-HTTP and delivered-row cleanup concerns to Judge/Worker expectations.

Antigravity synthesis:

- First pass artifact: `.codex/artifacts/antigravity-peer-loop-t041-webhook-outbox-antigravity-synthesis-20260526T092430Z.md`; the model response was empty, so no verdict was accepted.
- Retry artifact: `.codex/artifacts/antigravity-peer-loop-t041-webhook-outbox-antigravity-retry-20260526T093235Z.md`; verdict was effectively non-green/conditional. It rejects ref-only reconstruction and recommends a materialized encrypted webhook request snapshot.

Valid Antigravity concerns to carry into Judge:

- A worker must not import `FlowRunExecutor` or duplicate a broad execution runtime just to deliver an outbox row.
- Ref-only delivery is only safe if every request input is reconstructable from persisted run/version/result state and pending delivery prevents retention cleanup.
- Materialized request snapshots reduce worker complexity and retention coupling, but create a new resolved request storage surface.
- Claim/lease and no-transaction-during-HTTP are mandatory.

Codex disagreement/source nuance:

- Antigravity's claim that draft config edits would necessarily change ref-only delivery is not proven by current runtime source: executor loads `run.flow_version` through `flow_version_repo.get(...)` and parses that published `definition_json` (`executor.py:508`, `executor.py:530`), so a correct worker should also use the published snapshot, not mutable draft rows.
- Materialized encrypted storage may be the right design, but it is not approved merely because a reviewer recommended it. It stores resolved URL/header/body data and therefore needs Judge/security/data approval before Worker implementation.
