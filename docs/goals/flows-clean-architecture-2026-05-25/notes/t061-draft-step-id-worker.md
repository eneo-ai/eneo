# T061 Draft Step Id Worker Receipt

## Result

Done. Draft authoring updates now preserve persisted `FlowStep.id` from the public update contract through the assembler, service invariants, repository persistence sync, generated client schema, and `FlowEditor` payload handling.

## Source Changes

- `FlowStepUpdateRequest` is the update-only authoring request shape. `FlowStepCreateRequest` remains id-less.
- `FlowAssembler.to_domain_step_for_update(...)` carries optional persisted draft step id into `FlowStep`.
- `flow_authoring_router.update_flow(...)` uses the update-specific assembler method only for PATCH steps.
- `FlowService.update_flow(...)` rejects:
  - duplicate `step_order` with `duplicate_step_order`;
  - duplicate persisted step id with `duplicate_step_id`;
  - unknown persisted step id with `unknown_step_id`;
  - id-less new steps carrying secret sentinels with `sentinel_secret_requires_step_id`.
- `FlowService._merge_step_secrets(...)` merges stored encrypted HTTP secrets by persisted draft step id, not mutable order.
- `FlowRepository._sync_flow_steps(...)` syncs retained rows by `FlowSteps.id`, inserts id-less steps, deletes stale ids, and uses a two-phase temporary negative `step_order` band plus `flush()` before final positive orders.
- `FlowEditor` includes persisted step ids in step diffs, strips `_temp_` ids before API submit, and uses `_temp_` ids as stable local keys during reorder/remap.
- `frontend/packages/intric-js/src/types/schema.d.ts` now includes `FlowStepUpdateRequest`, and `PartialFlowUpdateRequest.steps` points at it.

## Consolidation Effect

- Reused existing owner: `FlowStep.id` / `FlowSteps.id`, Flow authoring API models, `FlowAssembler`, `FlowService.update_flow(...)`, `FlowService._merge_step_secrets(...)`, `FlowRepository._sync_flow_steps(...)`, generated OpenAPI types, and `FlowEditor`.
- Logic moved from: mutable `step_order` matching inside service/repository behavior to persisted id matching inside the same existing owners.
- Logic deleted: order-as-identity behavior for retained draft steps in secret merge and repository sync.
- Duplicate path removed: the split where `FlowStepPublic.id` was returned to clients but the update contract and frontend PATCH path dropped it.
- New code added: `FlowStepUpdateRequest`, update-specific assembler method, service invariant checks, repository id-owned sync branch, and frontend local temp-id strip helper.
- Why existing owners were insufficient: existing owners were the right homes, but create/update were conflated in one id-less request shape, the assembler dropped id, service/repository matched by order, and `FlowEditor.editableFields.steps` omitted id.
- Guard/test preventing duplicate logic from returning: service validation/secret-merge tests, repository id-preservation integration tests, API/OpenAPI/model/assembler tests, generated schema diff, and FlowEditor payload/key tests.
- Net Flow logic surface area: reduced. There are more explicit checks, but the number of identity concepts and places-to-debug went down: draft step identity is now id-owned and order is order only.

## Naming Gate And Maintainer-Map Readiness

- `FlowStepUpdateRequest` names the Flow authoring update axis and should appear clearly in the final `docs/flows/architecture.md` "where to change X" table.
- No new module, manager, processor, helper package, fake interface, generic adapter, plugin system, service locator, or parallel identity owner was added.
- Final maintainer doc evidence captured:
  - Draft Flow authoring identity owner: `FlowStep.id` / `FlowSteps.id`.
  - Create request: id-less new draft steps.
  - Update request: optional persisted draft step id for retained steps.
  - Frontend state owner: `FlowEditor` keeps `_temp_` ids local and strips them before API submit.
  - Persistence owner: `FlowRepository._sync_flow_steps(...)` owns row synchronization and reorder flush behavior.

## Verification

Passed:

- `cd backend && uv run pytest tests/unittests/flows/test_flow_service.py -k "step_id or step_order or secret or sentinel"`
  - `8 passed, 58 deselected, 1 warning`
- `cd backend && uv run pytest tests/unittests/flows/test_flow_models.py tests/unittests/flows/test_flow_review_policy.py tests/unit/test_flow_openapi_contract.py`
  - `106 passed, 15 warnings`
- `cd backend && uv run pyright src/intric/flows/api/flow_models.py src/intric/flows/api/flow_assembler.py src/intric/flows/api/flow_authoring_router.py src/intric/flows/application/flow_service.py src/intric/flows/infrastructure/flow_repo.py tests/unittests/flows/test_flow_service.py tests/integration/flows/test_flow_repository.py tests/unittests/flows/test_flow_models.py tests/unittests/flows/test_flow_review_policy.py tests/unit/test_flow_openapi_contract.py`
  - `0 errors, 0 warnings, 0 informations`
