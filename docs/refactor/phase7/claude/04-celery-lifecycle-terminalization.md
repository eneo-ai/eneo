## Summary

The **DB-state-machine + thin Celery resume task** decision is the right call and matches the proposal in `docs/refactor/prd/PRD-003-runtime-reliability-and-feature-gaps.md:55-76, 244-301`. The codebase is already standardized on Celery with the right knobs (`task_acks_late=True`, `task_reject_on_worker_lost=True`, `worker_prefetch_multiplier=1` in `backend/src/intric/worker/celery/app.py:28-30`), and the `mark_running_if_claimable` + `update_status(... from_statuses=...)` CAS primitives at `flow_run_repo.py:293-343, 420-431` are the natural seats for an idempotent terminalization command. ARQ would be a regression. However, the proposal as written has three concrete blockers that need to be made explicit before Codex can build:

1. **There is no DB outbox today.** `audit_service.log_async` at `audit_service.py:319-324` enqueues to **ARQ Redis** via `job_manager.enqueue("log_audit_event", …)`. PRD-003's "audit outbox insert in same transaction as terminal state" rule cannot be implemented against a Redis enqueue. PRD-009 §"Reliability Requirements" defers to PRD-003 for this policy, so the outbox table is a precondition, not a follow-up.
2. **Terminalization is *not* one command today.** `_handle_*_failure` paths in `executor.py:837-936, 1047-1068` interleave `_rollback`, `finish_attempt`, `save_step_result`, `update_status`, `_audit_run_terminal_state`, and `_commit` per failure shape. The proposal collapses them into one transaction, but the executor's commit-as-you-go style (commits at lines 346, 484, 544, 654, 730, 802, 973, 1044) means a half-applied terminalization can leave `flow_step_attempts.status='started'` paired with `flow_runs.status='failed'`. PRD-003 already names this in §"Current State".
3. **The status enum check constraint and reconciler don't know about pause.** `flow_tables.py:397-400` constrains `flow_runs.status IN ('queued','running','completed','failed','cancelled')`. Adding `waiting_for_review` requires a migration *and* updating every status-aware predicate: `_ACTIVE_STATUSES` (`flow_run_repo.py:40`), `_TERMINAL_STATUSES` in both `executor.py:239` and `flow_run_service.py:88`, the stale-running reconciler predicate (`flow_run_repo.py:235`), the implicit `from_statuses` defaulting in `update_status` (`flow_run_repo.py:319-324`), and `count_active_runs` (`flow_run_repo.py:155`). The reconciler at `tasks.py:322-358` fails any RUNNING run over `task_timeout+60s`; if the checkpoint commit is delayed, this races and flips a legitimately-pausing run to FAILED.

## Alternatives

| Alternative | Verdict | Why |
|---|---|---|
| **DB state machine + thin resume task** (proposal) | Strongest | Aligned with existing CAS primitives. PRD-003 already specifies the checkpoint schema and stale-edit table. Worker never blocks. |
| **Terminate task + dispatch fresh task, no checkpoint row** | Reject | Loses revision counter, awaiting/resumed/cancelled distinct states, and the `flow_review_stale_revision` 409 path PRD-003 §"Stale edit semantics" depends on. |
| **Celery chain/chord with human gate** | Reject | Worker starvation; PRD-003 §"Alternatives" already rejected this. Chains/chords can't model an indefinite human wait. |
| **Periodic reconciliation as primary** | Reject as primary, **keep as safety net** | Beat-interval latency on resume is a UX regression. But the reconciler should also handle `waiting_for_review` runs whose `updated_at` exceeds a TTL — a TTL hole exists in the proposal as written. |

## Risks or Blind Spots

