# Batch 9 — Human Review Pause/Edit/Resume Journal

## Status
IN_PROGRESS

## Starting Point

- Branch: `feature/refactor-flows-flowai`
- Previous completed slice: Batch 8 Slice 8.9 committed as `e0c95a9c flows: include rerun lineage in evidence exports`
- Unrelated local files present before Batch 9 work:
  - `frontend/packages/ui/src/icons/types.d.ts`
  - `scripts/run_codex_review.sh`
  - `PRODUCT.md`
  - `docs/refactor/goals.md`
- Batch 9 directory: `docs/refactor/execution/batch-9-human-review-pause-edit-resume/`
- Docker container selected for validation: `eneo-41ae93-eneo-1`

## Iteration Log

### Iteration 1 — Plan

- Plan: `docs/refactor/execution/batch-9-human-review-pause-edit-resume/plan.md`
- Validation: not run yet
- Claude review: changes required, artifact `.codex/artifacts/claude-peer-loop-batch-9-human-review-plan-20260502T152839Z.md`
- Reconciliation: `docs/refactor/execution/batch-9-human-review-pause-edit-resume/claude-reconciliation-1.md`
- Outcome: plan revised for status naming, CAS/idempotency, payload ownership, webhook ordering, permissions, audit lifecycle ownership, evidence versioning, and frontend status ownership

### Iteration 2 — Plan Verification

- Plan: `docs/refactor/execution/batch-9-human-review-pause-edit-resume/plan.md`
- Validation: not run yet
- Claude review: changes required, artifact `.codex/artifacts/claude-peer-loop-batch-9-human-review-plan-verification-20260502T153942Z.md`
- Reconciliation: `docs/refactor/execution/batch-9-human-review-pause-edit-resume/claude-reconciliation-2.md`
- Outcome: plan revised for checkpoint-revision outbox keys, `started_at` preservation, a separate lifecycle-source rename slice, GET permission semantics, output-mode side-effect classification, and resume transaction ordering

### Iteration 3 — Plan Verification

- Plan: `docs/refactor/execution/batch-9-human-review-pause-edit-resume/plan.md`
- Validation: not run yet
- Claude review: green, artifact `.codex/artifacts/claude-peer-loop-batch-9-human-review-plan-verification-2-20260502T155504Z.md`
- Reconciliation: `docs/refactor/execution/batch-9-human-review-pause-edit-resume/claude-reconciliation-3.md`
- Outcome: plan accepted for implementation after adding Claude's non-blocking data-model reviewability nits

## Carry-Forward Risks

- Review policy wire shape is pinned as `{"review_policy": {"mode": "view" | "edit"}}`; Slice 9.2 still needs API/schema tests before source implementation.
- Resume CASes the checkpoint and run, moves the run from `awaiting_review` to `queued`, and dispatches the existing `flows.execute` task. Batch 9 should not add a separate `flows.resume` task unless it deletes code.
- Frontend generated type updates must not overwrite unrelated local changes.

## Decisions Made During This Batch

- Runtime review checkpoints are separate from `care_data_policy`, because `care_data_policy` models outside-flow governance metadata.
- `awaiting_review` is planned as non-active, non-terminal, and cancellable.
- Checkpoint TTL auto-cancellation is out of scope by default; reconciliation repairs orphan state only until an ADR/product decision changes this.
- Review-policy steps cannot use any output mode classified by `flow_output_mode_has_outbound_delivery` until reviewed outbound delivery is explicitly designed.
- Review/resume endpoints use `FLOWS_MANAGE` and user principals only for the first implementation.
- The active checkpoint read endpoint uses existing flow view semantics.
- Review checkpoint outbox rows are keyed by checkpoint revision; terminal outbox rows remain keyed by run revision.
- Slice 9.0a is the next implementation slice before checkpoint data-model work.
