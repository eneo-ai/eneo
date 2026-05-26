# T030 Step Identity Preflight

## Decision

T030 recommends a migration-first step-identity slice before the source/API/frontend id-owned draft persistence work. The next task should be a read-only Judge that converts this Scout evidence into a small migration Worker for runtime step identity decoupling and backfill.

Do not activate the current T012 source-only Worker as written. Published snapshots are clean enough to delete the preseed fallback later, but runtime history already has null `step_id` rows and the `flow_step_results.step_id` / `flow_step_attempts.step_id` columns still foreign-key mutable draft `flow_steps.id` with `ON DELETE SET NULL`. Tightening draft sync before that FK is removed or hardened can create more nulled runtime history.

## Concept Inventory

| Concept | Current locations | Behavior differences | Canonical owner | Merge/delete path |
|---|---|---|---|---|
| Draft step identity | `backend/src/intric/flows/domain/flow.py:39`; `backend/src/intric/flows/infrastructure/flow_repo.py:118`; `backend/src/intric/flows/infrastructure/flow_repo.py:752` | Domain has `FlowStep.id`, but repository write path omits it and `_sync_flow_steps` updates by `step_order`. | `FlowStep.id` persisted by `FlowRepository`. | After migration-first runtime decoupling, make update payload round-trip step ids and change repository sync to id-owned. |
| Authoring API step shape | `backend/src/intric/flows/api/flow_models.py:444`; `backend/src/intric/flows/api/flow_models.py:527`; `backend/src/intric/flows/api/flow_assembler.py:38` | Public response exposes `FlowStepPublic.id`, but create/update request uses `FlowStepCreateRequest` without `id`, and assembler drops identity. | Separate create/update schema or explicit upsert semantics owned by Flow authoring API models. | Prefer a dedicated update schema with required id for existing steps before T012 source work; do not silently add optional id to the create schema. |
| Frontend step patch identity | `frontend/apps/web/src/lib/features/flows/FlowEditor.ts:74`; `frontend/apps/web/src/lib/features/flows/FlowEditor.ts:106`; `frontend/apps/web/src/lib/core/editing/getDiff.ts:201` | Web editor strips temp ids if present, but `editableFields.steps` omits `id`, so persisted ids are not sent in normal PATCH diffs. | Flow editor draft state and generated Flow API type. | Source Worker must preserve real step ids in PATCH payloads and strip only `_temp_` ids. |
| Secret merge identity | `backend/src/intric/flows/application/flow_service.py:673` | Secret sentinels merge by `step_order`; reorders can merge stored secrets into the wrong step. | `FlowService` application write path using `FlowStep.id`. | Change to id-first only after update payload can carry ids; add a red test proving secrets do not cross steps after reorder. |
| Published runtime snapshot identity | `backend/src/intric/flows/application/flow_service.py:713`; `backend/src/intric/flows/published_definition.py:107`; `backend/src/intric/flows/runtime/step_definition_parser.py:147` | Published definition writes `step_id`, `step_order`, and `assistant_id`; runtime parser already requires valid UUID identifiers. | Published definition snapshot and runtime parser. | Keep as canonical runtime owner; delete draft fallback once runtime persistence migration is safe. |
| Run preseed identity | `backend/src/intric/flows/application/flow_run_service.py:256`; `backend/src/intric/flows/application/flow_run_service.py:644` | `create_run` loads the published snapshot but still passes mutable `flow.steps` as fallback; `_build_preseed_steps` repairs missing snapshot identifiers by `step_order`. | Published snapshot parser. | Delete `fallback_steps` path and guard the signature after runtime tables are decoupled/backfilled. |
| Runtime result/attempt step identity | `backend/src/intric/flows/infrastructure/flow_run_repo.py:220`; `backend/src/intric/flows/infrastructure/flow_run_repo.py:2168`; `backend/src/intric/database/tables/flow_tables.py:684`; `backend/src/intric/database/tables/flow_tables.py:878` | Application writes snapshot ids, but DB columns are nullable and FK mutable draft `flow_steps.id` with `ON DELETE SET NULL`. | Runtime run snapshot identity stored as non-null UUID, independent of mutable draft rows. | First Worker should backfill nulls from pinned published snapshots, drop runtime-to-draft FKs, and make result/attempt `step_id` non-null if preflight passes. |
| Review/rerun/file step identity | `backend/src/intric/database/tables/flow_tables.py:989`; `backend/src/intric/database/tables/flow_tables.py:1096`; `backend/src/intric/database/tables/flow_tables.py:1287`; `backend/src/intric/database/tables/flow_tables.py:1358` | These rows store non-null `step_id` without direct `FlowSteps` FK. Rerun operation itself stores non-null step ids. | Runtime snapshot identity. | Preserve as evidence that runtime tables do not need to FK draft rows. |
| Evidence/export presentation identity | `backend/src/intric/flows/flow_run_export_json.py:689`; `backend/src/intric/flows/flow_run_evidence.py:116`; `backend/src/intric/flows/flow_run_evidence_export_manifest.py:53` | Evidence views often group and label by `step_order`, while identities are still emitted as `step_id`. | Runtime snapshot plus result/attempt projections. | Keep grouping by order for presentation, but do not use order as persistence identity. |

