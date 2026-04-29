# Implementation Bootstrap

## Handoff Brief

This document is the durable handoff for Flow / Flow AI Builder
implementation batches. It summarizes the load-bearing decisions from
Phase 7 readiness; the canonical batch input order lives in
`docs/refactor/execution/loop-protocol.md`.

### Load-bearing decisions and chosen designs

| Decision | Chosen design |
|---|---|
| Pre-production deletion | Delete never-shipped source-only false owners after behavior pins and `rg` proof. Persisted/public readers require behavior pin, count proof, and backfill/rewrite if rows exist. |
| Celery runtime | Flow / Flow AI Builder use Celery. ARQ is not an option for Flow runtime or AI Builder. |
| Pause/edit/resume | DB state machine plus thin Celery resume task. Worker persists checkpoint and exits; resume API dispatches a typed command with IDs only. |
| Terminalization | One idempotent terminalization command owns status transition, open attempts, step results, outbox/audit row, metrics, and no-op duplicate handling. |
| Flow audit ARQ dependency | Lifecycle audit for terminalization/review/rerun/resume moves to relational outbox and must not depend on ARQ; existing non-lifecycle Flow audit callers through `audit_service.log_async` need inventory and migration/default decision before their owning route/service is refactored. |
| Per-step file mapping | `step_inputs` is the only request shape. Top-level request `file_ids` is rejected/removed. |
| File mapping data model | Keep immutable normalized JSON snapshot for idempotency/evidence; add attempt-scoped `flow_run_step_input_files` and output `flow_run_step_result_files`. |
| Step rerun | Dedicated rerun endpoint/command plus `flow_run_rerun_operations`; invalidation is DAG-derived from the run's published definition snapshot. |
| Permissions | Typed `FlowApiAction` and `FlowPrincipal`; no raw Flow/AI Builder route reads of `request.state.api_key_scope_*`. |
| JSONB | Keep for versioned snapshots, heterogeneous LLM/user output, and provider metadata; add parser/version/corruption behavior. |
| Frontend types | Generated OpenAPI schemas become canonical after PRD-004 source fixes; manual Flow runtime blocks become generated aliases or UI-only models. |
| File splitting | Split by domain/lifecycle responsibility, not LOC. Delete compatibility before moving code. |

### Behavior pins required before destructive cleanup

| Pin | Test path |
|---|---|
| Flow run + worker + audit | `backend/tests/integration/flows/test_flow_runtime_worker_contract.py` |
| API start-run/poll/result | `backend/tests/integration/flows/test_flow_consumer_api_contract.py` |
| Idempotency golden vector | `frontend/packages/intric-js/src/endpoints/flows.test.js` plus backend API test |
| Current file handling | `backend/tests/integration/flows/test_flow_step_file_mapping_contract.py` |
| Terminalization modes | `backend/tests/integration/flows/test_flow_terminalization_contract.py` |
| Permission matrix | `backend/tests/unittests/flows/test_flow_permissions.py` and `backend/tests/integration/flows/test_flow_tenant_isolation_contract.py` |
| AI Builder create/plan/revise/apply | `backend/tests/integration/flows/test_ai_builder_session_api_regressions.py`, `test_ai_builder_apply_to_draft.py` |
| Evidence/artifact retrieval | `backend/tests/integration/flows/test_flow_evidence_api_contracts.py` |
| Webhook delivery lifecycle | `backend/tests/integration/flows/test_flow_webhook_delivery_contract.py` |
| Frontend critical routes/dialogs | `frontend/apps/web/tests/flows-runtime.spec.ts` or component tests |

### Kill list summary

- Delete Batch 0 Tier A source-only false owners after pins: Flow import shims and router callable identity exports.
- Defer the frontend redispatch alias unless Batch 0 adds a frontend behavior pin; otherwise keep it for Batch 10 cleanup.
- Defer the AI Builder barrel to Batch 6 after AI Builder imports move to their canonical modules.
- Rewrite/delete Tier B persisted/public readers only after proof: top-level request `file_ids`, `template_file_id`, old form field types, HTTP config converters, historical evidence fallbacks.
- Keep active LLM/provider repair only when typed and covered by prompt/contract tests.

