# Phase 7 Claude Reconciliation

## TL;DR

Claude was used as a senior adversarial reviewer for load-bearing Flow / Flow AI Builder decisions.
Concrete attacks were verified against repository evidence before changing docs.
Most accepted attacks tightened gates, data ownership, status predicates, and behavior pins.
Rejected attacks were speculative or would preserve long-term compatibility debt.
No unresolved load-bearing disagreement remains.

## Method

Claude packets are stored verbatim under `docs/refactor/phase7/claude/`. Codex accepted an attack only when it identified repository evidence, a missing evidence check, a specific failure mode, or a concrete alternative with a named maintainability/reliability gain.

## Packet Reconciliation

| Packet | Claude attack | Status | Reason | Doc changes made | Remaining disagreement |
|---|---|---|---|---|---|
| 1. Deletion policy | The kill list conflated source-only shims with persisted/public readers. | Accepted | Repository evidence shows both import shims and live payload/read models such as `file_ids`, `template_file_id`, old form types, and historical evidence keys. | Added Tier A/Tier B deletion policy in PRD-001, PRD-008, `implementation-readiness.md`, `dead-tests-cleanup.md`. | None. |
| 1. Deletion policy | Some "legacy" paths may be active repair/read behavior, not dead compatibility. | Accepted | AI Builder repair and strict planning-state rejection protect current LLM/JSON boundaries. | Active boundary repair class added to PRD-001/008 and test cleanup docs. | None. |
| 1. Deletion policy | `Permission.FLOWS`, `FlowFactory`, historical evidence, and `is_authored_config` are not first-pass deletion candidates. | Accepted | These have live behavior or migration semantics. | Tier B gates and kill-list readiness now separate them from Tier A deletion. | None. |
| 2. Dead tests | Do not wholesale-delete `test_server_startup_imports.py`; it contains OpenAPI/package-init pins. | Accepted | Test file mixes bad shim identity tests with useful contract pins. | PRD-007 and `dead-tests-cleanup.md` now require split/keep before deletion. | None. |
| 2. Dead tests | Do not wholesale-delete `test_flow_router.py`; it contains SSRF, tenant scope, audit, broker-down, idempotency, and service-key pins. | Accepted | Mock structure is poor, but behavior is real. | PRD-007 and `dead-tests-cleanup.md` require TestClient/API rewrites before deleting mock-heavy tests. | None. |
| 2. Dead tests | Runtime data-migration tests that look legacy are not dead until data proof/backfill exists. | Accepted | HTTP config, form field normalization, and template ID readers may still parse persisted rows. | Added migration-pin framing to PRD-007 and `dead-tests-cleanup.md`. | None. |
| 2. Dead tests | Tests for prompt "legacy" behavior may protect active prompt contract. | Accepted | The current wording is stale, but the behavior can still prevent LLM regression. | Marked as keep/rename to prompt-as-contract owner rather than delete. | None. |
| 3. Runtime IO model | Per-step file mapping should be attempt-scoped, especially for rerun. | Accepted | Rerun can change inputs per step/attempt; run-level rows would hide lineage. | Added attempt-scoped `flow_run_step_input_files` in PRD-002/003 and stress test. | None. |
| 3. Runtime IO model | Output/generated files need relational projection too. | Accepted | Evidence/artifact retrieval, retention, and rerun invalidation need FK/queryable ownership. | Added `flow_run_step_result_files` to PRD-002/003 and stress test. | None. |
| 3. Runtime IO model | Step rerun needs a dedicated operation table. | Accepted | Redispatch cannot represent root step, invalidation set, edited inputs, and idempotency. | Added `flow_run_rerun_operations` and rerun operation semantics. | None. |
| 3. Runtime IO model | DAG source truth must be run-version scoped. | Accepted | Current draft graph may differ from published run definition. | Added published `FlowVersions.definition_json` as rerun graph default and authoring graph consistency acceptance. | None. |
| 3. Runtime IO model | Keeping only a current `FlowStepResults` projection risks losing history. | Partial | Accepted history concern; retained current projection only if attempts/rerun ops preserve history. | Stress test and PRD-003 now require history in attempts/rerun ops or a partial current-row constraint if implementation changes the projection. | None. |
| 4. Celery lifecycle | DB state machine plus thin resume task is right, but terminalization/outbox must exist first. | Accepted | Current terminalization is split and audit uses async ARQ infrastructure outside Flow lifecycle. | PRD-003 and PRD-009 now make terminalization/outbox preconditions before review/rerun. | None. |
| 4. Celery lifecycle | `waiting_for_review` needs status predicate sweep. | Accepted | DB CHECK, repo predicates, reconciler, concurrency limits, API, and frontend statuses can drift. | Added PRD-003 status predicate sweep. | None. |
| 4. Celery lifecycle | Periodic reconciliation should remain as safety net. | Partial | Rejected as primary resume path, accepted as checkpoint expiry/orphan repair. | PRD-003 option comparison keeps reconciliation as safety net only. | None. |
| 4. Celery lifecycle | Duplicate resume/cancel/terminalization require compare-and-set and idempotency. | Accepted | Duplicate Celery delivery and repeated API calls are expected failure modes. | Added CAS/idempotency semantics to PRD-003 and behavior pins. | None. |
| 5. Typed policy | Existing helper structure should be reused rather than inventing a parallel policy surface. | Accepted | `flow_api_common.py` and route dependencies already centralize pieces of the current policy. | PRD-002/004 now target typed actions through a Flow policy dependency and forbid raw route scope reads. | None. |
| 5. Typed policy | AI Builder create sessions are space-scoped until a flow exists. | Accepted | Create target has no flow ID. | Added space-scoped builder action and apply-time flow action in PRD-002. | None. |
| 5. Typed policy | Permission migration must include negative tests for legacy aliases and service keys. | Accepted | Broad aliases could accidentally grant review/resume/rerun/audit. | Added negative permission pins in PRD-002/007 and leakage audit. | None. |
| 6. JSONB inventory | Add output-file relational projection and graph consistency between `input_bindings` and `FlowStepDependencies`. | Accepted | These are concrete hidden-schema and lifecycle issues. | Added stress-test rows and authoring graph consistency section. | None. |
| 6. JSONB inventory | Add schema/version/corruption requirements and `jsonb_typeof` checks. | Accepted | Keep-JSONB decisions are unsafe without parser/version/corruption behavior. | Added JSONB hardening section to PRD-002 and stress test. | None. |
| 6. JSONB inventory | Clarify `FlowRuns.user_id` as historical-only before dropping. | Accepted | Identity fields are authorization-sensitive. | Kept as open risk/question with historical-only default. | None. |
| 7. Behavior pins | Add idempotency, expected flow version, audit, tenant isolation, evidence redaction/schema version, cancel/redispatch, SSE, planning-state, and file guards. | Accepted | These protect load-bearing contract changes. | Expanded PRD-007 behavior pins and implementation bootstrap. | None. |
| 7. Behavior pins | Behavior pins must be observable, not private method assertions. | Accepted | Current tests over-mock routers/executor. | PRD-007 now requires API/worker/frontend behavior tests and rewrites brittle tests before deletion. | None. |
| 8. Final green-light | Indirect Flow audit path still uses `audit_service.log_async` -> ARQ Redis. | Accepted | Source evidence at `backend/src/intric/audit/application/audit_service.py:234-324` means the direct ARQ grep inventory was incomplete for Flow audit. | PRD-003, PRD-009, and implementation readiness now require lifecycle audit outbox and inventory/migration/default decision for non-lifecycle Flow audit callers. | None. |
| 8. Final green-light | `waiting_for_review` concurrency and TTL defaults were under-specified. | Accepted | Implementation needs a default before adding status migration and concurrency predicates. | PRD-003 now excludes waiting runs from active worker slots and defaults to no auto-cancel TTL. | None. |
| 8. Final green-light | `scope_enforcement_enabled` and list deny-vs-filter policy were not pinned. | Accepted | Typed policy migration could otherwise silently preserve a soft-disable or create noisy denial semantics. | PRD-002/004 now require explicit policy modes and deletion/isolation of the production soft switch. | None. |
| 8. Final green-light | Legacy permission mapping was both open and defaulted in the ADR backlog. | Accepted | The default is already load-bearing enough for implementation. | `open-questions.md` now closes the question with the minimal explicit mapping default. | None. |
| 8. Final green-light | FlowRunDialog journey pin sequencing needed one cross-check sentence. | Accepted | Frontend extraction should not start before its journey/component pin exists. | `implementation-readiness.md` now names the Batch 7 prerequisite. | None. |

