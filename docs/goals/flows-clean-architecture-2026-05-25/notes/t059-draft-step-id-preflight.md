# T059 Draft Step Id Preflight

## Summary

T059 reconfirmed that the remaining draft step identity issue is a real correctness bug in the authoring update path, not a generic cleanup task. The current source has a canonical `FlowStep.id`, but the update request shape drops it, the API assembler cannot carry it, the repository syncs draft rows by `step_order`, and `FlowService._merge_step_secrets()` preserves redacted HTTP secrets by `step_order`. Reordering steps can therefore attach one step's stored secret to another step.

The first safe Worker should not be backend-only. The main frontend caller keeps `FlowStep.id` in editor state, but its generated PATCH diff excludes `id`, so a backend-only change would create a typed path that the primary UI still does not use.

Recommended next task: a read-only Judge, `T060`, should approve the smallest implementation slice for "draft authoring update preserves FlowStep.id across request, editor payload, service secret merge, and repository sync".

## Source Evidence

| Evidence | Finding |
|---|---|
| `backend/src/intric/flows/domain/flow.py:39` | `FlowStep` already has `id: UUID | None`; this is the existing canonical draft step identity field. |
| `backend/src/intric/flows/api/flow_models.py:447` | `FlowStepCreateRequest` has no `id`; it is used for create and update steps. |
| `backend/src/intric/flows/api/flow_models.py:530` | `FlowUpdateRequest.steps` is `list[FlowStepCreateRequest]`, so authoring PATCH cannot express persisted step ids. |
| `backend/src/intric/flows/api/flow_models.py:561` | `FlowStepPublic` exposes `id`, so clients receive the identity but cannot submit it back through the generated update contract. |
| `backend/src/intric/flows/api/flow_assembler.py:39` | `FlowAssembler.to_domain_step()` constructs `FlowStep` without `id`, even if an update schema later carries one. |
| `backend/src/intric/flows/application/flow_service.py:229` | `update_flow()` normalizes incoming steps, merges secrets, prepares persistence, and passes the aggregate to the repository; this is the right application owner for update-time secret preservation. |
| `backend/src/intric/flows/application/flow_service.py:673` | `_merge_step_secrets()` builds `stored_by_order` and selects stored config by `step_order`, not by `FlowStep.id`. |
| `backend/src/intric/flows/http_transport/secret_codec.py:121` | `merge_secrets_on_update()` correctly preserves sentinel fields once the right stored step is selected; the bug is not in the HTTP secret codec owner. |
| `backend/src/intric/flows/infrastructure/flow_repo.py:118` | `_step_to_db_row()` omits `id`, so repository inserts always rely on database-generated ids. |
| `backend/src/intric/flows/infrastructure/flow_repo.py:745` | `_sync_flow_steps()` indexes existing rows by `step_order`, updates by matched order, and deletes stale orders. |
| `backend/src/intric/database/tables/base_class.py:43` | `BasePublic.id` is a non-null primary key with `gen_random_uuid()` default. |
| `backend/src/intric/database/tables/flow_tables.py:184` | `FlowSteps` extends `BasePublic`; persisted draft steps already have durable ids. |
| `backend/src/intric/database/tables/flow_tables.py:245` | `FlowSteps` has uniqueness for `(flow_id, step_order)`, `(flow_id, id)`, and `(id, tenant_id)`. No schema migration is needed for a first id-preserving update slice. |
| `backend/src/intric/flows/application/flow_service.py:772` | Published definition snapshots already write `step_id` from `FlowStep.id`, so stable draft ids feed the published runtime contract. |
| `frontend/packages/intric-js/src/types/schema.d.ts:16918` | Generated `FlowStepCreateRequest` lacks `id`. |
| `frontend/packages/intric-js/src/types/schema.d.ts:19997` | Generated `PartialFlowUpdateRequest.steps` currently uses `FlowStepCreateRequest[]`, so generated client consumers cannot type an update step id. |
| `frontend/apps/web/src/lib/features/flows/FlowEditor.ts:74` | `FlowEditor` is the frontend update payload owner for draft Flow edits. |
| `frontend/apps/web/src/lib/features/flows/FlowEditor.ts:77` | The UI strips temporary ids before calling the API, but this only runs on ids present in `cleanChanges.steps`. |
| `frontend/apps/web/src/lib/features/flows/FlowEditor.ts:109` | `editableFields.steps` omits `id`, so `getDiff()` excludes persisted step ids from PATCH payloads. |
| `frontend/apps/web/src/lib/core/editing/getDiff.ts:201` | Array diffs include only the configured fields; omitted `id` fields are not sent. |
| `frontend/apps/web/src/lib/features/flows/FlowEditor.ts:751` | The UI already has a stable step key preference: persisted `id`, then `assistant_id`, then index. This is caller evidence that id ownership is intended. |
| `frontend/apps/web/src/lib/features/flows/FlowEditor.test.ts:615` | Existing save-flush coverage asserts step update payload content, making it the natural frontend red-test home. |
| `backend/src/intric/flows/application/flow_draft_materialization.py:145` | Materialization still references existing steps by `existing_step_<step_order>`, but this is outside the first Worker unless Judge proves it blocks the request -> repository -> secret-merge slice. |