## Source Evidence

- `backend/src/intric/flows/domain/flow.py:39` defines `FlowStep` with `id: UUID | None`.
- `backend/src/intric/flows/infrastructure/flow_repo.py:118` builds DB row payloads without `id`.
- `backend/src/intric/flows/infrastructure/flow_repo.py:752` syncs steps by `step_order`, including deletes by missing order.
- `backend/src/intric/flows/api/flow_models.py:444` defines `FlowStepCreateRequest` without `id`; `backend/src/intric/flows/api/flow_models.py:527` reuses it for update.
- `backend/src/intric/flows/api/flow_assembler.py:38` converts request steps to domain steps without `id`.
- `frontend/apps/web/src/lib/features/flows/FlowEditor.ts:74` strips `_temp_` ids if present, but `frontend/apps/web/src/lib/features/flows/FlowEditor.ts:106` omits `id` from editable step fields.
- `backend/src/intric/flows/application/flow_service.py:673` merges step config secrets by `step_order`.
- `backend/src/intric/flows/application/flow_service.py:713` builds published definitions; `backend/src/intric/flows/application/flow_service.py:725` includes `step_id`, `step_order`, and `assistant_id`.
- `backend/src/intric/flows/runtime/step_definition_parser.py:147` rejects invalid `step_id` and `assistant_id`; `backend/src/intric/flows/runtime/models.py:32` models runtime steps with non-null UUID ids.
- `backend/src/intric/flows/application/flow_run_service.py:273` still passes `fallback_steps=flow.steps`; `backend/src/intric/flows/application/flow_run_service.py:657` builds the fallback by order.
- `backend/src/intric/database/tables/flow_tables.py:700` and `backend/src/intric/database/tables/flow_tables.py:894` keep runtime result/attempt `step_id` nullable and FK mutable `FlowSteps.id` with `ON DELETE SET NULL`.
- `backend/src/intric/database/tables/flow_tables.py:1018`, `backend/src/intric/database/tables/flow_tables.py:1116`, `backend/src/intric/database/tables/flow_tables.py:1302`, and `backend/src/intric/database/tables/flow_tables.py:1377` show adjacent runtime/review/file rows already store non-null `step_id` without a draft-step FK.

## Live Data Preflight

Ran read-only SQL against Docker container `eneo-41ae93-db-1`.

Published snapshot identity on database `postgres`:

| Metric | Value |
|---|---:|
| flow_versions | 254 |
| published_steps | 1684 |
| bad_step_identity_rows | 0 |
| bad_definition_envelopes | 0 |

Published snapshot identity on database `flows_migration_smoke`:

| Metric | Value |
|---|---:|
| flow_versions | 0 |
| published_steps | 0 |
| bad_step_identity_rows | 0 |
| bad_definition_envelopes | 0 |

