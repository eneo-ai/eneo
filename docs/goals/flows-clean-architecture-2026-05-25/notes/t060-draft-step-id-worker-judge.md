# T060 Judge: Draft Step Id-Owned Authoring Worker

## Decision

Activate T061: `fix(flows): preserve draft step identity through authoring updates`.

The Worker is not backend-only. The current bug crosses the Flow authoring request shape, assembler, application invariant, repository sync, generated client, and FlowEditor payload owner. A backend-only slice would preserve a hidden split where clients receive draft step ids but the update contract and frontend PATCH path still drop them.

## Source Evidence

| Concept | Evidence | Current problem | Canonical owner |
|---|---|---|---|
| Draft step identity | `backend/src/intric/flows/domain/flow.py:39`; `backend/src/intric/flows/api/flow_models.py:561` | `FlowStep.id` exists and is returned to clients. | `FlowStep.id` |
| Update request shape | `backend/src/intric/flows/api/flow_models.py:447`; `backend/src/intric/flows/api/flow_models.py:530` | `FlowUpdateRequest.steps` reuses create-step shape and cannot carry persisted ids. | Flow authoring API models |
| Assembly | `backend/src/intric/flows/api/flow_assembler.py:39`; `backend/src/intric/flows/api/flow_authoring_router.py:226`; `backend/src/intric/flows/api/flow_authoring_router.py:555` | PATCH currently calls the create-step mapper and drops ids. | `FlowAssembler` plus thin router adapter |
| Secret merge | `backend/src/intric/flows/application/flow_service.py:673` | Stored HTTP secrets are matched by `step_order`, so reordering can attach secrets to the wrong logical step. | `FlowService.update_flow` and `_merge_step_secrets` |
| Persistence | `backend/src/intric/flows/infrastructure/flow_repo.py:745`; `backend/src/intric/database/tables/flow_tables.py:246` | Rows are matched/deleted by `step_order`; the `(flow_id, step_order)` unique constraint is non-deferrable. | `FlowRepository._sync_flow_steps` |
| Frontend payload | `frontend/apps/web/src/lib/features/flows/FlowEditor.ts:109`; `frontend/apps/web/src/lib/features/flows/FlowEditor.ts:751`; `frontend/apps/web/src/lib/core/editing/getDiff.ts:201` | FlowEditor stores ids but omits them from PATCH diffs; `_temp_` ids are not stable keys before save. | `FlowEditor` payload boundary |

## Worker Invariant

- `FlowStep.id` is draft step identity.
- `step_order` is ordering metadata only.
- Existing draft steps are updated by `FlowStep.id`.
- New draft steps may omit `id` and receive a database id.
- Unknown incoming persisted ids are rejected with `unknown_step_id`; do not probe across tenant or flow boundaries.
- Duplicate incoming persisted ids are rejected with `duplicate_step_id`.
- Id-less steps are new. Id-less secret sentinels are rejected with `sentinel_secret_requires_step_id`.
- Missing existing ids mean deletion, while preserving flow-managed assistant cleanup.
- Repository reorder must stay local to `_sync_flow_steps`; no schema migration in T061.

## T061 Allowed Files

- `docs/goals/flows-clean-architecture-2026-05-25/state.yaml`
- `docs/goals/flows-clean-architecture-2026-05-25/notes/t061-draft-step-id-worker.md`
- `backend/src/intric/flows/api/flow_models.py`
- `backend/src/intric/flows/api/flow_assembler.py`
- `backend/src/intric/flows/api/flow_authoring_router.py`
- `backend/src/intric/flows/application/flow_service.py`
- `backend/src/intric/flows/infrastructure/flow_repo.py`
- `backend/tests/unittests/flows/test_flow_models.py`
- `backend/tests/unittests/flows/test_flow_review_policy.py`
- `backend/tests/unittests/flows/test_flow_service.py`
- `backend/tests/integration/flows/test_flow_repository.py`
- `backend/tests/unit/test_flow_openapi_contract.py`
- `frontend/packages/intric-js/src/types/schema.d.ts`
- `frontend/apps/web/src/lib/features/flows/FlowEditor.ts`
- `frontend/apps/web/src/lib/features/flows/FlowEditor.test.ts`

