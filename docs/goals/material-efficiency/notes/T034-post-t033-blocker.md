# T034 Post-T033 Blocker: Dirty Builder Policy Baseline

## TL;DR

- T033 is committed and verified.
- The broader material-efficiency goal is not complete.
- The next meaningful implementation slice is still C3 comparison/material-routing quality.
- That slice should not start while Flow AI Builder policy/pattern files have unowned dirty edits.
- User/owner input is needed: either commit/assign those edits, revert them, or explicitly authorize treating them as the new baseline.

## Current State

After T033, `active_task` is intentionally `null`. The next obvious source-code target would be a deterministic C3 comparison-archetype/material-routing slice, because live evals showed C3 can apply while producing shallow near-zero-material flows.

However, current `git status --short` still includes uncommitted edits in files that overlap planner/policy classification:

```text
 M backend/src/intric/flows/ai_builder/ai_builder_framework_policy.py
 M backend/src/intric/flows/ai_builder/ai_builder_planner_pattern_signals.py
 M backend/tests/unittests/flows/ai_builder/test_ai_builder_framework_policy.py
 M scripts/run_codex_review.sh
?? PRODUCT.md
?? docs/refactor/flow-ai-builder-material-efficiency-review-handoff.md
?? docs/refactor/goals.md
?? docs/refactor/new/
?? docs/refactor/runtime-hang-and-builder-rootcause.md
?? flow_ai_builder_prd.md
?? flow_ai_builder_review.md
?? utvecklingssamtal.mp3
```

The source edits are small, but they are not harmless for this goal:

- `ai_builder_framework_policy.py` changes text-terminal marker behavior.
- `ai_builder_planner_pattern_signals.py` changes/comment-documents pattern signal matching.
- `test_ai_builder_framework_policy.py` rewrites a policy test prompt.
- `scripts/run_codex_review.sh` is unrelated to material efficiency and must not be mixed into the next phase.

## Decision

`blocked_on_dirty_builder_policy_baseline`

Do not activate the next source-code Worker until those dirty files are resolved or explicitly assigned. This prevents the next C3 slice from relying on unrecorded planner-policy behavior.

## Next Safe Worker After Blocker Clears

Candidate objective:

> Add deterministic red tests and the smallest canonical-owner fix so comparison-intent create flows cannot compile into shallow near-zero-material topologies. The comparison archetype must preserve justified compare fan-in and expose measurable material-routing floors, while non-comparison flows remain unaffected.

Required first step after blocker clears:

1. Inspect the clean baseline owners:
   - `backend/src/intric/flows/ai_builder/pattern_registry.py`
   - `backend/src/intric/flows/ai_builder/ai_builder_critic_invariants.py`
   - `backend/src/intric/flows/ai_builder/ai_builder_step_skeleton.py`
   - `backend/src/intric/flows/ai_builder/ai_builder_create_outline.py`
   - `backend/src/intric/flows/ai_builder/ai_builder_create_dataflow.py`
2. Choose one canonical owner before editing.
3. Add a red deterministic test that fails without live LLM output.
4. Avoid adding new marker lists or using blanket `all_previous_steps`.

## Evidence

- Latest full live eval and T030 receipt: C3 applied but generated shallow/poor material routing.
- T033 receipt: live eval error paths now preserve plan-envelope metrics, so future failing C3/E1 runs retain diagnostics.
- Claude artifact `.codex/artifacts/claude-peer-loop-t032-next-safe-slice-after-live-eval-20260506T035802Z.md` independently flagged dirty Flow AI Builder policy/pattern files as a blocker before C3 implementation.

## Required Owner Input

Pick one:

1. Commit/assign the dirty policy/pattern edits to a separate task or commit.
2. Revert them if they were accidental.
3. Explicitly authorize the next Worker to treat them as the current baseline and include them in review scope.

Until then, the goal should remain active but blocked.

Confidence: high.