Runtime row identity on database `postgres`:

| Metric | Value |
|---|---:|
| flow_step_results_total | 581 |
| flow_step_results_null_step_id | 4 |
| flow_step_attempts_total | 484 |
| flow_step_attempts_null_step_id | 2 |
| review_checkpoints_total | 15 |
| rerun_operations_total | 0 |
| rerun_invalidated_steps_total | 0 |
| step_input_files_total | 61 |
| step_result_files_total | 46 |

The six null runtime rows are recoverable from pinned published snapshots by `(flow_run.flow_version, step_order)`: 2/2 null attempts and 4/4 null results matched a snapshot `step_id`.

## Runnable SQL

Published snapshot threshold query. Stop threshold for deleting `fallback_steps=flow.steps`: `bad_step_identity_rows = 0` and `bad_definition_envelopes = 0` in the target database.

```sql
WITH published_versions AS (
  SELECT tenant_id, flow_id, version, definition_json
  FROM flow_versions
),
published_steps AS (
  SELECT
    fv.tenant_id,
    fv.flow_id,
    fv.version,
    step.ordinality::int AS step_index,
    step.value AS step_json
  FROM published_versions fv
  CROSS JOIN LATERAL jsonb_array_elements(
    CASE
      WHEN jsonb_typeof(fv.definition_json->'steps') = 'array'
      THEN fv.definition_json->'steps'
      ELSE '[]'::jsonb
    END
  ) WITH ORDINALITY AS step(value, ordinality)
),
bad_steps AS (
  SELECT *
  FROM published_steps
  WHERE nullif(step_json->>'step_id', '') IS NULL
     OR nullif(step_json->>'assistant_id', '') IS NULL
     OR (
       step_json ? 'step_id'
       AND nullif(step_json->>'step_id', '') IS NOT NULL
       AND (step_json->>'step_id') !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
     )
     OR (
       step_json ? 'assistant_id'
       AND nullif(step_json->>'assistant_id', '') IS NOT NULL
       AND (step_json->>'assistant_id') !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
     )
),
bad_envelopes AS (
  SELECT tenant_id, flow_id, version
  FROM published_versions
  WHERE definition_json->>'schema_version' IS DISTINCT FROM '1'
     OR jsonb_typeof(definition_json->'steps') IS DISTINCT FROM 'array'
)
SELECT 'flow_versions' AS metric, count(*)::text AS value FROM published_versions
UNION ALL
SELECT 'published_steps', count(*)::text FROM published_steps
UNION ALL
SELECT 'bad_step_identity_rows', count(*)::text FROM bad_steps
UNION ALL
SELECT 'bad_definition_envelopes', count(*)::text FROM bad_envelopes;
```

Runtime null recovery query. Stop threshold for making `step_id` non-null: every null result/attempt row must be recoverable from the pinned published snapshot.

```sql
WITH result_nulls AS (
  SELECT 'result' AS source_table, r.id, r.flow_run_id, r.flow_id, r.tenant_id, r.step_order, r.status, fr.flow_version
  FROM flow_step_results r
  JOIN flow_runs fr ON fr.id = r.flow_run_id AND fr.tenant_id = r.tenant_id AND fr.flow_id = r.flow_id
  WHERE r.step_id IS NULL
),
attempt_nulls AS (
  SELECT 'attempt' AS source_table, a.id, a.flow_run_id, a.flow_id, a.tenant_id, a.step_order, a.status, fr.flow_version
  FROM flow_step_attempts a
  JOIN flow_runs fr ON fr.id = a.flow_run_id AND fr.tenant_id = a.tenant_id AND fr.flow_id = a.flow_id
  WHERE a.step_id IS NULL
),
nulls AS (
  SELECT * FROM result_nulls
  UNION ALL
  SELECT * FROM attempt_nulls
),
published_step AS (
  SELECT
    n.source_table,
    n.id,
    n.flow_run_id,
    n.flow_id,
    n.tenant_id,
    n.step_order,
    n.status,
    n.flow_version,
    step.value->>'step_id' AS snapshot_step_id,
    step.value->>'assistant_id' AS snapshot_assistant_id
  FROM nulls n
  LEFT JOIN flow_versions fv
    ON fv.flow_id = n.flow_id
   AND fv.tenant_id = n.tenant_id
   AND fv.version = n.flow_version
  LEFT JOIN LATERAL jsonb_array_elements(
    CASE
      WHEN jsonb_typeof(fv.definition_json->'steps') = 'array'
      THEN fv.definition_json->'steps'
      ELSE '[]'::jsonb
    END
  ) AS step(value)
    ON (step.value->>'step_order')::int = n.step_order
)
SELECT source_table, status, count(*) AS rows, count(snapshot_step_id) AS recoverable_from_snapshot
FROM published_step
GROUP BY source_table, status
ORDER BY source_table, status;
```

