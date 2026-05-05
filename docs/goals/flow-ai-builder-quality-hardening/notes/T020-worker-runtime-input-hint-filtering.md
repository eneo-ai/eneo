# T020 Worker Receipt: Runtime Input Hint Filtering

## Objective

Filter server-derived runtime input field hints so only planner-referenced hints
become create-mode `form_fields`.

## Red Evidence

- `cd backend && uv run pytest -n 4 -q tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py::test_compile_outline_flow_drops_server_derived_hints_when_planner_did_not_reference_them tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py::test_compile_outline_flow_keeps_hint_when_planner_referenced_it_via_uses_input_fields tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py::test_compile_outline_flow_drops_extracted_metadata_hints_when_planner_did_not_wire_them` — failed before implementation.

All three failures showed `draft.form_fields` containing unreferenced
server-derived runtime input hints.

## Change

- `compile_outline_to_create_draft` now computes the set of field names
  referenced by outline steps through `uses_input_fields`.
- `_compile_form_fields` receives that set explicitly and only materializes a
  server-derived `RuntimeInputFieldHint` when the planner referenced the hint
  name.
- Explicit planner-declared `input_fields` remain unchanged and unconditional.
- Primary-input shadow filtering and `NO_EXTRA_RUNTIME_METADATA` handling remain
  unchanged.

## Tests

- `test_compile_outline_flow_drops_server_derived_hints_when_planner_did_not_reference_them`
- `test_compile_outline_flow_keeps_hint_when_planner_referenced_it_via_uses_input_fields`
- `test_compile_outline_flow_includes_only_referenced_runtime_hints`
- `test_compile_outline_flow_drops_extracted_metadata_hints_when_planner_did_not_wire_them`
- `test_compile_outline_flow_overlap_planner_declared_field_and_hint_with_same_name`
- `test_compile_outline_flow_drops_field_that_shadows_primary_text_input`
- `test_compile_outline_flow_drops_runtime_fields_when_metadata_is_disabled`

## Validation

- `cd backend && uv run pytest -n 4 -q tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py::test_compile_outline_flow_drops_server_derived_hints_when_planner_did_not_reference_them tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py::test_compile_outline_flow_keeps_hint_when_planner_referenced_it_via_uses_input_fields tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py::test_compile_outline_flow_includes_only_referenced_runtime_hints tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py::test_compile_outline_flow_drops_extracted_metadata_hints_when_planner_did_not_wire_them tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py::test_compile_outline_flow_overlap_planner_declared_field_and_hint_with_same_name tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py::test_compile_outline_flow_drops_field_that_shadows_primary_text_input tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py::test_compile_outline_flow_drops_runtime_fields_when_metadata_is_disabled` — passed, 7 tests.
- `cd backend && uv run pytest -n 4 -q tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py` — failed with the 7 deferred targeted-underlag/audio fan-in tests only.
- `cd backend && uv run pyright src/intric/flows/ai_builder/ai_builder_create_outline.py tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py` — passed, 0 errors.
- `cd backend && uv run ruff check src/intric/flows/ai_builder/ai_builder_create_outline.py tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py` — passed.
- `cd backend && uv run ruff format --check src/intric/flows/ai_builder/ai_builder_create_outline.py tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py` — passed.
- `cd backend && uv run lint-imports --no-cache` — passed, 3 contracts kept.
- `git diff --check` over touched paths — passed.

## Claude Review

- Iteration 1 returned `GREEN_LIGHT: yes`, `MIN_SCORE: 8`, with one accepted
  test-quality finding: the partial-hint regression overlapped too much with an
  existing single referenced-hint test.
- The partial-hint test was strengthened to use two referenced hints across two
  steps while leaving a third server-derived hint unreferenced.
- Iteration 2 returned `GREEN_LIGHT: yes`, `MIN_SCORE: 8`.
- Final full compiler-file check after the strengthened test reported
  `99 passed, 7 failed`, with the same 7 deferred Cluster 2 failures listed
  below.

## Deferred Cluster 2 Failures

The full compiler test file now has 7 remaining failures, all in the deferred
targeted-underlag/audio fan-in cluster:

- `test_compile_outline_audio_docx_four_phase_body_step_fans_in_prior_work`
- `test_compile_outline_audio_artifact_final_body_step_fans_in_prior_structured_work[docx]`
- `test_compile_outline_audio_artifact_final_body_step_fans_in_prior_structured_work[pdf]`
- `test_compile_outline_audio_pdf_protocol_step_auto_authors_targeted_underlag`
- `test_compile_outline_audio_document_without_pattern_still_creates_transcript_source[docx]`
- `test_compile_outline_audio_document_without_pattern_still_creates_transcript_source[pdf]`
- `test_compile_outline_audio_docx_body_step_auto_authors_targeted_refs_when_json_predecessor`

These are the live quality issue reported by the user and are intentionally
left for the next source slice so the auto-binder ownership boundary can be
fixed once, through the shared dataflow normalization path.
