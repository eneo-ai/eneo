# Fable 06 v2 Prompt: Flow Runtime Reliability, Operability, And Runtime Ownership

You are Claude Fable running a max-effort, source-backed production reliability and maintainability review for Eneo Flows runtime.

Repository root: `/Users/ccimen/eneo/eneo-flows-clean`

Save-path expectation: stdout will be saved to:

`fablereview/2026-07-03-eneo-flows-ai-builder/fable-06-operational-runtime-reliability-maintainability-review.md`

## Mission

Review Eneo Flow runtime as a production execution system and as code a senior engineer must maintain for years.

Focus on:

- run lifecycle;
- step execution lifecycle;
- Celery/task boundaries;
- idempotency;
- retries and duplicate starts;
- worker crash recovery;
- stale queued/running recovery;
- locks/leases and terminalization;
- audit/webhook/outbox/dead-letter delivery;
- review checkpoints;
- rerun operations;
- retention/purge;
- observability/operator debugging;
- canonical ownership boundaries between runtime tasks, services, repositories, policies, terminalizers, and evidence/artifact persistence;
- what runtime-coupled complexity can be deleted, merged, moved, or simplified before production.

This must not repeat completed Fable reviews on:

- Builder proposal repair and model self-correction;
- Builder compiler/topology/underlag/RAG semantic contracts except where runtime reliability depends on them;
- Builder planning-state/JSONB trade-offs except where runtime persistence depends on them;
- Builder discovery, attachments, dialog cadence, and user-question behavior.

## Non-Negotiable Output Rules

- Return a complete Markdown review.
- Start with a five-line TL;DR.
- Use file:line citations for concrete claims.
- Include confidence for every material finding.
- Apply Ponytail: delete, merge, move, reuse, simplify before adding.
- Do not edit source, tests, migrations, package files, config, or docs.
- Do not write files yourself.
- Treat Fable as a reviewer, not an implementer.
- If output length becomes a problem, prioritize `Ranked Findings`, `Idempotency / Retry / Crash Recovery Review`, `State / Attempt / Claim / Lease Review`, and `Missing Red Tests` before lower-value narrative sections.

## Read First

Read:

- `fablereview/2026-07-03-eneo-flows-ai-builder/index.md`
- `fablereview/2026-07-03-eneo-flows-ai-builder/fable-retry-priority.md`
- `docs/engineering/maintainability-standards.md`
- `docs/engineering/testing-standard.md`

Then inspect source yourself.

## Primary Source Scope

Start with:

- `backend/src/eneo/flows/application/flow_run_service.py`
- `backend/src/eneo/flows/application/flow_run_rerun_service.py`
- `backend/src/eneo/flows/application/flow_dispatch.py`
- `backend/src/eneo/flows/application/flow_run_terminalization.py`
- `backend/src/eneo/flows/application/stale_queued_redispatch.py`
- `backend/src/eneo/flows/application/flow_run_recovery_policy.py`
- `backend/src/eneo/flows/application/flow_run_audit_outbox_delivery.py`
- `backend/src/eneo/flows/application/flow_run_audit_outbox_policy.py`
- `backend/src/eneo/flows/application/flow_run_lifecycle_events.py`
- `backend/src/eneo/flows/application/flow_run_review_checkpoint_service.py`
- `backend/src/eneo/flows/application/flow_webhook_delivery_policy.py`
- `backend/src/eneo/flows/execution_backend.py`
- `backend/src/eneo/flows/runtime/tasks.py`
- `backend/src/eneo/flows/runtime/celery_app.py`
- `backend/src/eneo/flows/runtime/celery_execution_backend.py`
- `backend/src/eneo/flows/runtime/claim_resolution.py`
- `backend/src/eneo/flows/runtime/executor.py`
- `backend/src/eneo/flows/runtime/flow_run_actor.py`
- `backend/src/eneo/flows/runtime/flow_runtime_health.py`
- `backend/src/eneo/flows/runtime/flow_runtime_trace.py`
- `backend/src/eneo/flows/runtime/flow_webhook_delivery.py`
- `backend/src/eneo/flows/runtime/run_outcome.py`
- `backend/src/eneo/flows/runtime/step_attempt_runtime.py`
- `backend/src/eneo/flows/infrastructure/flow_run_repo.py`
- `backend/src/eneo/flows/infrastructure/flow_run_rerun_repo.py`
- `backend/src/eneo/flows/infrastructure/flow_run_audit_outbox_repo.py`
- `backend/src/eneo/flows/infrastructure/flow_run_review_checkpoint_repo.py`
- `backend/src/eneo/flows/infrastructure/flow_run_webhook_delivery_repo.py`
- `backend/src/eneo/flows/infrastructure/flow_run_history_purge_repo.py`
- `backend/src/eneo/flows/flow_run_step_result_file.py`
- `backend/src/eneo/flows/flow_run_provenance.py`
- `backend/src/eneo/database/tables/flow_tables.py`

Inspect tests:

