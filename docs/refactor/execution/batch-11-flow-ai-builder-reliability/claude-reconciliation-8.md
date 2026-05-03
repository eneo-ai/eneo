# Batch 11.2b Claude Reconciliation - Model Slot Resolver Runtime Overlay

## TL;DR

1. Claude rejected the first 11.2b plan because it risked a duplicate resolver
   owner, async logic in the sync builder, and weak merge semantics.
2. The accepted plan extracts one shared classifier, keeps PlanningState merge
   synchronous, and makes discovery runtime the async LLM boundary.
3. Implementation review found low-severity cleanup only; Codex accepted the
   single-source and gating findings before final verification.
4. A dead model-to-model merge branch was deleted instead of documented as
   speculative behavior.
5. Final parser-clean verification reached `GREEN_LIGHT: yes`, minimum score
   `9/10`.

## Iteration 1

| Item | Value |
|---|---|
| Artifact | `.codex/artifacts/claude-peer-loop-batch-11-2b-slot-resolver-runtime-plan-20260503T043632Z.md` |
| Verdict | `changes_required` |
| Green light | `no` |
| Minimum score | `5` |

Accepted findings:

| Finding | Resolution |
|---|---|
| A new resolver module would duplicate the existing discovery semantic classification path. | Added one shared classifier core and rewired discovery classification through it. |
| `planning_state_builder.py` should stay synchronous. | Added a sync merge function only; async model calls live in `ai_builder_discovery_runtime.py`. |
| Merge priority was too weakly specified. | Pinned explicit/summary/default protection, high-confidence policy-default replacement, medium-confidence heuristic replacement, and low/unknown skip behavior. |
| Evidence needed a stable prompt identity. | Added `slot_classification_prompt_hash()` and persisted evidence as `model:<slot>:<prompt_hash>`. |
| DOCX non-LLM policy needed PDF parity. | Added `NON_LLM_RESOLVABLE_SLOT_NAMES` with both DOCX and PDF generation mode slots. |

Rejected findings:

| Finding | Reason |
|---|---|
| None. | All blocking findings improved ownership or failure behavior. |

## Iteration 2

| Item | Value |
|---|---|
| Artifact | `.codex/artifacts/claude-peer-loop-batch-11-2b-slot-resolver-runtime-plan-verification-20260503T044044Z.md` |
| Verdict | `changes_required` |
| Green light | `no` |
| Minimum score | `7` |

Accepted findings:

| Finding | Resolution |
|---|---|
| Preserve only one classifier JSON shape. | Parser accepts `slots/slot_name` only; old `signals/question_id` is not accepted. |
| Stale semantic names would hide the new responsibility. | Deleted `SemanticAdjudicationResult` and `SemanticAdjudicationSignal`; introduced `SlotClassificationResult` and `ClassifiedSlot`. |
| `prompt_hash` should not live on the result object. | Kept it as a helper result passed to the merge call. |
| Gating needed to include all unresolved LLM-resolvable catalog slots. | Runtime candidate selection includes missing slots and weak heuristic/policy-default slots. |
| Blocking discovery needed an explicit call-site gate. | Added `allow_classification` to `build_runtime_planning_state()`. |

## Iteration 3

| Item | Value |
|---|---|
| Artifact | `.codex/artifacts/claude-peer-loop-batch-11-2b-slot-resolver-runtime-plan-verification-3-20260503T044548Z.md` |
| Verdict | `green` |
| Green light | `yes` |
| Minimum score | `8` |

Accepted findings:

| Finding | Resolution |
|---|---|
| Keep the deterministic corpus baseline out of the live model path. | `test_slot_resolver_corpus.py` continues to call the sync builder. |
| Do not claim the final 85% target in CI without a real model eval. | Recorded provider-backed eval as carry-forward. |

## Iterations 4-7

| Iteration | Artifact | Verdict | Green light | Minimum score | Resolution |
|---:|---|---|---|---:|---|
| 4 | `.codex/artifacts/claude-peer-loop-batch-11-2b-slot-resolver-runtime-implementation-20260503T050605Z.md` | `green` | `yes` | 7 | Accepted cleanup findings: shared unknown constant, explicit classification gate, planner-level no-overlay test, split merge skip tests, and `dataclasses.replace`. |
| 5 | `.codex/artifacts/claude-peer-loop-batch-11-2b-slot-resolver-runtime-final-verification-20260503T051437Z.md` | `green` | `yes` | 8 | Accepted the weak-slot candidate fix and identified the dead model-to-model merge branch. |
| 6 | `.codex/artifacts/claude-peer-loop-batch-11-2b-slot-resolver-runtime-post-dead-branch-removal-20260503T052014Z.md` | `green` | `yes` | 9 | Content was green, but the wrapper exited nonzero because the output-contract fields were Markdown-bolded. |
| 7 | `.codex/artifacts/claude-peer-loop-batch-11-2b-slot-resolver-runtime-parser-clean-final-20260503T052115Z.md` | `green` | `yes` | 9 | Parser-clean final verification confirmed the dead branch removal was clean. |

Accepted implementation findings:

| Finding | Resolution |
|---|---|
| `"unknown"` literals should have one owner. | Exported `UNKNOWN_SLOT_VALUE` from the classifier and imported it in merge/discovery consumers. |
| `litellm_client=None` should not stand in for an intentional skip. | Added explicit `allow_classification`. |
| Planner-level blocking discovery must not trigger the overlay call. | Added/kept coverage through `test_discovery_flow.py` and runtime disabled-classification tests. |
| Low, unknown, and non-LLM slot skip behavior should fail independently. | Split merge tests by rule. |
| Cached result copying should be idiomatic. | Switched to `dataclasses.replace(cached, cached=True)`. |
| Model-to-model replacement was dead speculative behavior. | Deleted the branch and its test instead of preserving unshipped recency semantics. |

## Remaining Disagreements

No blocking disagreement remains.

Claude noted that `_llm_candidate_slot_values()` and `_model_slot_can_replace()`
both know `heuristic` and `policy_default` are weak sources. Codex left that as
carry-forward because the set has only two current consumers and no third weak
source exists. If another weak source is introduced, the set should move to one
named owner before the new behavior lands.

## Confidence

High. The final peer review was green after the dead branch was removed, the
accepted findings were implemented, and remaining concerns are scoped future
cleanup rather than correctness blockers.
