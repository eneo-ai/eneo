# T138 Flow Runtime File Snapshot Judge

Date: 2026-05-27
Task: T138 read-only Judge
Decision: `approve_worker`
Approved next task: T139 Worker, `migration(flows-db): snapshot runtime input files for Flow runs`

## Standing Architecture Rule

For T139 and every later non-trivial Flow Judge/Worker, do not assume the current implementation is the correct model just because it exists.

Before improving an existing Flow path, answer:

1. What is the correct domain model if designed cleanly today?
2. What is the canonical owner of this concept?
3. Does the current implementation match that model?
4. If the current model is wrong, should it be replaced/refactored instead of improved?
5. What accidental compatibility, fallback, legacy, or duplicate path should be deleted?
6. Can the correct model be implemented in reviewable slices with tests and migration/preflight evidence?

Because Flow proper has no production users, prefer the long-term reliable model over preserving accidental behavior. Do not polish a bad abstraction.

## Decision

Approve the first implementation slice as **runtime input snapshots first**, with explicit rerun semantics and source-of-truth collapse.

Do not implement generated artifact snapshots, blob purge, admin purge, API tombstone endpoints, retention policy expansion, frontend changes, or generic Files lifecycle redesign in this slice.

This is the smallest slice that fixes the wrong runtime input model:

- public upload endpoints may keep storing principal-owned `Files` rows as upload staging;
- run creation and rerun turn submitted staging bytes into Flow-owned, run-private `FlowRunFileSnapshot` rows;
- `FlowRunStepInputFiles` remains the relationship owner for run/step/attempt/ordinal bindings and points to the runtime snapshot;
- runtime execution reads input files from current-attempt xrefs and snapshots, not from `run.input_payload_json` or principal `FileRepository.get_list_by_id_for_owner`;
- `run.input_payload_json` and rerun `step_inputs_json` remain request/audit payloads, not runtime byte truth.

Generated artifacts are deliberately deferred because they have a different write-order problem: `output_runtime.py` and `template_fill_runtime.py` save `Files` rows before `executor.py` persists result-file xrefs. That needs a later Worker with generated-artifact pending/atomic/reconciler design. Input snapshots come first because runtime input bytes are already known at run creation/rerun acceptance, so this slice can make execution deterministic and remove the JSON/principal-file read path before retention work.

## Architecture Challenge

| Question | Answer |
| --- | --- |
| Correct model if designed today | Runtime uploads are staging inputs until run creation/rerun acceptance. The Flow runtime then owns immutable run-private file snapshots. Runtime execution, retention, and future evidence tombstones use Flow-owned snapshots. |
| Current model | Uploads and generated artifacts are principal-owned `Files`. Run creation stores input file IDs in both JSON and xrefs. Runtime execution reads JSON IDs and loads principal files by owner. Rerun stores `step_inputs_json` but currently lacks a clear runtime file-binding path. |
| Is current model wrong or only incomplete? | Wrong for runtime input bytes: byte lifetime and execution depend on mutable/shared principal file rows and duplicate ID paths. Rerun is incomplete because requested input changes are not connected to typed runtime file ownership. |
| Refactor/replace needed? | Yes. Replace runtime input byte ownership; keep public upload staging and relationship xrefs. |
| Why not just improve the existing path | Retention flags on xrefs or `DataRetentionService` nulling would not make principal `Files` run-private. Extending `Files` with `scope/flow_run_id` would push Flow lifecycle state into a shared file owner and broaden non-Flow semantics. |
| Canonical owner | `FlowRunFileSnapshot` owns run-private content; `FlowRunStepInputFiles` owns step/run/attempt relationship; `FlowRunService` owns creation copy; `FlowRunRerunService` owns rerun request validation; `FlowRunRepository` owns persistence/read projection; runtime step input resolution consumes snapshots. |
| Existing code to reuse/move/merge/delete | Reuse `FlowFileUploadService` validation and `FileService` staging. Reuse xrefs for relationship order. Move runtime input loading out of `RuntimeInputFileRepository.get_list_by_id_for_owner`. Delete or replace that principal-file Protocol; do not add a new one-implementation Protocol when `FlowRunRepository` is the concrete persistence owner. Delete/guard the runtime path that treats JSON file IDs as execution truth. |
| Compatibility paths to delete | For input execution, delete principal `FileRepository` ownership lookup as the runtime read path. Keep request JSON only as audit/request projection. |
| Tests that should be deleted/replaced | Keep existing retention/generated-artifact fences. Replace tests that assume runtime input bytes are loaded from `run.input_payload_json` with snapshot-based behavior tests. Do not delete retention tests in T139. |
| Migration/data preflight needed | Yes: new table, xref column replacement, backfill from current input xrefs, source-file `ON DELETE SET NULL`, tenant/run FKs, indexes, lock notes, downgrade behavior, and no generated artifact mutation. |
| Smallest reviewable slice | T139 input snapshots only, no retention purge, no API/frontend changes, and no generated artifact snapshots. |