- `backend/tests/unittests/flows/test_flow_run_service.py`
- `backend/tests/unittests/flows/test_flow_executor_runtime.py`
- `backend/tests/unittests/flows/test_celery_runtime.py`
- `backend/tests/unittests/flows/test_celery_preflight.py`
- `backend/tests/unittests/flows/test_stale_queued_redispatch.py`
- `backend/tests/unittests/flows/test_flow_run_history_purge_repo.py`
- `backend/tests/unittests/flows/test_flow_audit_outbox_delivery.py`
- `backend/tests/integration/flows/test_flow_runtime_worker_contract.py`
- `backend/tests/integration/flows/test_flow_terminalization_contract.py`
- `backend/tests/integration/flows/test_flow_audit_outbox_delivery.py`
- `backend/tests/integration/flows/test_flow_webhook_outbox_delivery.py`
- `backend/tests/integration/flows/test_flow_runtime_health.py`
- relevant migration tests for runtime state, attempt lineage, outbox, retention, and review checkpoints.

Use `rg` to find:

- task names and Celery entrypoints;
- retry settings;
- terminal states;
- status transitions;
- idempotency keys;
- `for update`, locks, leases, `skip locked`;
- stale queued/running recovery;
- duplicate start handling;
- outbox claim/delivery/dead-letter;
- webhook attempts;
- audit outbox;
- broad `except Exception`;
- fallback/repair/best-effort paths;
- retention and purge selectors;
- health endpoint signals.

## Questions To Answer

1. Are run and step lifecycle states explicit, constrained, and hard to misuse?

2. Are Celery tasks idempotent and safe under duplicate delivery, retry, and worker crash?

3. Is runtime state persisted in the database rather than worker memory/task args?

4. Are transaction boundaries clear around:
   - run creation;
   - dispatch;
   - step start;
   - step completion;
   - failure terminalization;
   - review checkpoint creation;
   - rerun operation creation;
   - artifact/evidence persistence;
   - audit outbox delivery;
   - webhook outbox delivery;
   - retention/purge.

5. Are locks, leases, stale states, and duplicate starts recovered safely?

6. Do concurrent reruns/reviews/resumes have clear behavior?

7. Are external side effects delivered through reliable outbox/dead-letter mechanics?

8. Can an operator debug failed/stuck/partially completed runs from persisted state, logs, health endpoints, and evidence?

9. Are broad catches, retries, fallbacks, or "best effort" paths hiding bugs?

10. What is the canonical owner for:
    - run lifecycle state;
    - step lifecycle state;
    - dispatch;
    - terminalization;
    - retry/crash recovery;
    - outbox delivery;
    - webhook delivery;
    - audit events;
    - retention/purge;
    - runtime health/debuggability.

11. Which modules are shallow pass-through seams or duplicate owners within runtime reliability?

12. Which runtime interfaces/protocols/services/repos/policies earn their existence, and which should be concrete, merged, or deleted?

13. Which tests protect real behavior, and which tests pin implementation wiring or legacy behavior we should delete?

14. What is not worth fixing now?

## Required Sections

Return:

1. `TL;DR`
2. `Ratings`
   - runtime reliability;
   - idempotency;
   - crash recovery;
   - outbox/dead-letter reliability;
   - observability/debuggability;
   - maintainability ownership;
   - data retention safety;
   - testability;
   - production readiness.
3. `Runtime Lifecycle Map`
4. `State Transition / Transaction Boundary Inventory`
5. `Runtime Owner Map`
6. `State / Attempt / Claim / Lease Review`
7. `Change-Path Analysis`
   - add new run status;
   - add new step status;
   - add new retry policy;
   - add new outbox delivery type;
   - add new retention rule;
   - add new operator health signal.
8. `Ranked Findings`
    - severity, problem, why it matters, evidence, canonical owner/fix, acceptance criteria, tests, risk/trade-off, confidence.
9. `Idempotency / Retry / Crash Recovery Review`
10. `Outbox / Webhook / Audit Delivery Review`
11. `Retention / Purge / Artifact Safety Review`
12. `Observability / Operator Debugging Review`
13. `Runtime-Coupled Delete / Merge / Move List`
14. `What Current Tests Already Cover`
15. `Missing Red Tests`
16. `What Is Not Worth Fixing`
17. `Tomorrow Implementation Slices`
18. `Claims Codex Must Verify`
19. `Challenge This Brief`
20. `Confidence`

## Guardrails

- Do not propose a generic workflow engine rewrite.
- Do not propose new abstractions without naming the concrete failure mode they prevent.
- Do not preserve compatibility for pre-production Flow runtime behavior without persisted-data evidence, an owner, and a deletion trigger.
- Do not recommend interfaces solely for tests.
- Prefer one canonical owner per lifecycle concept.
- Keep recommendations reviewable and sliceable.
- Treat passing tests as insufficient if crash/retry behavior is unclear.
- Treat runtime-coupled deletion/simplification as a first-class finding, but do not turn this into the broad dead-code audit reserved for Fable 08.
