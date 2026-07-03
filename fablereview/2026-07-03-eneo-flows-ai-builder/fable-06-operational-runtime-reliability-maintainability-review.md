# Fable 06 v2: Runtime Reliability And Runtime Ownership Review

All source and test evidence is gathered. Here is the complete review.

---

# Fable 06 — Flow Runtime Operational Reliability & Maintainability Review

Reviewer: Claude (Fable 5) · Date: 2026-07-03 · Repo: `/Users/ccimen/eneo/eneo-flows-clean` @ `refactor/flows-clean`

## TL;DR

1. **One P0 blocks production:** the stale-RUNNING reconciler beat task (`flows.reconcile_running`) runs against an `autobegin=False` session with no `session.begin()` and no commit (`backend/src/eneo/flows/runtime/tasks.py:656-692` vs `backend/src/eneo/database/database.py:50-55`) — worker-crash recovery for RUNNING runs cannot persist (and most likely raises on its first query); its only tests fully mock the session.
2. Everything else in the idempotency/claim layer is unusually strong: CAS run claims, single-winner step claims under real concurrency, idempotent attempt creation, fingerprint-backed run and rerun idempotency with partial unique indexes, lease-based webhook outbox, skip-locked audit outbox with idempotent audit-log insert.
3. Two P1 operability gaps: all six task types (hour-long executes + all recovery/delivery beats) share one Celery queue with prefetch 1, and the health endpoint has zero webhook-outbox signals even though webhook dead-letters fail runs.
4. Ownership is mostly canonical (terminalizer is the single terminal-state writer), with one split-brain: `flow_step_results` has two repository writers (`FlowRunRepository` claims/closes, `FlowRepository.save_step_result` upserts) and the table docstring names only one.
5. Ponytail deletions are small but real: `DISPATCH_FAILURE` lifecycle source, `RETRIED` attempt status, `FlowRunService.execution_backend`, and the executor's legacy non-config constructor path are all dead.

---

## Ratings

Per `docs/engineering/maintainability-standards.md`, overall = minimum dimension.

| Dimension | Score | Basis |
|---|---:|---|
| Runtime reliability | 7 | CAS lifecycle + fencing are excellent; undermined by the dead reconciler |
| Idempotency | 9 | Fingerprints + partial unique indexes + CAS + concurrency-tested (test_flow_run_repository.py:1502-2272) |
| Crash recovery | **3** | QUEUED recovery works (30s beat + claim); RUNNING recovery is dead in production (P0-1) |
| Outbox/dead-letter reliability | 8 | Both outboxes correct by design; webhook throughput serialized, no webhook health signals |
| Observability/debuggability | 7 | Health endpoint, lifecycle events, OTel spans, `celery_task_id` persisted on attempts; webhook blind spot |
| Maintainability ownership | 7 | Terminalizer is a model owner; step-result dual-writer and enum string-coupling detract |
| Data retention safety | 8 | Terminal-only + undelivered-audit + active-rerun blockers + metadata-complete file-reference guard |
| Testability | 7 | Outstanding DB-level CAS tests; the riskiest beat task is mock-only — exactly the anti-pattern `docs/engineering/testing-standard.md` flags |
| **Production readiness** | **5** | Blocked on P0-1; P1-2/P1-3 should land before real traffic |

Action band: a dimension at 3 ⇒ fix required before further feature work.

---

## Runtime Lifecycle Map

**Create → dispatch:** `FlowRunService.create_run` (flow_run_service.py:295-334) validates, takes the per-tenant creation lock (`acquire_tenant_run_creation_lock`, flow_run_repo.py:258-261, `FOR UPDATE` on the tenant row), replays by idempotency key + SHA-256 request fingerprint, enforces the concurrency cap, inserts the run as QUEUED with preseeded PENDING step results. The router commits, then dispatches via FastAPI background task `dispatch_flow_run_recoverably_after_commit` (flow_run_execution_router.py:765-769 → flow_dispatch.py:14-31), which **swallows dispatch failures by design** — the QUEUED run is the durable intent and the 30s `flows.redispatch_stale_queued` beat is the repair path (tasks.py:718-731 docstring says exactly this).

**Execute:** `flows.execute` (tasks.py:463-653) parses dispatch kwargs into typed variants (`FlowRunUserDispatchRequest` / `FlowRunServiceKeyDispatchRequest` / missing-principal / malformed), runs the async executor on a per-process daemon event loop, bounds it with `future.result(timeout=flow_task_timeout_seconds)`, and on timeout **cancels the asyncio task, drains it, then terminalizes** (tasks.py:604-632). The executor (executor.py:563-1067): terminal short-circuit → `mark_running_if_claimable` CAS (QUEUED→RUNNING only, flow_run_repo.py:809-821) → checksum/snapshot/definition validation with source-specific terminalization → per-step loop: security evaluation, run-status gate, `claim_step_result` CAS (PENDING/FAILED→RUNNING), attempt allocation (`create_or_get_attempt_started`, idempotent upsert on `uq_flow_step_attempts_run_step_attempt`), attempt-start provenance persisted **before** LLM dispatch, handler execution, success/failure plans, `finish_attempt` CAS on open statuses → finalization via `finalize_run_from_current_results` (run_outcome.py:80-133) delegating to the terminalizer.

**Review:** completed step with a review policy → `open_review_checkpoint_for_completed_step` (review_checkpoint_repo.py:209-341; run `FOR UPDATE`, RUNNING→AWAITING_REVIEW with revision bump) and the executor returns. Approve/edit/reject/resume are revision-CAS state transitions; resume requires an idempotency key with replay semantics and flips AWAITING_REVIEW→QUEUED (review_checkpoint_repo.py:567-638), after which the API dispatches again. Expiry is reconciled per-tenant by the 60s `flows.reconcile_review_expiry` beat.

