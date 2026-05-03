# Batch 11.1a Claude Reconciliation — StepSkeleton Materialization

## TL;DR

1. Claude initially rejected the 11.1a plan because fixed skeleton shapes would
   preserve backend mechanics drift instead of making it impossible.
2. The accepted owner is `ai_builder_step_skeleton.py`, a narrow module for
   typed skeleton contracts and deterministic materialization.
3. The implementation was revised from fixed linear/comparison skeletons to a
   prefix/repeatable-semantic/suffix `StepSkeletonPlan`.
4. Final tests compare skeleton output against current compiler mechanics for
   audio, linear, DOCX template, and comparison paths.
5. Claude final verification reached green; compile integration remains scoped
   to 11.1b.

## Iteration 1

| Item | Value |
|---|---|
| Artifact | `.codex/artifacts/claude-peer-loop-batch-11-1a-step-skeleton-plan-20260503T005555Z.md` |
| Verdict | `changes_required` |
| Green light | `no` |
| Minimum score | `6` |

Accepted findings:

| Finding | Resolution |
|---|---|
| The first owner plan risked renaming/moving pattern-chain logic before proving a better contract. | Kept current chain realization in place and limited 11.1a to typed skeleton materialization. |
| Fixed semantic step counts would not match arbitrary user-requested chains. | Made variable semantic count an explicit requirement before implementation. |
| Edit-path behavior needed a different policy from create-path behavior. | Documented that 11.1a only defines create skeleton materialization; edit preservation/rejection rules remain for 11.1b/11.1c. |
| Tests needed to prove mechanics parity against current compiler behavior. | Added equivalence tests against `compile_outline_to_create_draft` outputs instead of only direct field assertions. |

## Iteration 2

| Item | Value |
|---|---|
| Artifact | `.codex/artifacts/claude-peer-loop-batch-11-1a-step-skeleton-revised-plan-20260503T010206Z.md` |
| Verdict | `green` |
| Green light | `yes` |
| Minimum score | `8` |

Accepted polish:

| Finding | Resolution |
|---|---|
| The new module must earn its existence by becoming the canonical typed skeleton owner. | Added `StepSkeleton` and `StepSkeletonPlan` in `ai_builder_step_skeleton.py`; pattern-chain realization imports defaults from that owner. |
| LLM-facing semantics and backend-owned mechanics must stay separate. | `StepSkeleton` carries semantic defaults separately from mechanic policy fields such as input/output tuple, input source, and fan-in policy. |
| Current compiler helpers should not be deleted before integration. | Left create-outline helper deletion for 11.1b, when the compiler consumes skeleton materialization directly. |

## Iteration 3

| Item | Value |
|---|---|
| Artifact | `.codex/artifacts/claude-peer-loop-batch-11-1a-step-skeleton-implementation-20260503T012233Z.md` |
| Verdict | `changes_required` |
| Green light | `no` |
| Minimum score | `6` |

Accepted findings:

| Finding | Resolution |
|---|---|
| Linear skeletons were still fixed to one semantic slot. | Added `StepSkeletonPlan.slots_for_semantic_count` to expand a repeatable semantic slot for arbitrary outline counts. |
| Comparison skeletons invented a fixed three-step shape. | Added backend prefix/suffix slots and placed comparison fan-in on the last semantic slot. |
| Direct tests could pass while current compiler mechanics drifted. | Added parametrized parity tests for current compiler output across one, two, three, and four semantic-slot scenarios where relevant. |
| Terminal defaults were leaking into non-terminal semantic slots. | Added slot-id-specific semantic defaults for audio, comparison, structured analysis, template content, and final response slots. |

## Iteration 4

| Item | Value |
|---|---|
| Artifact | `.codex/artifacts/claude-peer-loop-batch-11-1a-step-skeleton-verification-20260503T013423Z.md` |
| Verdict | `green` |
| Green light | `yes` |
| Minimum score | `8` |

Accepted polish:

| Finding | Resolution |
|---|---|
| Expanded semantic slots reuse the same template id, which could confuse later consumers. | The `StepSkeleton` docstring now states that `slot_ordinal` is the per-instance key after expansion. |
| Audio and linear parity coverage could be broader. | Added parametrized compiler-equivalence tests for audio and document-input linear paths. |
| Single-step semantic defaults should not all read as final-response work. | Added domain-specific defaults before final verification. |

## Iteration 5

| Item | Value |
|---|---|
| Artifact | `.codex/artifacts/claude-peer-loop-batch-11-1a-step-skeleton-final-verification-20260503T013954Z.md` |
| Verdict | `green` |
| Green light | `yes` |
| Minimum score | `4/5` |

Accepted verification:

| Finding | Resolution |
|---|---|
| No blocking maintainability, typed-contract, or comment-hygiene issue remained. | Proceeded to slice validation and commit preparation. |
| Equivalence tests should disappear once the compiler consumes skeletons directly. | Carried forward to 11.1b so tests do not preserve two implementations longer than needed. |
| Existing create-outline mechanics helpers remain a temporary split. | Carried forward to 11.1b as the delete/move path for `_derive_step_*`, `_ensure_required_server_owned_fan_in`, `_document_delivery_mode_for_step`, and `_ensure_final_artifact_step`. |

## Remaining Disagreements

No findings were rejected. No disagreements remain.

## Confidence

High. The source diff is still pre-integration, but the 11.1a contract is typed,
directly tested, and checked against the current compiler mechanics it is meant
to replace in 11.1b.