## Owner Options

| Option | Verdict | Reason |
| --- | --- | --- |
| Deepen existing input xrefs by adding content columns | Reject | It would make relationship rows also store bytes. Reusing the same uploaded file across multiple steps would duplicate bytes and lifecycle state per relationship row. |
| Add `FlowRunFileSnapshot` as the Flow runtime content owner | Accept for first slice | It creates one Flow-owned content owner while xrefs remain relationships. T139 only permits `runtime_input`; later generated-artifact work must explicitly expand the owner after its orphan-window design. |
| Extend `Files` with `scope` / `flow_run_id` | Reject for T139 | It is cheaper, but it makes the shared Files table understand Flow run lifecycle and exposes all file consumers to a Flow-specific owner state. That is the coupling T125/T137 fenced off. |
| DataRetentionService-only changes | Reject | Retention is not the owner of runtime file truth. It should consume ownership metadata, not create it. |
| Generated artifacts first | Defer | Higher risk because generated bytes are created before result-file xrefs; needs atomic/pending/reconciler decision. |

## Approved Worker: T139

Suggested commit:

`migration(flows-db): snapshot runtime input files for Flow runs`

### Objective

Introduce Flow-owned runtime input file snapshots and make Flow runtime input execution read from those snapshots instead of mutable principal `Files` rows or JSON file IDs.

### Allowed Files

- `backend/alembic/versions/20260527_flow_runtime_file_snapshots.py`
- `backend/src/intric/database/tables/flow_tables.py`
- `backend/src/intric/flows/flow_run_file_snapshot.py`
- `backend/src/intric/flows/flow_run_step_inputs.py`
- `backend/src/intric/flows/application/flow_run_service.py`
- `backend/src/intric/flows/application/flow_run_rerun_service.py`
- `backend/src/intric/flows/infrastructure/flow_run_repo.py`
- `backend/src/intric/flows/runtime/input_files.py`
- `backend/src/intric/flows/runtime/step_input_resolution.py`
- `backend/src/intric/flows/runtime/transcription_runtime.py`
- `backend/src/intric/flows/runtime/models.py`
- `backend/src/intric/flows/runtime/executor.py`
- `backend/tests/integration/migrations/test_flow_runtime_file_snapshot_migration.py`
- `backend/tests/integration/flows/test_flow_run_repository.py`
- `backend/tests/integration/flows/test_flow_step_file_mapping_contract.py`
- `backend/tests/unittests/flows/test_flow_run_service.py`
- `backend/tests/unittests/flows/test_flow_run_rerun_service.py`
- `backend/tests/unittests/flows/test_flow_run_input_payload.py`
- `backend/tests/unittests/flows/test_flow_executor_runtime.py`
- `backend/tests/unittests/flows/test_flow_architecture_guards.py`
- `docs/goals/flows-clean-architecture-2026-05-25/state.yaml`

Stop and return to Judge if implementation requires FastAPI routers, public API models, generated client files, frontend files, `DataRetentionService`, generated artifact output code, Flow AI Builder, or generic Files service/repository changes beyond reading source.

### Data Model Direction

Add `flow_run_file_snapshots` as the Flow runtime content owner.

Required semantics:

