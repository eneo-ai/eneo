# Knowledge document versions — implementation contract

## Outcome

Eneo keeps one complete searchable version active for each logical knowledge
document. A replacement becomes active only after its text, chunks, and
embeddings are ready in one transaction. Failure preserves the previous active
version. Byte-identical input is a no-op.

PostgreSQL remains a complete default deployment. Compatible object storage is
optional and only affects original file-byte placement; searchable knowledge
text, chunks, embeddings, and version state remain in PostgreSQL/pgvector.

## Canonical owners

- `InfoBlobs` stores complete versions using `source_id` and
  `active|superseded` state.
- The partial unique index on active `source_id` is the final concurrency fence.
- `InfoBlobService.publish_info_blob_without_validation` owns non-crawler
  publication.
- `persist_batch` retains the crawler's existing bounded two-phase embedding and
  publication path.
- Repository queries own active-only product projections and whole-family
  deletion.
- Exact historical IDs remain readable for saved citations and authorization
  until an authorized deletion removes the complete source family.

## Required behavior

1. Lock the logical source identity and current active row.
2. Return the existing row without embedding when the SHA-256 digest is equal.
3. Otherwise supersede the current row, insert the replacement and all chunks,
   and update size within one savepoint/transaction.
4. Roll back the whole replacement on quota, embedding, chunking, database, or
   timeout failure.
5. Product lists, retrieval, counts, sizes, crawler bootstrap, and stale cleanup
   use active versions only; quota enforcement includes retained versions.
6. Saved Question/Session/Analysis references and exact-ID authorization may
   read a superseded row.
7. Explicit deletion and source-owner cascades remove every version and chunk.
8. An unchanged crawler page remains in stale reconciliation even when another
   prepared page later rolls back.

## Migration and recovery

Legacy rows are backfilled as `source_id=id, version_state=active` in bounded
PostgreSQL batches. The schema adds validated checks, non-null columns, an
indexed source lookup, and a partial unique active-source index without server
defaults. A separate no-op Alembic merge revision joins the parallel assistant
permission migration, so rolling versioning back does not undo unrelated
permissions.

Downgrade is allowed before any source has history. Once a replacement creates
a superseded row, downgrade fails closed; recover forward or restore the paired
pre-upgrade database backup.

## Deliberate non-goals

- no generation/job table, leases, retry pipeline, or automatic cleanup;
- no provider-specific storage behavior or object-storage requirement;
- no public API for browsing version history;
- no per-tenant storage routing or multi-tenancy expansion;
- no Flow adoption or migration of original file bytes;
- no speculative vector-index tuning without measured query evidence.

## Verification evidence

- PostgreSQL publication/failure/reference packet: 25 passed.
- PostgreSQL 13 migration upgrade/downgrade/re-upgrade/history fence: 1 passed.
- Backend non-integration suite: 4,077 passed, 1,309 deselected.
- Whole-backend Pyright: 0 errors, 0 warnings, 0 informations.
- Changed Python Ruff/format, OpenAPI generated-schema drift, docs build, diff
  check, and Goal-board checker: green.
- Resumable Claude session `knowledge-document-versions`, planning iteration 4
  and final commit-gate iteration 5: `GREEN_LIGHT: yes`, `MIN_SCORE: 8`.

Follow-up #571 work may add a durable ingestion pipeline, retention, and
publication UI only when those product requirements are implemented. They are
not compatibility requirements for this slice.
