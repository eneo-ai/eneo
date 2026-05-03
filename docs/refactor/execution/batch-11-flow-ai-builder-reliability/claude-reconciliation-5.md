# Batch 11.1c Claude Reconciliation — Architecture Error Surface

## TL;DR

1. Claude rejected the first 11.1c plan until architecture errors had explicit
   telemetry, public codes, and a non-`ValueError` parent.
2. The accepted design keeps one critic invariant registry and adds typed issue
   evaluation plus architecture enforcement.
3. Claude found one blocking swallow point in `_process_outline_arguments`; the
   implementation re-raises `AIBuilderArchitectureError` before the broad
   fallback.
4. `ProposalFailureKind` and `ProposalRepairReason` are now separate so
   architecture failures cannot be repair reasons.
5. Final implementation verification reached parser-clean `GREEN_LIGHT: yes`,
   minimum score `9/10`.

## Iteration 1

| Item | Value |
|---|---|
| Artifact | `.codex/artifacts/claude-peer-loop-batch-11-1c-architecture-error-plan-20260503T024035Z.md` |
| Verdict | `changes_required` |
| Green light | `no` |
| Minimum score | `6` |

Accepted findings:

| Finding | Resolution |
|---|---|
| Architecture errors need a telemetry policy. | Record first-attempt failure kind `architecture`; do not record repair invocation. |
| Parent class was underspecified. | `AIBuilderArchitectureError` inherits `Exception`; bridge `MaterializationError` subclasses it. |
| Critic invariant classes needed a complete policy table. | Added architecture/semantic classification for all 21 current invariants. |
| `hybrid` was speculative. | Removed it; only `architecture` and `semantic` exist in this slice. |
| Critic feedback needed split responsibilities. | Added context build, typed evaluation, render shim, and architecture enforcement. |
| Public codes were too long. | Used `architecture_materialization_failed` and `architecture_critic_invariant_failed`. |

Rejected findings:

| Finding | Reason |
|---|---|
| Move `MaterializationError` out of the bridge. | The bridge-specific error name remains useful at the materialization seam; only the shared parent moved. |

## Iteration 2

| Item | Value |
|---|---|
| Artifact | `.codex/artifacts/claude-peer-loop-batch-11-1c-architecture-error-plan-verification-20260503T024513Z.md` |
| Verdict | `changes_required` |
| Green light | `no` |
| Minimum score | `7` |

Accepted findings:

| Finding | Resolution |
|---|---|
| `_process_outline_arguments` broad catch would convert architecture errors to parse feedback. | Added an explicit `except AIBuilderArchitectureError: raise` before the broad fallback. |
| `ProposalRepairReason = ProposalFailureKind` would make `architecture` a legal repair reason. | Split the literal aliases. |
| Repair non-invocation was only in risk prose. | Added tests that assert no self-correction call and zero repair invocation count. |
| Multiple catch sites could drift. | Added shared private helpers for telemetry recording and SSE error event construction. |
| Frontend SSE code handling was unverified. | Checked the Svelte driver and protocol; AI Builder error codes are strings with only requirements-gate special-casing. |

## Iteration 3

| Item | Value |
|---|---|
| Artifact | `.codex/artifacts/claude-peer-loop-batch-11-1c-architecture-error-plan-verification-3-20260503T024858Z.md` |
| Verdict | `green` |
| Green light | `yes` |
| Minimum score | `7` |

Accepted non-blocking findings:

| Finding | Resolution |
|---|---|
| `_handle_edit_flow` catch was speculative for a create-path slice. | Dropped it from implementation; edit-path architecture enforcement remains in the follow-up edit mechanics slice. |
| First-write-wins was an implicit helper dependency. | Recorded that `_record_proposal_architecture_failure` must not overwrite an existing first-attempt kind. |
| Audio-to-DOCX unit canary and parent integration gate should not be conflated. | This slice adds the unit canary; manual/API smoke remains the parent 11.1 gate. |

## Iteration 4

| Item | Value |
|---|---|
| Artifact | `.codex/artifacts/claude-peer-loop-batch-11-1c-architecture-error-implementation-20260503T030741Z.md` |
| Verdict | `green` |
| Green light | `yes` |
| Minimum score | `8` |

Accepted findings:

| Finding | Resolution |
|---|---|
| Repair conversion helper returned `ProposalRepairReason`, so its old name was stale. | Renamed it to `proposal_repair_reason_from_tool_failure` and renamed local variables at both call sites. |
| `MaterializationError` currently protects no production caller because the bridge is test/import-linter-only. | Recorded as a future delete-or-wire question, not a blocker for the shared error parent. |
| Two surfaces share `architecture_materialization_failed`. | Kept one public code; log context distinguishes bridge from create-outline materialization. |

The wrapper exited nonzero because the response used Markdown-bold output
contract labels, even though the content verdict was green.

## Iteration 5

| Item | Value |
|---|---|
| Artifact | `.codex/artifacts/claude-peer-loop-batch-11-1c-architecture-error-final-verification-contract-20260503T031047Z.md` |
| Verdict | `green` |
| Green light | `yes` |
| Minimum score | `9` |

Accepted findings:

| Finding | Resolution |
|---|---|
| Repair-reason conversion rename needed repo-wide consistency. | Claude verified definition, import, call sites, local variables, and tests all use the new name. |

## Remaining Disagreements

No findings were rejected after iteration 1. No implementation disagreement
remains.

## Confidence

High. Claude's final parser-clean implementation pass was green with minimum
score `9/10`, and the implemented source matches the accepted ownership
decisions: one shared architecture-error parent, one critic registry/evaluator,
proposal-level sanitized error translation, and typed telemetry that makes
architecture repair impossible.