- `id` is the runtime snapshot ID.
- `tenant_id`, `flow_id`, and `flow_run_id` are required.
- table has composite FKs to `flow_runs(id, tenant_id)` and `flow_runs(id, flow_id)` with `ON DELETE CASCADE`.
- `snapshot_kind` is required, typed in domain code as `Literal["runtime_input"]` or an equivalent domain enum, and constrained to `runtime_input`; do not add generated-artifact behavior in T139.
- `source_file_id` is nullable and references `files(id)` with `ON DELETE SET NULL`; source/staging files are audit context and must not be required for execution after snapshotting. Runtime-input snapshot creation must always start from a non-null submitted source file; the column is nullable only because later source-file deletion must not delete or invalidate the snapshot.
- content fields copy the source file metadata/content needed by runtime execution: `name`, `checksum`, `size`, `mimetype`, `file_type`, `text`, and `blob`.
- content presence invariant is `text IS NOT NULL OR blob IS NOT NULL`. Do not require XOR because the current `FileBaseWithContent` domain model permits both while requiring at least one content representation.
- do not copy or update shared `Files.transcription` as a runtime cache. Flow audio transcription is step-attempt derived text, not source-file content.
- do not add `content_state` in T139. Purge/tombstone states belong to the later retention Worker that owns those transitions.
- indexes cover the actual read/write shape: current-attempt xref lookup by `(flow_run_id, step_id, attempt_no, ordinal)`, snapshot lookup by `(tenant_id, flow_run_id)`, snapshot lookup by `(flow_run_id, snapshot_kind)`, source-file audit lookup, and a partial unique index enforcing one runtime-input snapshot per source file per run: `UNIQUE (flow_run_id, source_file_id) WHERE source_file_id IS NOT NULL AND snapshot_kind = 'runtime_input'`.
- new indexes must be created/dropped concurrently in autocommit blocks unless the Worker records a source-evidence-backed reason this local-only/pre-production migration intentionally accepts the lock.
- FKs and check constraints should use `NOT VALID` plus validation where supported, or record why a single migration is acceptable for this no-production-user Flow table shape.

`FlowRunStepInputFiles` should stop using `file_id` as runtime byte truth:

- replace the input xref `file_id` column with required `runtime_file_snapshot_id` FK to `flow_run_file_snapshots(id)`;
- do not add `source_file_id` to the xref. The snapshot row owns the source/staging pointer. Duplicating it on the relationship row would create a steady-state divergence path and exists only for downgrade convenience.
- drop the old ambiguous `file_id` name in the same migration;
- keep run/tenant/flow/step/attempt/ordinal uniqueness and ordering;
- xrefs remain relationship truth and runtime execution reads through them.

### Snapshot Copy Policy

Use **run-level source-file deduplication**, not per-binding byte copies:

- one snapshot per `(flow_run_id, source_file_id)` for `snapshot_kind='runtime_input'` when `source_file_id` is present;
- multiple step/attempt xrefs may point to the same `runtime_file_snapshot_id`;
- source-file identity is required when T139 creates a runtime-input snapshot, but may become null later if the source staging file is deleted; runtime must still use the snapshot row;
- the unique/dedup rule must not collapse distinct uploaded files that happen to share name, checksum, size, or content.

This preserves true snapshot semantics while avoiding N x byte duplication when the same upload is bound to multiple steps.

The partial unique index owns this invariant at schema level. Application code may select existing snapshots to avoid duplicate writes, but correctness must not depend on convention alone.

### Source Of Truth

T139 must make this invariant true:

> Runtime execution resolves submitted files from `FlowRunStepInputFiles.runtime_file_snapshot_id -> FlowRunFileSnapshot`, scoped to the current step attempt, not from `run.input_payload_json`.

`run.input_payload_json` remains the public request/audit payload. It may continue to contain submitted `file_ids` so public run records preserve the consumer request, but runtime must not load files from those IDs.

Rerun `step_inputs_json` remains the rerun request payload. It may drive snapshot/xref creation before execution, but it must not become a second runtime read path.

Runtime file metadata must make the owner clear. Request payloads may preserve submitted source `file_ids`, but execution metadata and provenance should identify `runtime_file_snapshot_id` values as the runtime byte owner. If a compatibility `file_ids` field remains in step input metadata, T139 must document whether those IDs are source-file IDs or snapshot IDs and add a guard test proving runtime never reloads bytes from that field.

The existing `RuntimeInputFileRepository` Protocol should be deleted or replaced by direct snapshot lookup on the concrete Flow run persistence owner. Do not add a new one-implementation `SnapshotResolver`/adapter Protocol just to keep the old shape; the stable boundary is run/step/attempt to ordered runtime snapshots.

