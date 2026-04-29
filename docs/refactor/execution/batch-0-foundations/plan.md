# Batch 0 Foundations Plan

TL;DR:
1. Branch is `feature/refactor-flows-flowai`; no further branch operations are authorized for this loop.
2. Behavior pins land before deleting source-only false owners.
3. Tier A deletion is limited to root Flow service/repository/dispatch shims and router callable re-export surfaces.
4. Tier B public/persisted readers remain documented and untouched.
5. Validation uses the exact Batch 0 Docker commands from `implementation-order.md`, plus pin/import-linter commands created by this plan.

## Scope

Batch: `0`
Name: `foundations`
Loop iteration: `1`

Canonical schedule: `docs/refactor/implementation-order.md`.

Primary PRDs:

- `docs/refactor/prd/PRD-001-foundations.md`
- `docs/refactor/prd/PRD-007-testing-strategy.md`
- `docs/refactor/prd/PRD-008-dead-code-comments-and-readability.md`

Non-goals:

- Do not delete `backend/src/intric/flows/flow.py`.
- Do not delete `backend/src/intric/flows/ai_builder/ai_builder_models.py`.
- Do not delete the frontend redispatch alias.
- Do not change top-level run `file_ids`, `template_file_id`, legacy form field readers, HTTP config converters, or historical evidence keys.
- Do not add runtime pause, rerun, generated frontend type migration, data migrations, PRs, pushes, or extra branches.

## Acceptance Criteria Restated Verbatim

### PRD-001

- [ ] `rg` shows no imports from deleted true shim modules. Batch 0 scope.
- [ ] Router aggregation modules no longer export endpoint callables unless a documented external consumer exists. Batch 0 scope.
- [ ] OpenAPI route tests pin current behavior before contract changes. Batch 0 scope.
- [ ] Runtime worker characterization test exists or is explicitly blocked by a fixture gap. Batch 0 scope.
- [ ] Compatibility paths are classified with owner, deletion condition, and confidence. Batch 0 scope.
- [ ] Phase 5 guardrail proposals cover non-canonical imports and broad typed-boundary escapes. Deferred guardrail hardening unless `.importlinter` changes expose a Batch 0 gap.

### PRD-007

- [ ] API-plus-worker contract test exists. Batch 0 scope for the runtime worker contract path.
- [ ] API consumer contract test exists. Deferred to PRD-004/API consumer batch except current route/OpenAPI pins.
- [ ] OpenAPI/generated-client contract tests cover PRD-004 surfaces. Batch 0 pins current schema only; source fixes are deferred to Batch 1.
- [ ] Dead shim identity tests are deleted after shim cleanup. Batch 0 scope for root shims/router callable identity tests.
- [ ] Runtime private-method tests are reduced only after persisted behavior tests cover same risk. Deferred; Batch 0 does not delete runtime private-method tests.
- [ ] Frontend journey tests protect AI Builder and run launch state migrations. Deferred to frontend state-owner batches.

### PRD-008

- [ ] True shim imports are gone. Batch 0 scope for listed Tier A shims.
- [ ] Router callable re-export tests are replaced with route tests. Batch 0 scope.
- [ ] Stale comments identified by Agent D are deleted with their branches. Batch 0 scope only for deleted shim files; broader comment cleanup is deferred.
- [ ] Compatibility paths that remain have deletion owner and gate. Batch 0 scope.
- [ ] No active LLM repair path is deleted without behavior replacement. Batch 0 scope: no AI Builder repair path edits.
- [ ] Large-file splits are tied to PRD-003, PRD-005, or PRD-006 ownership changes. Batch 0 scope: no large-file splits.
- [ ] No commented-out code remains in Flow / AI Builder source. Deferred broad cleanup; Batch 0 must not add any.
- [ ] No comments remain that merely restate function names, variable names, or control flow. Deferred broad cleanup; Batch 0 must not add any.
- [ ] No "temporary" comments remain without owner, removal condition, and PRD/work item. Batch 0 must not add any.
- [ ] Every kept non-trivial comment explains intent, constraint, invariant, or trade-off. Batch 0 scope for edited files only.

### User Batch 0 Criteria

