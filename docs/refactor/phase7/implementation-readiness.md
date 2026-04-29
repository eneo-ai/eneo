# Phase 7 — Implementation Readiness

## TL;DR

Flow / Flow AI Builder is implementation-ready with three named risks.
Celery is the only chosen runtime; ARQ is not a Flow option.
Delete source-only false owners early, but migrate or prove persisted/public readers before removal.
Use relational owners for lifecycle, file-reference, rerun, review, and audit facts; keep JSONB only for versioned snapshots or heterogeneous blobs.
Implementation must start with behavior pins before destructive cleanup.

## Scope

This readiness gate covers Flow runtime, Flow AI Builder, frontend Flow runtime, frontend Flow AI Builder, tests touching those areas, and shared dependencies touched only because they directly affect Flow / Flow AI Builder data model, Celery runtime, API, permissions, audit/outbox, OpenAPI, or generated frontend types.

Out of scope: unrelated product areas, unrelated platform-wide refactors, unrelated migrations, unrelated tests, non-Flow ARQ platform work, and speculative distributed systems complexity.

Branch scope: this Flow / Flow AI Builder refactor is broader than any AI Builder-only hardening branch protocol. Before source/test implementation starts, confirm the branch lineage if a local project instruction requires staying on an existing branch. The recommended review shape is one long-running initiative branch, `feature/refactor-flows-flowai`, after the readiness and execution docs are landed as a docs-only commit.

Execution scope: Phase 7 is the one-time readiness gate. Durable per-batch loop mechanics, retrospectives, journals, validation logs, and Claude attack/reconciliation artifacts live under `docs/refactor/execution/` for all implementation batches.

## What changed in the plan

| Change | Reason | Updated docs |
|---|---|---|
| Added Tier A/Tier B deletion policy. | Claude showed that source-only shims and persisted/public readers need different gates. | PRD-001, PRD-008, `dead-tests-cleanup.md`. |
| Made dead test deletion explicit. | Tests that preserve code being intentionally deleted should not survive as hidden compatibility. | PRD-007, `dead-tests-cleanup.md`. |
| Chose Celery-only pause/edit/resume mechanics. | Workers must not wait for humans; runtime state belongs in DB. | PRD-003, PRD-009. |
| Promoted file mapping, output files, rerun operations, review checkpoints, and audit/outbox to relational owners. | These are lifecycle/audit/debug/idempotency facts, not arbitrary JSON. | PRD-002, PRD-003, `data-model-scalability-stress-test.md`. |
| Added behavior pins before destructive cleanup. | Contract changes and deletion need observable behavior coverage first. | PRD-007, `docs/refactor/execution/implementation-bootstrap.md`. |
| Made file split plan responsibility-based. | Large files should split only into deeper domain/lifecycle modules. | `do-not-split.md`. |
| Added Claude reconciliation and final disagreement tracking. | Claude is adversarial review, not source of truth. | `claude-reconciliation.md`, `disagreements.md`. |

## Pre-production deletion policy

The acceptable choices for Flow / Flow AI Builder are:

- keep because the behavior is genuinely needed
- delete now after the relevant behavior pin exists
- rewrite to the correct canonical model

There is no staged deprecation plan for never-shipped Flow / AI Builder compatibility. Deletion is still data-aware:

| Tier | Examples | Action |
|---|---|---|
| Tier A: source-only false owners | Flow import shims, router callable re-exports, frontend redispatch alias, AI Builder model barrel after imports move. | Delete in Iteration 1 after canonical imports/route pins and `rg` zero-import proof. |
| Tier B: persisted/public readers | Top-level request `file_ids`, `template_file_id`, old form field types, HTTP config converters, historical evidence keys. | Behavior pin, count-query proof, backfill/rewrite if rows exist, then delete/rewrite in the owning PRD batch. |
| Active boundary repair | AI Builder LLM proposal repair, strict planning state rejection, provider metadata preservation. | Keep only if typed, tested, and named as current boundary behavior. |

## Kill list readiness