**Webhook (terminal `http_post` output step):** the executor persists the completed step + PENDING delivery rows in one commit and returns with the run still RUNNING (executor.py:1014-1054). `flows.deliver_webhook_outbox` (30s) claims rows with a token+TTL lease, sends HTTP **outside any transaction**, then success-CAS marks delivered and finalizes the run; dead-letter after 5 attempts fails the run with `WEBHOOK_DELIVERY_FAILED` (flow_webhook_delivery.py:116-401). Runs with PENDING deliveries are excluded from stale-RUNNING reconciliation (flow_run_repo.py:358-384).

**Rerun:** `FlowRunRerunService.rerun_step` → `accept_or_replay_rerun_operation` (flow_run_rerun_repo.py:141-411): fingerprint replay, run `FOR UPDATE`, revision CAS, eligibility (COMPLETED/FAILED only), invalidated-step lineage rows with prior attempt ids, step-result reset to PENDING, run→QUEUED with revision+1 — then normal dispatch. The executor links new attempts to the operation and supersedes predecessors.

**Recovery:** stale QUEUED → 30s beat, atomic claim via `updated_at`-bump CAS (flow_run_repo.py:386-409) + redispatch. Stale RUNNING → 60s beat → `terminalize_stale_running_run` with `stale_before` fencing. Hard backstop: Celery `task_time_limit = timeout + 60`, `visibility_timeout` validated at startup to exceed it (config.py:677-686).

**Retention:** `data_retention_service` selects terminal runs past their effective retention (flow/space/classification `LEAST`), **skipping runs with undelivered audit outbox rows or active rerun operations** (data_retention_service.py:648-728), then `FlowRunHistoryPurgeRepository.purge_run_history` deletes deliveries/outbox/checkpoints/runs and reclaims files only when unreferenced by any of ten reference tables (flow_run_history_purge_repo.py:84-112, 359-377).

---

## State Transition / Transaction Boundary Inventory

Run statuses: `queued → running → awaiting_review → (queued) | completed | failed | cancelled`, encoded once in `FLOW_RUN_STATUS_CAPABILITIES` (enums.py:129-194) with derived ACTIVE/TERMINAL/CANCELLABLE/RERUN-ELIGIBLE sets and a DB check constraint (flow_tables.py:783-786). Key consequences the code relies on:

- FAILED/COMPLETED terminalization claims only from ACTIVE = {QUEUED, RUNNING}; CANCELLED claims from CANCELLABLE = {QUEUED, RUNNING, AWAITING_REVIEW} (flow_run_repo.py:434-447). So AWAITING_REVIEW can never become FAILED — this quietly protects against orphaned checkpoints in the task-timeout drain race, but nothing states it (see F-7).
- Step results: `pending → running → completed | failed | cancelled`; FAILED is re-claimable (rerun path) (flow_run_repo.py:840-872).
- Attempts: `started → completed | failed | cancelled` (+ `retried`, never written — F-10).

Transaction boundaries (owner in parentheses):

| Operation | Boundary | Evidence |
|---|---|---|
| Run creation | one request transaction, committed before response; dispatch strictly after commit (router) | flow_run_execution_router.py:724-769 |
| Run claim / step claim / attempt start | executor commits after each CAS write (executor) | executor.py:594, 812, 875 |
| Attempt-start provenance | committed before LLM dispatch (executor) | executor.py:1343-1353 |
| Step success | step result + finish_attempt (+ delivery intents) in one commit | executor.py:1014-1054, 1690-1742 |
| Step failure | rollback → failure rows + terminalize + commit | executor.py:1575-1688 |
| Terminalization | single logical unit inside caller's transaction: CAS run update + close children + close reruns + cancel checkpoints + audit outbox insert (terminalizer) | flow_run_terminalization.py:102-274; rollback-on-outbox-failure proven at test_flow_terminalization_contract.py:593 |
| Review transitions | run+checkpoint `FOR UPDATE`, revision CAS, outbox insert, one transaction (checkpoint repo) | review_checkpoint_repo.py:782-812 |
| Rerun accept | run `FOR UPDATE` + fingerprint replay + reset + QUEUED in one transaction (rerun repo; "Callers own the active database transaction" docstring) | flow_run_rerun_repo.py:1-5, 141-411 |
| Audit outbox delivery | outer `session.begin()` + per-row `begin_nested()` savepoints; skip-locked claims held to commit | tasks.py:784-793; flow_run_audit_outbox_delivery.py:73-99 |
| Webhook delivery | claim committed → HTTP outside transaction → success/failure in own transaction with claim-token CAS | flow_webhook_delivery.py:136-196; test_flow_webhook_outbox_delivery.py:463 |
| Stale-queued redispatch | claim committed before dispatch (comment explains why) | tasks.py:752-761 |
| **Stale-running reconcile** | **none — no begin, no autobegin, no commit** | tasks.py:656-692 (F-1) |
| Purge | caller's retention transaction; ordered deletes then conditional file delete | flow_run_history_purge_repo.py:84-112 |

---

## Runtime Owner Map