## Required Worker Design

- Add `FlowStepUpdateRequest` for the update contract; keep `FlowStepCreateRequest` id-less.
- Add `FlowAssembler.to_domain_step_for_update(step: FlowStepUpdateRequest) -> FlowStep`; do not overload the existing method with a union.
- Keep create router calls on `to_domain_step`; change update router calls to `to_domain_step_for_update`.
- Validate incoming ids in `FlowService.update_flow` before sentinel secret merge and before repository persistence.
- Sync existing rows by id inside `FlowRepository._sync_flow_steps`.
- For rows whose order changes, apply a temporary negative `step_order` phase, flush the session, then apply final positive orders. The flush is required so SQLAlchemy cannot collapse the two phases against the non-deferrable `uq_flow_steps_flow_step_order` constraint.
- Keep the repository algorithm O(n) in step count with maps/sets; do not add nested scans.
- Preserve `_temp_` ids as stable frontend keys during local authoring, then strip them at the API boundary before submit.
- Do not write or update `docs/flows/architecture.md` in this Worker; only preserve enough ownership evidence for final T901.

## Red Tests

1. Service secret merge: swap two stored HTTP-authored steps while preserving ids and sentinel secrets; assert secrets stay attached to the same ids.
2. Service unknown id: incoming id not in `existing.steps` raises `BadRequestException(code="unknown_step_id")`.
3. Service id-less sentinel: id-less step with a secret sentinel raises `BadRequestException(code="sentinel_secret_requires_step_id")`.
4. Service duplicate id: duplicate incoming non-null ids raise `BadRequestException(code="duplicate_step_id")`.
5. Repository adjacent swap: two existing step ids swap orders without `UniqueViolation`; row ids stay with logical steps.
6. Repository insert at position 1: new id-less step shifts existing steps while preserving existing row ids.
7. Repository removed existing id: omitted stored id is removed and still feeds flow-managed assistant cleanup.
8. Repository assistant change on same id: changing `assistant_id` still feeds cleanup candidates.
9. Models/OpenAPI: create-step has no `id`; update-step has optional `id`; partial update steps use `FlowStepUpdateRequest`.
10. Assembler: create assembly stays id-less; update assembly preserves `id` and `review_policy`.
11. Frontend PATCH: existing ids are sent; `_temp_` ids are stripped before submission.
12. Frontend diff guard: name-only saves do not include `steps` after `id` enters editable step fields.
13. Frontend local ordering: `_temp_` ids are stable keys for unsaved steps before submit.

## Verification Commands

- `cd backend && uv run pytest tests/unittests/flows/test_flow_service.py -k "step_id or secret or sentinel"`
- `cd backend && uv run pytest tests/integration/flows/test_flow_repository.py -k "step_id or reorder or insert"`
- `cd backend && uv run pytest tests/unittests/flows/test_flow_models.py tests/unittests/flows/test_flow_review_policy.py tests/unit/test_flow_openapi_contract.py -k "FlowStep"`
- `cd backend && uv run pyright src/intric/flows/api/flow_models.py src/intric/flows/api/flow_assembler.py src/intric/flows/api/flow_authoring_router.py src/intric/flows/application/flow_service.py src/intric/flows/infrastructure/flow_repo.py tests/unittests/flows/test_flow_service.py tests/integration/flows/test_flow_repository.py tests/unittests/flows/test_flow_models.py tests/unittests/flows/test_flow_review_policy.py tests/unit/test_flow_openapi_contract.py`
- `cd backend && uv run ruff check src/intric/flows/api/flow_models.py src/intric/flows/api/flow_assembler.py src/intric/flows/api/flow_authoring_router.py src/intric/flows/application/flow_service.py src/intric/flows/infrastructure/flow_repo.py tests/unittests/flows/test_flow_service.py tests/integration/flows/test_flow_repository.py tests/unittests/flows/test_flow_models.py tests/unittests/flows/test_flow_review_policy.py tests/unit/test_flow_openapi_contract.py`
- `cd backend && uv run ruff format --check src/intric/flows/api/flow_models.py src/intric/flows/api/flow_assembler.py src/intric/flows/api/flow_authoring_router.py src/intric/flows/application/flow_service.py src/intric/flows/infrastructure/flow_repo.py tests/unittests/flows/test_flow_service.py tests/integration/flows/test_flow_repository.py tests/unittests/flows/test_flow_models.py tests/unittests/flows/test_flow_review_policy.py tests/unit/test_flow_openapi_contract.py`
- `cd frontend/apps/web && bun test src/lib/features/flows/FlowEditor.test.ts`
- `cd frontend/packages/intric-js && bun run update`
- `git diff --stat`
- `git diff --check`
- `scripts/gate-local/anti_slippage.sh`

