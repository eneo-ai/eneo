# Phase 7 Dead Tests Cleanup

## TL;DR

Deleting Flow tests is acceptable when the tests preserve code the plan intentionally deletes.
Do not delete behavior coverage before the replacement behavior pin exists.
The highest-risk cleanup is over-mocked router/runtime tests: rewrite them as API, worker, and repository behavior tests before deleting call-count assertions.
Tests that look "legacy" but protect live persisted JSONB readers are not dead.
Compatibility-only import/barrel/alias tests should be deleted in Iteration 1 after canonical import and OpenAPI coverage exists.
This pass is Flow / Flow AI Builder only.

## Cleanup Rule

Each candidate is classified as:

- `delete`: test protects a never-shipped compatibility path or implementation identity.
- `rewrite as behavior test`: test protects a real user/operator/API behavior through a brittle implementation assertion.
- `keep`: test protects current correctness or a deliberate guardrail.

## Dead And Unnecessary Flow Test Cleanup

| Test file / test | Evidence | Problem | Action | Replacement behavior test | Risk |
|---|---|---|---|---|---|
| Server startup Flow template validation shim test | `backend/tests/unit/test_server_startup_imports.py:37` | Protects a re-export identity instead of app startup or canonical import behavior. | Delete. | Startup/import smoke that imports canonical `intric.flows` routes and validators. | Low after canonical import smoke exists. |
| Flow domain/repo shim import identity tests | `backend/tests/unit/test_server_startup_imports.py:78-109`; shims at `backend/src/intric/flows/flow.py:1` and `backend/src/intric/flows/flow_run_repo.py:1` | Preserves old import paths and module identity. | Delete after imports move to canonical modules. | `backend/tests/unit/test_flow_canonical_imports.py` checks canonical imports and app route registration. | Low; pre-production import break is intended. |
| AI Builder `ai_builder_models` barrel tests | `backend/tests/unit/test_server_startup_imports.py:257-301`; barrel at `backend/src/intric/flows/ai_builder/ai_builder_models.py:3-5` | Freezes star-export barrel instead of canonical API/domain/event model ownership. | Delete after test/source imports move. | Canonical model import smoke plus planner/session API behavior tests. | Medium because many tests import the barrel; migrate test imports first. |
| Top-level run `file_ids` API/client tests | Backend field at `backend/src/intric/flows/api/flow_models.py:431-435`; frontend wrapper at `frontend/packages/intric-js/src/endpoints/flows.js:67-93`; router tests at `backend/tests/unittests/flows/test_flow_router.py:671` and `:716` | Preserves duplicate public request shape. | Rewrite as `step_inputs` behavior tests, then delete `file_ids` expectations. | `backend/tests/integration/flows/test_flow_run_file_mapping_contract.py` and `frontend/packages/intric-js/src/endpoints/flows.test.js` assert `step_inputs` only. | High if idempotency/evidence behavior is not pinned first. |
| Legacy step-one adapter tests | Adapter at `backend/src/intric/flows/flow_run_step_inputs.py:104-128`; service merge at `backend/src/intric/flows/application/flow_run_service.py:385-407`; test `backend/tests/unittests/flows/test_flow_run_service.py:972` | Keeps a compatibility adapter for top-level `file_ids`. | Delete with adapter after `step_inputs` contract lands. | API test rejects top-level `file_ids` with named error and accepts non-contiguous step file mapping. | Medium. |
| Legacy HTTP normalizer tests | `backend/tests/unittests/flows/http_transport/test_normalizer.py:27-211` | Tests converter branches for old authored config shapes. | Delete converter tests after DB proof/backfill; keep authored-config discriminator tests. | `backend/tests/unittests/flows/http_transport/test_authored_config.py` validates current authored config only. | Medium if existing rows still require conversion. |
| Template `template_file_id` compatibility tests | `frontend/apps/web/src/lib/features/flows/templateFillConfig.test.ts:90-110`; backend runtime uses `template_file_id` at `backend/src/intric/flows/runtime/template_fill_runtime.py:294-299` | Preserves file-id based template selection alongside template asset ID. | Rewrite around canonical `template_asset_id`; delete legacy match tests after backfill. | Template asset API/runtime test loads template by asset ID and rejects missing asset. | Medium; requires DB count/backfill of saved configs. |
| Frontend `getRedispatchFeedback` alias tests/imports | Alias at `frontend/apps/web/src/lib/features/flows/components/flowRunRedispatchFeedback.ts:7-8` | Preserves local compatibility alias. | Delete alias and any alias-only test/import. | Keep test for canonical `getRedispatchToastKind`. | Low. |
| Frontend legacy invalid option tests | `frontend/apps/web/src/lib/features/flows/flowStepTypes.test.ts:66-75`; implementation uses `legacyInvalid` in `flowStepTypes.ts:101-161` | Preserves saved invalid values in authoring UI. | Rewrite after typed lifecycle/backfill; keep only if DB proof shows existing authored invalid options must render for cleanup. | Flow authoring validation test rejects invalid saved type before publish and displays repair banner if migration leaves rows. | Medium. |
| Flow router call-count tests | `backend/tests/unittests/flows/test_flow_router.py:200-269`, `:579-724`, `:1552-1600` | Asserts mocks/internal delegation instead of HTTP behavior and contract. | Rewrite as API behavior tests. | `backend/tests/integration/flows/test_flow_api_contract.py` covers auth, schema, idempotency, run launch, evidence. | High if deleted before contract tests exist. |
| Flow executor private-method tests | `backend/tests/unittests/flows/test_flow_executor_runtime.py` is 3,707 LOC and heavily mocks internal collaborators. | Makes executor refactors expensive and may preserve implementation shape. | Rewrite by lifecycle phase only after worker/API behavior pins land. | Runtime worker integration tests for happy path, failure, duplicate delivery, cancellation, terminalization. | High. |
| AI Builder service/planner over-mocked tests | `backend/tests/unittests/flows/ai_builder/test_ai_builder_service.py` is 2,847 LOC; many repo/file service mocks. | Some tests pin internal orchestration rather than session behavior. | Rewrite selectively; keep prompt/contract guardrails that protect LLM behavior. | AI Builder create/plan/revise/apply integration tests plus prompt obligation tests. | Medium-high. |
| AI Builder legacy prompt guard tests | `backend/tests/unittests/flows/ai_builder/test_ai_builder_conditional_prompt.py:86-182` | These mention legacy but protect against regressing to retired tool/payload shapes. | Keep until prompt contract split; then rename from legacy framing to active contract framing. | Same test content under prompt-as-contract owner. | Low; deleting would lose a valuable guardrail. |
| Planning state legacy rejection test | `backend/tests/unittests/flows/ai_builder/test_planning_state_storage.py:156` | Rejects unexpected legacy root key; protects parser strictness. | Keep. | None. | Low. |
| Startup import side-effect and OpenAPI tests in `test_server_startup_imports.py` | Same file as shim tests; Claude identified package-init purity and OpenAPI/operation/error examples as live pins. | File contains both dead shim identity tests and live public contract pins. | Split first, delete only shim tests. | Keep/rename OpenAPI and import side-effect tests under `backend/tests/unit/test_flow_openapi_contract.py` or equivalent. | High if wholesale-deleted. |
| SSRF, tenant scope, audit, dispatch failure, and service-key tests in `test_flow_router.py` | `backend/tests/unittests/flows/test_flow_router.py` contains SSRF guard, scope denial, audit positive/negative, broker-down, idempotency, and service-key assertions. | Mock-heavy structure is bad, but many assertions protect real behavior. | Rewrite as TestClient/API integration tests before deletion. | `backend/tests/integration/flows/test_flow_consumer_api_contract.py`, `test_flow_tenant_isolation_contract.py`, `test_flow_http_authored_config_contract.py`. | High. |
| Celery runtime task schema tests | Existing Celery tests pin task kwargs such as `principal_api_key_id`. | Cross-process task schema is a public runtime seam for audit attribution. | Keep until typed command payload replaces kwargs, then rewrite. | Worker contract test asserting `FlowRunExecutionCommand` payload. | High. |
| Flow form schema legacy text-like field normalization | Frontend test `flowFormSchema.test.ts:16` and backend normalization at `flow_run_input_payload.py:9-13`. | This is a persisted JSONB reader until old rows are backfilled. | Keep as data-migration pin until count/backfill proves zero rows. | After backfill, replace with canonical form schema parser test. | Medium. |