- [ ] Route/OpenAPI pins cover current Flow endpoint registration and generated-client-sensitive schema.
- [ ] Startup/import tests assert canonical imports and app behavior, not shim identity.
- [ ] Tier A deletion candidates have canonical replacements and zero-import proof.
- [ ] Router callable identity tests are replaced by route/OpenAPI behavior tests.
- [ ] Tier B items remain documented, not deleted: top-level request file_ids, template_file_id, old form field types, HTTP config converters, historical evidence keys.
- [ ] No source-only shim is restored as compatibility unless a real external consumer is proven.

## Behavior Pins Before Deletion

| Pin | Tag | File | Behavior | Unlocks |
|---|---|---|---|---|
| Flow route registration snapshot | `[rewrite]` | `backend/tests/unit/test_flow_openapi_contract.py` | Assert live `APIRoute` method/path/operation IDs for Flow and AI Builder routes, including `/api/v1/flows/{id}/runs/{run_id}/evidence/export`. | Replaces router callable identity assertions. |
| OpenAPI generated-client-sensitive schema | `[rewrite]` | `backend/tests/unit/test_flow_openapi_contract.py` | Assert current multipart `upload_file` binary schema, `FlowRunCreateRequest` request/response schema, explicit top-level `file_ids` property presence, `step_inputs`, evidence export response/errors, and enum constraints. | Later OpenAPI source cleanup and Batch 4 file mapping. |
| Pagination current shape | `[new]` | `backend/tests/unit/test_flow_openapi_contract.py` | Assert `/api/v1/flows/` and `/api/v1/flows/{id}/runs/` return `PaginatedResponse_*` components with current `count` and `items` fields. | Batch 1 pagination contract changes. |
| Startup canonical imports | `[rewrite]` | `backend/tests/unit/test_server_startup_imports.py` | Keep server import and package side-effect smoke; replace shim identity checks with canonical `domain`, `application`, and `infrastructure` imports plus app route behavior. | Root shim deletion. |
| Runtime worker contract | `[new]` | `backend/tests/integration/flows/test_flow_runtime_worker_contract.py` | Seed a published single-step flow, create a run, execute it through the worker/runtime boundary using real DB repos plus a deterministic fake completion service, then assert terminal run state, closed step attempt/result, readable evidence, and audit behavior where current fixtures support it. | Future executor/terminalization refactors. |

Fixture-gap rule for runtime worker contract:

- Default is to add the test in this iteration.
- A fixture-gap note is allowed only if implementation proves a concrete missing fixture or unmockable boundary, such as no deterministic completion-service seam for integration execution or no audit fixture that can be asserted without external services.
- If blocked, write the exact blocker and next-batch trigger to `journal.md` before any deletion, and keep the required validation command result separated from product regressions.

## Startup Test Classification

| Test block | Current lines | Action | Reason |
|---|---:|---|---|
| `test_server_main_imports_without_circular_flow_template_validation_cycle` | 10-13 | Keep | Startup smoke protects package import behavior. |
| `test_server_main_imports_in_fresh_python_process` | 16-34 | Keep | Fresh-process startup smoke catches import cycles. |
| `test_flow_template_validation_shim_reexports_files_domain_helpers` | 37-49 | Keep | `flow_template_validation.py` is not in Batch 0 deletion scope, so this identity pin remains until a boundary rule replaces it. |
| `test_intric_flows_package_does_not_import_services_as_side_effect` | 52-60 | Rewrite | Keep side-effect behavior but stop naming deleted submodules as active compatibility paths if files are removed. |
| `test_intric_flows_runtime_package_does_not_import_celery_as_side_effect` | 63-71 | Keep | Runtime import side-effect pin remains load-bearing. |
| `test_flow_layer_packages_reexport_existing_symbols` | 74-110 | Delete/replace | Identity test preserves root shims scheduled for deletion. |
| `test_flow_consumer_router_split_modules_reexport_existing_handlers` | 113-213 | Delete/replace | Identity test preserves router callable re-export surfaces. |
| `test_flow_and_ai_builder_routes_have_unique_contracts_and_docs` | 216-252 | Keep or move into OpenAPI contract test | Route uniqueness/docs are behavior pins. |
| `test_flow_and_ai_builder_request_models_expose_openapi_examples` | 255-275 | Keep | Generated-client/schema documentation pin. |
| `test_flow_and_ai_builder_response_models_expose_openapi_examples` | 278-306 | Keep | Generated-client/schema documentation pin. |
| `test_flow_and_ai_builder_openapi_documents_parameters_and_error_examples` | 309-451 | Keep | OpenAPI error/parameter behavior pin. |

