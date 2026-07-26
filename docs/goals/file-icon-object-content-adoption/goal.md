# File and Icon object-content adoption

## Objective

Implement Slice 2 of Eneo's accepted optional object-content architecture:
move File variants and Icon primary bytes from domain-specific columns into
concrete `eneo.object_content` references while preserving their business
identity, authorization, existing user behavior, and PostgreSQL-only operation.

## Goal Kind

`specific`

## Current Tranche

Complete task #551 only: inventory and classify File/Icon bytes, implement
honest original and derived variants through the shared content owner, normalize
existing rows in bounded resumable batches, verify one authority flip, remove
obsolete byte and duplicate integrity columns, update both documentation
surfaces, publish a review-ready pull request to `develop`, and iterate CI and
`/review` until green.

## Non-Negotiable Constraints

- Follow the accepted
  `docs/adr/object-content-and-knowledge-ingestion.md` blueprint and epic #549.
- Keep `FileService` and `IconService` responsible for business identity,
  authorization, filename, purpose, and accepted media policy.
- Keep `eneo.object_content` as the sole owner of durable bytes, canonical
  SHA-256, exact size/type, lifecycle, references, retention, audit, and
  recovery.
- This slice creates File/Icon content as `postgres_inline`. It must work with
  no object-store configuration and must not force municipalities to deploy S3.
- Preserve the platform's ability to contain both inline and object-store
  records, but give every individual content record exactly one immutable byte
  authority. Never add fallback reads or dual writes.
- Preserve exact original bytes when they exist. Treat extracted text,
  transcription, derived pages, model inputs, generated artifacts, and previews
  as honest typed variants rather than overwriting or mislabeling the original.
- Reuse the existing concrete File/Icon reference tables, ownership triggers,
  capture/read/delete lifecycle, and inline backend. Do not create another
  storage module, generic provider interface, migration framework, or queue
  abstraction.
- Keep ARQ/Celery concerns outside File/Icon and object-content domain logic.
- Do not deepen multi-tenant storage topology. Preserve current authorization
  fences but add no tenant buckets, routing, policy, or deduplication.
- Do not begin InfoBlob indexing, admin placement/migration policy, Flow
  adoption, crawler work, or approximate vector indexing.
- Use behavior-first tests, real PostgreSQL migration/concurrency evidence, and
  bounded I/O proof. Do not accept mock-only persistence evidence.
- Update `docs/deployment/` and docs.eneo.ai in the same pull request.
- Keep docs.eneo.ai task-oriented and layered: lead with a short storage-choice
  TL;DR, one simple ownership/flow diagram, and direct navigation for
  PostgreSQL-only, bundled SeaweedFS, and external compatible endpoints. Keep
  detailed migration, backup, recovery, and troubleshooting procedures behind
  those entry points rather than duplicating walls of text.
- Explain ownership in product language: File/Icon own identity, filename,
  authorization, and purpose; `eneo.object_content` owns exact bytes, canonical
  digest, placement, and lifecycle; searchable facts and vectors remain in
  PostgreSQL.
- Use Fable Medium only after a concrete locally verified design or diff exists
  and provide the complete blueprint, evidence, tradeoffs, and unresolved
  questions in one focused review.
- Do not merge the Slice 2 pull request.

## Stop Rule

Stop when the Slice 2 audit passes and the new pull request has no review
findings with all required checks green, or when every safe local action is
blocked by missing product evidence, destructive migration risk, or authority
outside this board.

Do not stop after inventory, schema work, or a partial compatibility path while
a required safe Slice 2 task remains.

## Canonical Board

Machine truth lives at:

`docs/goals/file-icon-object-content-adoption/state.yaml`

If this charter and `state.yaml` disagree, `state.yaml` wins for task status,
active task, receipts, verification freshness, and completion truth.

## Run Command

```text
/goal Follow docs/goals/file-icon-object-content-adoption/goal.md through Slice 2, publication, and its final audit. Do not start admin placement, InfoBlob, or Flow work.
```

## PM Loop

1. Read this charter, the board, and the accepted blueprint.
2. Work only inside the active task's scope.
3. Add one observable behavior at a time with RED, GREEN, then refactor.
4. Record compact receipts with exact paths and validation.
5. Activate the next required task unless a stop condition applies.
6. Update deployment docs and docs.eneo.ai before publication.
7. Publish a ready PR, post `/review`, and iterate genuine findings and CI.
8. Finish only with a final audit mapped to task #551 and the user outcome.