## Concept Inventory

| Concept | Current locations | Behavior differences | Canonical owner | Merge/delete path |
|---|---|---|---|---|
| Draft step identity in authoring updates | `FlowStep.id`, `FlowStepPublic.id`, missing from `FlowUpdateRequest.steps`, missing from generated `PartialFlowUpdateRequest.steps`, omitted from `FlowEditor` diff | Backend returns ids, frontend stores ids, but PATCH drops ids and backend syncs by order | `FlowStep.id` with Flow authoring API request schema and `FlowEditor` update payload as adapters | Add an update-specific step schema that carries `id`, regenerate client, include `id` in FlowEditor step diffs, and remove order-owned update behavior where id evidence exists. |
| Stored HTTP secret preservation | `FlowService._merge_step_secrets()`, `http_transport.secret_codec.merge_secrets_on_update()` | Codec preserves sentinels correctly; service selects the wrong stored step after reorder because it keys by order | `FlowService._merge_step_secrets()` selects the stored step; `merge_secrets_on_update()` remains the leaf codec | Deepen service selection to id-first and keep codec unchanged. Add behavior test proving step B keeps step B's secret after reorder. |
| Draft step persistence sync | `FlowRepository._sync_flow_steps()`, `FlowSteps` constraints | Persistence rows already have ids; sync ignores incoming ids and treats order as identity | `FlowRepository._sync_flow_steps()` owns row matching and persistence operations | Deepen repository sync to match/update by `FlowStep.id` for existing rows, insert id-less new steps, and delete existing ids not retained. |
| Frontend draft edit payload | `FlowEditor`, `ResourceEditor.getDiff()` | Editor has ids and strips temp ids, but `editableFields.steps` excludes `id`, so the strip branch does not help normal saves | `FlowEditor` owns Flow-specific draft update shaping; `ResourceEditor` remains generic diff utility | Add `id` to FlowEditor step editable fields and test that existing ids are sent while `_temp_` ids are stripped. Do not change generic `ResourceEditor`. |
| Published runtime step identity | `FlowService._step_to_definition()`, `published_definition.py`, runtime parsers | Published snapshots already consume `FlowStep.id` into `step_id`; this tranche should preserve better draft ids before publish | Published definition owner remains unchanged for this slice | No implementation in first Worker unless tests reveal breakage; cite as maintainer-doc readiness evidence. |
| AI Builder/draft materialization existing-step references | `flow_draft_materialization.py`, `flow_draft_materialization_executor.py` | Existing refs are order-based and materialized `FlowStep` omits id | Materialization owner, not authoring API update owner | Defer to a later Scout/Judge unless T060 proves it blocks the first Worker. This task is Flow AI Builder-adjacent and must not broaden the slice by default. |

## Persisted Data And Caller Preflight

- Persisted data shape: `FlowSteps` already has a non-null UUID primary key through `BasePublic.id`, with uniqueness constraints including `(flow_id, id)` and `(id, tenant_id)`. The first Worker does not require a schema migration.
- Caller shape: the main Flow editor receives and stores `FlowStepPublic.id`, uses it for UI selection/stable keys, and already strips `_temp_` ids before API submission. The missing piece is that the Flow-specific diff whitelist omits `id`, so the normal PATCH payload does not include persisted step ids.
- Compatibility risk: external clients generated from the current OpenAPI contract cannot type an update step id. Because public API/OpenAPI/generated-client changes must stay in the same tranche, the first Worker should include generated client updates. T060 should decide whether id-less update steps are accepted only for new steps, rejected for existing persisted steps, or temporarily order-matched with a documented deletion trigger.

