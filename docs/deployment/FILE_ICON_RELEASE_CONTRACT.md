# File/Icon bridge and contraction releases

Existing installations must finish online adoption in the bridge release before
installing the later contraction release. The bridge preserves frozen legacy
payloads for recovery. Contraction removes those payloads and their temporary
application paths together; it closes direct rollback to a pre-content image.

This contract is tracked by `ocs-51g.7`; implementation is `ocs-51g.8` under the
[object-content epic](https://github.com/eneo-ai/eneo/issues/549). The existing
[operator runbook](OBJECT_CONTENT.md#upgrade-and-rollback) remains the entry
point for preflight, backup, adoption, and recovery.

## Supported route and release gate

| Starting point                                                                                     | Required route                                                                                                                                                                                                                                                                 |
| -------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Published `v2.1.1`, commit `527c49ec48029f80845e8672694d6e58ecd78220`, Alembic head `3eb6a34b6733` | Run the bridge preflight; back up; upgrade to the bridge; complete adoption and the verification window; then install contraction.                                                                                                                                             |
| Bridge schema at `202609071000` with unfinished adoption                                           | Keep the bridge API and worker. Resolve the reported wait or failure, resume, and finish verification before contraction.                                                                                                                                                      |
| Bridge schema at `202609071000` with verified completion                                           | Back up the current state, complete the deployment's recovery window, then install contraction in a maintenance window.                                                                                                                                                        |
| New empty installation                                                                             | The complete migration chain may run through contraction because there are no legacy sources to preserve.                                                                                                                                                                      |
| Other historical or unreleased schema shapes                                                       | A known Alembic ancestor accepted by preflight is not automatically a qualified release source. Rehearse that exact image and schema through the bridge first. Restore unsupported deployments to a supported recovery point, or recreate disposable pre-production databases. |

The bridge candidate is based on develop commit
`07a89aaa8808953b7e571b7f68d5cbc8079770e8`, plus the released-schema preflight
compatibility fix and qualification tests. Its schema head is `202609071000`.
The product/release owner must assign and retain the actual bridge image digest,
release version, support interval, and deployment verification window before
shipping contraction. No version or elapsed interval is implied by the schema
revision. Local correctness tests do not authorize deployment or source removal.

A direct old-schema upgrade to contraction must refuse while leaving all legacy
payloads intact. Earlier additive revisions can already have committed their
write fence and inventory; a failed contraction does not mean that the database
is back on its original schema. Continue with the bridge image and worker, or
restore the coordinated pre-upgrade backup. Do not start the old application
against a partially upgraded schema.

## Verification and recovery window

Before contraction, the operator must have:

1. A completed, unpaused campaign without pending, ready, leased, or failed work.
2. Successful reads of representative old and new files, original bytes,
   extracted text, transcriptions, page images, and public icons that exist in
   the deployment. Include empty values and large values.
3. A restored current PostgreSQL backup that serves the expected bytes and
   references. If any authoritative content is remote, restore and test the
   matching PostgreSQL/object-store pair as well.
4. Retained pre-upgrade and current recovery points, the corresponding runnable
   images and configuration, and an agreed recovery-time and retention policy.
5. A maintenance window with API and worker writers stopped, plus sufficient
   database memory, free disk, and time for the final source verification scan.

The bridge's `complete` flag is necessary but insufficient. It can become stale
after a content failure or manual data change. Contraction must independently
check the current sources and their authoritative references.

## Atomic contraction guard

The new Alembic revision is self-contained. It imports SQLAlchemy/Alembic
primitives, never the removable application backfill module. It takes database
table locks covering owners, the admission/campaign/ledger, concrete references,
content state, and inline/remote descriptors before validating or dropping
anything. Use a finite lock timeout and one transaction for the final validation
and every removal. A lock timeout or failed check aborts the whole contraction.
Do not perform network I/O while holding these locks.

The guard must establish all of the following:

- The expected bridge schema exists. Admission is not paused. Any campaign is
  complete; no unfinished ledger rows remain. A database with no legacy sources
  and no ledger work does not need an artificial campaign.
- Enumerating the four original inventory groups finds every surviving legacy
  source: primary file payloads, text-file originals, transcriptions, and icons.
  `NULL` means absent; an empty byte string or text is a real source. File
  variant selection still distinguishes audio originals, extracted text,
  derived pages, and legacy images.
- Each source has the exact surviving owner/variant/ordinal reference, with the
  same tenant and available content. Its byte count and SHA-256 match the frozen
  source. Inline payloads exist and match those facts too. Remote placements
  have their valid descriptor; actual endpoint and paired-restore verification
  belongs to the preceding operator window.
- Every surviving ledger item is done and points to that exact reference and
  available content. A missing inventory row with no verified reference fails.
  The original inventory deliberately excluded existing references, so a
  verified pre-existing reference can cover a source without a ledger row.
  Requiring a fabricated ledger row for that supported case would be incorrect.
- Deleted owners do not require a reference. Their cancelled or historical
  terminal ledger rows must not block legitimate deletion. A surviving owner
  with a cancelled item or a missing/wrong/unavailable reference does block.

Verification hashes source values inside PostgreSQL. It scans real bytes and
can detoast a full large value; the metadata-only preflight is not its performance
model. Qualify the maintenance window on the target dataset. Table locking
prevents owner deletion, reference changes, adoption, moves, and content failure
from passing between validation and removal.

## Removal inventory

The contraction revision and runtime change are one release unit:

| Owner                                        | Remove                                                                                                                                                                                                   |
| -------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `files` and `Files` mapping                  | Legacy `text`, `blob`, `checksum`, `size`, and `transcription` columns and deferred mappings. Keep file metadata and `parent_file_id`.                                                                   |
| `icons` and `Icons` mapping                  | Legacy `blob`, `mimetype`, and `size` columns and deferred mappings. Media type and size come from authoritative content.                                                                                |
| File repository, content loader, and service | Legacy selectors, payload readers, fallback branches, and legacy-only DTO fields. Preserve current concrete references, variants, tenant checks, authorization, and streaming behavior.                  |
| Icon repository and service                  | Legacy byte/metadata fallback and legacy-only DTO fields. Preserve public immutable downloads and normal lifecycle handling.                                                                             |
| Temporary database state                     | File/Icon freeze triggers/functions, owner-delete adoption triggers/functions, ledger, campaign, admission generation, and persisted pause.                                                              |
| Maintenance runtime                          | Backfill scheduling and entry points, settings and runtime instance, migration CLI/preflight, and temporary models/imports. Keep ordinary retention, reconciliation, and S3 moves.                       |
| Content repository                           | Temporary adoption lock/reopen hooks and imports in failure and recovery paths. Preserve placement-conditional failure handling and ordinary content recovery.                                           |
| Tests and operator documentation             | Retire bridge-runtime-only tests from the contraction branch; retain the runnable bridge candidate and its evidence. Update current fixtures, settings/contracts, and guidance to the contracted schema. |
| Alembic history                              | Keep all historical migrations and their self-contained functions unchanged so fresh installs and supported bridge upgrades still run.                                                                   |

No automatic `VACUUM FULL`, table rewrite, content purge, S3 selection, or
retention-policy change belongs to contraction. Dropping columns does not promise
that filesystem allocation shrinks. Optional physical reclamation remains the
separate maintenance procedure in the operator runbook.

## Required implementation evidence

Use disposable PostgreSQL 13 databases to prove successful fresh and adopted
bridge upgrades; refusal for direct skips, paused/incomplete/failed work, stale
completion, missing coverage, wrong references, unavailable content, and corrupt
inline payloads; transaction rollback on interruption; and coordinated concurrent
owner/content mutations. Verify surviving bytes and references after contraction
and after restoring the contracted backup. A downgrade must explicitly refuse to
pretend that discarded legacy values can be reconstructed.

Run the migration graph/import checks, affected File/Icon/content lifecycle
suites, backend static/type/unit checks, generated-contract checks if their
source changes, and documentation build. Keep the qualified bridge release
available independently of contraction. Release approval additionally requires
the real image/version/window decisions and deployment-specific performance and
backup evidence above.
