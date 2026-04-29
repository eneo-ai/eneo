# Phase 7 Final Claude Green-Light Review

I've reviewed all eight Phase 7 docs (`README`, `implementation-readiness`, `implementation-bootstrap`, `data-model-scalability-stress-test`, `dead-tests-cleanup`, `comment-cleanup`, `edge-cases-and-leakage`, `do-not-split`, `disagreements`, `claude-reconciliation`, all seven Claude packets), all ten PRDs, `implementation-order.md`, `architecture-decision-backlog.md`, and `open-questions.md`, and grep-verified two of the load-bearing claims against source.

## Summary

**GREEN_LIGHT: YES** (carry the named risks).

The plan is implementation-ready. Tier A vs Tier B deletion is gated, Celery is the chosen runtime with a concrete pause/edit/resume design, JSONB vs relational decisions are field-level with parser/version/corruption requirements, behavior pins have test paths, terminalization-as-precondition for review/rerun is enforced by batch ordering, and the DAG-source-of-truth question is closed (published `FlowVersions.definition_json`). Claude's load-bearing attacks are reconciled with traceable doc edits. No load-bearing decision is missing, contradictory, or unsafe to hand to an implementation agent — but two doc fixes would prevent foreseeable Batch 3 churn.

## Alternatives

The brief asked for blocking-vs-non-blocking and concrete fixes, mapped here:

**Blocking issues:** None. I cannot find a single load-bearing decision that is missing, contradictory, or unsafe.

**Non-blocking risks** (carry into implementation):

- **Implicit ARQ touchpoint in Flow runtime via `audit_service.log_async`.** The Phase 7 ARQ inventory (`prd/PRD-003-runtime-reliability-and-feature-gaps.md:343-353`, `phase7/implementation-readiness.md:75`) is grep-only and concludes the "only scoped ARQ hit is `flow_repo.py:503`, a stale docstring." Verified: `backend/src/intric/audit/application/audit_service.py:23, :234-324` shows `log_async` enqueues every audit event to ARQ via `job_manager.enqueue("log_audit_event", ...)`. Every Flow/AI Builder route that audits today goes through this path. The brief says "ARQ must not be part of Flow runtime or AI Builder." PRD-003+PRD-009 implicitly handle this by requiring a DB outbox for terminalization, but they do not say whether existing non-lifecycle Flow audit (flow create/update, evidence access, AI Builder turns) keeps using `log_async→ARQ`, migrates to the new outbox, or stays as-is until a separate cleanup. Codex will hit this in Batch 3.
- **`waiting_for_review` concurrency-limiter and TTL defaults are unpinned** (Claude packet 4 flagged both). PRD-003 §"Status Predicate Sweep" mentions both ("concurrency limiter so waiting runs do not occupy worker slots", "separate paused-run cap/TTL if product wants one") but does not commit a default. The implementation thread will need a value before adding the migration.
- **`scope_enforcement_enabled` flag fate is undecided.** `ai_builder_router.py:183, :199` (cited by Claude packet 5) carries a soft-disable used today; PRD-002 typed-policy migration does not state keep/rename/delete. Risk: silent behavior change in the policy refactor.
- **List endpoint denial-vs-filter contract.** Claude packet 5 noted `list_sessions` silently filters unauthorized rows rather than denying. PRD-002/004 do not pin a `list_filter` vs `assert` policy mode. Becomes audit-noise the moment list endpoints emit denial events.
- **`open-questions.md` ↔ `architecture-decision-backlog.md` mismatch on legacy permission mapping.** ADR backlog has a default ("Minimal explicit mapping; no pause/resume/review grant"); open-questions still lists it as "Owner Needed: Backend auth/product." Pick one.
- **`FlowRunDialog.svelte` PRD-006 dependency not in Batch 0 frontend pin list.** `phase7/dead-tests-cleanup.md` and `do-not-split.md` both target this file, but the bootstrap behavior pins for Batch 0 only name `flows-runtime.spec.ts`. Likely fine — Batch 5/7 ownership is correct — but worth one cross-check sentence so the FE state owner refactor doesn't begin before its pin lands.

**Concrete doc fixes (would take ~10 lines of doc edits each):**

