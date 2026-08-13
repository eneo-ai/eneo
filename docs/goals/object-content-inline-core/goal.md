# Optional object-content inline core

## Objective

Implement the first bounded slice of Eneo's accepted object-content and
knowledge-ingestion architecture: deepen `eneo.object_content` into one
backend-neutral lifecycle owner that supports PostgreSQL-inline bytes when no
object store is configured and the existing private S3-compatible byte backend
when it is.

## Goal Kind

`specific`

## Current Tranche

Complete Slice 1 only: migrate the control schema to explicit storage kinds,
add bounded inline capture/read/delete behavior, preserve and verify existing
object-store behavior, make remote storage an optional capability rather than a
global readiness dependency, update operator and docs-site documentation, and
publish a review-ready pull request to `develop`.

## Non-Negotiable Constraints

- Follow `docs/adr/object-content-and-knowledge-ingestion.md` from the accepted
  design worktree as the architectural decision record.
- Keep `eneo.object_content` as the canonical owner; use one exhaustive
  backend dispatch and do not create a plugin registry or speculative port.
- Keep one byte authority for each content row and enforce the backend shape in
  PostgreSQL.
- Inline content must be bounded by an operator-configurable safety ceiling;
  exceeding it must fail explicitly and never fall back silently.
- Object storage remains vendor-neutral, optional, and private. A remote outage
  degrades only the remote-content capability, not core application readiness.
- Do not cut over File, InfoBlob, Icon, Flow, or other producers in this slice.
- Do not add multi-tenant storage topology, cross-tenant deduplication, a local
  filesystem backend, or a PostgreSQL/object-store dual write.
- Preserve bounded streaming, checksum verification, retention, references,
  holds, audit, reconciliation, and the existing tested S3-compatible subset.
- Prefer deletion and consolidation over compatibility branches. Any downgrade
  is valid only before inline rows exist.
- The pull request must be concise and human-readable, be marked Ready for
  review, and receive a `/review` comment only after publication is complete.

## Stop Rule

Stop when the Slice 1 audit passes, all safe local work is blocked, or
continuing would require producer cutover, product policy, credentials,
destructive operations, or strategy outside this board.

Do not stop after discovery or schema work while a safe required Slice 1 task
remains.

## Canonical Board

Machine truth lives at:

`docs/goals/object-content-inline-core/state.yaml`

If this charter and `state.yaml` disagree, `state.yaml` wins for task status,
active task, receipts, verification freshness, and completion truth.

## Run Command

```text
/goal Follow docs/goals/object-content-inline-core/goal.md through Slice 1 and its final audit. Do not start a producer cutover.
```

## PM Loop

1. Read this charter, the board, and the accepted ADR.
2. Work only inside the active task's scope.
3. Record a compact receipt with changed paths and exact validation.
4. Activate the next Slice 1 task immediately unless a stop condition applies.
5. Publish only after the final implementation and documentation gates pass.
6. Mark the PR Ready, then post one `/review` comment.
7. Finish only with a final audit that maps evidence to the Slice 1 contract.
