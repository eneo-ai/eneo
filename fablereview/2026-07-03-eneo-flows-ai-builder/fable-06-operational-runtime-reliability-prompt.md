# Fable 06 Prompt: Flow Runtime Operability, Idempotency, Crash Recovery, And Outbox Reliability

You are Claude Fable running a max-effort, source-backed production reliability review for Eneo Flows runtime.

Repository root: `/Users/ccimen/eneo/eneo-flows-clean`

## Mission

Review Eneo Flow runtime as a production execution system:

- run lifecycle;
- step execution lifecycle;
- Celery/task boundaries;
- idempotency;
- retries and duplicate starts;
- worker crash recovery;
- locks and terminalization;
- outbox/webhook/audit delivery;
- review checkpoints;
- rerun operations;
- retention/purge;
- observability/debuggability.

This must not repeat the current Fable sessions on Builder proposal repair, underlag/RAG contract semantics, JSONB schema trade-offs, or discovery dialog. Focus on production operations and reliability.

## Non-Negotiable Output Rules

- Return a complete Markdown review.
- Start with a five-line TL;DR.
- Use file:line citations for concrete claims.
- Include confidence for every material finding.
- Apply Ponytail: delete, merge, move, reuse, simplify.
- Do not edit source, tests, migrations, package files, config, or docs.
- Do not write files yourself. Your stdout will be saved to:
  `.codex/artifacts/fable-review-program-20260703/fable-06-operational-runtime-reliability-review.md`

## Read First

Read:

- `.codex/artifacts/fable-review-program-20260703/index.md`
- `docs/engineering/maintainability-standards.md`
- `docs/engineering/testing-standard.md`

Then inspect source yourself.

## Primary Source Scope

Inspect relevant runtime/application/infrastructure code. Start with:

- `backend/src/eneo/flows/application/flow_run_service.py`
- `backend/src/eneo/flows/application/flow_run_rerun_service.py`
- `backend/src/eneo/flows/runtime`
- `backend/src/eneo/flows/infrastructure/flow_run_repo.py`
- `backend/src/eneo/flows/infrastructure/flow_run_rerun_repo.py`
- `backend/src/eneo/flows/infrastructure/flow_run_history_purge_repo.py`
- `backend/src/eneo/flows/flow_run_outbound_delivery.py`
- `backend/src/eneo/flows/flow_run_audit_outbox.py`
- `backend/src/eneo/flows/flow_run_review_checkpoint*`
- `backend/src/eneo/flows/flow_run_step_result_file.py`
- `backend/src/eneo/flows/flow_run_provenance.py`
- `backend/src/eneo/database/tables/flow_tables.py`
- Celery/task registration files that call Flow runtime.
- relevant integration/unit tests for run lifecycle, worker/runtime, rerun, outbox, retention.

Use `rg` to find task names, retries, locks, status transitions, terminal states, idempotency keys, delivery attempts, dead-letter behavior, and crash recovery paths.

## Questions To Answer

1. Are run and step lifecycle states explicit, constrained, and hard to misuse?

2. Are Celery tasks idempotent and safe under duplicate delivery, retry, and worker crash?

3. Is runtime state persisted in the DB rather than worker memory/task args?

4. Are transaction boundaries clear around:
   - run creation;
   - step start;
   - step completion;
   - failure terminalization;
   - review checkpoint creation;
   - rerun operation creation;
   - artifact/evidence persistence;
   - outbox/audit delivery?

5. Are locks/leases/stale states recovered safely?

6. Do duplicate starts or concurrent reruns have clear behavior?

7. Are external side effects delivered through reliable outbox/dead-letter mechanics?

8. Are template-generated files, evidence bundles, RAG provenance, and artifacts retained/purged safely?

9. Can an operator debug failed/stuck/partially completed runs from persisted state and logs?

10. Are broad catches, retries, or fallback paths hiding bugs?

11. What should be deleted, merged, or simplified before production?

12. What is not worth fixing now?

## Required Sections

Return:

1. `TL;DR`
2. `Ratings`
   - runtime reliability;
   - idempotency;
   - crash recovery;
   - outbox/dead-letter reliability;
   - observability/debuggability;
   - data retention safety;
   - testability;
   - production readiness.
3. `Runtime Lifecycle Map`
4. `State Transition / Transaction Boundary Inventory`
5. `Ranked Findings`
   - severity, problem, why it matters, evidence, owner/fix, acceptance criteria, tests, risk/trade-off, confidence.
6. `Idempotency / Retry / Crash Recovery Review`
7. `Outbox / Webhook / Audit Delivery Review`
8. `Retention / Purge / Artifact Safety Review`
9. `Observability / Operator Debugging Review`
10. `Delete / Merge / Move List`
11. `What Current Tests Already Cover`
12. `Missing Red Tests`
13. `What Is Not Worth Fixing`
14. `From-Scratch Cleaner Runtime Design`
15. `Tomorrow Implementation Slices`
16. `Claims Codex Must Verify`
17. `Challenge This Brief`
18. `Confidence`

## Guardrails

- Do not propose a generic workflow engine rewrite.
- Do not propose new abstractions without naming the concrete failure mode they prevent.
- Keep recommendations reviewable and sliceable.
- Treat "passing tests" as insufficient if crash/retry behavior is unclear.