## First Worker Recommendation

Recommended Worker title:

`fix(flows): preserve draft step identity through authoring updates`

Recommended invariant:

Existing draft steps are updated by `FlowStep.id`, not by `step_order`; `step_order` remains ordering metadata. New draft steps may omit `id` and receive a database id. Redacted HTTP secret sentinels must preserve the stored secret attached to the same `FlowStep.id` after reorder.

Recommended allowed files:

- `docs/goals/flows-clean-architecture-2026-05-25/state.yaml`
- `docs/goals/flows-clean-architecture-2026-05-25/notes/t060-draft-step-id-worker-judge.md`
- `backend/src/intric/flows/api/flow_models.py`
- `backend/src/intric/flows/api/flow_assembler.py`
- `backend/src/intric/flows/application/flow_service.py`
- `backend/src/intric/flows/infrastructure/flow_repo.py`
- `backend/tests/unittests/flows/test_flow_models.py`
- `backend/tests/unittests/flows/test_flow_review_policy.py`
- `backend/tests/unittests/flows/test_flow_service.py`
- `backend/tests/integration/flows/test_flow_repository.py`
- `frontend/packages/intric-js/src/types/schema.d.ts`
- `frontend/apps/web/src/lib/features/flows/FlowEditor.ts`
- `frontend/apps/web/src/lib/features/flows/FlowEditor.test.ts`

Recommended red tests:

- `backend/tests/unittests/flows/test_flow_service.py`: update a draft with two stored HTTP-authored output configs, swap their `step_order` values while preserving their ids, submit sentinel secrets, and assert each incoming step keeps the stored secret for the same id.
- `backend/tests/integration/flows/test_flow_repository.py`: create a two-step flow, update with the same step ids in swapped orders, and assert the persisted row ids remain attached to the same logical steps while `step_order` changes.
- `backend/tests/unittests/flows/test_flow_models.py`: assert create steps still do not accept or require persisted ids, while draft update steps accept optional ids.
- `backend/tests/unittests/flows/test_flow_review_policy.py` or `test_flow_models.py`: assert assembler preserves review policy and id when assembling an update step.
- `frontend/apps/web/src/lib/features/flows/FlowEditor.test.ts`: assert flushing a changed existing step sends its `id`, and assert `_temp_` ids are not sent.

Recommended verification commands:

```bash
cd backend && uv run pytest tests/unittests/flows/test_flow_service.py -k "secret and update_flow"
cd backend && uv run pytest tests/integration/flows/test_flow_repository.py -k "step id or reorder"
cd backend && uv run pytest tests/unittests/flows/test_flow_models.py tests/unittests/flows/test_flow_review_policy.py
cd backend && uv run pyright src/intric/flows/api/flow_models.py src/intric/flows/api/flow_assembler.py src/intric/flows/application/flow_service.py src/intric/flows/infrastructure/flow_repo.py tests/unittests/flows/test_flow_service.py tests/integration/flows/test_flow_repository.py tests/unittests/flows/test_flow_models.py tests/unittests/flows/test_flow_review_policy.py
cd backend && uv run ruff check src/intric/flows/api/flow_models.py src/intric/flows/api/flow_assembler.py src/intric/flows/application/flow_service.py src/intric/flows/infrastructure/flow_repo.py tests/unittests/flows/test_flow_service.py tests/integration/flows/test_flow_repository.py tests/unittests/flows/test_flow_models.py tests/unittests/flows/test_flow_review_policy.py
cd backend && uv run ruff format --check src/intric/flows/api/flow_models.py src/intric/flows/api/flow_assembler.py src/intric/flows/application/flow_service.py src/intric/flows/infrastructure/flow_repo.py tests/unittests/flows/test_flow_service.py tests/integration/flows/test_flow_repository.py tests/unittests/flows/test_flow_models.py tests/unittests/flows/test_flow_review_policy.py
cd frontend/apps/web && bun test src/lib/features/flows/FlowEditor.test.ts
cd frontend/packages/intric-js && bun run update
git diff --check
scripts/gate-local/anti_slippage.sh
```

T060 should refine the exact `-k` selectors after writing the Worker acceptance criteria.

Recommended stop rules:

