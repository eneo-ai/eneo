# T035 Judge Receipt: C3 Comparison Routing

## Decision

Activate T036.

## Problem

The live C3 comparison prompt applied successfully but compiled into a shallow
linear topology with near-zero material-routing metrics. A local deterministic
probe reproduced the upstream cause: the prompt resolves to document input and
structured analysis, but not to multi-document scope or compare aggregation.

## Canonical Owner

- `ai_builder_discovery_signal_inference.py` owns lexical source/comparison
  evidence.
- `ai_builder_framework_policy.py` owns whether freeform inferred evidence is
  accepted as an answer signal.
- `ai_builder_architecture_derivation.py` remains the architecture owner and
  should consume existing resolved slots rather than raw prompt text.

## Worker Boundary

T036 should replace the existing blanket freeform `comparison_scope` suppression
with a narrow high-confidence gate. The gate may admit `same_run_compare` only
when the same user text has both explicit multi-source/package evidence and
source-to-source contradiction/comparison evidence. Ambiguous comparison prompts
must still ask the discovery question.

## Claude Peer Loop

- Iteration 1: `changes_required`, min score 6. Claude rejected the first plan
  because the boundary and file scope were too loose.
- Iteration 2: `green`, min score 8. Claude approved the revised plan after it
  named the canonical evidence owner, removed optional compiler-file scope, added
  negative tests, and restated dirty-worktree discipline.

Artifacts:

- `.codex/artifacts/claude-peer-loop-t035-judge-c3-comparison-routing-20260506T042751Z.md`
- `.codex/artifacts/claude-peer-loop-t035-judge-c3-comparison-routing-revised-20260506T043239Z.md`

## T036 Worker Contract

Add red tests and a minimal canonical-owner fix so high-confidence multi-source
contradiction/comparison prompts route through existing `comparison_scope` and
architecture aggregation mechanics, without broad fan-in fallbacks or prompt-only
tuning.
