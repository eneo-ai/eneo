# Preserve Knowledge On Ingestion Failure

## Objective

Ensure a failed upload or transcription processing attempt records failure without destroying, partially replacing, or publishing knowledge that was previously usable.

## Goal Kind

`specific`

## Current Tranche

Verify the current ingestion and transaction owners; freeze the smallest owner-level design with a skeptical Claude plan pass; prove the unsafe behavior red; implement the bounded restoration/savepoint fix; validate it against real PostgreSQL and whole-backend gates; then publish, review, and merge one PR linked to the correct development task under epic #549.

## Problem And Why It Matters

Current processing may mutate an existing `InfoBlob` and its chunks before extraction, chunking, or embedding has safely succeeded. A refresh failure can therefore remove previously queryable knowledge or expose a partial first version. This is a data-integrity and runtime-reliability defect.

## Ownership Direction To Verify

- Current owner: the upload/transcription worker orchestration and embedding datastore transaction path in current source.
- Proposed canonical owner: deepen that existing ingestion owner and transaction model with the smallest savepoint or transactional restoration at the mutation seam.
- Reuse: current `InfoBlob`, chunk, job/attempt, session, and domain-failure owners.
- Move or merge: only transaction/error handling that current source proves is misplaced or duplicated at this seam.
- Delete: no path unless source and behavior tests prove it is weaker, dead, or duplicated.
- Create: only the minimum typed zero-extractable-text failure if no equivalent exists.

## Non-Negotiable Constraints

- Branch from live `origin/develop` base `0c8741c2da1ad3eec210fed55160131f7842d78c` in the isolated worktree.
- Do not newly move extraction, transcription, chunking, or model I/O into a long PostgreSQL transaction. The current worker already holds one ambient transaction; this temporary savepoint must not extend that scope, and task #571's later ingestion slice owns separating preparation, publication, and status transactions.
- Preserve a prior active `InfoBlob` and chunks byte-for-byte and query-equivalently when extraction, chunking, embedding, or zero-text processing fails, while recording the attempt as failed.
- Publish no partial knowledge when a new document's first processing attempt fails.
- Add no generation API, retry framework, lifecycle table, migration, background-job system, repository abstraction, provider branch, generalized multi-tenancy, or object-content migration/move change.
- PostgreSQL remains the complete supported default; optional object storage is not required.
- Keep complexity at existing asymptotic work with no per-chunk transaction or query fan-out.
- Use behavior-first red/green/refactor cycles and one resumable Claude session.
- Stop and coordinate before expanding beyond the ingestion failure seam or files likely owned by slice 2.

## Acceptance Criteria

- Focused tests fail on the frozen base for the intended data-integrity reason.
- Existing knowledge survives representative extraction, chunking, embedding, and zero-text failures while the processing attempt is `FAILED`.
- A new-document failure leaves no partially visible knowledge.
- Transaction and session ownership are explicit and remote/model I/O does not move into a long database transaction.
- Targeted tests, relevant real PostgreSQL integration, whole-backend type/format checks, exact-diff Claude commit gate, PR review, and required CI pass.
- Docs impact is recorded; no documentation is changed unless current source proves operator or user behavior needs it.
- The PR links an existing equivalent development task under epic #549, or a single new task created only after a verified search finds none.
- The exact reviewed PR head is merged into `develop`.

## Risk And Recovery

The primary risk is incorrect session/savepoint scope that either rolls back the failure record or keeps partial knowledge. Recovery is to revert the single bounded PR; no schema or data migration is permitted in this tranche.

## Stop Rule

Stop when the tranche audit passes, all safe local work is blocked, or continuing would require owner input, credentials, destructive operations, or strategy the board cannot decide.

Do not stop after planning, discovery, or Judge selection while a safe Worker task can be activated.

## Canonical Board

Machine truth lives at:

`docs/goals/knowledge-ingestion-failure-safety/state.yaml`

If this charter and `state.yaml` disagree, `state.yaml` wins for task status, active task, receipts, verification freshness, and completion truth.

## Run Command

```text
/goal Follow docs/goals/knowledge-ingestion-failure-safety/goal.md through the first safe verified implementation slice. Do not stop after planning unless blocked.
```

## PM Loop

On every continuation:

1. Read this charter and `state.yaml`.
2. Work only on the active board task.
3. Record a compact receipt before selecting the next task.
4. Finish only after the audit maps current receipts and validation back to the original outcome.