## Tier A Source-Only False Owners

| Candidate | Canonical replacement | Current evidence | Planned action | Safe after pins? |
|---|---|---|---|---|
| `backend/src/intric/flows/flow_repo.py` | `intric.flows.infrastructure.flow_repo` | Only identity startup import currently found. | Retarget/delete file; remove from `.importlinter`. | Yes. |
| `backend/src/intric/flows/flow_version_repo.py` | `intric.flows.infrastructure.flow_version_repo` | Only identity startup import currently found. | Retarget/delete file; remove from `.importlinter`. | Yes. |
| `backend/src/intric/flows/flow_run_repo.py` | `intric.flows.infrastructure.flow_run_repo` | Startup identity import and `backend/tests/integration/flows/test_flow_run_repository.py`. | Retarget test; delete file; remove from `.importlinter`. | Yes. |
| `backend/src/intric/flows/flow_service.py` | `intric.flows.application.flow_service` | Startup identity import and three unit test imports. | Retarget tests; delete file; remove from `.importlinter`. | Yes. |
| `backend/src/intric/flows/flow_run_service.py` | `intric.flows.application.flow_run_service` | Startup identity import and two unit test imports. `rg` found no logger patch outside the shim itself. | Retarget tests; delete subclass/logger-rebinding shim; remove from `.importlinter`. | Yes. |
| `backend/src/intric/flows/flow_dispatch.py` | `intric.flows.application.flow_dispatch` | Startup identity import and `test_flow_router.py` module import. | Retarget test; delete module alias; remove from `.importlinter`. | Yes. |
| `backend/src/intric/flows/api/flow_consumer_router.py` callable exports | Concrete endpoint routers: upload, run execution, run evidence, run steps. | Endpoint callables imported by `test_flow_router.py`; app includes only `router`. | Remove callable imports and `__all__` entries; keep router assembly. | Yes. |
| `backend/src/intric/flows/api/flow_run_router.py` callable exports | Concrete endpoint routers: run execution, run evidence, run steps. | Identity startup test currently protects callable names. | Remove callable imports and `__all__` entries; keep router assembly. | Yes. |

Tier A deferred:

| Candidate | Why deferred | Owner batch |
|---|---|---|
| `backend/src/intric/flows/flow.py` | Many production/test importers remain, including AI Builder and actors. PRD-008 open question says this is not part of first true-shim deletion batch. | Later cleanup after production imports move. |
| `backend/src/intric/flows/ai_builder/ai_builder_models.py` | AI Builder contract split must move boundary-specific model imports first. | Batch 6. |
| Frontend `getRedispatchFeedback` alias | Batch 0 has no frontend behavior pin for this alias and readiness defers it by default. | Batch 10 unless separately pinned. |

## Router Callable Retarget Map

| Callable currently imported from `flow_consumer_router` | Concrete owner |
|---|---|
| `get_flow_run_contract` | `intric.flows.api.flow_upload_router` |
| `get_flow_input_policy` | `intric.flows.api.flow_upload_router` |
| `upload_flow_file` | `intric.flows.api.flow_upload_router` |
| `upload_flow_runtime_file` | `intric.flows.api.flow_upload_router` |
| `create_flow_run` | `intric.flows.api.flow_run_execution_router` |
| `list_flow_runs_alias` | `intric.flows.api.flow_run_execution_router` |
| `get_flow_run_alias` | `intric.flows.api.flow_run_execution_router` |
| `cancel_flow_run_alias` | `intric.flows.api.flow_run_execution_router` |
| `redispatch_flow_run_alias` | `intric.flows.api.flow_run_execution_router` |
| `get_flow_run_evidence_alias` | `intric.flows.api.flow_run_evidence_router` |
| `export_flow_run_evidence_alias` | `intric.flows.api.flow_run_evidence_router` |
| `list_flow_run_steps` | `intric.flows.api.flow_run_steps_router` |
| `get_flow_graph` | `intric.flows.api.flow_run_steps_router` |
| `generate_flow_run_artifact_signed_url` | `intric.flows.api.flow_run_steps_router` |

