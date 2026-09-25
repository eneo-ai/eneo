# Knowledge document versions

## Objective

Give every knowledge document exactly one active complete version while preserving historical citations and the last working searchable version when rebuilding fails. Keep the change independent of byte placement so PostgreSQL remains complete by default and compatible object storage remains optional.

## Goal Kind

`specific`

## Current Tranche

Re-verify the green preflight against the merged ingestion-failure and verified-move prerequisites, settle the smallest durable version owner, implement it with behavior-first PostgreSQL tests, document the operator and product behavior concisely, and deliver one reviewable PR.

## Non-Negotiable Constraints

- Product changes require an active bounded Worker task and a frozen path map.
- Reuse existing `InfoBlob` rows and ownership unless source evidence disproves the hypothesis.
- Exactly one complete version may be active; failed builds must never replace the active version.
- PostgreSQL remains the complete default and object storage remains optional; identity does not depend on storage placement.
- The merged ingestion-failure slice owns task-level failure preservation; this slice owns version visibility and publication.
- No chunks/citations rewrite, generic generation framework, retry UI, retrieval ranking change, robust ingestion/publication/deletion expansion, Flow work, or unrelated metadata/crawler cleanup.

## Stop Rule

Stop only after the implementation is merged, current review has no blocking findings, required CI is green, and the final Goal audit maps the result to this objective.

## Canonical Board

Machine truth lives at:

`docs/goals/knowledge-document-versions/state.yaml`

If this charter and `state.yaml` disagree, `state.yaml` wins for task status, active task, receipts, verification freshness, and completion truth.

## Run Command

```text
/goal Follow docs/goals/knowledge-document-versions/goal.md through the first safe verified implementation slice. Do not stop after planning unless blocked.
```

## PM Loop

1. Read this charter and `state.yaml`.
2. Work only on the active task.
3. Keep source read-only unless the active board task explicitly authorizes its paths.
4. Record compact receipts and exact validation evidence.
5. Continue through the next safe verified task until the tranche audit passes or a real blocker remains.
