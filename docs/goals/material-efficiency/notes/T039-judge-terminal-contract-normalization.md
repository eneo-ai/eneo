# T039 Judge: Terminal Contract Normalization

## Decision

Activate T040 as a Worker slice.

## Problem

Post-T038 live evals made the remaining C3 failure diagnosable instead of opaque. The compiled plan can end with a pass-through text terminal even when the requested terminal output is structured JSON. Strict compiled-spec preparation then rejects the plan because the runtime returns the final step.

## Why It Matters

This is not a C3-only prompt problem. It is a terminal-contract drift class: when a model inserts the requested terminal-producing helper before an existing text finalizer, the flow's last step no longer matches the public run contract. The canonical owner is the step topology normalizer, which already folds the analogous PDF/DOCX helper-before-text shape.

## Evidence

- `/tmp/material-efficiency-live-eval/20260506-073730-t038-create-suite-repair-feedback/summary.json`: C3 failed with `terminal_output_type_mismatch` after T038 preserved validator feedback.
- `/tmp/material-efficiency-live-eval/20260506-074728-t038-c3-regression-check/summary.json`: targeted C3 rerun reproduced the JSON terminal mismatch.
- `backend/src/intric/flows/ai_builder/ai_builder_compiled_spec_preparation.py`: strict terminal alignment rejects JSON/PDF/DOCX terminal mismatches after topology normalization.
- `backend/src/intric/flows/ai_builder/ai_builder_step_transition_policy.py`: `normalize_ai_builder_spec` is the canonical pre-validation topology normalizer and already owns PDF/DOCX helper-tail folding.
- `backend/src/intric/flows/ai_builder/ai_builder_step_skeleton.py`: skeleton-created drafts can append a matching terminal step, but live invalid drafts can still arrive through model/repair paths. Skeleton is not the right owner for this repair boundary.

## Claude Gate

- Session: `flow-ai-builder-material-efficiency-t039-terminal-contract`
- Iteration 1 artifact: `.codex/artifacts/claude-peer-loop-t039-judge-terminal-contract-normalization-20260506T055911Z.md`
- Iteration 2 artifact: `.codex/artifacts/claude-peer-loop-t039-revised-terminal-contract-normalization-20260506T060326Z.md`
- Final verdict: `GREEN_LIGHT: yes`, `MIN_SCORE: 8`

Claude required explicit red tests, an exact fold predicate, a binding rewrite contract, and C3 live eval with at least three runs. The revised Worker scope includes those requirements.

## Selected Worker

T040 should generalize the existing terminal helper-tail normalizer for strict terminal output types without touching planner prompts or skeleton construction.

Fold only when:

- requested terminal output is JSON
- there are at least two steps
- the penultimate helper outputs JSON
- the final step outputs text
- the final step is pass-through
- the final step reads `PREVIOUS_STEP`
- helper binding rewrites are foldable

Do not fold:

- `ALL_PREVIOUS_STEPS` JSON terminal tails
- non-pass-through text terminals
- already-correct JSON terminals
- ambiguous non-adjacent topology
- any case requiring prompt tuning or skeleton edits

## Acceptance Criteria

- Red tests cover positive JSON fold, instruction merge, binding rewrite with form-field preservation, no-fold for `ALL_PREVIOUS_STEPS`, no-fold for non-pass-through text terminal, already-JSON unchanged, compiled-spec acceptance for foldable JSON tail, and compiled-spec rejection for ambiguous trailing text.
- The implementation reuses the existing terminal helper-tail normalizer rather than creating a parallel owner.
- JSON-specific `ALL_PREVIOUS_STEPS` exclusion is documented with a short invariant comment.
- Scoped tests, full AI Builder unit suite, pyright, ruff, C3 live eval with three runs, and a full create-suite eval verify the change.

## Confidence

High.