### Audio Transcription Contract

Current source evidence shows audio runtime intentionally avoids the shared file transcription cache: `transcribe_audio_input` calls `transcriber.transcribe(..., persist_cache_to_file=False)`, and `resolve_transcribe_and_attach_audio_input` persists the combined transcript to `run.input_payload_json`, in-memory context, audit metadata, and step result/provenance metadata. T139 must preserve that behavior unless it returns to Judge.

For T139:

- `FlowRunFileSnapshot` owns source bytes, not per-step derived transcript text.
- Do not cache audio transcription on the snapshot or source `Files` row in T139.
- Rerun attempts that reuse an audio snapshot may re-transcribe, matching the current no-file-cache behavior.
- `run.input_payload_json[transkribering]` may remain the existing derived transcript projection for crash/audit/context compatibility, but it must not be used to resolve runtime file IDs or bytes.
- A later step-behavior/output-isolation task should choose the long-term owner for combined transcript text if the run-input projection remains a maintainability problem.

### Rerun Contract

T139 must define and test rerun file input behavior:

- rerun with new `step_inputs_json` creates or reuses run-level snapshots for submitted source file IDs and writes `FlowRunStepInputFiles` rows for the rerun root step at `root_attempt_no`;
- rerun without new file inputs for a step reuses the latest prior input snapshot relationships for the new attempt by creating new xref rows pointing to the same run-level snapshot IDs;
- downstream invalidated steps that use runtime file input must either receive cloned xref rows for their new attempt before resolution, or the Worker must stop and return to Judge when `test_rerun_downstream_step_with_runtime_file_input_keeps_input_xref_for_new_attempt` proves the current lifecycle needs a separate executor design;
- the preferred downstream rerun cloning owner is the concrete attempt-start lifecycle in `FlowRunRepository.create_or_get_attempt_started`, because downstream attempt numbers are resolved during execution rather than at rerun request acceptance;
- runtime resolution should be side-effect free: snapshot/xref creation or cloning belongs in service/repository/executor lifecycle code before `_resolve_step_input`, not inside byte rendering/parsing.

### Source File Delete Semantics

T139 intentionally changes runtime input relationship semantics:

- staging/principal `Files` rows may be deleted after run creation/rerun snapshotting;
- `FlowRunFileSnapshot.source_file_id` must be nullable and use `ON DELETE SET NULL`;
- runtime execution must still succeed from `runtime_file_snapshot_id`;
- tests must prove deleting the source `Files` row after run creation does not break input resolution.

### Downgrade / Rollback Contract

For T139 input snapshots:

- downgrade should restore the previous input xref `file_id` behavior from `flow_run_file_snapshots.source_file_id` when the source file still exists;
- when `flow_run_file_snapshots.source_file_id` is null or no longer resolves because a staging file was deleted after snapshotting, downgrade must reconstruct one replacement `Files` row per affected snapshot from the snapshot's copied bytes/metadata and the owning `flow_runs` principal fields (`principal_type`, `principal_user_id`, `principal_service_id`, `tenant_id`);
- downgraded xrefs that pointed at the same snapshot must point at the same reconstructed `Files` row;
- fail loudly only if the snapshot is corrupt enough that a valid replacement `Files` row cannot be created, such as missing content despite the content check, invalid owner identity, or tenant/run mismatch;
- since generated artifacts are not moved in T139, no generated-artifact bytes need to be backfilled to `Files`;
- before implementation, the Worker must record whether local no-production-user reality allows a single migration with backfill/set-not-null, or whether best practice still requires staged `NOT VALID` constraints and concurrent indexes.

### Red Tests / Failure Contracts

Add failing tests first:

- `test_create_run_snapshots_runtime_input_files`: run creation copies a submitted staging file into a Flow snapshot and xref stores `runtime_file_snapshot_id`.
- `test_runtime_input_reads_snapshot_not_request_file_id`: runtime resolution uses the snapshot row even if `run.input_payload_json` points to a missing or changed staging file.
- `test_same_uploaded_file_bound_to_multiple_steps_reuses_one_run_snapshot`: one uploaded source file bound more than once creates one run-level snapshot and multiple xrefs.
- `test_duplicate_runtime_input_snapshot_for_same_run_source_is_rejected_or_reused`: schema/application path enforces one snapshot per `(flow_run_id, source_file_id, runtime_input)`.
- `test_concurrent_snapshot_insert_for_same_source_file_collapses_to_one`: if the test harness can simulate the race, the partial unique index/retry path yields one snapshot; otherwise the migration/schema test must prove a second insert violates the partial unique index.
- `test_runtime_input_snapshot_survives_source_file_delete`: deleting the principal staging file after run creation does not break runtime input resolution.
- `test_rerun_with_new_step_inputs_creates_root_attempt_snapshots`: rerun input changes get current-attempt snapshot xrefs.
- `test_rerun_without_new_step_inputs_reuses_prior_runtime_input_snapshots_for_new_attempt`: rerun without file changes does not fall back to JSON/principal files.
- `test_rerun_downstream_step_with_runtime_file_input_keeps_input_xref_for_new_attempt`: proves invalidated downstream runtime-file steps either get current-attempt xrefs or trigger the stop rule.
- `test_audio_runtime_input_snapshot_preserves_no_file_cache_contract`: audio snapshots feed transcription without writing transcript caches to snapshot/source files; transcript projection remains separate from file ID resolution.
- migration test backfills existing input xrefs into snapshots, downgrades by reusing surviving source files, reconstructs replacement `Files` rows for snapshots whose source was deleted, and fails loudly only on corrupt snapshots that cannot produce a valid `Files` row.
- schema test rejects snapshot rows with both `text` and `blob` null and rejects cross-run/tenant mismatches.
- architecture guard: Flow runtime input resolution modules must not import `intric.files.file_repo.FileRepository`, call `FileRepository.get_list_by_id_for_owner`, or parse runtime file IDs directly from `run.input_payload_json` as byte truth.

Guard implementation should be AST/import based and targeted to runtime input modules such as `runtime/input_files.py` and `runtime/step_input_resolution.py`; do not blanket-ban legitimate generated-output/template-fill file persistence.

### Verification Commands

Run narrow red tests first, then after implementation:

```bash
cd backend && uv run pytest \
  tests/unittests/flows/test_flow_run_service.py \
  tests/unittests/flows/test_flow_run_rerun_service.py \
  tests/unittests/flows/test_flow_run_input_payload.py \
  tests/unittests/flows/test_flow_executor_runtime.py \
  tests/unittests/flows/test_flow_architecture_guards.py \
  tests/integration/flows/test_flow_run_repository.py \
  tests/integration/flows/test_flow_step_file_mapping_contract.py \
  tests/integration/migrations/test_flow_runtime_file_snapshot_migration.py \
  -q

cd backend && uv run ruff check \
  src/intric/database/tables/flow_tables.py \
  src/intric/flows/flow_run_file_snapshot.py \
  src/intric/flows/flow_run_step_inputs.py \
  src/intric/flows/application/flow_run_service.py \
  src/intric/flows/application/flow_run_rerun_service.py \
  src/intric/flows/infrastructure/flow_run_repo.py \
  src/intric/flows/runtime/input_files.py \
  src/intric/flows/runtime/step_input_resolution.py \
  src/intric/flows/runtime/transcription_runtime.py \
  src/intric/flows/runtime/models.py \
  src/intric/flows/runtime/executor.py \
  tests/unittests/flows/test_flow_run_service.py \
  tests/unittests/flows/test_flow_run_rerun_service.py \
  tests/unittests/flows/test_flow_run_input_payload.py \
  tests/unittests/flows/test_flow_executor_runtime.py \
  tests/unittests/flows/test_flow_architecture_guards.py \
  tests/integration/flows/test_flow_run_repository.py \
  tests/integration/flows/test_flow_step_file_mapping_contract.py \
  tests/integration/migrations/test_flow_runtime_file_snapshot_migration.py

cd backend && uv run ruff format --check <same files>

cd backend && uv run pyright \
  src/intric/database/tables/flow_tables.py \
  src/intric/flows/flow_run_file_snapshot.py \
  src/intric/flows/flow_run_step_inputs.py \
  src/intric/flows/application/flow_run_service.py \
  src/intric/flows/application/flow_run_rerun_service.py \
  src/intric/flows/infrastructure/flow_run_repo.py \
  src/intric/flows/runtime/input_files.py \
  src/intric/flows/runtime/step_input_resolution.py \
  src/intric/flows/runtime/transcription_runtime.py \
  src/intric/flows/runtime/models.py \
  src/intric/flows/runtime/executor.py \
  tests/unittests/flows/test_flow_run_service.py \
  tests/unittests/flows/test_flow_run_rerun_service.py \
  tests/unittests/flows/test_flow_run_input_payload.py \
  tests/unittests/flows/test_flow_executor_runtime.py \
  tests/unittests/flows/test_flow_architecture_guards.py \
  tests/integration/flows/test_flow_run_repository.py \
  tests/integration/flows/test_flow_step_file_mapping_contract.py \
  tests/integration/migrations/test_flow_runtime_file_snapshot_migration.py

cd backend && uv run alembic heads
cd backend && uv run alembic upgrade head
cd backend && uv run pytest tests/unittests/flows/test_flow_executor_runtime.py::test_runtime_input_snapshot_survives_source_file_delete -q
git diff --check
```

