# Verified object-content moves

## Objective

Let administrators explicitly and gradually move existing durable content between PostgreSQL inline storage and the configured compatible object store in either direction without creating two writable truths.

## Goal Kind

`specific`

## Current Tranche

Deepen `eneo.object_content` with the smallest resumable, pausable, observable move lifecycle; prove both directions, crash/retry behavior, integrity, readiness, retention/reference blockers, bounded work, and PostgreSQL-only compatibility; update directly required operator documentation; then pass peer review, CI, PR review, and merge.

## Non-Negotiable Constraints

- Base source work on live `origin/develop` commit `a3652e59fbf057c1b7607cf6b5b8c9992c76d9be` on branch `feature/verified-object-content-moves`.
- Keep `eneo.object_content` as canonical owner and reuse its capture, digest/size/type verification, publication/adoption, references, retention/holds, reconciliation, readiness, and worker seams.
- At every commit exactly one placement is authoritative; a known former remote object is only an existing orphan-cleanup candidate, never a second writable authority.
- PostgreSQL remains the complete default and requires no object-store service or configuration.
- Keep orchestration replaceable and bounded; no per-object unbounded task fan-out.
- Do not add a generic migration framework, provider registry, automatic fleet migration, scheduler DSL, provider branches, cross-tenant routing/deduplication, bucket-per-tenant design, or compatibility fallback.
- Do not edit InfoBlob version semantics, knowledge ingestion owners, Flow, File/Icon product contracts, or unrelated metadata/crawler behavior.
- Own one serialized Alembic revision and keep exactly one head; if develop moves first, rebase and repair `down_revision` without a merge head.
- Reuse issue #569 under epic #549; create no duplicate planning item.
- Use behavior-first red/green/refactor cycles, one resumable Claude session, and require `GREEN_LIGHT: yes` with `MIN_SCORE >= 8` before each commit and on the immutable PR head before merge.

## Acceptance Criteria

- Explicit inline-to-object-store and object-store-to-inline moves are resumable, pausable, idempotent, bounded, and observable with aggregate progress and typed failure reasons.
- Target bytes are streamed/captured once with bounded memory and verified for digest, size, and media type before one short authority-flip transaction; maximum-plus-one is rejected.
- Crash points before/after upload and before/after authority flip converge safely on retry.
- Readiness outage/recovery, final-reference/hold blockers, and orphan cleanup interactions are proved.
- Normal Eneo-mediated moves do not require a second full source read unless ambiguity requires canonical re-verification.
- Real PostgreSQL and real compatible-store integration evidence covers both directions.
- Focused owner, migration roundtrip/one-head, broad backend, docs, review, and CI gates pass on the exact merged head.

## Deliberately Not Changed

- Default new-write policy and upload-limit ownership delivered in slice 0.
- Existing File/Icon, InfoBlob, knowledge ingestion, Flow, or tenant routing contracts.
- Automatic migration scheduling, provider selection, or external object-store configuration.

## Risk and Recovery

The main risks are authority skew after crashes, target corruption, object-store outages, oversized inline copies, unbounded worker/query work, and migration-head conflicts. Before the authority flip, retry safely; after the flip, recover forward. Inline-to-object has no retained former payload, while the old remote object from object-to-inline becomes an ordinary non-authoritative orphan for the existing bounded cleanup owner. Rebase onto live develop before merge if another Alembic revision lands, then rerun upgrade/downgrade/re-upgrade and ORM parity.

## Stop Rule

Stop when the tranche audit passes and the exact PR head is merged, or when every safe local action is blocked by missing credentials, external approval, persistent non-converging review, or a product decision outside this board.

## Canonical Board

Machine truth lives at `docs/goals/verified-object-content-moves/state.yaml`.

## Run Command

```text
/goal Follow docs/goals/verified-object-content-moves/goal.md through the first safe verified implementation slice. Do not stop after planning unless blocked.
```
