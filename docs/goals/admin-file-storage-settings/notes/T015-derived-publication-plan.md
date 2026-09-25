# T015 derived File/Icon readiness plan

## Decision

Use `object_contents.state` as the only source of truth for File-family and Icon
product visibility. Do not add File/Icon publication columns, a migration,
reconciler publication/deletion work, a shared lifecycle helper, or automatic
aggregate cleanup.

This narrows the frozen phrase “all-or-nothing visibility” without relaxing
it: an aggregate becomes visible on the final content
`PENDING -> AVAILABLE` commit, when every byte in its family is verified.
Visibility before HTTP delivery is ordinary committed-operation ambiguity, not
partial durability. Any caught error or cancellation before that point
compensates the whole new aggregate in a fresh transaction.

## Why the marker alternative is rejected

- `ObjectContentRepository.mark_backend_failure()` can change published
  `AVAILABLE` content to `FAILED`; a File/Icon marker would remain true and
  product reads would still need the content-state predicate.
- A crash after final content promotion but before a separate publish update
  would leave verified user data hidden with no permitted PR1 converger.
- Adding automatic deletion of stale aggregates violates this tranche’s
  explicit “no automatic cleanup” boundary.
- The marker therefore adds a second truth, migration, indexes, crash recovery,
  and reconciliation branches without removing the readiness query.

## File family predicate

`FileRepository` owns one private SQL clause for product reads. For a selected
root File, it requires:

1. at least one root content reference; and
2. no referenced `ObjectContents.state != 'available'` row for either the root
   or a direct derivative (`parent_file_id = root.id`).

For a selected derivative, the same clause resolves its root ID and proves the
same root-plus-direct-child family. The current producer creates exactly one
derivative level. The predicate uses existing indexes:

- `files.parent_file_id`;
- primary key `file_content_references(file_id, variant, ordinal)`;
- `object_contents.id`.

No per-file query, Python readiness loop, expression index, or N+1 is allowed.
Use correlated `EXISTS`/`NOT EXISTS` or an equally bounded equivalent. Verify
the actual PostgreSQL plan and constant query count.

Apply the predicate to every product metadata read:

- `get_list_by_id_and_user`;
- `get_by_ids`;
- `get_by_parent_ids`;
- `get_by_id`;
- `get_by_id_for_update` when mutating a readable File;
- `get_list_by_user`;
- projections built from those methods.

`FileRepository.get_by_id` and `IconRepository.get` must change from
identity-map `session.get()` calls to predicate-bearing `select()` calls.

Do not filter `FileRepository.get_content_references()` by content state.
Metadata readiness is the single aggregate gate. Historical question and
conversation attachment relationships bypass FileRepository metadata
selection; keeping their reference projection unchanged prevents one later
failed attachment from aborting the whole historical projection. Actual byte
reads remain protected by `ObjectContentRepository.get_readable_sources()`,
which requires `AVAILABLE`.

Likewise, keep `IconRepository.get_primary_reference()` unfiltered. The Icon
metadata `get()` predicate gates the bytes endpoint. Icon relationships held by
assistants, apps, spaces, and group chats keep today's behavior; only a later
byte read fails. T010 does not expand into those owners.

## Lifecycle/deletion boundary

Lifecycle access must remain able to find an invisible `PENDING` or `FAILED`
aggregate:

- File deletion preview, user deletion, compensation, family locking, and the
  unfiltered reference snapshot used to return deletion metadata deliberately
  bypass product visibility.
- Icon user deletion and compensation deliberately use an unfiltered
  existence/tenant path.
- Name lifecycle methods literally (`*_for_lifecycle` or equivalent); do not
  add a generic boolean flag to every query.
- File and Icon repositories remain distinct owners. Shared stream capture and
  object-store verification remain in `ObjectContentService`.

An existing inline/object-store content row that later becomes `FAILED` makes
its File disappear from FileRepository product reads and its Icon disappear
from Icon product GET, while both remain explicitly deletable. Historical
question/conversation attachment metadata keeps today's projection behavior;
only a later byte read fails. T010 does not expand into question repositories.

## Crash and cleanup semantics

- A caught object-store unavailable, integrity, cancellation, or publication
  path error deletes the entire new root family/Icon in a fresh transaction.
  Existing final-reference triggers own object-content cleanup.
- Process death before compensation may retain an invisible referenced
  `PENDING`/`FAILED` aggregate. PR1 adds no aggregate reaper or automatic
  cleanup; later scoped cleanup remains deferred.
- If existing object-content reconciliation legitimately promotes the final
  pending row to `AVAILABLE`, the derived predicate makes a fully durable
  aggregate visible without a second transition.
- PostgreSQL-inline creation remains immediately `AVAILABLE` in its original
  transaction, so the complete default deployment keeps current behavior.

## RED-first proof

1. Committed root plus direct derivatives remain absent from FileRepository
   list, get, info, content, and derived-image product paths while any
   reference is `PENDING` or `FAILED`.
2. Each individual remote promotion leaves the family hidden until the final
   promotion; then every family member becomes readable together.
3. Pending/failed Icons are absent from product GET but remain tenant-deletable.
4. Lifecycle access can find and compensate an aggregate already hidden from
   product access.
5. Failure/cancellation at first, middle, and final multi-content upload
   deletes the whole File family/Icon and exercises existing trigger cleanup.
6. A simulated process-death leftover is invisible; later legitimate final
   promotion makes it visible without a publication write.
7. Existing content transitioned from `AVAILABLE` to `FAILED` disappears from
   FileRepository/Icon product reads and remains deletable. A listing with one
   failed File still returns its other Files; a historical conversation with
   that attachment still renders metadata, while only the byte read fails.
8. Inline File/Icon and generated SSE image behavior is unchanged.
9. `EXPLAIN (ANALYZE, BUFFERS)` and query-count tests prove indexed,
   constant-query family filtering with representative root/derivative rows:
   index scans on the File-reference primary key and `parent_file_id`, no
   sequential scan on `object_contents`, and no runtime-threshold assertion.

## Review evidence and disposition

- Claude iteration 8: chose derived visibility but required this exact freeze;
  artifact
  `.codex/artifacts/claude-peer-loop-eneo-admin-file-storage-settings-20260725T170957Z.md`.
- Goal Maker Judge: chose explicit markers plus automatic reconciliation.
  Rejected because the marker does not handle post-publication `FAILED`
  transitions, duplicates truth, and its deletion branch violates the frozen
  no-cleanup scope.
- Antigravity synthesis: independently chose derived visibility and supplied
  the marker crash/invalidation proof; artifact
  `.codex/artifacts/antigravity-peer-loop-eneo-file-icon-publication-boundary-20260725T171535Z.md`.

T010 may resume only after the existing Claude session returns
`GREEN_LIGHT: yes` and `MIN_SCORE >= 8` on this corrected plan.