If local host tooling fails for the Alembic environment but Docker is healthy, use the devcontainer app mount at `/workspace` with `docker exec eneo-41ae93-eneo-1`.

### Peer Review Gates

Before T139 implementation:

- Claude plan gate with `--require-green --required-min-score 8 --timeout-seconds 1200`.
- Antigravity schema/data-integrity synthesis with `--spend-mode auto`, using the Claude artifact.

After T139 implementation:

- Claude commit gate with `--require-green --required-min-score 8 --timeout-seconds 1200`.
- Antigravity data-integrity/migration review before commit.

### Stop If

- Any required change touches FastAPI routers/API schemas/generated client/frontend/`DataRetentionService`/generated-artifact output path.
- Runtime execution still reads principal `Files` by request JSON file IDs after snapshots exist.
- Rerun file-input behavior cannot be made single-owner and current-attempt based inside the allowed lifecycle files.
- The migration cannot preserve or reconstruct downgrade rows when `flow_run_file_snapshots.source_file_id` is missing.
- The implementation requires a broad generic Files redesign or generic helper/manager/controller.
- The schema creates two independent lifecycle truths.
- The implementation adds `content_state`, purge/tombstone behavior, or generated-artifact snapshot behavior.
- Tests require `Any`, pyright ignores, `as any`, or mock-only behavior that does not prove the runtime failure.
- The Worker needs more than one new source module or starts splitting files for style rather than ownership.
- The patch exceeds 20 files or 800 LOC excluding the migration SQL/DDL and board receipt.
- The implementation adds tutorial docstrings, `Args:`/`Returns:` blocks on obvious methods, or comments that restate type signatures instead of explaining invariants.
- The patch becomes too broad to review as one schema/runtime slice; return to Judge with a smaller implementation plan.

## Consolidation Effect

- Reused existing owner: `FlowFileUploadService` for upload policy; `FlowRunStepInputFiles` for relationship ordering; `FlowRunRepository` for run persistence.
- Logic moved from: runtime file loading moves from principal `FileRepository.get_list_by_id_for_owner` plus request JSON IDs to Flow run snapshots.
- Logic deleted: runtime input execution path that treats `run.input_payload_json.file_ids` as byte truth.
- Duplicate path removed: request JSON and input xrefs can no longer both act as runtime source of truth.
- New code added: one Flow runtime file snapshot owner and focused repository/domain methods.
- Why existing owners were insufficient: xrefs do not own bytes; Files owns shared/principal bytes; DataRetentionService is an executor.
- Guard/test preventing duplicate logic from returning: targeted AST/import guard against runtime input direct FileRepository/request-JSON byte loading; unit/integration tests tying current-attempt xrefs to snapshots.
- Net Flow logic surface area: initially increased by schema/domain rows, but concept surface area reduced because runtime byte truth moves to one owner.
- If increased, why the increase is necessary: schema encodes the correct invariant and removes the wrong principal-file runtime owner.

## Naming Gate

Approved new names are domain-specific and suitable for `docs/flows/architecture.md` and the future "where to change X" table:

- `FlowRunFileSnapshot`
- `flow_run_file_snapshots`
- `runtime_file_snapshot_id`
- `source_file_id`
- `snapshot_kind = "runtime_input"`