## Decision Tree

1. If published snapshots have missing/invalid `step_id` or `assistant_id`, do not remove the preseed fallback. Add a backfill/migration task for `flow_versions.definition_json` first.
2. If runtime result/attempt rows have null `step_id` values that are not recoverable from pinned published snapshots, stop and request a data decision.
3. If runtime nulls are recoverable, run the migration-first Worker:
   - backfill null `flow_step_results.step_id` and `flow_step_attempts.step_id` from `(flow_runs.flow_version, flow_versions.definition_json.steps[*].step_order)`;
   - drop `flow_step_results_step_id_fkey` and `flow_step_attempts_step_id_fkey`;
   - make both columns non-null;
   - update `FlowStepResults.step_id` and `FlowStepAttempts.step_id` table models to non-optional UUID.
4. After migration-first is verified, activate a source/API/frontend Worker for id-owned draft persistence and preseed fallback deletion.

Do not add `flow_version_steps`; no relational query need was found.

## Proposed Next Judge

Create or activate a read-only Judge task before any Worker implementation:

**T032:** Approve the migration-first runtime step identity Worker from T030 evidence. Decide the exact migration/backfill allowed files, downgrade posture, migration test shape, and verification commands. Do not allow source/API/frontend id-owned draft persistence in this task.

Recommended T032 output:

- Decision: approve or reject migration-first.
- Exact Worker objective.
- Allowed files.
- Red tests.
- Migration preflight SQL.
- Verification commands.
- Stop conditions.

## Candidate Migration Worker

Recommended objective:

> Backfill nullable runtime result/attempt `step_id` from pinned published snapshots, then decouple those columns from mutable draft `flow_steps` and enforce non-null runtime step identity.

Proposed allowed files:

- `backend/alembic/versions/<new>_flow_runtime_step_identity_snapshot_owned.py`
- `backend/src/intric/database/tables/flow_tables.py`
- `backend/src/intric/flows/infrastructure/flow_run_repo.py`
- `backend/tests/integration/flows/test_flow_runtime_step_identity_migration.py`
- `backend/tests/unittests/flows/test_flow_rerun_data_model.py`
- `backend/tests/unittests/flows/test_flow_review_checkpoint_data_model.py`
- `docs/goals/flows-clean-architecture-2026-05-25/state.yaml`

Stop conditions:

- Any null runtime row cannot be recovered from its pinned published snapshot.
- Migration needs to change retention, service-key identity, webhook delivery, Flow AI Builder, or `flow_version_steps`.
- Migration cannot be made downgrade-safe enough for the repo's migration policy.
- Required edits exceed the allowed files.
- Dirty unrelated files would need to be touched.

Red tests:

- Migration test seeds a published version with valid step ids, a flow run pinned to it, and result/attempt rows with null `step_id`; upgrade backfills both from the snapshot.
- Migration test proves the backfill is tenant-scoped and does not match a cross-tenant published version with the same `flow_id`/`version` shape.
- Migration test proves an unrecoverable null result/attempt row aborts the upgrade before `NOT NULL` is applied.
- Migration test proves the `flow_step_results_step_id_fkey` and `flow_step_attempts_step_id_fkey` constraints are gone after upgrade.
- Migration test proves result/attempt `step_id` columns are non-null after upgrade.
- Migration round-trip test documents downgrade posture: schema reversible, recovered UUID data not reverted to null.
- Data model unit test proves `FlowStepResults.step_id` and `FlowStepAttempts.step_id` are not optional in the SQLAlchemy table model.
- Repository typing cleanup test/static check proves stale `row.step_id is None` guards are removed from `flow_run_repo.py`.

