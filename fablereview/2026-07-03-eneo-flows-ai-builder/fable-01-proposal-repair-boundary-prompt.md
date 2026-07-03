# Fable 01 Prompt: Flow AI Builder Proposal Repair Boundary

You are Claude Fable running a max-effort, source-backed architecture review for Eneo Flow AI Builder.

Repository root: `/Users/ccimen/eneo/eneo-flows-clean`

## Mission

Review Flow AI Builder's proposal submission / repair / self-correction boundary with a strict maintainability and Ponytail lens.

The user is specifically worried that the system relies too much on "repair" instead of making the architecture and contracts less brittle. This is pre-production code, so compatibility with imaginary production users is not a reason to keep complexity.

Your job is not to implement. Your job is to identify the highest-ROI true issues and the clean architecture direction.

## Non-Negotiable Output Rules

- Return a complete Markdown review.
- Start with a five-line TL;DR.
- Use file:line citations for concrete claims.
- Use findings tables.
- Include confidence for every material finding.
- Include "No findings." for any requested section with nothing to report.
- Apply Ponytail: what can be deleted, merged, moved, reused, or made less AI-sloppy?
- Distinguish valid model-boundary resilience from brittle internal repair.
- Do not edit source, tests, migrations, package files, config, or docs.
- Do not write files yourself. Your stdout will be saved to:
  `.codex/artifacts/fable-review-program-20260703/fable-01-proposal-repair-boundary-review.md`

## Read First

Read these local artifacts before reviewing source:

- `.codex/artifacts/fable-review-program-20260703/index.md`
- `.codex/artifacts/fable-review-program-20260703/fable-session-plan.md`
- `.codex/artifacts/fable-review-program-20260703/fable-source-evidence-packet.md`
- `.codex/artifacts/fable-review-program-20260703/agent-repair-fable-split-review.md`
- `.codex/artifacts/fable-review-program-20260703/agent-maintainability-boundaries-review.md`
- `.codex/artifacts/ask-claude-fable-ai-builder-review-split-long-20260702T223104Z.md`

Then inspect source yourself. Do not blindly trust the artifacts.

## Primary Source Scope

Inspect at least these files:

- `backend/src/eneo/flows/ai_builder/ai_builder_proposal_submission.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_proposal_repair.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_proposal_tool_contracts.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_tool_parsing.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_create_proposal.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_edit_proposal.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_proposal_intent.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_create_feedback.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_proposal_finalization.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_create_dataflow.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_step_transition_policy.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_compiled_spec_preparation.py`
- `backend/src/eneo/flows/ai_builder/planning_state.py`
- `backend/src/eneo/flows/ai_builder/pattern_registry.py`
- relevant tests under `backend/tests/unittests/flows/ai_builder`

Use `rg`/`grep`/read tools as needed.

## Classification Rubric

For every repair/fallback/normalization/self-correction branch you discuss, classify it as exactly one:

1. `MODEL_BOUNDARY`
   - Keep or narrow.
   - It protects against unavoidable provider/tool-call volatility: malformed tool JSON, missing tool call despite forced tool choice, provider truncation, upstream model output shape volatility.

2. `CONTRACT_BRITTLENESS`
   - Delete or redesign.
   - It compensates for the system giving the model too many ways to produce invalid internal mechanics, or for the compiler accepting/patching shapes that should be impossible.

3. `UPSTREAM_VALIDATION`
   - Move earlier.
   - It catches something that should have failed at request parsing, proposal schema validation, compiler input validation, shared Flow validation, or runtime parser/publish gate.

If something does not fit, say why.

## Questions To Answer

1. What is the clean boundary between:
   - raw LLM/tool-call adapter repair;
   - semantic proposal validation;
   - deterministic compile/materialization;
   - Flow runtime validation?

2. Which repair/fallback paths should survive production, and why?

3. Which paths should be deleted now because Flow AI Builder is pre-production?

4. Does `CreateFlowIntent` actually function as the strict semantic proposal contract, or is it weakened by post-parse normalization?

5. Are broad exception catches in create/edit proposal processing hiding product/compiler bugs as model repair?

6. Is JSON-text fallback after conversational model output worth keeping, or should Fable recommend narrowing it?

7. Does `ToolRetryConfig` / `ProposalCompletionFn` earn its abstraction, or are there fake seams to delete after repair is narrowed?

8. Should create-quality feedback map structured issue codes instead of string-rewriting validation prose?

9. What is the smallest implementation slice tomorrow that reduces repair/debt without a broad rewrite?

10. What is not worth fixing now?

## Required Sections

Return these sections:

1. `TL;DR`
2. `Ratings`
   - architecture cleanliness;
   - maintainability;
   - reliability/robustness;
   - testability;
   - production readiness;
   - human reviewability.
3. `Repair Boundary Map`
   - table of branch/function, classification, current owner, proposed owner, keep/delete/move, evidence.
4. `Ranked Findings`
   - severity;
   - problem;
   - why it matters;
   - evidence;
   - proposed canonical owner/fix;
   - acceptance criteria;
   - tests required;
   - risk/trade-off;
   - confidence.
5. `Delete / Merge / Move List`
6. `What Current Tests Already Cover`
7. `Missing Red Tests`
8. `What Is Not Worth Fixing`
9. `From-Scratch Cleaner Design`
   - based on the current learnings, not abstract theory.
10. `Tomorrow Implementation Slices`
11. `Claims Codex Must Verify`
12. `Challenge This Brief`
   - where might Codex/Opus/subagents be over-diagnosing?
13. `Confidence`

## Strong Preference

Prefer concrete deletion/merge/rehome recommendations over "add a new service" recommendations. Do not propose plugin systems, generic orchestration frameworks, one-method interfaces, or broad compatibility layers.
