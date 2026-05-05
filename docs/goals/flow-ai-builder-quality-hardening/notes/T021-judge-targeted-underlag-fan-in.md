# T021 Judge: Targeted Underlag Fan-In

## Decision

Proceed with a narrow source slice that invokes the existing targeted-underlag auto-binder at the create outline compilation boundary.

## Evidence

- Red tests: the seven remaining `test_ai_builder_create_compiler.py` failures all asserted that audio/document body composer drafts should use `previous_step` plus explicit structured refs instead of `all_previous_steps` or a last-JSON-only chain.
- User live test: AI Builder returned `Plan still invalid after correction` with the quality issue asking for a semantic composition step that weaves in relevant structured results from multiple prior steps.
- Existing owner: `backend/src/intric/flows/ai_builder/ai_builder_create_dataflow.py` already owns `auto_bind_targeted_underlag_for_text_composer`.
- Production gap: the binder was exported and unit-tested, but not invoked by the create outline compilation path that produced the bad shape.

## Claude Review

- Iteration 1: `changes_required`. Claude rejected broad aggregation-intent plumbing through `compile_create_draft`, `normalize_create_draft_mechanics`, proposal processing, and materialization because it widened ownership and preserved double/triple normalization.
- Iteration 2: `GREEN_LIGHT: yes`, `MIN_SCORE: 8`. Claude green-lit Option A: invoke the existing binder once at `compile_outline_to_create_draft`, after skeleton/form-field composition and before returning the `FlowCreateDraft`.

## Allowed Worker Scope

- `backend/src/intric/flows/ai_builder/ai_builder_create_outline.py`
- `backend/tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py` only if assertions need small alignment
- Goal board notes/state

## Deferred

- Bridge/materialization fan-in handling, unless evidence shows that path emits the same bad shape.
- Removing existing double-normalization.
- Changing compiler or normalizer signatures.