| Candidate | Evidence | Ready action | Owner |
|---|---|---|---|
| Flow package import shims | `backend/src/intric/flows/flow.py:1`, `flow_run_repo.py:1`, similar root shims. | Delete after source/test imports move to canonical modules. | PRD-001/008, Batch 0. |
| Router callable re-exports | `flow_consumer_router.py` and `flow_run_router.py` re-export endpoint callables. | Replace identity tests with route/OpenAPI tests, then remove callable exports. | PRD-001/004/007, Batch 0-1. |
| Frontend redispatch alias | `frontend/apps/web/src/lib/features/flows/components/flowRunRedispatchFeedback.ts:7-8`. | Defer to Batch 10 cleanup unless Batch 0 adds a frontend behavior pin that covers the alias deletion. | PRD-008, Batch 10 by default. |
| Top-level run `file_ids` | `backend/src/intric/flows/api/flow_models.py:431-435`; `frontend/packages/intric-js/src/endpoints/flows.js:67-93`. | Rewrite request contract to `step_inputs`; reject legacy shape with named error. | PRD-003/004/006, Batch 4. |
| DOCX `template_file_id` fallback | Backend/frontend template config readers. | Count/backfill to canonical asset ID before deleting fallback. | PRD-002/008, Batch 4/10. |
| HTTP config converters | `backend/tests/unittests/flows/http_transport/test_normalizer.py:27-211` pins old shapes. | Keep as migration pins until row proof/backfill; delete converter branches after proof. | PRD-002/008, Batch 10. |
| AI Builder model barrel | `backend/src/intric/flows/ai_builder/ai_builder_models.py:3-5`. | Move source/tests to boundary-specific modules, then delete. | AI Builder split batch. |

## Dead test cleanup readiness

Deleting tests is acceptable when the implementation deletes the behavior being tested. It is not acceptable to delete tests that currently protect security, audit, idempotency, OpenAPI, runtime task schema, or live persisted readers without replacement behavior pins.

Full inventory: `docs/refactor/phase7/dead-tests-cleanup.md`.

## Comment cleanup readiness

Comment cleanup is executable, not advisory:

- keep `intent` and `constraint`
- delete or rewrite `restate`, `outdated`, and `slop`
- convert `todo` into a PRD/work item or delete it with the branch

Full inventory: `docs/refactor/phase7/comment-cleanup.md`.

## Celery runtime readiness

Celery is the chosen runtime for Flow / Flow AI Builder. Targeted Phase 7 search found no direct Flow / Flow AI Builder ARQ runtime hot path. The direct scoped code hit is a stale docstring at `backend/src/intric/flows/infrastructure/flow_repo.py:503`; unrelated audit/platform ARQ tests are outside this Flow runtime pass.

Claude's final review identified one indirect shared dependency touched because Flow uses it: `backend/src/intric/audit/application/audit_service.py:234-324` currently enqueues audit writes through ARQ Redis. The chosen default is that Flow lifecycle audit for terminalization, review, rerun, and resume writes to the relational outbox required by PRD-003/009. Existing non-lifecycle Flow audit callers must be inventoried and migrated or explicitly deferred in PRD-009 before their owning route/service is refactored; new Flow lifecycle audit must not depend on ARQ.

Pause/edit/resume uses option 4: DB state machine plus thin Celery resume task. At pause, the current task persists `waiting_for_review` and checkpoint/revision state, writes audit/outbox, returns, and releases the worker slot. Resume is an API command that compare-and-sets the checkpoint and dispatches `FlowRunResumeCommand` with IDs and metadata only.

## Data model and scalability readiness

The plan now uses relational modeling where the data is lifecycle-stateful, permissioned, audited, referenced, retry/idempotency relevant, human-review relevant, or needed for production debugging.

No sharding, Kafka, or generic workflow engine rewrite is recommended. The evidence supports indexes, constraints, typed state, idempotency keys, relational file/review/rerun/outbox owners, and generated schema parity.

Full stress test: `docs/refactor/phase7/data-model-scalability-stress-test.md`.

## JSONB vs relational decisions

