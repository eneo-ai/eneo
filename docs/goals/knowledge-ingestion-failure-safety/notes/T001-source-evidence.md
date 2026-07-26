# T001: Ingestion Failure Source Evidence

Task: `T001`
Kind: `scout`
Status: `done`

## Summary

Upload and transcription use `Worker.function`, which opens one ambient PostgreSQL transaction for the job. `TaskManager` catches ordinary processing exceptions, records `FAILED`, and does not re-raise, so earlier same-title deletion and replacement work commits with the failure. Extraction and transcription failures precede knowledge mutation; chunking and embedding failures follow it; zero chunks currently return success. Live searches found no equivalent bounded failure-safety task, so [#607](https://github.com/eneo-ai/eneo/issues/607) was created as a Task and true sub-issue of epic #549. The larger [#571](https://github.com/eneo-ai/eneo/issues/571) remains open and downstream.

## Verified Evidence

- `backend/src/eneo/worker/routes.py:81-90` registers upload and transcription through `Worker.function`.
- `backend/src/eneo/worker/worker.py:331-348` owns the ambient session and transaction for those routes.
- `backend/src/eneo/worker/task_manager.py:90-128` catches ordinary exceptions, writes `FAILED`, and lets the wrapper return normally.
- `backend/src/eneo/worker/upload_tasks.py:16-91` owns upload/transcription orchestration and calls `TextProcessor` inside the status context.
- `backend/src/eneo/info_blobs/text_processor.py:29-81` extracts before `process_text`, then creates/replaces the `InfoBlob`, embeds chunks, and updates size.
- `backend/src/eneo/info_blobs/info_blob_service.py:120-165` deletes same-title knowledge before inserting its replacement.
- `backend/src/eneo/database/tables/info_blob_chunk_table.py:12-24` makes chunks cascade with the deleted `InfoBlob`.
- `backend/src/eneo/embedding_models/infrastructure/datastore.py:87-145` chunks after replacement insertion, treats zero chunks as success, performs remote embedding before inserts, and writes chunks in existing batches.
- `backend/src/eneo/files/text.py:22-58` already owns typed extraction failures; no equivalent typed zero-extractable-text failure exists for upload/transcription.
- Real integration fixtures in `backend/tests/integration/conftest.py:181-304,400-599,657-756` use disposable PostgreSQL 16 with pgvector and Alembic at head.
- `backend/.env.template` and `.github/workflows/ci.yml` provide the repository-approved test bootstrap; no canonical-checkout `.env` may be read, copied, or linked.

## Mutation Timeline

1. `Worker.function` opens the ambient transaction and builds the user-scoped container.
2. `TaskManager` writes `IN_PROGRESS`.
3. Upload extraction or remote transcription completes before knowledge mutation.
4. `TextProcessor.process_text` deletes the same-title `InfoBlob`; PostgreSQL cascades its chunks.
5. The replacement `InfoBlob` is inserted.
6. Chunking, zero-chunk handling, remote embedding, and batched chunk inserts occur.
7. On an ordinary exception, `TaskManager` writes `FAILED` but suppresses the exception, so the ambient transaction commits pending knowledge changes.
8. On zero chunks, processing proceeds to `COMPLETE` with an empty replacement.

## Frozen Scope Disposition

- Reuse and deepen the current upload/transcription ingestion and transaction model.
- The bounded candidate is a nested savepoint around current destructive publication work so an exception rolls back knowledge mutations before `TaskManager` records `FAILED` in the ambient transaction.
- Add or reuse one typed failure when chunking yields no extractable text so the savepoint follows the same failure path.
- Do not split preparation, publication, and status into separate transactions here. That larger and ultimately cleaner shape is already owned by task #571's later generation-based ingestion slices; it would expand slice 0 into the work explicitly required to wait.
- Do not globally change `Worker.function`, crawler persistence, object-content owners, schema, lifecycle, retry, public contracts, or same-title concurrency semantics.

## RED Proofs To Freeze

- Existing exact `InfoBlob` and chunks survive chunking and embedding exceptions while the job is `FAILED`.
- Existing exact `InfoBlob` and chunks survive zero extractable text while the job is `FAILED`.
- A first-attempt chunking, embedding, or zero-text failure publishes no `InfoBlob` or chunks and leaves the job `FAILED`.
- Extraction failure preserves prior knowledge and records `FAILED` (expected baseline-safe because it precedes mutation).
- Upload and transcription converge on the same protected `process_text` mutation seam.

## Verification And Planning

- Baseline focused unit tests pass with `cd backend && bash -lc 'set -a; source .env.template; set +a; uv run pytest -q tests/unittests/ai_models/embedding_models/test_datastore.py tests/unittests/info_blobs/test_info_blobs_service.py'`.
- Baseline Ruff, format, and focused devcontainer Pyright pass.
- Development-task search: no equivalent bounded failure-safety task existed. [#607](https://github.com/eneo-ai/eneo/issues/607) is the exact Backend/S prerequisite, a real sub-issue of #549 and Project 5 Task with the epic's Backend/P1/2.X/Sundsvalls metadata. [#571](https://github.com/eneo-ai/eneo/issues/571) is referenced only as downstream work and must not be closed by this slice.
- Documentation impact: no docs change for this internal atomicity correction unless the implementation changes the public job/error contract.

## Stop Conditions

- A migration, generation/lifecycle table, retry framework, public interface, or object-content/crawler owner becomes necessary.
- The savepoint cannot preserve `FAILED` independently from the rolled-back knowledge work.
- Tests require a real provider credential or model network call.
- The implementation needs files outside the Judge-approved reduced set.

## Board Receipt Snippet

```yaml
receipt:
  result: done
  note: notes/T001-source-evidence.md
  summary: "Verified the defect and savepoint seam, found no exact task, and created bounded task #607 under epic #549 while leaving downstream #571 open."
```