## Stop Rules

- The two-phase repository reorder needs a migration or files outside allowed files.
- Unknown-id or id-less semantics need a product compatibility decision.
- Generated client update changes files outside `frontend/packages/intric-js/src/types/schema.d.ts`.
- Red tests cannot fail on current bad behavior.
- Pyright requires `Any`, broad casts, type ignores, a union-overloaded assembler method, or generic helpers.
- Implementation adds a parallel identity owner instead of deepening existing Flow authoring/API/service/repository/frontend owners.
- The frontend clone path proves id-less sentinel secrets are a shipped behavior that needs a product decision before rejection.

## Consolidation Effect

- Reused existing owner: `FlowStep.id`, Flow authoring API models, `FlowAssembler`, `FlowService.update_flow/_merge_step_secrets`, `FlowRepository._sync_flow_steps`, and `FlowEditor`.
- Logic moved from: `step_order`-owned row/secret matching to id-owned matching inside existing owners.
- Logic deleted: order-as-identity behavior for retained draft steps.
- Duplicate path removed: clients receive step ids while update contracts and FlowEditor payloads drop them.
- New code added: `FlowStepUpdateRequest`, an update-specific assembler method, validation, repository reorder mechanics, and frontend payload/key guards.
- Why existing owners were insufficient: existing owners are sufficient for behavior; the create/update request shape was conflated and could not carry persisted ids safely.
- Guard/test preventing duplicate logic from returning: service, repository, API/OpenAPI, assembler, generated-client, and FlowEditor tests listed above.
- Net Flow logic surface area: reduced conceptually; `step_order` stops being both identity and order, while `FlowStep.id` becomes the single draft identity.

## Naming Gate

- `FlowStepUpdateRequest` is acceptable because it aligns with the existing Flow authoring API axis and appears clearly in the final maintainer-map authoring/update section.
- No new helper, manager, processor, common, or generic owner is approved.
- Any new comment must explain the non-deferrable unique-constraint invariant or id semantics, not restate code.
- T061 changed names must be clear enough for the final `docs/flows/architecture.md` "where to change X" table.

## Peer Review

- Claude plan gate iter 1: changes required; valid blocker that id-based reorder can violate the non-deferrable `(flow_id, step_order)` unique constraint.
- Claude plan gate iter 2: changes required; valid blocker that `flow_authoring_router.py` must be in allowed files.
- Claude plan gate iter 3: `GREEN_LIGHT: yes`, `MIN_SCORE: 8`, artifact `.codex/artifacts/claude-peer-loop-t060-draft-step-identity-worker-judge-final-20260526T162643Z.md`.
- Antigravity synthesis: `GREEN_LIGHT: yes`, `MIN_SCORE: 8`, artifact `.codex/artifacts/antigravity-peer-loop-t060-draft-step-identity-antigravity-synthesis-20260526T163219Z.md`.
- Accepted Antigravity concerns: require session flush between temporary and final reorder phases; treat `_temp_` ids as stable frontend keys before submit; record frontend clone/sentinel behavior as a Worker stop rule if source evidence shows it is shipped.

## Maintainer Doc Readiness

T060 does not write `docs/flows/architecture.md`. It records the ownership map needed for T901:

- draft authoring request owner: Flow authoring API models;
- draft identity owner: `FlowStep.id`;
- update validation owner: `FlowService.update_flow`;
- persistence owner: `FlowRepository._sync_flow_steps`;
- frontend payload owner: `FlowEditor`;
- generated-client owner: `frontend/packages/intric-js/src/types/schema.d.ts`.