## Owner Mapping

| Cleanup family | Owning PRD/work item |
|---|---|
| Import shims/barrels/router callable identity tests | PRD-001, PRD-008, Phase 4 Iteration 1 |
| Top-level `file_ids` and step input tests | PRD-003, PRD-004, Phase 4 Iteration 4 |
| Permission alias tests | PRD-002, Phase 4 Iteration 2 |
| Terminalization/runtime private-method tests | PRD-003, PRD-007, PRD-009, Phase 4 Iteration 3 |
| AI Builder prompt/planner/service tests | PRD-005, PRD-007, Phase 4 Iteration 6 |
| Frontend state/dialog tests | PRD-006, PRD-007, Phase 4 Iteration 7 |

## Acceptance Criteria

- [ ] Every deleted test has a source deletion or behavior replacement in the same implementation batch.
- [ ] Tests that preserve never-shipped behavior are removed rather than renamed to hide compatibility.
- [ ] Tests that protect live persisted row readers are renamed as migration pins, not deleted as dead tests.
- [ ] Router tests no longer assert service call counts for public API behavior.
- [ ] Runtime behavior pins exist before executor split or terminalization rewrite.
- [ ] Test files above 1,500 LOC are either split by lifecycle behavior, reduced through deletion, or explicitly kept because they are cohesive.