**Duplicate delivery (acks_late + visibility_timeout):**
- With `task_acks_late=True` (`worker/celery/app.py:28`), if the worker commits the checkpoint then crashes before ack, the broker redelivers. The redelivered task must short-circuit. Today `_TERMINAL_STATUSES` at `executor.py:239` is `{COMPLETED, FAILED, CANCELLED}` — `waiting_for_review` would slip past, re-execute the gate step, and create a second checkpoint row or a duplicate terminal audit event. **Fix:** add `waiting_for_review` to the executor's bail set *and* make checkpoint inserts CAS via `ON CONFLICT DO NOTHING` keyed on `(flow_run_id, step_id, attempt_no)`.
- The relationship `visibility_timeout > task_time_limit + grace` is not asserted at worker boot. `celery_app.py:34-35` sets `task_time_limit = soft + 60`; `visibility_timeout` comes from a separate setting in `worker/celery/app.py:32, 37`. If misconfigured, a long step gets re-delivered to a second worker mid-execution and both race the run-level CAS. The CAS prevents corruption but burns capacity. Worth a runtime invariant check.

**Terminalization races and duplicate audit (live bug today):**
- `_mark_run_failed` at `executor.py:1047-1068` calls `_audit_run_terminal_state` whenever `updated_run.status == FAILED` after the update. The CAS in `update_status` returns the *current* row whether or not it transitioned (see `flow_run_repo.py:333-343` — falls back to a SELECT when `from_statuses` mismatch). So a duplicate terminalization on an already-failed run still re-fires the FAIL audit event. The proposal's "idempotent terminalization" must return *whether the transition actually happened* and gate audit/metrics on that boolean. Today this is a latent duplicate-audit bug, not a hypothetical.

**Stale-running reconciler doesn't close attempt rows:**
- `_reconcile_stale_running_runs_all_tenants` at `tasks.py:322-358` calls `mark_pending_steps_cancelled` + `fail_stale_running_run` but never touches `flow_step_attempts`. Open `STARTED`/`RETRIED` attempts persist forever. PRD-003 §"Reliability Requirements" calls this out (`Terminalization closes open attempts`). The same hole exists for `waiting_for_review` if the worker crashes after the run flips status but before the gate step's attempt is closed. The terminalization command (and the resume task on entry) must close the dangling attempt for the gate step explicitly.

