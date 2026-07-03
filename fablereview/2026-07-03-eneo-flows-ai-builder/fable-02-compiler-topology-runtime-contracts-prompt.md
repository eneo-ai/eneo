# Fable 02 Prompt: Compiler, Topology, Underlag, RAG, And Runtime Contracts

You are Claude Fable running a max-effort, source-backed architecture and correctness review for Eneo Flows / Flow AI Builder.

Repository root: `/Users/ccimen/eneo/eneo-flows-clean`

## Mission

Review whether Flow AI Builder and Flow runtime make invalid specs hard to produce, or whether they rely on post-hoc normalization, underlag repair, weak validation, and runtime failures.

Focus on:

- `underlag till text`;
- `input_bindings.question` as the pivot contract;
- runtime input / previous step output / JSON field references;
- JSON input/output schema contracts;
- RAG/knowledge retrieval query efficiency;
- source grounding across steps;
- shared Builder/manual/publish/runtime validation.

This session is running in parallel with other Fable sessions, so do not depend on their output. If your conclusion depends on a proposal-contract change, state the assumption explicitly.

## Non-Negotiable Output Rules

- Return a complete Markdown review.
- Start with a five-line TL;DR.
- Use file:line citations for concrete claims.
- Use findings tables.
- Include confidence for every material finding.
- Apply Ponytail: delete, merge, move, reuse, simplify.
- Do not edit source, tests, migrations, package files, config, or docs.
- Do not write files yourself. Your stdout will be saved to:
  `.codex/artifacts/fable-review-program-20260703/fable-02-compiler-topology-runtime-contracts-review.md`

## Read First

Read these local artifacts before reviewing source:

- `.codex/artifacts/fable-review-program-20260703/index.md`
- `.codex/artifacts/fable-review-program-20260703/fable-source-evidence-packet.md`
- `.codex/artifacts/fable-review-program-20260703/agent-runtime-dataflow-review.md`
- `.codex/artifacts/fable-review-program-20260703/agent-repair-fable-split-review.md`
- `.codex/artifacts/fable-review-program-20260703/agent-maintainability-boundaries-review.md`
- `.codex/artifacts/fable-max-review-20260702/summary.md`

Then verify source yourself.

## Primary Source Scope

Inspect at least these files:

- `backend/src/eneo/flows/ai_builder/ai_builder_create_compiler.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_edit_compiler.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_new_step_compiler.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_create_dataflow.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_underlag_policy.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_source_material.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_step_transition_policy.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_compiled_spec_preparation.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_validator.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_validation_references.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_json_schema_paths.py`
- `backend/src/eneo/flows/flow_authoring_spec.py`
- `backend/src/eneo/flows/flow_validators.py`
- `backend/src/eneo/flows/variable_resolver.py`
- `backend/src/eneo/flows/template_reference_analyzer.py`
- `backend/src/eneo/flows/runtime/step_definition_parser.py`
- `backend/src/eneo/flows/runtime/step_input_resolution.py`
- `backend/src/eneo/flows/runtime/step_execution_runtime.py`
- `backend/src/eneo/flows/runtime/rag_retrieval.py`
- `backend/src/eneo/assistants/references.py`
- relevant tests under `backend/tests/unittests/flows` and `backend/tests/unittests/flows/ai_builder`

## Questions To Answer

1. Does Builder compile valid create/edit specs directly, or does it rely on broad post-compile normalization?

2. Which topology/dataflow/terminal-artifact transformations belong in:
   - create compiler;
   - edit compiler;
   - shared Flow validation;
   - runtime parser;
   - migration/legacy compatibility?

3. Is `input_bindings.question` the right pivot contract replacing implicit input, and is it enforced everywhere that can create/update/publish/run flows?

4. Does `underlag till text` preserve enough source details from:
   - audio transcription;
   - document text;
   - runtime flow input;
   - previous step outputs;
   - JSON structured fields;
   - final PDF/DOCX/text rendering?

5. Does the system ever select too little structured source material, especially for final artifact/report steps?

6. Should RAG/knowledge retrieval use an explicit bounded retrieval-query contract instead of full `prepared.step_input.text`?

7. Are Builder/manual/publish/runtime validators equivalent for:
   - JSON array paths;
   - contractless JSON field refs;
   - `step_input` keys;
   - `indata_text` / `indata_json`;
   - template expressions;
   - runtime input files/audio/document requirements?

8. Where are the canonical owners for:
   - variable/path grammar;
   - JSON output contract shape;
   - `step_input` metadata;
   - source-material grounding;
   - RAG retrieval query;
   - typed runtime input requirements?

9. What should be deleted or merged because it is post-hoc normalization instead of ownership?

10. What is not worth fixing now?

## Required Sections

Return:

1. `TL;DR`
2. `Ratings`
   - architecture cleanliness;
   - maintainability;
   - runtime robustness;
   - dataflow correctness;
   - token/RAG efficiency;
   - testability;
   - production readiness.
3. `End-To-End Dataflow Map`
   - user/runtime input -> Builder compile -> publish validation -> runtime step input -> RAG -> output -> next step.
4. `Canonical Ownership Map`
5. `Ranked Findings`
   - severity, problem, why it matters, evidence, owner/fix, acceptance criteria, tests, risk/trade-off, confidence.
6. `Runtime Equivalence Gaps`
7. `Delete / Merge / Move List`
8. `What Current Tests Already Cover`
9. `Missing Red Tests`
10. `What Is Not Worth Fixing`
11. `From-Scratch Cleaner Design`
12. `Tomorrow Implementation Slices`
13. `Claims Codex Must Verify`
14. `Challenge This Brief`
15. `Confidence`

## Carry-Forward Known Risks

Previous reviews found:

- RAG retrieval can use full composed `prepared.step_input.text`.
- File/audio/document flow input can compile to `{{ step_input.text }}` but runtime/rerun file availability must be carefully characterized.
- Manual/UI binding validation can be weaker than Builder validation.
- Builder accepted array item paths runtime rejected.
- `INTENTIONAL_PARTIAL` underlag can preserve too-narrow source.
- Whole-plan edits can leave stale literal `step_N` aliases.
- `STEP_INPUT_KEY_SHAPES` can drift from runtime metadata.
- Structured refs into contract-less JSON steps are risky.

Do not simply repeat these. Verify, refine, prioritize, and propose the clean canonical owner/fix.