| Decision | Summary |
|---|---|
| Keep JSONB with parser/version | Flow metadata form schema, step input/output contracts, heterogeneous step config, published definition snapshot, final output summary, step result payload snapshots, attempt provenance, AI Builder conversation/planning/plan/observation payloads. |
| Split relational core plus JSONB metadata | `flow_runs.input_payload_json`, `flow_step_results.output_payload_json`, runtime file/output artifact facts. |
| Convert to relational table | `flow_run_step_input_files`, `flow_run_step_result_files`, `flow_run_rerun_operations`, `flow_run_review_checkpoints`, Flow lifecycle audit/outbox. |
| Delete/rewrite old JSON shapes | Top-level request `file_ids`, old form field types, `template_file_id`, old HTTP config shapes after data proof/backfill. |

## Edge cases and leakage risks

High-risk leakage now has owners:

- raw AI Builder request-scope reads -> typed Flow policy and `FlowPrincipal`
- string permission actions -> `FlowApiAction`
- loose run-create payload -> typed request envelope and `step_inputs`
- primitive Celery payloads -> typed command payloads
- scattered terminalization -> one idempotent terminalization command
- manual frontend Flow types -> generated schema plus narrow UI aliases
- frontend evidence internals -> typed evidence projection

Full audit: `docs/refactor/phase7/edge-cases-and-leakage.md`.

## Behavior pins required before implementation

| Pin | Test path | Unlocks |
|---|---|---|
| Flow run + worker + audit | `backend/tests/integration/flows/test_flow_runtime_worker_contract.py` | Executor split and terminalization command. |
| API start-run/poll/result | `backend/tests/integration/flows/test_flow_consumer_api_contract.py` | Router rewrite, OpenAPI cleanup, generated client. |
| Idempotency golden vector | `frontend/packages/intric-js/src/endpoints/flows.test.js` plus backend API test | `file_ids` deletion and fingerprint versioning. |
| Current file handling | `backend/tests/integration/flows/test_flow_step_file_mapping_contract.py` | Relational file mapping and top-level `file_ids` deletion. |
| Terminalization modes | `backend/tests/integration/flows/test_flow_terminalization_contract.py` | Terminalization command, review, rerun. |
| Permission matrix | `backend/tests/unittests/flows/test_flow_permissions.py` plus API tenant-isolation contract | Typed Flow policy. |
| AI Builder create/plan/revise/apply | `backend/tests/integration/flows/test_ai_builder_session_api_regressions.py`, `test_ai_builder_apply_to_draft.py` | AI Builder router/service/planner split. |
| Evidence/artifact retrieval | `backend/tests/integration/flows/test_flow_evidence_api_contracts.py` | Evidence export split and output file table. |
| Webhook delivery lifecycle | `backend/tests/integration/flows/test_flow_webhook_delivery_contract.py` | Webhook pending/delivered/failed state and terminalization safety. |
| Frontend critical routes/dialogs | `frontend/apps/web/tests/flows-runtime.spec.ts` or component tests | PRD-006 state-owner refactor. |

The FlowRunDialog journey pin must exist before Batch 7 extracts frontend state owners from `FlowRunDialog.svelte`; Batch 0 does not need that frontend refactor pin unless it touches frontend run-launch state.

## Load-bearing decisions sent to Claude

| Packet | Decision |
|---|---|
| 1 | Pre-production deletion policy and kill-list approach. |
| 2 | Dead test cleanup approach. |
| 3 | Runtime input/output data model, per-step file mapping, deletion of top-level `file_ids`, rerun lifecycle. |
| 4 | Celery lifecycle, pause/edit/resume, terminalization, audit/outbox. |
| 5 | Typed Flow policy actions and enforcement point. |
| 6 | JSONB vs relational modeling decisions. |
| 7 | Behavior pins before destructive cleanup. |

Claude responses are stored verbatim in `docs/refactor/phase7/claude/`.

## Claude attacks accepted