Verification commands:

- `cd backend && uv run pytest -m migration_isolation tests/integration/flows/test_flow_runtime_step_identity_migration.py -q`
- `cd backend && uv run pytest tests/unittests/flows/test_flow_rerun_data_model.py tests/unittests/flows/test_flow_review_checkpoint_data_model.py -q`
- `cd backend && uv run pytest tests/unittests/flows/test_flow_run_service.py tests/unittests/flows/test_published_definition_contract.py -q`
- `cd backend && uv run pytest tests/unittests/flows -q`
- `cd backend && uv run pyright src/intric/database/tables/flow_tables.py src/intric/flows/infrastructure/flow_run_repo.py`
- `git diff --check`

## Later Source/API/Frontend Worker Requirements

After migration-first, the source Worker should:

- Introduce a real update step schema or documented upsert semantics; do not add ambiguous optional `id` to create without a decision.
- Preserve real step ids in frontend PATCH diffs and strip only temp ids.
- Make `_sync_flow_steps` id-owned.
- Make `_merge_step_secrets` id-first and add a red test that secrets do not cross steps after reorder.
- Remove `_build_preseed_steps(... fallback_steps=flow.steps)` and add a guard test that invalid/missing snapshot identifiers fail without reading mutable draft state.
- Include strict pyright and generated-client/OpenAPI checks if API schemas change.

## Consolidation Effect

- Reused existing owner: published definition/runtime parser remains runtime identity owner; `FlowStep.id` remains draft identity owner.
- Logic moved from: mutable draft fallback in run preseed will later be removed in favor of snapshot-only parsing.
- Logic deleted now: none in T030; proposed migration deletes runtime-to-draft FK dependency.
- Duplicate path removed next: source/API/frontend Worker removes draft-state repair of invalid published snapshots.
- New code added: one migration and focused migration tests; existing owners are insufficient because physical DB constraints currently let draft deletion null runtime history.
- Why existing owners were insufficient: runtime code already writes snapshot ids, but DB schema still treats them as optional references to draft rows.
- Guard/test preventing duplicate logic from returning: migration tests for no FK/non-null columns, later guard test for no `fallback_steps`.
- Net Flow logic surface area: reduced after migration because runtime step identity no longer depends on mutable authoring rows.

## Non-Goals

- No retention changes.
- No service-key identity changes.
- No webhook outbox work.
- No Flow AI Builder cleanup unless directly required by a Flow proper contract.
- No `flow_version_steps`.
- No source/API/frontend id-owned draft persistence before the migration-first Judge/Worker.

## Peer Review

Claude plan gate artifact: `.codex/artifacts/claude-peer-loop-t030-step-identity-preflight-20260526T041730Z.md`.

Valid concerns accepted:

- Migration-first should be the explicit Scout recommendation.
- A standalone T012 source/API/frontend Worker risks more `ON DELETE SET NULL` runtime history before FK decoupling.
- Do not add ambiguous optional `id` to `FlowStepCreateRequest` without a create/update schema decision.
- Add a later cross-step secret leakage test and preseed no-draft-read guard.
- Avoid speculative order fallback unless a real no-id caller is proven.
- Embed the runtime recovery preflight in the migration and abort on unrecoverable null rows.
- Document downgrade as schema-reversible but data-forward: recovered UUIDs are not reverted to null.
- Include `flow_run_repo.py` in the migration Worker allowed files if non-null table metadata makes stale `step_id is None` guards dead code.

Antigravity synthesis artifact: `.codex/artifacts/antigravity-peer-loop-t030-step-identity-migration-first-synthesis-20260526T042613Z.md`.