1. In `prd/PRD-003-runtime-reliability-and-feature-gaps.md` §"ARQ Inventory And Celery Standard" and `phase7/implementation-readiness.md` §"Celery runtime readiness", add one sentence acknowledging `audit_service.log_async` as the indirect Flow audit path, and state the chosen scope: e.g. "Flow lifecycle audit (terminal/review/rerun) writes to a relational outbox in the lifecycle transaction; non-lifecycle Flow audit (create/update/evidence-view/AI Builder turn) continues via existing `audit_service.log_async` until a separate audit-platform PRD." This closes the brief's "ARQ must not be part of Flow runtime or AI Builder" rule unambiguously.
2. In `prd/PRD-003-...md` §"Status Predicate Sweep For `waiting_for_review`", commit defaults: (a) exclude `waiting_for_review` from `count_active_runs`/concurrency limiter; (b) no auto-cancel TTL by default — checkpoint reconciliation only handles orphan repair. ADR can change this later.
3. In `prd/PRD-002-data-model-and-permissions.md` §"Permission Model" or `prd/PRD-004-...md` §"API Maintainer Playbook Additions", state the `scope_enforcement_enabled` decision (likely: delete; was a test-only escape hatch — confirm before deleting) and the list-endpoint contract (deny-vs-filter mode is per-route and declared in the policy call site).
4. Reconcile `open-questions.md` row "Should legacy FLOWS/FLOWS_MANAGE map to granular permissions?" with the ADR backlog default — close it or rephrase as "what specific action set does FLOWS_MANAGE expand to?"
5. Add a one-line note in `phase7/implementation-readiness.md` "Behavior pins" that the FlowRunDialog journey pin must land before any FE state-owner extraction in Batch 7, since it currently appears only in `dead-tests-cleanup.md` and `do-not-split.md`.

**Speculative concerns to ignore:**

- Sharding / Kafka / generic workflow engine — already explicitly rejected in `data-model-scalability-stress-test.md` §"Non-Goals."
- Snapshot-only indexed JSONB instead of relational file-mapping rows (Claude packet 3 alternative 1) — the rerun lineage and "files referenced by run X / runs referencing file Y" use cases justify the table; the ADR-bypass concern is satisfied by Phase 7 explicitly *being* the architecture decision.
- A separate `flow_run_lifecycle_events` projection table (Claude packet 6) — already declined; status + attempts + outbox is sufficient.
- Auto-extracting `BuilderSessions.conversation` to a relational table now — Phase 7 stress test correctly defers; documented threshold is enough.
- Re-validating assistant snapshots on resume (Claude packet 4) — runs are version-pinned, this is a real but distinct hardening item; not a Phase 7 blocker.
- Re-opening `open-questions.md`'s evidence export (JSON-vs-attachment) for the gate — PRD-004 default is "JSON for SDK"; the open question is a Batch 1 decision, not a Batch 0 blocker.

## Risks or Blind Spots

The single most consequential blind spot is item #1 above (the indirect ARQ path through `audit_service.log_async`). Today every Flow audit row is enqueued to ARQ Redis. The Phase 7 doc's "no Flow ARQ hot path" finding rests on a string-grep, not a call-graph trace. The PRDs *do* require a DB outbox for terminalization — that decision is correct and unambiguous — but the docs do not say whether the new outbox replaces `log_async` for Flow lifecycle audit only, or for all Flow audit, or coexists indefinitely. The implementation thread will hit this on day one of Batch 3 and will need a decision before writing a migration. Resolving it now is a 3-sentence doc edit; resolving it mid-Batch 3 means re-reviewing the migration shape.

Lesser blind spots: the `scope_enforcement_enabled` knob (small but real), the `waiting_for_review` concurrency-limiter default (a value, not a design), and the open-questions/ADR-backlog drift on legacy permission mapping. None of these is severe enough to block — but each is the kind of detail that, left unpinned, becomes a follow-up commit.

## Recommended Next Step

Apply the five concrete doc fixes above (~30 minutes of edits across PRD-002, PRD-003, PRD-009, `open-questions.md`, and `phase7/implementation-readiness.md`), then ship Batch 0 with the bootstrap iteration-1 prompt as written. Carry the named risks in the gate; do not delay implementation behind them.

If time forces a single fix, prioritize fix #1 (the `audit_service.log_async` ARQ scoping) — it is the only one with a non-trivial chance of blocking a Batch 3 commit.

## Confidence

**High** on:
- The structural completeness of Phase 7 (Tier A/B, JSONB-with-parser-version, lifecycle owners, behavior-pin paths, batch ordering) — I cross-checked Phase 7 docs ↔ PRD acceptance criteria ↔ implementation-order.md ↔ architecture-decision-backlog.md.
- The `audit_service.log_async`→ARQ finding (grep-verified at `audit/application/audit_service.py:23, :234, :320` — and matching Claude packet 4's reading verbatim).
- That the chosen designs (Celery + DB state machine + thin resume task; per-attempt file mapping rows + JSONB snapshot; one terminalization command with `did_transition` boolean) are buildable as specified.

**Medium** on the magnitude of the `waiting_for_review` concurrency/TTL gap — depends on product input, not engineering.

**Lower** on whether the `scope_enforcement_enabled` flag has any prod path I missed; I did not trace its callers and am relying on Claude packet 5's read.

Artifact saved to `/Users/ccimen/eneo/eneo/.codex/artifacts/ask-claude-phase7-final-green-light-20260428T203700Z.md`