**Stale revisions and resume payload on the wire:**
- The proposal says "fresh Celery resume command with typed IDs only" — keep that strictly. Pass `(run_id, checkpoint_id, expected_revision)`, **not** the edited payload. The resume task must re-read the checkpoint row in its own transaction and verify revision matches what the API saw at acknowledgement time. Otherwise, two queued resume tasks based on different revisions can both pass their pre-dispatch CAS (because the API's CAS happens at request time, not dispatch time).
- **Concurrent resume + cancel** during `waiting_for_review`: both fire. CAS on the checkpoint state column (`awaiting_review` → `resumed` vs `awaiting_review` → `cancelled`) is the right primitive. PRD-003 §"Stale edit semantics" already names this — make sure cancel during waiting also closes the checkpoint, not just the run, and emits its own audit event.

**Frontend paused state — checkpoint metadata isn't on the run resource:**
- The current run resource carries `status`, `output_payload_json`, `error_message` but no checkpoint surface. UI showing "Paused for review" needs (a) checkpoint id, (b) reviewer assignment if any, (c) revision, (d) TTL. Either inline the active checkpoint into the run GET response or add `GET /flow_runs/{id}/review_checkpoint`. PRD-003's Frontend Requirements §"UI controls render only when generated lifecycle state allows the action" implies the OpenAPI surface must carry this, otherwise the client can't gate buttons.

**Concurrency limiter semantics on `waiting_for_review`:**
- `count_active_runs` at `flow_run_repo.py:155-162` includes QUEUED + RUNNING. Adding `waiting_for_review` here would block other runs from starting while a human reviews — wrong (humans can take days). Excluding it means a flow could have arbitrarily many paused runs. Decide and document: probably exclude from concurrency, but cap with a separate per-tenant `max_paused_runs` to prevent unbounded checkpoint growth.

**TTL on checkpoints is not in the proposal:**
- A run paused for weeks is an audit/UX/storage leak. Need a `flow_review_ttl_days` setting and a beat reconciler that auto-cancels expired checkpoints with a distinct audit action (so it isn't conflated with user cancellation). This is the place where periodic reconciliation legitimately earns its keep.

**Re-publish during pause:**
- Runs are version-pinned (`flow_runs.flow_version` FK to `flow_versions`, `flow_tables.py:407-411`), so re-entry uses the original definition. ✅ But the assistant-snapshot drift check at `executor.py:1224-1272` only runs at the start of `execute`, not on resume. If an assistant was edited between pause and resume, downstream steps could silently produce different outputs. Either re-validate snapshots on resume (consistent with create-time semantics) or document this as out-of-scope and add a runtime warning. PRD-003 §"Open Questions" doesn't cover this.

**Schema-version on checkpoint:**
- The PRD specifies `schema_version: 1` on the checkpoint payload (`PRD-003-runtime-reliability-and-feature-gaps.md:255`). Good. But the resume code path needs an explicit "refuse with `flow_review_schema_outdated`" branch when a long-pending checkpoint pre-dates a schema bump. Don't silently upgrade; that's an audit-trail integrity hazard.

## Recommended Next Step

Before Codex starts the implementation slice, get explicit decisions on these three:

1. **Outbox table.** Add `flow_audit_outbox` (or reuse a generic outbox) written in the same DB transaction as the terminal status flip. Specify: row shape, dispatcher (likely a beat task), retry policy, alert metric. Without this, "fail before terminal state change" cannot be implemented and PRD-009's contract is unenforceable. If the team prefers not to add a table, change PRD-003 §"Audit fail policy" to fail-open with a durable compensation record — and document the compliance trade-off.
2. **Status enum migration + predicate sweep.** One PR adds `waiting_for_review` to the `flow_runs` check constraint, and updates every status-aware predicate listed in the Summary §3 in the same diff. Land this before any executor change so the new state is reachable but the executor is the only producer of it. Tests must cover the reconciler skipping `waiting_for_review` and the concurrency limiter not counting it.
3. **Terminalization-as-one-command refactor *first*, lifecycle changes *second*.** Today's duplicate-audit bug at `executor.py:1047-1068` and the open-attempt leak in the stale-running reconciler are pre-existing reliability issues. Land a `terminalize_run(run_id, target_status, error, source) -> TerminalizationResult` command that (a) flips run status with `from_statuses` CAS, (b) closes open attempts for the offending step in the same transaction, (c) writes the outbox row, (d) returns `did_transition: bool` so callers gate metric/audit emission on real transitions. Once this is the only writer to terminal status, adding `waiting_for_review` and the resume task is mechanical.

After those three, the resume task is straightforward: typed IDs only, reads checkpoint inside the resume transaction, CAS run from `waiting_for_review` → `running` and checkpoint from `awaiting_review`/`edited` → `resumed` in the same transaction, then re-enters `executor.execute`. The executor already handles "resume from completed steps" via `claim_step_result` returning None for already-completed work and `state.append_completed` (`executor.py:485-528`); the only addition is teaching `mark_running_if_claimable` to also accept `from_status='waiting_for_review'`.

## Confidence

**High** on the lifecycle decision (Celery + DB state machine + thin resume task), the duplicate-audit and open-attempt bugs in the current code, and the missing-outbox blocker. **Medium** on the precise concurrency-limiter decision for `waiting_for_review` (depends on product input on max-paused-runs semantics) and on the schema-version refusal policy (depends on whether checkpoints are expected to live across deploys). **Low** on the right TTL value — that is product/compliance input, not engineering.


Artifact saved to /Users/ccimen/eneo/eneo/.codex/artifacts/ask-claude-phase7-packet-04-celery-lifecycle-20260428T201555Z.md