- `cd backend && uv run ruff check src/intric/flows/api/flow_models.py src/intric/flows/api/flow_assembler.py src/intric/flows/api/flow_authoring_router.py src/intric/flows/application/flow_service.py src/intric/flows/infrastructure/flow_repo.py tests/unittests/flows/test_flow_service.py tests/integration/flows/test_flow_repository.py tests/unittests/flows/test_flow_models.py tests/unittests/flows/test_flow_review_policy.py tests/unit/test_flow_openapi_contract.py`
  - `All checks passed`
- `cd backend && uv run ruff format --check src/intric/flows/api/flow_models.py src/intric/flows/api/flow_assembler.py src/intric/flows/api/flow_authoring_router.py src/intric/flows/application/flow_service.py src/intric/flows/infrastructure/flow_repo.py tests/unittests/flows/test_flow_service.py tests/integration/flows/test_flow_repository.py tests/unittests/flows/test_flow_models.py tests/unittests/flows/test_flow_review_policy.py tests/unit/test_flow_openapi_contract.py`
  - `10 files already formatted`
- `cd frontend/apps/web && bun test src/lib/features/flows/FlowEditor.test.ts`
  - `34 pass`
- `cd backend && uv run python - <<'PY' > /tmp/eneo-openapi-t061.json ... app.openapi() ... PY`
  - generated OpenAPI snapshot from the FastAPI app without a running server
- `cd frontend/packages/intric-js && bun run update --schema-file /tmp/eneo-openapi-t061.json`
  - update completed successfully; only `src/types/schema.d.ts` changed
- `git diff --check`
  - passed

Environment-blocked:

- `cd backend && uv run pytest tests/integration/flows/test_flow_repository.py -k "step_id or reorder or insert"`
  - blocked because testcontainers cannot connect to the local Docker socket.
- `docker exec eneo-41ae93-eneo-1 sh -lc 'cd /workspace/backend && uv run pytest tests/integration/flows/test_flow_repository.py -k "step_id or reorder or insert"'`
  - blocked because the host Docker CLI cannot connect to `/Users/ccimen/.orbstack/run/docker.sock`.
- `cd frontend/packages/intric-js && bun run update`
  - initially blocked by no server on `localhost:8123`; starting `cd backend && uv run start` was blocked by missing Redis on `localhost:6379`.
- Direct local DB fallback script using `get_settings().database_url`
  - blocked by connection refused on `localhost:5432`.

Stop-before-push condition:

- Run `cd backend && uv run pytest tests/integration/flows/test_flow_repository.py -k "step_id or reorder or insert"` against PostgreSQL locally once Docker/DB is available, or confirm CI runs those tests and gates push/merge.

## Peer Review

Claude:

- Artifact: `.codex/artifacts/claude-peer-loop-preserve-draft-step-identity-through-authoring-updates-implementation-review-20260526T170508Z.md`
- Iteration 1 verdict: `GREEN_LIGHT no; MIN_SCORE 6`
- Valid concerns addressed:
  - Added `duplicate_step_order` service-boundary validation.
  - Added behavior test for duplicate `step_order`.
  - Documented repository `unknown_step_id` as defense-in-depth, with `FlowService` as canonical validation owner.
- Artifact: `.codex/artifacts/claude-peer-loop-preserve-draft-step-identity-through-authoring-updates-implementation-review-iteration-2-20260526T171030Z.md`
- Iteration 2 verdict: `GREEN_LIGHT yes; MIN_SCORE 8`
- Residual stop-before-push condition: run repository integration tests against PostgreSQL via Docker/CI.

Antigravity:

- Artifact: `.codex/artifacts/antigravity-peer-loop-preserve-draft-step-identity-antigravity-implementation-synthesis-20260526T171256Z.md`
- Verdict: `GREEN_LIGHT yes; MIN_SCORE 9`
- Accepted:
  - Commit is safe locally.
  - Do not leak frontend `_temp_` ids into backend API response protocol.
  - Repository integration tests remain a stop-before-push condition.
- Non-blocking follow-up noted:
  - Consider iterative or depth-bounded secret-sentinel traversal if future evidence shows deeply nested authored configs are accepted on this path.

## Residual Risk

- The most direct PostgreSQL proof for the two-phase `step_order` reorder is present as integration tests but could not run in this local host environment because Docker and local DB are unavailable.
- CI or restored local Docker must run the focused repository integration tests before push/merge.
- A future frontend/API follow-up may improve active-step reconciliation after saving newly created steps, but backend must remain unaware of `_temp_` UI ids.