### JSONB to relational decisions

- Relational: `flow_run_step_input_files`, `flow_run_step_result_files`, `flow_run_rerun_operations`, `flow_run_review_checkpoints`, Flow lifecycle audit/outbox.
- JSONB with parser/version: flow metadata form schema, step contracts/config, published definition snapshot, run input/output snapshots, step result envelopes, attempt provenance, AI Builder conversation/planning/plans/observations.
- Hybrid: run input/output and step result payloads keep evidence/idempotency summaries while relational rows own file, rerun, review, and audit facts.

### Known risks carried into implementation

| Risk | Where resolved |
|---|---|
| Persisted/public reader count proof may reveal rows needing backfill. | Batches 0, 4, 10. |
| Terminalization/outbox is prerequisite for review/rerun and is not implemented yet. | Batch 3. |
| Frontend test command is blocked by known `jsdom` baseline issue. | Batches 5 and 7. |

### Iteration order

Use `docs/refactor/implementation-order.md`. Do not pull step rerun or human review into earlier batches. Batch 0 starts with behavior pins and Tier A/Tier B deletion classification, then deletes only source-only false owners.

## Inputs The Implementation Thread Uses

Use the input order in `docs/refactor/execution/loop-protocol.md`.
For Batch 0, resolve "the PRD(s) for this batch" to:

1. `docs/refactor/prd/PRD-001-foundations.md`
2. `docs/refactor/prd/PRD-007-testing-strategy.md`
3. `docs/refactor/prd/PRD-008-dead-code-comments-and-readability.md`

This bootstrap summarizes the load-bearing decisions, behavior pins,
kill-list scope, JSONB/relational choices, known risks, and iteration
order. It does not replace the canonical input list in
`docs/refactor/execution/loop-protocol.md`. Do not pre-read every Phase
0-7 document in a fresh implementation context. Drill into a specific
Phase 0-7 doc only when a curated input cites it or ambiguity blocks
the current batch.

## Batch 0 Plan-Only Starter Prompt

Use this first if the implementation owner wants a human checkpoint before source/test edits. This thread may create or update only `docs/refactor/execution/batch-0-foundations/plan.md` and `docs/refactor/execution/batch-0-foundations/journal.md`; it must not modify source code, tests, migrations, package files, generated clients, branches, commits, pushes, or PRs.

```text
We are planning Batch 0 / Loop Iteration 1 for Eneo Flow + Flow AI Builder foundations.

Rules:
- Planning only.
- Do not create a branch.
- Do not commit.
- Do not push.
- Do not open a PR.
- Do not modify source code.
- Do not modify tests.
- Do not modify migrations.
- Do not modify package files.
- Do not modify generated clients.
- You may create or update only docs/refactor/execution/batch-0-foundations/plan.md and docs/refactor/execution/batch-0-foundations/journal.md.
- Do not modify unrelated product areas.
- Use the long-term clean architecture path, not compatibility workarounds.

Read these first, in order:
1. docs/refactor/phase4/refactor-plan.md
2. docs/refactor/implementation-order.md
3. docs/refactor/phase0/baseline.md
4. docs/refactor/phase7/implementation-readiness.md
5. docs/refactor/execution/implementation-bootstrap.md
6. docs/refactor/execution/loop-protocol.md
7. docs/refactor/execution/retrospective-checklist.md
8. docs/refactor/prd/PRD-001-foundations.md
9. docs/refactor/prd/PRD-007-testing-strategy.md
10. docs/refactor/prd/PRD-008-dead-code-comments-and-readability.md

Produce an implementation-ready Batch 0 plan. In the plan, identify:
- Tier A source-only false owners safe to delete after pins.
- Tier B persisted/public readers that must not be deleted yet.
- Behavior pins you will add or rewrite before deleting anything.
- Validation commands you will run.
- Exact source/test files likely to change in the implementation thread.
- Risks that should stop implementation until clarified.

Acceptance criteria for this planning thread:
- docs/refactor/execution/batch-0-foundations/plan.md exists or the response contains a ready-to-save plan with that exact structure.
- docs/refactor/execution/batch-0-foundations/journal.md exists or the response contains a ready-to-save journal entry for loop iteration 1.
- No source/test/migration/package/generated-client edits are made.
- The plan separates behavior pins from deletion work.
- The plan says what branch the implementation thread should use.
```