- Need API/schema files beyond the allowed files.
- Need schema migration or persisted data repair.
- Cannot define clear semantics for unknown incoming step ids or id-less existing-step updates.
- Frontend/generated-client update cannot be generated cleanly from OpenAPI.
- The implementation would add a second step identity owner instead of deepening `FlowStep.id`, Flow authoring API schemas, `FlowService`, `FlowRepository`, and `FlowEditor`.

## Consolidation Effect For The Proposed Worker

- Reused existing owner: `FlowStep.id`, Flow authoring API schemas, `FlowAssembler`, `FlowService._merge_step_secrets()`, `FlowRepository._sync_flow_steps()`, and `FlowEditor`.
- Logic moved from: no new owner should be created; order-owned matching should move behind the existing id-owned authoring update path.
- Logic deleted: order-as-identity behavior for updates where persisted ids are available.
- Duplicate path removed: backend returning step ids while update contracts and editor payloads drop them.
- New code added: likely an update-specific draft step request schema such as `FlowDraftStepUpdateRequest`; existing `FlowStepCreateRequest` is insufficient because create steps should not claim persisted ids while update steps must be able to carry them.
- Why existing owners were insufficient: existing owners are sufficient for behavior, but the create/update schema is conflated; a draft-update schema name makes the authoring axis explicit and avoids teaching create requests about persisted ids.
- Guard/test preventing duplicate logic from returning: service reorder secret test, repository id-preservation integration test, model/assembler id test, and FlowEditor payload test.
- Net Flow logic surface area: preserved or reduced. A new schema type may add lines, but it removes a hidden split between public step identity and update/persistence identity.
- If increased, why necessary: any increase should be limited to the public contract distinction between create-step input and draft-update-step input.

## Naming Gate And Maintainer-Doc Readiness

- Prefer `FlowStep.id` for the domain field.
- If a new request schema is needed, prefer a name with the draft authoring/update axis, for example `FlowDraftStepUpdateRequest`; avoid `step_key`, `step_ref`, `step_handle`, `manager`, or `helper`.
- The final `docs/flows/architecture.md` should be able to place this under "Draft Flow authoring: step identity and update semantics" and the "where to change X" table should point maintainers to Flow authoring API schemas, `FlowAssembler`, `FlowService._merge_step_secrets()`, `FlowRepository._sync_flow_steps()`, and `FlowEditor`.
- Do not write the final architecture doc in this tranche. Preserve this note as evidence for the final docs Worker.

## Board Invariant Recommendation

The board invariant "no task with `receipt.result == done` may keep `status != done`" should be enforced as a lightweight PM/state verification command before docs/state commits. It should live in the goal maintenance workflow or a small local check, not in Flow source. T058 normalized one stale violation (`T055`) manually; future PM tasks should run a state-only invariant check before committing board updates.

## Commands Run

- `python3 -m json.tool /Users/ccimen/.codex/overnight-watchdog/flows-clean-architecture-watchdog.json` - pass; watchdog status `ok`, no blockers.
- `rg -n "Human Maintainer|Naming Gate|architecture\\.md|where to change|reuse|move|merge|delete|canonical owner|T059|T901" ...` - pass; confirmed durable maintainer-map, naming-gate, reuse/consolidation, T059, and T901 entries.
- `sed -n '60,235p' docs/goals/flows-clean-architecture-2026-05-25/goal.md` - pass; re-read non-negotiable constraints, reuse gate, maintainer map, naming gate.
- `sed -n '20,135p' docs/goals/flows-clean-architecture-2026-05-25/notes/roadmap-and-taskfiles.md` - pass; re-read reuse-before-inventing and final docs requirements.
- `sed -n '20,135p' docs/goals/flows-clean-architecture-2026-05-25/notes/new-codex-session-prompt.md` - pass; re-read session prompt requirements.
- `sed -n '5836,5910p' docs/goals/flows-clean-architecture-2026-05-25/state.yaml` - pass; confirmed active T059 and queued T901.
- `nl -ba` reads over Flow domain, API models, assembler, service, repository, database tables, frontend editor, ResourceEditor diff, generated schema, materialization, and tests - pass; evidence summarized above.
- `rg` searches for existing update-step schema names, draft step id callers, repository/service tests, generated-client schema references, and frontend update payload paths - pass; no existing update-specific step request schema found.
- `git status --short --branch` - pass; only known unrelated dirty/untracked baseline before T059 edits.