| Attack | Resolution |
|---|---|
| Source-only false owners were conflated with persisted/public compatibility. | Added Tier A/Tier B deletion policy. |
| Startup/router tests contain live OpenAPI/security/audit/idempotency pins. | Dead-test plan now splits and rewrites before deletion. |
| Runtime file mapping should be attempt-scoped and output files need relational projection. | Added `flow_run_step_input_files` and `flow_run_step_result_files`. |
| Step rerun needs its own operation table and DAG source truth. | Added `flow_run_rerun_operations` and published-definition DAG default. |
| DB outbox does not currently exist and terminalization is scattered. | Made terminalization/outbox preconditions before review/rerun. |
| `waiting_for_review` needs a full status predicate sweep. | Added PRD-003 sweep. |
| Policy must cover legacy aliases, service keys, tenant/space keys, and AI Builder create sessions. | Added typed action matrix and negative pins. |
| JSONB fields need parser/version/corruption behavior, not only keep/convert labels. | Added JSONB hardening requirements. |

## Claude attacks rejected

| Attack | Reason |
|---|---|
| Treat all legacy-worded tests as delete candidates. | Rejected because some protect current persisted readers or prompt contracts. |
| Normalize arbitrary runtime output blobs now. | Rejected because arbitrary user/LLM output remains heterogeneous; only lifecycle/audit/reference facts become relational. |
| Use Celery chain/chord or periodic reconciliation as primary human gate. | Rejected because indefinite human wait belongs in DB state, not queue topology or polling as the primary resume path. |
| Preserve old request `file_ids` as a dual public shape. | Rejected because this is pre-production and dual shapes would create long-term API debt. |

## Remaining disagreements

No unresolved load-bearing disagreement remains. The carried risks are implementation risks with recommended defaults, not architectural deadlocks.

## Do-not-split summary

Files proposed for splitting have named lifecycle/domain responsibilities and line ranges in `docs/refactor/phase7/do-not-split.md`. Large cohesive files such as `planning_state.py`, `attachment_observation.py`, `flow_run_step_inputs.py` after adapter deletion, and specific runtime helpers should not be split.

The split rule is: delete compatibility first, then split only when the new module has one real reason to change and exposes a smaller interface than the moved implementation.

## Updated implementation order

Use `docs/refactor/implementation-order.md` as the scheduling source:

1. Batch 0: behavior pins, deletion classification, true false-owner cleanup.
2. Batch 1: OpenAPI source truth.
3. Batch 2: typed permissions and JSONB/data contracts.
4. Batch 3: lifecycle projection, terminalization command, audit/outbox.
5. Batch 4: per-step file mapping and relational file rows.
6. Batch 5: generated frontend Flow types.
7. Batch 6: AI Builder contract split.
8. Batch 7: frontend state owners.
9. Batch 8: step rerun.
10. Batch 9: human review pause/edit/resume.
11. Batch 10: operability, dead tests, comment cleanup, ADR/docs polish.

## Stop/go assessment

`GO WITH RISKS`

The load-bearing designs are concrete: Celery pause/edit/resume is chosen, per-step file mapping and rerun data models are chosen, ARQ inventory has run, behavior pins are named with test paths, and JSONB fields have decision rows.

Named risks carried into implementation:

| Risk | Iteration where resolved | Rollback / recovery |
|---|---|---|
| Persisted/public readers need count-query proof before deletion: `template_file_id`, old form field types, HTTP config shapes, top-level `file_ids`, historical evidence keys. | Batches 0, 4, and 10. | If rows exist, backfill/rewrite first; emergency adapter only with owner, trigger, removal condition, and PRD/work item. |
| Terminalization and durable audit/outbox are not implemented yet, review/rerun depend on them, and existing Flow audit has an indirect `audit_service.log_async` ARQ path to inventory/migrate. | Batch 3 before Batches 8-9. | Keep rerun/review endpoints disabled; use existing terminal paths until command passes behavior pins; do not add new Flow lifecycle audit on ARQ. |
| Frontend Flow test command remains blocked by the known `jsdom` baseline issue. | Batch 5/7 before frontend state-owner refactor. | Isolate env fix from product refactor; do not claim frontend state refactor complete without documented command. |
