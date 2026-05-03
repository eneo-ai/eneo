# Batch 11.5b Claude Reconciliation - Proposal Boundary And Document Artifact Body

## TL;DR

1. Claude rejected the first instinct to add another document-compose step and pushed the fix toward existing skeleton/input-binding owners.
2. Codex verified the live failure locally: the final DOCX path was fed metadata JSON instead of body text.
3. The accepted implementation keeps proposal kwargs filtering in the proposal seam and artifact body planning in StepSkeleton mechanics.
4. Claude green-lit the final shape with follow-ups; Codex implemented the immediate threshold, PDF, and four-phase test follow-ups before commit.
5. The remaining concern is conversation quality, because the builder still asked avoidable questions during live smoke.

## Plan Review

| Iteration | Artifact | Verdict | Green light | Minimum score | Outcome |
|---:|---|---|---|---:|---|
| 1 | `.codex/artifacts/claude-peer-loop-batch-11-flow-builder-reliability-architecture-20260503T084034Z.md` | `changes_required` | `no` | 6 | Rejected adding a new compose artifact step; asked for canonical owner clarity and tests around skeleton/input mechanics. |
| 2 | `.codex/artifacts/claude-peer-loop-batch-11-flow-builder-reliability-architecture-20260503T085003Z.md` | `green` | `yes` | 8 | Approved fixing the failure in proposal boundary and StepSkeleton mechanics before live smoke. |

## Accepted Findings

| Finding | Resolution |
|---|---|
| A new document-compose step would duplicate artifact rendering concepts. | No compose step was added; terminal DOCX/PDF rendering stays owned by the final artifact step. |
| The body writer must not output metadata JSON right before artifact creation. | Final semantic DOCX/PDF body synthesis stays `text` and records dropped proposal output fields as drift. |
| Later artifact creation needs source material, not just previous metadata. | Multi-phase DOCX/PDF body synthesis reads `all_previous_steps`. |
| Proposal tool-call boundaries should be separate from planner structured-output JSON turns. | `call_proposal_completion` strips planner-only kwargs at the central tool-call seam. |
| JSON-to-text handoff can lose structured material without explicit underlag. | Compiler now binds previous structured output for JSON-to-text transitions. |

## Implementation Review

| Iteration | Artifact | Verdict | Green light | Minimum score | Outcome |
|---:|---|---|---|---:|---|
| 3 | `.codex/artifacts/claude-peer-loop-batch-11-flow-ai-builder-final-verification-after-live-smoke-20260503T090402Z.md` | `GREEN-LIGHT-WITH-FOLLOWUPS` | `yes` | 7.5 | Approved the implementation and requested immediate polish around fan-in naming and additional DOCX/PDF coverage. |

Accepted implementation follow-ups:

| Finding | Resolution |
|---|---|
| Fan-in threshold was a magic number. | Added `_MIN_DOCUMENT_BODY_FAN_IN_PHASES`. |
| PDF artifact body path needed parity coverage. | Added a PDF body-planning regression. |
| Four-phase document chains needed coverage, not just the three-phase example. | Added a four-phase DOCX regression that pins `all_previous_steps`. |
| Parallel fan-in predicates could become harder to read later. | Deferred until a second artifact pattern proves the need for a shared chain-analysis object. |

## Final Shape

| Concept | Owner |
|---|---|
| Proposal LiteLLM kwargs filtering | `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py`. |
| Create/edit proposal completion calls | `ai_builder_create_outline.py`, `ai_builder_edit_proposal.py`, and proposal repair callers. |
| Semantic artifact body output type | `backend/src/intric/flows/ai_builder/ai_builder_step_skeleton.py`. |
| Multi-phase DOCX/PDF body fan-in | `StepSkeletonPlan` in `ai_builder_step_skeleton.py`. |
| JSON-to-text underlag bridge | `backend/src/intric/flows/ai_builder/ai_builder_new_step_compiler.py`. |
| Manual smoke procedure and evidence endpoints | `docs/refactor/execution/batch-11-flow-ai-builder-reliability/manual-eval-runbook.md`. |

## Validation

| Command | Result |
|---|---|
| `uv run pytest tests/unittests/flows/ai_builder/test_ai_builder_step_skeleton.py tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py tests/unittests/flows/ai_builder/test_ai_builder_proposal_repair.py tests/unittests/flows/ai_builder/test_ai_builder_parse_repair.py tests/unittests/flows/ai_builder/test_ai_builder_response_format.py -q` | Passed: `187 passed`, 1 existing warning. |
| `uv run ruff check <11.5b touched source and test files>` | Passed. |
| `uv run ruff format --check <11.5b touched source and test files>` | Passed. |
| `uv run pyright <11.5b touched source and test files>` | Passed: `0 errors, 0 warnings, 0 informations`. |
| Live local API smoke | Passed plan, apply, graph, run, evidence, export, and artifact signed-url checks. |

## Remaining Disagreement Or Deferred Work

No accepted Claude blocker remains for this slice. The one deferred design point
is whether to consolidate fan-in predicates into a shared chain-analysis object.
That is not justified yet because this slice has one concrete artifact pattern
and the current predicate is named, tested, and local.

Conversation-quality follow-up remains separate: the live builder still asked
about input material mode and final output mode even though the Swedish prompt
made audio input and Word output clear. That should be handled in a later
question-policy slice with reliability-corpus coverage.

Confidence: high.
