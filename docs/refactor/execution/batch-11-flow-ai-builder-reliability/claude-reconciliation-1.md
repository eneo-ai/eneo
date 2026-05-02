# Batch 11 — Claude Reconciliation 1

## TL;DR

1. Three ask-claude ideation passes converged on backend-owned Flow mechanics as the primary reliability fix.
2. Claude rejected a structured-output-first plan because it would reduce parse errors without fixing the reported audio-to-DOCX mechanics failure.
3. The final plan makes `StepSkeleton` / `materialize_step_skeleton` the first implementation target, followed by Swedish slot resolution, resource/form-field semantics, goldens, and provider-aware structured outputs.
4. Claude peer review found concrete plan defects; Codex accepted and fixed them.
5. Final Claude verification is green with minimum score 8.

## Ideation Inputs

| Artifact | Result |
|---|---|
| `.codex/artifacts/ask-claude-batch-11-flow-ai-builder-reliability-ideation-1-20260502T201019Z.md` | Diagnosed the reported failure as a server derivation/materialization gap, not primarily a prompt or JSON-shape issue. |
| `.codex/artifacts/ask-claude-batch-11-flow-ai-builder-reliability-ideation-2-focused-20260502T202440Z.md` | Reordered the plan: mechanics skeleton first, Swedish slot resolver second, structured outputs later. |
| `.codex/artifacts/ask-claude-batch-11-flow-ai-builder-reliability-ideation-3-retry-20260502T203231Z.md` | Produced the final five-slice shape, success metrics, and explicit non-goals. |

Timed-out ask-claude artifacts exist but were not counted as valid iterations.

## Peer Review Iteration 1

- Artifact: `.codex/artifacts/claude-peer-loop-batch-11-flow-ai-builder-reliability-plan-20260502T204313Z.md`
- Verdict: `changes_required`
- Green light: `no`
- Minimum score: `6`

Accepted findings:

| Finding | Resolution |
|---|---|
| Reliability metrics were circular because goldens were introduced later in the same batch. | Added 11.0 production-failure corpus and made goldens coverage gates, not the baseline reliability gate. |
| 11.1 materialization gate was mixed with 11.2 Swedish intent resolution. | Split fixed-PlanningState/FCM tuple correctness from corpus-level Swedish success. |
| Skeleton fill rules were undefined. | Added a canonical Skeleton Fill Contract. |
| Structured-output capability source was forked. | Made `TenantModelAdapter` the single provider-capability owner. |
| Tool calls were treated as a structured-output fallback rung. | Collapsed output modes to `strict_json_schema`, `json_object`, and `prompt_with_pydantic_validation`; tool calls remain orthogonal. |
| Architecture-class invariant failures lacked a runtime contract. | Added `AIBuilderArchitectureError` bypassing repair. |
| Keyword prior deletion was vague. | Added numeric deletion criteria. |
| 11.1 was too large. | Split it into 11.1a, 11.1b, and 11.1c with a further-split gate. |
| Corpus integrity was not concrete. | Added minimum-count and integrity-test requirements. |
| Capability reference rollout was too vague. | Added a top-level per-slice rollout table. |

## Peer Review Iteration 2

- Artifact: `.codex/artifacts/claude-peer-loop-batch-11-flow-ai-builder-reliability-plan-verification-20260502T204917Z.md`
- Verdict: `changes_required`
- Green light: `no`
- Minimum score: `7`

Accepted findings:

| Finding | Resolution |
|---|---|
| A stale four-tier structured-output rail remained. | Removed it everywhere and used the three-mode rail consistently. |
| Provider call mechanics row used stale language. | Updated canonical owner wording for `TenantModelAdapter`. |
| A resolved structured-output question remained open. | Removed the resolved open question. |
| Naming still hedged across multiple terms. | Standardized on `StepSkeleton` and `materialize_step_skeleton`. |
| Decision boundary omitted architecture failure surface. | Added the boundary row. |
| Capability reference rollout was buried under one slice. | Promoted it to top-level in PRD and plan. |
| Suggested commits did not match slice structure. | Made commit suggestions align with slices. |
| Skeleton fill rules were duplicated. | Kept the canonical contract in the PRD and cross-referenced it from the plan. |

## Peer Review Iteration 3

- Artifact: `.codex/artifacts/claude-peer-loop-batch-11-flow-ai-builder-reliability-plan-verification-2-20260502T205507Z.md`
- Verdict: `green`
- Green light: `yes`
- Minimum score: `8`

Accepted polish:

| Finding | Resolution |
|---|---|
| One problem-statement row still echoed old structured-output wording. | Replaced it with `strict_json_schema`, `json_object`, and `prompt_with_pydantic_validation`. |
| `StepSkeleton` was used awkwardly as the bug locus. | Reworded to backend materialization or validator bugs. |
| 11.1 sub-slice commit shape was implicit. | Added guidance to split 11.1 commits if the LOC ceiling is approached. |

## Final Decision

Batch 11 is ready as a plan-only handoff. Implementation should start with 11.0 measurement baseline and production-failure corpus after the current worktree is clean or unrelated dirty files are explicitly classified.