| Concept | Canonical owner | Notes |
|---|---|---|
| Run lifecycle state | `FlowRuns` row; non-terminal transitions via `FlowRunRepository` CAS; **all terminal transitions via `FlowRunTerminalizer`** | Genuinely single-owner; executor, tasks, cancel, review-reject, webhook dead-letter all delegate |
| Step result state | **Split**: `FlowRunRepository` (claim, close-for-terminal) + `FlowRepository.save_step_result` (upsert with active-run guard, flow_repo.py:634-714) | Table docstring "Writer: FlowRunRepository" (flow_tables.py:851) is wrong — F-8 |
| Step attempts | `FlowRunRepository` (create_or_get, provenance, finish, supersede) | Clean |
| Dispatch | `CeleryFlowExecutionBackend` behind `FlowExecutionBackend` protocol; all three entry points (create, resume/rerun re-dispatch, stale-queued beat, manual redispatch endpoint) build the same `FlowRunDispatchRequest` | Protocol has one real impl; justified as the cross-process seam |
| Terminalization | `FlowRunTerminalizer` | Exemplary |
| Retry/crash recovery | policy constants in `flow_run_recovery_policy.py`; mechanics in `tasks.py` beats + `FlowRunRepository` claim methods; shared core `redispatch_stale_queued_run` | Coherent |
| Audit outbox | insert: terminalizer + checkpoint repo; delivery: `FlowRunAuditOutboxDeliveryService` | Delivery deliberately bypasses tenant audit feature flags (documented, flow_run_audit_outbox_delivery.py:44-49) |
| Webhook outbox | insert: executor success plan; delivery: `FlowRunWebhookDeliveryService` | Delivery also finalizes/fails the run — an intentional second consumer of the terminalizer, not a second owner |
| Retention/purge | selection: `data_retention_service`; deletion: `FlowRunHistoryPurgeRepository` | Clean split |
| Health/debuggability | `flow_runtime_health.py` + `/api/healthz/flows` (server/main.py:700-767) | DB-only probe, 2s budget |

---

## State / Attempt / Claim / Lease Review

**Run claim (QUEUED→RUNNING):** pure CAS `UPDATE ... WHERE status='queued'` (flow_run_repo.py:809-821); single winner proven under real concurrency (test_flow_run_repository.py:1679, 1753). Duplicate Celery delivery (acks_late + visibility timeout) lands on a RUNNING/terminal run and exits as skipped — the correct absorb-duplicates design given `task_acks_late=True`, `task_reject_on_worker_lost=True` (worker/celery/app.py:29-30).

**Step claim:** CAS PENDING/FAILED→RUNNING; non-claims are classified by the pure `resolve_step_claim` (claim_resolution.py:23-53) into proceed/already-claimed/append-completed/missing, so a second executor pass (rerun, resume) replays completed steps instead of re-executing them.

**Attempt identity:** `allocate_next_attempt_no` + insert with `on_conflict_do_nothing` on `(run, step, attempt_no)` then select — idempotent and single-row under concurrency (test_flow_run_repository.py:2081, 2175). Rerun root attempts pre-allocate `root_attempt_no` at accept time so the executor and operation agree on lineage; `link_rerun_invalidated_step_attempt` CAS raises `FlowRunRerunAttemptLineageConflictError` on divergence, which the executor terminalizes explicitly (executor.py:876-884).

**Stale-queued claim:** `UPDATE ... WHERE status='queued' AND updated_at <= stale_before` returning, bumping `updated_at` — atomic cross-process cooldown; crash between claim-commit and dispatch self-heals on the next 30s tick. Correct.

**Webhook lease:** token + `claim_expires_at` TTL (300s) + `FOR UPDATE SKIP LOCKED` candidate select; success/failure CAS on `(id, claim_token, status=PENDING)`; lost claims raise and skip counting (flow_run_webhook_delivery_repo.py:76-210). At-least-once HTTP with a per-attempt `idempotency_key` handed to the receiver — the right contract.

**Audit outbox claim:** `FOR UPDATE SKIP LOCKED` rows locked for the outer transaction, per-row savepoints, delivery idempotent because the audit-log id **is** the outbox id via `create_if_absent` (flow_run_audit_outbox_delivery.py:107-119; test at test_flow_audit_outbox_delivery.py:227).

**Fencing:** `updated_at` (auto-`onupdate`, base_class.py:35-40) is the staleness clock despite the `FlowRuns.revision` comment calling it "display metadata" (flow_tables.py:734-737) — the comment undersells a load-bearing column (F-11). `stale_before` is re-checked inside `terminalize_run_status` (flow_run_repo.py:445-446), so a run that made progress between list and terminalize is not killed. Late writes after terminalization are rejected by `save_step_result`'s active-run guard and by `finish_attempt`'s open-status CAS — both integration-tested (test_flow_runtime_worker_contract.py:386, 489).

**One real hole:** none of this matters for crashed RUNNING runs if the reconciler cannot commit — see F-1.

---

## Change-Path Analysis

- **Add a run status:** `FlowRunStatus` + one `FlowRunStatusCapability` entry (enums.py) auto-derives ACTIVE/TERMINAL/CANCELLABLE/rerun sets; plus DB check-constraint migration (flow_tables.py:783-786), trace allowlists (flow_runtime_trace.py:52-92), health counts if operator-relevant, API models/frontend. One obvious starting file; the traps are the check constraint and the string-mirrored `FlowRunRerunOperationStatus` (F-9). Good path.
- **Add a step status:** enum + ACTIVE/OPEN set + check constraint + claim CAS filters + terminal-close sweeps. Contained; the frozensets make omission visible.
- **Add a retry policy:** no in-run step retry exists today (attempts advance only via rerun). A retry policy would slot into the executor's failure handlers + a backoff module following the existing `*_policy.py` pattern. No parallel implementation to fight — good.
- **Add an outbox delivery type:** two divergent templates exist — audit (savepoints, no lease, DB-only effect) vs webhook (lease+token, external effect). The divergence is principled (external side effect ⇒ lease), but nothing records the decision rule; a third type will copy the wrong one. Write the one-paragraph rule down (F-12).
- **Add a retention rule:** policy field (flow_retention_policy.py) + selector in data_retention_service + tombstone shape; the metadata-completeness guard (test_flow_run_history_purge_repo.py:11) protects the file side. Good.
- **Add an operator health signal:** snapshot field + loader query + flag + classify + thresholds + response model — ~6 touchpoints all in `flow_runtime_health.py`. Fine.