## Tier B Persisted/Public Readers Not Deleted

| Reader | Current owner | Why not deleted in Batch 0 | Delete/rewrite gate |
|---|---|---|---|
| Top-level run request `file_ids` | `FlowRunCreateRequest`, `flow_run_execution_router`, `flow_run_step_inputs`, `intric-js` | Public request shape; Batch 0 only pins current schema. | Batch 4 after `step_inputs` contract/client/docs/idempotency update. |
| `template_file_id` | Flow service/template asset runtime/frontend readers | Persisted draft/published config reader. | Count/backfill/prove zero rows, then delete in owning batch. |
| Old form field types | Flow validation/input payload normalization | Persisted metadata shape. | Count/backfill canonical field types, then delete normalization/tests. |
| HTTP config converters | `http_transport` authored config normalizers | Persisted HTTP step config shape. | Count/backfill authored config rows, then remove converters. |
| Historical evidence keys | Evidence/provenance/export builders | Historical run export/read compatibility. | Evidence ownership PRD with migration/export policy. |

## Files To Change

### Tests

- `backend/tests/unit/test_flow_openapi_contract.py`
- `backend/tests/unit/test_server_startup_imports.py`
- `backend/tests/integration/flows/test_flow_runtime_worker_contract.py`
- `backend/tests/unittests/flows/test_flow_router.py`
- `backend/tests/unittests/flows/test_typed_io_service.py`
- `backend/tests/unittests/flows/test_flow_service.py`
- `backend/tests/unittests/flows/test_flow_template_asset_compatibility.py`
- `backend/tests/unittests/flows/test_flow_run_service.py`
- `backend/tests/unittests/flows/test_typed_io_run_service.py`
- `backend/tests/integration/flows/test_flow_run_repository.py`

### Source

- `backend/src/intric/flows/api/flow_consumer_router.py`
- `backend/src/intric/flows/api/flow_run_router.py`
- `backend/src/intric/flows/__init__.py` only to drop package-level module aliases such as `flow_service` and `flow_run_service` once their shim files are gone, so canonical imports remain the single module path; keep class-level package facade exports unless implementation proves they are unnecessary and in scope.
- `backend/.importlinter`

### Deletions

- `backend/src/intric/flows/flow_repo.py`
- `backend/src/intric/flows/flow_version_repo.py`
- `backend/src/intric/flows/flow_run_repo.py`
- `backend/src/intric/flows/flow_service.py`
- `backend/src/intric/flows/flow_run_service.py`
- `backend/src/intric/flows/flow_dispatch.py`

### Execution Artifacts

- `docs/refactor/execution/batch-0-foundations/plan.md`
- `docs/refactor/execution/batch-0-foundations/journal.md`
- `docs/refactor/execution/batch-0-foundations/validation-1.log`
- `docs/refactor/execution/batch-0-foundations/retrospective-1.md`
- `docs/refactor/execution/batch-0-foundations/claude-attack-1.md`
- `docs/refactor/execution/batch-0-foundations/claude-reconciliation-1.md`

## Validation Commands

Exact commands copied from Batch 0 in `docs/refactor/implementation-order.md`:

```bash
docker exec -w /workspace/backend eneo-41ae93-eneo-1 uv run pyright
docker exec -w /workspace/backend eneo-41ae93-eneo-1 uv run pytest tests/unit/test_flow_openapi_contract.py tests/integration/flows/test_flow_runtime_worker_contract.py -q
```

Additional exact Batch 0 pin/import validation commands created by this plan:

```bash
docker exec -w /workspace/backend eneo-41ae93-eneo-1 uv run pytest tests/unit/test_server_startup_imports.py tests/unittests/flows/test_flow_router.py tests/unittests/flows/test_flow_service.py tests/unittests/flows/test_flow_run_service.py tests/unittests/flows/test_typed_io_service.py tests/unittests/flows/test_typed_io_run_service.py tests/unittests/flows/test_flow_template_asset_compatibility.py tests/integration/flows/test_flow_run_repository.py -q
docker exec -w /workspace/backend eneo-41ae93-eneo-1 uv run lint-imports --no-cache
```

Docker policy note:

- `docker ps --format '{{.Names}}'` was rejected by the current tool policy before planning.
- Step 3 still starts with the exact Docker commands above.
- If `docker exec -w /workspace/backend eneo-41ae93-eneo-1 ...` fails specifically because the container does not exist, retry the same command once with `eneo_devcontainer-eneo-1` before falling back to local commands, and record the selected container in `journal.md`.
- If Docker remains blocked, record that in `validation-1.log` and `journal.md`, then run local backend fallbacks only as environment fallback:

```bash
cd backend && uv run pyright
cd backend && uv run pytest tests/unit/test_flow_openapi_contract.py tests/integration/flows/test_flow_runtime_worker_contract.py -q
cd backend && uv run pytest tests/unit/test_server_startup_imports.py tests/unittests/flows/test_flow_router.py tests/unittests/flows/test_flow_service.py tests/unittests/flows/test_flow_run_service.py tests/unittests/flows/test_typed_io_service.py tests/unittests/flows/test_typed_io_run_service.py tests/unittests/flows/test_flow_template_asset_compatibility.py tests/integration/flows/test_flow_run_repository.py -q
cd backend && uv run lint-imports --no-cache
```

The fallback commands are not substitutes for the required Docker commands; they are only for separating environment blockers from product regressions when Docker execution is unavailable.

## Deletion Gates

Before deleting each Tier A file:

- Route/OpenAPI and startup behavior pins above exist.
- A targeted `rg` shows no remaining imports from the deleted module outside docs and deletion records.
- Tests have been retargeted to canonical modules.
- `.importlinter` no longer lists deleted modules as source modules.
- No new compatibility shim, fallback, `legacy_*` branch, or source-only alias is added.

Zero-import proof commands to run before deletion:

```bash
rg -n "intric\\.flows\\.(flow_repo|flow_version_repo|flow_run_repo|flow_service|flow_run_service|flow_dispatch)" backend/src backend/tests frontend
rg -n "from intric\\.flows\\.api\\.flow_consumer_router import \\(" backend/src backend/tests frontend
rg -n "from intric\\.flows\\.api\\.flow_run_router import \\(" backend/src backend/tests frontend
```

## Claude Plan Review

Iteration 1 artifact: `.codex/artifacts/claude-peer-loop-batch-0-foundations-plan-20260429T143721Z.md`.

Iteration 2 verification artifact: `.codex/artifacts/claude-peer-loop-batch-0-foundations-plan-verification-20260429T144455Z.md`.

Accepted plan changes from Claude:

- Add `.importlinter` to scope and validate with `uv run lint-imports --no-cache`.
- Classify `test_server_startup_imports.py` by test block before editing.
- Treat `test_flow_router.py` retarget as a non-trivial mechanical rewrite with an explicit callable owner map.
- Add explicit pagination response-shape and top-level `file_ids` schema pins.
- Treat runtime worker contract as required by default, with fixture gap allowed only after concrete proof.
- Record Docker container/fallback behavior in validation artifacts.

## Risks And Stop Conditions

| Risk | Stop condition |
|---|---|
| Runtime worker contract cannot be written deterministically with current fixtures. | Stop before deletion, write fixture-gap note with exact missing seam and trigger condition, then continue only if deletion remains independent and user criteria allow the note. |
| `test_flow_router.py` retarget becomes a behavior rewrite instead of import-only retarget. | Stop, update this plan, re-run plan step. |
| `.importlinter` source-module sync test reveals broader package facade issues. | Stop and decide whether to limit Batch 0 to file-shim deletion or expand with evidence. |
| Docker validation remains blocked. | Record blocked Docker output verbatim, run local fallback commands, and report environment failure separately from product regressions. |
| Any Tier B reader appears in the deletion diff. | Stop and revert that local Batch 0 edit before continuing. |