## Rejected Or Limited Attacks

| Attack | Status | Reason |
|---|---|---|
| Preserve top-level request `file_ids` as a dual public request shape. | Rejected | Pre-production scope allows breaking cleanup; dual shape would create long-term API debt. Historical evidence keys can remain under schema version. |
| Normalize arbitrary runtime/model output into tables. | Rejected | Arbitrary LLM/user output is heterogeneous. Relational extraction is limited to lifecycle/audit/reference facts. |
| Use Celery chain/chord or periodic reconciliation as primary pause/resume gate. | Rejected | Indefinite human waits belong in DB state plus explicit resume commands, not worker/broker topology. |
| Delete every test with legacy wording. | Rejected | Some tests are migration pins or active prompt-contract pins. Rename/rewrite them instead. |

## Final Green-Light

Claude's final Phase 7 review returned `GREEN_LIGHT: YES` with no blocking issues. The final concrete doc fixes were accepted and applied. The verbatim final review is stored at `docs/refactor/phase7/claude/08-final-green-light.md`.

## Final Position

The plan is `GO WITH RISKS`. No Claude attack remains unresolved as a load-bearing architecture disagreement. The risks are:

- persisted/public readers need count proof and possible backfill
- terminalization/outbox must land before rerun/review, including the indirect Flow audit `log_async` ARQ inventory/migration decision
- frontend test command needs the `jsdom` baseline fixed before frontend state refactor validation
