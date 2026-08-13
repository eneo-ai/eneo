# T010 runtime and producer implementation validation

## Outcome

The implementation moves all closed business upload-limit consumers to the
persisted deployment policy and applies one request-scoped immutable admission
snapshot to eligible new File-family and Icon writes. PostgreSQL-inline remains
the complete default. Object-store writes are target-pinned, verify every
captured content object, never fall back, and expose product metadata only when
the entire aggregate is `AVAILABLE`.

## Canonical ownership

- `object_content.deployment_policy` owns the persisted policy projection and
  immutable `UploadAdmissionSnapshot`.
- `ObjectContentService` owns target-aware capture, readiness, byte storage, and
  verification primitives.
- `FileService` owns whole root-plus-direct-derivative admission and
  compensation; `FileRepository` owns its single product-visibility predicate.
- `IconService` and `IconRepository` own the corresponding Icon lifecycle and
  visibility boundary.
- Container dependencies load the snapshot once for selected HTTP operations.
  Worker/container use cases load a new snapshot per transaction and therefore
  observe committed revisions without process restart.
- `LimitService` remains the public upload-limit projection; the persisted
  policy is its source instead of process settings.

## Reuse, deletion, and deliberately excluded work

- Reused existing object-content intent/reference triggers, storage drivers,
  runtime readiness, and reconciliation. No new policy engine, storage port,
  lifecycle coordinator, publication marker, or cleanup owner was added.
- Removed the four business limit fields from runtime `Settings`, removed
  `required_inline_bytes`, and removed all application-source reads of the
  legacy environment names. T004 owns templates and documentation deletion.
- Preserved inline-only generated image behavior and existing historical
  attachment/reference projections.
- Added no fallback, dual write, moves, per-tenant policy, recursive family,
  provider registry, automatic cleanup, Flow, or knowledge-generation work.

## Failure and concurrency semantics

- Policy mutation retains compare-and-swap revision semantics from T003.
- Every eligible write pins one policy revision and target, then rechecks that
  target before persistence.
- Inline ceiling enforcement happens during bounded capture. Object-store
  capture uses the existing spool/multipart bounds and the admin business
  limit; no inline capacity ceiling is applied to remote placement.
- Caught pre-final errors and cancellation compensate the entire newly-created
  aggregate in a fresh transaction. Cancellation is deferred until the cleanup
  task has reached a terminal result.
- Once the final content promotion commits, the aggregate is visible and is
  preserved even if response delivery is cancelled.
- Crash leftovers can remain hidden; PR1 deliberately adds no automatic
  aggregate cleanup.

## Test-isolation repair

The broad integration fixture truncated every table after each test, including
the migration-seeded singleton policy, but only reseeded tenants and feature
flags. The fixture now captures the actual migration seed before the test
session and restores that exact policy after every truncate. This does not add
runtime seeding or a second production owner.

The existing original-download corruption test now expects a subsequent 404:
the first integrity failure marks content failed, and the frozen product
visibility predicate intentionally hides that aggregate instead of leaking its
internal state through a 409.

## Exact validation evidence

- Relevant unit directories:
  `uv run pytest -q tests/unittests/object_content tests/unittests/files
  tests/unittests/icons tests/unittests/jobs tests/unittests/limits
  tests/unittests/apps/api tests/unittests/server` => **269 passed**.
- Deployment-policy, lifecycle, adoption, and route subsets => **144 passed**
  unit and **16 passed** PostgreSQL/object-store integration.
- Broad PostgreSQL/object-content and File-usage integration:
  `uv run pytest -q -m integration tests/integration/object_content
  tests/integration/test_file_usage_relations.py --tb=short` =>
  **107 passed**.
- Whole-backend `uv run pyright` => **0 errors, 0 warnings, 0
  informations**.
- Ruff check over application source and all relevant test paths => **passed**.
- Ruff format check over the same paths => **896 files already formatted**.
- `uv run alembic heads` => **202607251700 (head)**, exactly one head.
- `git diff --check` => **passed**.
- Application-source scan for the four legacy environment names => **zero
  matches**.
- PostgreSQL query-count and `EXPLAIN (ANALYZE, BUFFERS)` proof is in
  `test_file_family_visibility.py`: one statement, primary-key/reference and
  parent-file indexes, and no `object_contents` sequential scan.

## Pre-commit review questions

1. Can any product File/Icon route still expose a pending/failed aggregate or
   can any lifecycle/deletion route lose access to one?
2. Can cancellation or a store/verification failure leave a visible partial
   aggregate, or can compensation delete a fully committed visible aggregate?
3. Is the one-snapshot-per-operation boundary actually consistent across API
   and worker/container consumers?
4. Does any remaining code preserve restart-dependent business-limit
   ownership, a hidden hard-coded cap, or an accidental inline fallback?
5. Can the File/Icon lifecycle implementation be materially simplified without
   adding shared fake abstractions, weakening the frozen invariants, or moving
   responsibility out of the aggregate owners?
6. Are query count, plans, error contracts, audit behavior, and test isolation
   honest and bounded?

## Claude iteration 11 disposition

Claude returned `GREEN_LIGHT: yes`, `MIN_SCORE: 8`, with no blockers on staged
hash `928091bc…c4ea80`. Every finding was checked locally:

- Collapsed the identical “all but last / last” remote upload branches into one
  loop. Visibility still changes only after the loop completes.
- Deleted the duplicate `capture_inline` entry point. `capture_for_target` is
  now the sole capture owner; a missing business maximum is permitted only for
  explicitly inline-pinned producers and rejected for object-store capture.
- Consolidated File metadata/intent/reference persistence into
  `_persist_captured_file`. The generated-image orchestration retains its
  existing private entry point and inline transaction behavior, but no longer
  owns a second persistence body.
- Verified the two repository guard-test edits are mechanical: File deletion
  names the new literal lifecycle accessor, and the Limit route asserts both
  authenticated and upload-admission container flags. No exemption was added.
- Retained `limit_name` as the stable persisted-policy error vocabulary for
  T004-generated contracts/docs.
- Retained the correlated content-state lookup because the real PostgreSQL plan
  proves indexed bounded behavior and no `object_contents` sequential scan.

Post-cleanup validation:

- focused capture, File lifecycle/router/protocol, and streaming transaction
  tests => **44 passed**;
- exact File PostgreSQL/object-store lifecycle and original-download tests =>
  **13 passed**;
- relevant unit directories => **269 passed**;
- whole-backend Pyright => **0/0**;
- relevant Ruff and format checks => **passed**, **897 files formatted**;
- new staged SHA-256 => `d99dac3968ef8c5867243f3ad98c59210e13d714536438aed59494cec362bbcd`.

Claude iteration 12 returned `GREEN_LIGHT: yes`, `MIN_SCORE: 8`. Its only
remaining P3 observation was resolved with one intent comment explaining the
optional receipt revision and a direct test that rejects object-store capture
without a business maximum. Iteration 13 returned `GREEN_LIGHT: yes`,
`MIN_SCORE: 8`, with no findings on final staged SHA-256
`e0d62bfa13bda9f08d338e7d860946e8b12f90cb54045e6d1a61488564ca089e`.
Commit: `ffe4f6ff0c131eeef49aad923fddee02cf76e3d0`.