## Batch 0 Implementation Starter Prompt

Use this only after the Batch 0 plan is accepted. The agent may edit
source/tests for Batch 0, but the no-commit/no-PR rules remain
agent-session rules unless the user explicitly asks otherwise. Use the
same `feature/refactor-flows-flowai` branch for every implementation
batch.

Recommended precondition before opening this thread:

- The readiness and execution docs are committed as a docs-only commit or otherwise safely landed on the chosen base.
- The working tree is clean except for intentional Batch 0 work.
- Branch `feature/refactor-flows-flowai` exists or this prompt
  explicitly authorizes the agent to create it before `/plan`.

```text
We are implementing Batch 0 / Loop Iteration 1 for Eneo Flow + Flow AI Builder foundations.

Before `/plan`, create or switch to branch `feature/refactor-flows-flowai` if it does not already exist or is not already checked out. This is the only branch operation authorized in this session. After branch setup, do not create, switch, merge, delete, or push branches unless explicitly asked.

Follow docs/refactor/execution/loop-protocol.md exactly. Do not skip the retrospective or Claude review steps; use the protocol's stop conditions before declaring the batch done.

Rules:
- The user explicitly authorizes the pre-loop branch setup named above.
- After the pre-loop branch setup, the agent must not create branches unless explicitly asked.
- The agent must not commit unless explicitly asked.
- The agent must not push.
- The agent must not open a PR.
- Use this one branch for all Flow / Flow AI Builder refactor batches; do not create one branch per batch.
- Do not modify unrelated product areas.
- Keep source/test changes limited to Batch 0 foundations.
- Use the long-term clean architecture path, not compatibility workarounds.

Read these first, in order:
1. docs/refactor/phase4/refactor-plan.md
2. docs/refactor/implementation-order.md
3. docs/refactor/phase0/baseline.md
4. docs/refactor/phase7/implementation-readiness.md
5. docs/refactor/execution/implementation-bootstrap.md
6. docs/refactor/execution/loop-protocol.md
7. docs/refactor/execution/retrospective-checklist.md
8. docs/refactor/execution/batch-0-foundations/journal.md if it exists
9. docs/refactor/execution/batch-0-foundations/plan.md if it exists
10. docs/refactor/prd/PRD-001-foundations.md
11. docs/refactor/prd/PRD-007-testing-strategy.md
12. docs/refactor/prd/PRD-008-dead-code-comments-and-readability.md

/plan first. In the implementation plan, confirm:
- Tier A source-only false owners safe to delete after pins.
- Tier B persisted/public readers that must not be deleted yet.
- Behavior pins you will add or rewrite before deleting anything.
- Validation commands you will run.

Batch 0 acceptance criteria:
- Route/OpenAPI pins cover current Flow endpoint registration and generated-client-sensitive schema.
- Startup/import tests assert canonical imports and app behavior, not shim identity.
- Tier A deletion candidates have canonical replacements and zero-import proof.
- Router callable identity tests are replaced by route/OpenAPI behavior tests.
- Tier B items remain documented, not deleted: top-level request file_ids, template_file_id, old form field types, HTTP config converters, historical evidence keys.
- No source-only shim is restored as compatibility unless a real external consumer is proven.

Behavior pins required before destructive work in this iteration:
- backend/tests/unit/test_flow_openapi_contract.py
- backend/tests/integration/flows/test_flow_runtime_worker_contract.py, or an explicit fixture-gap note if blocked
- canonical import/startup smoke replacing shim identity assertions
- route registration/operation ID tests replacing router callable identity assertions

After changes, run the targeted backend validation commands named in implementation-order.md. Prefer the Docker validation mode documented in implementation-order.md. Report any baseline failure separately from product regressions.
```