---

## Ranked Findings

### F-1 · P0 — Stale-RUNNING reconciler cannot persist: worker-crash recovery is dead in production
- **Problem:** `_reconcile_stale_running_runs_all_tenants` (tasks.py:656-692) opens `sessionmanager.session()` and immediately queries/writes — but the production sessionmaker is `autobegin=False` (database.py:50-55), and this function, alone among the six flow tasks, neither calls `enable_autobegin_for_flow_task_session` nor wraps work in `session.begin()` **nor commits**. First statement is `tenant_repo.get_all_tenants()` → bare `session.execute` (tenant_repo.py:86-90). Expected behavior: SQLAlchemy raises `InvalidRequestError` on the first query, so `flows.reconcile_running` fails every 60s; even if queries somehow ran, `session.close()` without commit discards every terminalization. Compare the siblings that do it right: review-expiry (tasks.py:699-715), stale-queued (736-761), audit outbox (784-793), and `terminalize_flow_run_failure` (358-368).
- **Why it matters:** this beat task is the **only** recovery for a run left RUNNING by a worker crash (SIGKILL/OOM). Redelivered tasks deliberately skip RUNNING runs (`mark_running_if_claimable`), and the timeout-path secondary terminalization (10s budget, tasks.py:72) also lists this reconciler as its fallback. With it dead, crashed runs stay RUNNING forever; the health endpoint will scream `STALE_RUNNING_RECONCILER_LAG` but nothing repairs.
- **Why tests are green:** both unit tests mock `sessionmanager.session` with `AsyncMock()` and replace `Container` wholesale (test_celery_runtime.py:934-1053) — they pin call wiring, not behavior. The review-expiry equivalent **is** integration-tested as the real function against a real session (test_flow_run_review_checkpoint_repository.py:2153); reconcile-running has no such test.
- **Canonical fix (owner: tasks.py):** mirror the review-expiry shape — `enable_autobegin_for_flow_task_session(session)` and wrap the tenant list plus each per-run terminalization in `async with session.begin():` (per-run transactions so one poisoned run doesn't roll back the batch).
- **Acceptance criteria:** integration test seeds a RUNNING run with `updated_at` older than `flow_stale_running_reconcile_after_seconds`, calls the real `_reconcile_stale_running_runs_all_tenants()` against the testcontainer sessionmaker, asserts the run is FAILED with `RUN_WORKER_STALLED` **from a fresh session**, attempts/step results closed, audit outbox row inserted.
- **Risk/trade-off:** none; strictly a bug fix. **Confidence: high** on brokenness (the no-commit path is airtight even if the autobegin exception model differs); exact first-failure mode is for Codex to confirm (see Claims #1).

### F-2 · P1 — One Celery queue for hour-long executions and all recovery/delivery tasks
- **Problem:** all six tasks route to `settings.flow_celery_queue` (celery_app.py:42-49) with `worker_prefetch_multiplier=1` and `flow_task_timeout_seconds` defaulting to 3600 (config.py:301). If the worker pool is saturated with hour-long `flows.execute` tasks, `reconcile_running`, `redispatch_stale_queued`, `deliver_audit_outbox`, and `deliver_webhook_outbox` queue behind them — the recovery/delivery machinery starves behind exactly the workload it must repair. Beat keeps enqueuing new instances meanwhile.
- **Why it matters:** recovery latencies (30s/60s design points) silently degrade to hours under load; webhook/audit delivery SLOs collapse; the health endpoint degrades with no actor able to respond.
- **Fix (owner: celery_app.py + deployment):** route the five maintenance tasks to a `flows.maintenance` queue with a small dedicated worker (or dedicated consumer process on the same host). Keep `flows.execute` isolated.
- **Acceptance:** task_routes assert test; deployment config gains the second consumer; a runbook note stating the invariant "maintenance queue must always have a free worker."
- **Risk:** minimal (routing only). **Confidence: high** on the mechanism; severity depends on deployed worker concurrency (Claims #4).

### F-3 · P1 — Health endpoint has no webhook-outbox signals
- **Problem:** `FlowRuntimeHealthFlag` covers stale runs, review expiry, terminal integrity, and **audit** outbox backlog/dead letters (flow_runtime_health.py:48-58, 511-561) — nothing for `flow_run_webhook_deliveries`: no pending-backlog count, no dead-letter count, no expired-claim count. Yet webhook dead-lettering *fails runs* (flow_webhook_delivery.py:388-400) and pending deliveries *suppress stale-RUNNING reconciliation* (flow_run_repo.py:370-379), so a stuck webhook pipeline is both invisible and load-bearing.
- **Fix (owner: flow_runtime_health.py):** add `WEBHOOK_OUTBOX_DELIVERY_BACKLOG` (degraded) and `WEBHOOK_OUTBOX_DEAD_LETTERS` (unhealthy) mirroring the audit queries, plus an expired-claim count (claim_expires_at < now with status PENDING).
- **Acceptance:** integration test seeding a dead-lettered webhook row asserts UNHEALTHY with the new flag.
- **Risk:** none. **Confidence: high.**

### F-4 · P2 — Beat tasks orphan their coroutine on timeout
- **Problem:** the four beat wrappers use `future.result(timeout=30/60/…)` (tasks.py:813-867) but, unlike `flows.execute` (which cancels and drains, tasks.py:604-612), they do not cancel the coroutine on `TimeoutError`. The coroutine keeps running unsupervised on the shared loop while beat schedules the next instance — overlapping reconciler instances, session/connection pressure, and misleading "task failed" results for work that later succeeds. The per-tenant serial loops make >30s plausible as tenant count grows.
- **Fix (owner: tasks.py):** extract the existing cancel-and-join helper (tasks.py:371-419) and apply it in all beat wrappers; consider raising the timeout for the tenant-iterating tasks.
- **Acceptance:** unit test: patched slow coroutine → wrapper times out → coroutine observed cancelled.
- **Risk:** low. **Confidence: high.**

### F-5 · P2 — Per-tenant serial reconciliation scales O(tenants) per minute
- **Problem:** three beats iterate `get_all_tenants()` and query each tenant even when idle (tasks.py:670-691, 705-714, 744-777). At hundreds of tenants that is thousands of queries/minute inside 30-60s budgets (compounding F-4).
- **Fix:** cross-tenant variants of `list_stale_running_runs` / `list_stale_queued_runs` (drop the tenant predicate, keep the partial indexes `ix_flow_runs_running_updated_at`; group per-tenant afterward). Tenant-scoping here is repo convention, not an isolation requirement — the beat is a system actor.
- **Acceptance:** one query per beat tick regardless of tenant count; existing behavior tests still pass.
- **Risk:** low; touches recovery queries, so land with F-1's integration test. **Confidence: medium-high** (severity depends on tenant count trajectory).

### F-6 · P2 — Executor's mid-loop RUNNING return relies on a publish-time invariant it never checks
- **Problem:** on a delivery-intent step the executor inserts pending deliveries, commits, and returns with the run RUNNING and any remaining steps unexecuted (executor.py:1046-1054). This is only correct because `FLOW_HTTP_POST_OUTPUT_MUST_BE_TERMINAL` is enforced at validation time (domain/flow_step_validation.py:40). If a published definition ever violates it (validator regression, imported package, manual data), the run silently stalls and is later failed by the reconciler as misleading `flow_worker_stalled` — because after delivery succeeds nothing redispatches and `finalize_run_from_current_results` returns `run_in_progress` (run_outcome.py:47-51).
- **Fix (owner: executor):** one runtime guard — if `delivery_intents` and the step is not the highest `step_order`, terminalize with a precise definition-invariant error code instead of returning RUNNING.
- **Acceptance:** unit test with a mid-flow webhook step asserts immediate terminalization with the new code, not a late stall.
- **Risk:** none for valid flows. **Confidence: high** on the mechanism; the trigger requires an invariant breach (hence P2, not P1).

### F-7 · P2 — Two implicit invariants worth making explicit in the terminalizer
- **Problem:** (a) active review checkpoints are cancelled only when `target_status == CANCELLED` (flow_run_terminalization.py:232-240); FAILED terminalization leaves them untouched. This is safe **only** because FAILED cannot claim from AWAITING_REVIEW (ACTIVE statuses exclude it, enums.py:204-208 + flow_run_repo.py:434-438) — a three-file implicit proof. (b) The stale-running query's exclusion of pending-webhook runs (flow_run_repo.py:370-379) is the only thing preventing the reconciler from failing runs that are legitimately waiting out webhook retries (up to ~22 min of backoff, longer than the 60s grace).
- **Fix:** make the checkpoint sweep unconditional for all terminal targets (it's a no-op when none active — cheap, removes the coupling), and add a comment + test on the webhook exclusion tying it to `FLOW_WEBHOOK_RETRY_BACKOFF_SECONDS`.
- **Acceptance:** terminalization contract test: FAILED terminalization with a (synthetically) active checkpoint cancels it.
- **Risk:** none. **Confidence: high.**

### F-8 · P2 — `flow_step_results` has two repository writers and a false docstring
- **Problem:** claims and terminal closes live in `FlowRunRepository` (flow_run_repo.py:840-872, 472-516) while the upsert-with-active-run-guard lives in `FlowRepository.save_step_result` (flow_repo.py:634-714) — used by both the executor and the webhook delivery service. The table docstring asserts "Writer: FlowRunRepository" (flow_tables.py:850-851). Violates the canonical-ownership rule and misleads the next engineer hunting step-result writes.
- **Fix:** move `save_step_result` (and its file-row replacement helper) into `FlowRunRepository`; fix the docstring. Mechanical: ~4 call sites (executor ×4, webhook delivery ×1).
- **Acceptance:** `FlowRepository` no longer touches `FlowStepResults`; grep-clean.
- **Risk:** low; pure move. **Confidence: high.**

### F-9 · P3 — Rerun-operation status derived by stringly enum cast
- **Problem:** `FlowRunRerunOperationStatus(target_status.value)` (flow_run_rerun_repo.py:426) couples two enums by value identity; a future terminal `FlowRunStatus` without a mirror raises `ValueError` **inside terminalization** — the worst place to discover it.
- **Fix:** explicit `dict[FlowRunStatus, FlowRunRerunOperationStatus]` mapping with an exhaustiveness test, or share one terminal-status enum.
- **Confidence: high.**

### F-10 · P3 — Dead runtime symbols (Ponytail deletes)
- `FlowRunLifecycleSource.DISPATCH_FAILURE` (enums.py:265) — never raised since dispatch failures stopped terminalizing; grep shows zero writers.
- `FlowStepAttemptStatus.RETRIED` (enums.py:312) — never written, yet inflates `OPEN_FLOW_STEP_ATTEMPT_STATUSES` used in CAS filters, terminal sweeps, and health queries.
- `FlowRunService.execution_backend` (flow_run_service.py:199) — assigned, never read (redispatch takes the backend as an argument).
- `FlowRunExecutor` legacy kwargs path `max_inline_text_bytes`/`max_audio_files`/`max_generic_files` alongside `config` (executor.py:494-513) — production always passes `config` (tasks.py:331-338); collapse to config-only.
- **Fix:** delete all four (RETRIED needs a check-constraint migration if statuses are DB-constrained). **Confidence: high** on deadness; each is a two-minute grep for Codex to re-confirm.

### F-11 · P3 — `FlowRuns.revision` comment calls `updated_at` "display metadata"
`updated_at` is the fencing clock for stale-queued claims, stale-running reconciliation, and health staleness (flow_run_repo.py:346, 369, 399, 446; flow_runtime_health.py:418-422). The comment (flow_tables.py:734-737) will invite someone to stop bumping it. Reword to name both tokens' jobs. **Confidence: high.**

### F-12 · P3 — Undocumented decision rule between the two outbox mechanics
Audit outbox: savepoints + skip-locked, no lease (DB-only effect). Webhook outbox: lease + claim token (external effect, at-least-once + receiver idempotency key). Both are correct; the *choice criterion* lives nowhere. One paragraph in `docs/engineering/` prevents the third delivery type from copying the wrong template. **Confidence: high.**

---

## Idempotency / Retry / Crash Recovery Review

**Duplicate starts (API):** belt and suspenders — per-tenant creation `FOR UPDATE` lock serializes creation, idempotency-key replay compares a versioned SHA-256 request fingerprint (algo_version 3, flow_run_service.py:531-568) and rejects payload mismatch with a dedicated code, and partial unique indexes `uq_flow_runs_idempotency_user_key` / `_service_key` (flow_tables.py:803-824) enforce it even if a code path skips the lock. Replay happens **before** the concurrency-limit check (tested: test_flow_run_service.py:937). Reruns get the same treatment via `uq_flow_run_rerun_operations_request_fingerprint` with a lock-then-recheck replay. Review resume requires an idempotency key and replays on state+key match. This layer is exemplary.

**Duplicate delivery (Celery):** `task_acks_late=True` + `task_reject_on_worker_lost=True` + Redis `visibility_timeout` validated at startup to exceed the hard time limit (config.py:677-686). Every redelivery funnels into CAS gates: run claim (single winner, concurrency-tested), step claim (single winner), attempt insert (unique-constraint idempotent), finish_attempt (open-status CAS). The task returns result dicts instead of raising in all handled paths, so poisoned messages don't retry-loop; malformed payloads are parsed into a typed `FlowRunDispatchMalformedPayload` and dropped with logs (tasks.py:561-576).

**Worker crash:**
- Crash before dispatch (API process dies): run stays QUEUED → 30s redispatch beat → atomic claim → re-dispatch. Sound, self-healing on claim/dispatch crashes. Covered by unit tests of the classification core (test_stale_queued_redispatch.py) and repo cooldown test (test_flow_run_repository.py:2491).
- Crash mid-execution: redelivered task skips (run RUNNING); recovery is *fail-and-surface* via the stale-running reconciler at `timeout + 60s` — a deliberate at-most-once execution model (no step-level resume), which is the right call for LLM steps. **But the reconciler is broken (F-1)**, so today this leg does not exist in production. Everything downstream of it — the 10s secondary-terminalization fallback comment, health's `STALE_RUNNING_RECONCILER_LAG` — assumes it works.
- Crash mid-webhook-delivery: lease TTL (300s) expires → another tick reclaims → HTTP re-sent with the same receiver idempotency key. Success/failure records CAS on the claim token; claim-lost paths roll back step-result writes (tested: test_flow_webhook_outbox_delivery.py:685, 823).

**Timeouts:** task-level timeout cancels the executor task, drains 10s, terminalizes as TASK_TIMEOUT; late completed-step writes after that are rejected by the active-run guard (integration-proven, test_flow_runtime_worker_contract.py:489). Step-level deadlines come from runtime policy with a hard ceiling; RAG timeouts degrade to diagnostics rather than failures (executor tests at 4042-4081).

**Retries:** there are no in-run step retries — attempts advance only through explicit rerun operations. Retry machinery exists only where it belongs: outbox delivery backoffs (`(60,300,900,3600)` audit / `(30,120,300,900)` webhook) with asserts tying array length to max attempts. Clean.

---

## Outbox / Webhook / Audit Delivery Review

Covered in findings F-3/F-12 and the lease review; summary judgments:

- **Audit outbox:** correct exactly-once *effect* (audit-log id = outbox id + `create_if_absent`), skip-locked claims, `ValueError` = permanent → immediate dead-letter, other exceptions → backoff then dead-letter. Delivery deliberately bypasses tenant audit feature flags with a documented rationale. Dead letters flip health to UNHEALTHY. Retention refuses to purge runs with undelivered audit rows — the outbox is treated as part of committed state end to end. Strong.
- **Webhook outbox:** at-least-once with receiver idempotency key; `_prepare_delivery_payload` re-validates run status, published-snapshot step, and attempt match before sending (permanent-failure classification via `ValueError`); dead-letter fails the run with step context. Two gaps: no health signals (F-3) and **globally serialized throughput** — one beat instance, one row at a time, ≤50 rows or 30s per tick, worst case one slow 30s receiver per tick. Acceptable at 4 concurrent runs/tenant; document the ceiling, revisit when webhook volume grows.
- **Terminal-state audit:** one outbox row per transition guaranteed by CAS + rollback-on-insert-failure (test_flow_terminalization_contract.py:242, 593). Noop outcomes (`already_terminal`, `lost_race`) still emit structured log events — good operator forensics.

## Retention / Purge / Artifact Safety Review

- Selection is terminal-only with `LEAST(flow, space, classification)` retention, a constant `MIN_RETENTION_DAYS` floor matching the partial index predicate, and **blockers** for undelivered audit and active reruns, with a `count_blocked_..._candidates` observability query (data_retention_service.py:623-646). 
- Purge order (capture file ids → deliveries → outbox → checkpoints → runs (cascade) → conditionally files) is correct, and file deletion checks ten reference tables including derived-child protection; the table list is guard-tested for completeness against `Files` FKs (test_flow_run_history_purge_repo.py:11). Template-asset purge refuses when published-version references cannot be determined — fail-closed. 
- Debug-evidence redaction is tombstoned with schema-versioned, shape-validated markers (flow_retention_tombstone.py), and read paths classify `retention_purged` distinctly from `corrupt` (flow_run_provenance.py:35-45). `_file_availability` surfaces `content_purged` instead of 404s (flow_run_repo.py:1146-1149). 
- This is the most mature slice of the runtime. No findings beyond keeping the guard test in CI.

## Observability / Operator Debugging Review

An operator debugging a stuck run has: persisted `status/error_json/started_at/finished_at/revision`, per-step results with error codes, per-attempt rows with `celery_task_id`, model/provider/tokens/finish_reason, and pre-dispatch `attempt_start` provenance (deadline, timeout, prompt/input sizes) — so even a crash *mid-LLM-call* leaves triage data (executor.py:1310-1353; tested at test_flow_executor_runtime.py:3900). Correlation: `trace_id` on the run, request-context logging fields, OTel spans with allowlisted attributes (PII boundary enforced with drift warnings), structured `flow_run.lifecycle` events with schema version. `/api/healthz/flows` covers run staleness, reconciler lag, review expiry, terminal-integrity anomalies, and audit outbox — with thresholds echoed in the response. Gaps: webhook signals (F-3); generic step failures collapse to `"Flow step N execution failed."` on the run while the real exception lives only in logs — acceptable for user-facing sanitization but the attempt row's `error_message` also carries only the public string (executor.py:1654-1668); consider persisting the sanitized exception class on the attempt for log-free triage. Minor: queue named `flows.execute` carrying six task types confuses `celery -Q` output.

## Runtime-Coupled Delete / Merge / Move List

| Action | Item | Evidence |
|---|---|---|
| Delete | `FlowRunLifecycleSource.DISPATCH_FAILURE` | enums.py:265, zero writers |
| Delete | `FlowStepAttemptStatus.RETRIED` + shrink OPEN set (+migration if constrained) | enums.py:312,332 |
| Delete | `FlowRunService.execution_backend` attribute | flow_run_service.py:199 |
| Delete | Executor legacy non-config constructor path | executor.py:494-513 |
| Move | `save_step_result` (+file-row replace) `FlowRepository` → `FlowRunRepository`; fix flow_tables.py:851 docstring | F-8 |
| Simplify | Beat wrappers: shared cancel-on-timeout helper | F-4 |
| Simplify | Cross-tenant recovery queries replacing per-tenant loops | F-5 |
| Do **not** delete | `run_outcome.py`, `step_attempt_runtime.py`, `claim_resolution.py` — pure decision modules that keep the executor's DB-free logic testable; they are depth, not pass-through |
| Do **not** delete | `stale_queued_redispatch.py` result union — 4 dataclasses for one function is ceremony-adjacent, but the API endpoint and beat consume outcomes differently (raise vs continue), which the union makes type-safe |

## What Current Tests Already Cover

- Single-winner CAS under real Postgres concurrency: run claim, step claim, attempt creation (test_flow_run_repository.py:1502-2272).
- Idempotency: attempt creation/finish, terminalization, run creation replay incl. fingerprint mismatch, principal isolation, API-key rotation (test_flow_run_repository.py:625-995; test_flow_run_service.py:700-1041).
- Terminalization contract: one outbox event per transition, lost-race noop, rejects completing with open rows, rollback when outbox insert fails, stale-running query excludes AWAITING_REVIEW (test_flow_terminalization_contract.py).
- Late-write fencing after terminalization and after task timeout; failure persistence visible to fresh sessions (test_flow_runtime_worker_contract.py:386-1174).
- Webhook delivery: claim, out-of-transaction send, run completion, dead-letter fails run, claim-lost rollbacks, attempt-mismatch rejection, reconciler suppression, header decryption (test_flow_webhook_outbox_delivery.py).
- Audit outbox delivery: end-to-end log creation, dedup, per-row dead-letter isolation, retry-then-dead-letter, DB constraints (test_flow_audit_outbox_delivery.py integration).
- Executor lifecycle breadth: duplicate-worker exit, cancel fencing mid-step, review-open races and invariants, rerun lineage conflicts, provenance-before-LLM (test_flow_executor_runtime.py).
- Renderer preflight for worker images (test_celery_preflight.py).

## Missing Red Tests

1. **Real-session stale-RUNNING reconcile** (the F-1 acceptance test) — behavior: crashed-worker run becomes FAILED and persists; layer: integration/testcontainers; would have failed today and is the regression fence for any future session-discipline change in tasks.py.
2. **`flows.execute` end-to-end duplicate delivery** through the real task entrypoint (not the executor unit): second delivery of the same kwargs while the run is RUNNING → skipped, exactly one attempt row. Pins the task-session wiring (autobegin) plus CAS together.
3. **Webhook lease-expiry reclaim:** claimed row with expired `claim_expires_at` is re-claimable and re-sent with the same idempotency key; current tests cover claim-lost CAS but not TTL-expiry reclaim (flow_run_webhook_delivery_repo.py:101-106 is untested).
4. **Beat-timeout coroutine cancellation** (after F-4): slow reconcile coroutine is cancelled, not orphaned.
5. **Health webhook flags** (after F-3): dead-lettered webhook row ⇒ UNHEALTHY.
6. **Terminalizer cancels checkpoints on FAILED** (after F-7).
7. **Mid-flow webhook guard** (after F-6): invalid published definition terminalizes precisely instead of stalling.
8. **Enum-mirror exhaustiveness** (F-9): every terminal `FlowRunStatus` maps to a `FlowRunRerunOperationStatus`.

## What Is Not Worth Fixing

- Per-tenant creation `FOR UPDATE` lock granularity — coarse but correct at 4-concurrent-runs/tenant scale; revisit only with evidence of create-endpoint contention.
- `now` captured once per webhook delivery loop — retry timestamps skew by seconds; harmless.
- The shared daemon event-loop-per-worker-process pattern in tasks.py — unusual but working and heavily exercised; replacing it (e.g., asyncio pool) is churn without a named failure mode. Fix F-4 within it instead.
- Queue name `flows.execute` for six task types — rename only if F-2's queue split happens anyway.
- 4096-char inline truncation constant in `_apply_output_cap` (executor.py:2154) — magic number, but behavior is tested and bounded.
- Webhook delivery throughput serialization — document the ceiling (F-12's paragraph); don't parallelize speculatively.

## Tomorrow Implementation Slices

1. **Slice 1 (P0, ~1h):** F-1 fix + integration red test. Smallest possible diff: two `session.begin()` wrappers + autobegin enable in tasks.py.
2. **Slice 2 (~1h):** F-4 shared cancel-on-timeout helper for beat wrappers + unit test (same file, natural pairing with slice 1 for a tier-3 batched review).
3. **Slice 3 (~2h):** F-3 webhook health flags + integration test.
4. **Slice 4 (~1h):** F-2 maintenance-queue routing + deployment consumer + routes assert.
5. **Slice 5 (~1h):** F-10 deletions + F-11 comment fix (tier-4 cleanup; self-review only).
6. **Slice 6 (~2h):** F-8 move `save_step_result` into `FlowRunRepository` + docstring fix.
7. **Slice 7 (~1h):** F-6 runtime guard + F-7 unconditional checkpoint sweep + tests.
8. **Later:** F-5 cross-tenant recovery queries; F-9 explicit enum map; F-12 outbox decision-rule doc.

## Claims Codex Must Verify

1. **F-1 failure mode:** with `async_sessionmaker(autobegin=False)` (database.py:53), does `session.execute(select(...))` outside `begin()` raise `InvalidRequestError`? Verify empirically by invoking `_reconcile_stale_running_runs_all_tenants` against the real test sessionmaker. Either outcome (raise, or silent rollback at close) confirms the finding; the log signature differs.
2. **F-1 blast radius:** confirm no *other* path terminalizes stale RUNNING runs (I found none: grep `terminalize_stale_running_run` has one caller).
3. **Deployment concurrency for F-2:** how many workers/processes consume `flows.execute` in compose/k8s? Severity scales inversely with pool size.
4. **Pool type & hard-limit semantics:** confirm the flow worker runs prefork so `task_time_limit` kills the child process (including the shared loop thread); a threads/solo pool changes the timeout backstop analysis.
5. **Dead-symbol greps (F-10):** re-confirm zero writers for `DISPATCH_FAILURE`, `RETRIED`, `self.execution_backend`, and zero production callers of the executor's non-config constructor path.
6. **Beat single-instance assumption:** confirm only one beat scheduler is deployed (duplicate beats would double-fire delivery ticks — the claims tolerate it, but throughput math changes).

## Challenge This Brief

- The brief asks for "locks/leases and terminalization" review as if the design were in doubt — it isn't; the design is strong and the actual production risk is one *wiring* bug plus deployment topology. Future runtime prompts should ask "which recovery paths are exercised against a real session end-to-end?" first; that question finds F-1 in ten minutes.
- The brief's separation from Fable 07 (evidence) is slightly artificial here: attempt provenance persistence *is* crash-recovery state (pre-LLM `attempt_start` rows). I reviewed its runtime role only, as instructed.
- "Do not preserve compatibility for pre-production behavior" — the only such artifacts found are the four dead symbols (F-10); there is no legacy dual-path problem in this runtime worth a bigger deletion campaign, so Fable 08 should not expect much here.

## Confidence

**High** on F-1 (mechanism triple-checked: sessionmaker config, absent begin/commit, mock-only tests, sibling tasks doing it correctly), F-3, F-8, F-10, F-11 (direct source evidence). **Medium-high** on F-2 and F-5 (mechanism certain, severity deployment-dependent), F-4 (orphaning certain; practical frequency depends on tenant count), F-6/F-7 (correctly guarded today; findings are about implicitness, not active bugs). All file:line citations were read directly this session; nothing is inferred from names alone. The single deliberate extrapolation — SQLAlchemy's exact `autobegin=False` exception behavior — is isolated in Claims #1 with an empirical verification path that does not affect the finding's validity.
