# Efficient file views and explicit original downloads

## Objective

Complete task #586 by making File-backed views read metadata without loading
payload bytes unless their public contract requires content, and by adding an
authorized download that returns the exact persisted original file.

## Goal Kind

`specific`

## Current Tranche

Map the current read paths, freeze the smallest reusable File/object-content
contract, implement it with behavior-first tests, update docs.eneo.ai, publish
one reviewable pull request to `develop`, and audit the result.

## Non-Negotiable Constraints

- `File` remains the product owner for identity, filename, authorization, and
  public behavior; `eneo.object_content` remains the owner for bytes, integrity,
  placement, and lifecycle.
- PostgreSQL-inline remains the complete default. Optional S3-compatible
  storage must have the same product contract and no provider-specific branch.
- Metadata-only views must not load, hash, or transfer payload bytes.
- Byte-requiring views must reuse one bounded, access-validated batch read and
  must not regress into per-file transactions.
- Original download must use the persisted `original` reference and must never
  silently substitute extracted text, transcription, or a generated variant.
- Preserve bounded streaming, range behavior, close semantics, integrity
  verification, tenant authorization, and stable typed errors.
- Do not change storage placement, upload limits, admin policy, knowledge
  ingestion, cleanup/TTL, or Flow producers in this tranche.
- Avoid a generic variant API, provider registry, caching layer, or broad
  repository rewrite.
- Update docs.eneo.ai with a short explanation of metadata views, processing
  representations, and recoverable originals.

## Stop Rule

Stop when the tranche audit passes, all safe local work is blocked, or
continuing would require product policy, destructive migration, credentials,
or scope owned by #569 or #571.

Do not stop after discovery while a safe bounded implementation task remains.

## Canonical Board

Machine truth lives at:

`docs/goals/file-read-contract/state.yaml`

If this charter and `state.yaml` disagree, `state.yaml` wins for task status,
active task, receipts, verification freshness, and completion truth.

## Run Command

```text
/goal Follow docs/goals/file-read-contract/goal.md through implementation, publication, and final audit. Do not start #569 or #571.
```

## PM Loop

1. Read this charter, the board, task #586, epic #549, and the current
   object-content architecture/deployment documentation.
2. Work only inside the active task's scope.
3. Record a compact receipt with changed paths and exact validation.
4. Activate the next task immediately unless a stop condition applies.
5. Publish only after implementation, generated-contract, docs-site, and
   repository gates pass.
6. Mark the PR ready, post `/review`, and wait for CI and review.
7. Finish only with an audit that maps evidence to #586.
