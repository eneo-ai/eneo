# Fable 15 Implementation Progress - Underlag/Input Contract

## TL;DR

- Goal: make Flow AI Builder's `underlag till text`, input fields, prompts, and typed `source_refs` coherent without dumping unnecessary context.
- Current slice: preserve downstream structured-field needs in raw source-reader prompts without dumping the full downstream context.
- Do not treat this as a UI-only bug; the root owner is the Builder compiler/normalizer and authoring validation contract.
- The source-reader capture contract is bounded to the nearest downstream JSON extraction and emitted by the existing instruction compiler, not by a second prompt writer.
- Preserve unrelated frontend/devcontainer/fablereview dirty files from other agents.

## Source Artifacts

| Artifact | Role |
|---|---|
| `fable-15-underlag-input-contract-review.md` | Raw Fable review of exported document-analysis flow. |
| `codex-verify-fable-15-underlag-input-contract-report.md` | GPT-5.5 verification and corrected implementation order. |
| `.codex/artifacts/claude-fable15-underlag-plan-revised-v2.md` | Claude-reviewed final plan for slice boundaries. |
| `/Users/ccimen/Downloads/flow-debug-export-f0650612-baf2-4731-9898-d6c923388fd8.json` | User-supplied failing/illustrative export. |

## Implementation Sequence

| Slice | Status | Canonical owner | Acceptance criteria |
|---|---|---|---|
| 1. Duplicate `source_refs` | Implemented, peer-reviewed green, ready to commit | Builder compiler/normalizer for emission; `input_binding_contract_rules.py` for structural uniqueness; AI Builder validator for strict authoring gate | Duplicate refs by `(step_ref, output, field_path)` are collapsed before authoring validation, labeled refs win over unlabeled refs, runtime lowering still accepts duplicates, stale duplicate-pinning tests are flipped. |
| 2. Effective underlag visibility and reorder safety | Pending | Frontend editor projection/rendering; `flowStepOrderRemap.ts`; backend snapshot only if a read-only projection is needed | Typed refs and implicit previous-step underlag are visible; reorder remaps bare `source_refs[].step_ref`; deleting a referenced step shows stale/deleted source instead of silent rebinding. |
| 3. Upstream capture contract | Implemented, validation green, final peer verification pending | Create compiler collects downstream needs; schema-path helper owns terminal schema leaves; new-step instruction compiler renders bounded guidance | Raw source-reader steps preserve fields required by the nearest downstream JSON extraction or terminal schema; guidance is capped, deterministic, localized, and not duplicated when the instruction already names the field. |
| 4. Implicit-underlag diagnostics | Implemented, validation green, peer commit-gate pending | Runtime input-resolution diagnostics | Bindings-less previous/all-previous input gets `flow_underlag_summary` evidence for substantive implicit underlag without changing prompt text or emitting redundant refs. |
| 5. Source-ref writer consolidation / repair narrowing | Pending | Builder compiler/edit compiler and source-material normalizer | After create/edit compilers guarantee refs, delete or narrow repair that only compensates for invalid Builder output. |

## Slice 1 Boundaries

Allowed:

- `backend/src/eneo/flows/ai_builder/ai_builder_new_step_compiler.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_step_transition_policy.py` if whole-spec normalization is the cleanest dedup owner
- `backend/src/eneo/flows/input_binding_contract_rules.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_validator.py`
- Focused backend tests under `backend/tests/unittests/flows/`

Forbidden in slice 1:

- No frontend UI/reorder changes.
- No persisted `effective_underlag` field.
- No runtime duplicate rejection inside `source_ref_bindings()`, `_parse_source_ref()`, `effective_question_binding()`, or `lower_source_refs_to_question_binding()`.
- No RAG query, raw-document funnel, form-field detection, or terminal previous-step contract changes.

## Slice 1 Verification Checklist

- [x] Claude peer-loop plan gate reviewed current slice and required one shared dedupe owner across compiler and source-material normalization.
- [x] Duplicate compiler output is collapsed deterministically.
- [x] Authoring validation rejects manually authored duplicate semantic refs.
- [x] Runtime lowering remains tolerant of duplicate refs.
- [x] Mixed form-field + typed source refs keep form-field question content and do not lose non-ref sections.
- [x] Focused tests pass.
- [x] Claude peer-loop commit gate returns green before commit.

## Slice 1 Implementation Notes

- Added `dedupe_source_refs()` and `duplicate_source_ref_expressions()` to
  `backend/src/eneo/flows/input_binding_contract_rules.py`, keyed by the rendered
  source-ref template expression.
- Updated `compile_step_input_bindings()` to render deduped typed refs before
  deciding whether to emit `source_refs` or fallback `question`.
- Updated `source_material_bindings_for_boundary()` and
  `normalize_ai_builder_step()` so source-material completion and edit-time
  normalization collapse duplicate existing refs before `validate_spec()`.
- Added `duplicate_source_ref` as a structured AI Builder validation error in
  `validate_spec()`; the shared runtime parser/lowerer remains shape-only and
  duplicate-tolerant.

## Slice 1 Validation

| Command | Result |
|---|---|
| `uv run pytest tests/unittests/flows/test_input_binding_contract_rules.py tests/unittests/flows/ai_builder/test_ai_builder_authoring_projection.py::test_step_input_bindings_emit_source_refs_for_previous_output tests/unittests/flows/ai_builder/test_ai_builder_authoring_projection.py::test_step_input_bindings_dedupe_source_refs_without_dropping_form_fields tests/unittests/flows/ai_builder/test_ai_builder_step_transition_policy.py::test_normalize_ai_builder_spec_dedupes_existing_source_refs tests/unittests/flows/ai_builder/test_ai_builder_validator.py::TestDuplicates::test_duplicate_source_refs_rejected_as_structured_validation_error tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py::test_compile_create_steps_to_spec_dedupes_overlapping_previous_output_refs` | 21 passed |
| `uv run pytest tests/unittests/flows/test_input_binding_contract_rules.py tests/unittests/flows/ai_builder/test_ai_builder_authoring_projection.py tests/unittests/flows/ai_builder/test_ai_builder_step_transition_policy.py tests/unittests/flows/ai_builder/test_ai_builder_validator.py tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py` | 373 passed |
| `uv run ruff check src/eneo/flows/input_binding_contract_rules.py src/eneo/flows/ai_builder/ai_builder_new_step_compiler.py src/eneo/flows/ai_builder/ai_builder_source_material.py src/eneo/flows/ai_builder/ai_builder_step_transition_policy.py src/eneo/flows/ai_builder/ai_builder_validator.py tests/unittests/flows/test_input_binding_contract_rules.py tests/unittests/flows/ai_builder/test_ai_builder_authoring_projection.py tests/unittests/flows/ai_builder/test_ai_builder_step_transition_policy.py tests/unittests/flows/ai_builder/test_ai_builder_validator.py tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py` | passed |
| `uv run pyright src/eneo/flows/input_binding_contract_rules.py src/eneo/flows/ai_builder/ai_builder_new_step_compiler.py src/eneo/flows/ai_builder/ai_builder_source_material.py src/eneo/flows/ai_builder/ai_builder_step_transition_policy.py src/eneo/flows/ai_builder/ai_builder_validator.py tests/unittests/flows/test_input_binding_contract_rules.py tests/unittests/flows/ai_builder/test_ai_builder_authoring_projection.py tests/unittests/flows/ai_builder/test_ai_builder_step_transition_policy.py tests/unittests/flows/ai_builder/test_ai_builder_validator.py tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py` | 0 errors |

## Slice 1 Peer Review

| Reviewer | Artifact | Result |
|---|---|---|
| Claude peer loop iteration 1 | `.codex/artifacts/claude-peer-loop-fable-15-slice-1-source-refs-plan-20260705T102939Z.md` | `changes_required`; required shared dedupe owner across compiler and source-material producers, structured validation, and runtime tolerance. |
| Claude peer loop iteration 2 | `.codex/artifacts/claude-peer-loop-fable-15-slice-1-source-refs-implementation-20260705T104413Z.md` | `GREEN_LIGHT: yes`, `MIN_SCORE: 8`; safe to commit. |

## Slice 3 Boundaries

Allowed:

- `backend/src/eneo/flows/ai_builder/ai_builder_create_compiler.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_new_step_compiler.py`
- `backend/tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py`

Forbidden in slice 3:

- No frontend underlag visibility or reorder UI work.
- No runtime `input_bindings` semantics change.
- No full downstream prompt dump.
- No edit-path rewrite.
- No Fable/LLM eval golden yet; this slice adds the deterministic compiler contract that such a golden can later exercise.

## Slice 3 Implementation Notes

- `compile_create_steps_to_spec()` now collects capture fields for lossy source-reader steps after create-step mechanics are normalized.
- A source-reader step qualifies only when it reads flow input as `document`, `file`, or `text` and produces `text`.
- The collector uses only the nearest downstream JSON step with typed fields. If the JSON step is terminal and its model fields were cleared for an exact `terminal_output_schema`, the collector reuses `schema_leaf_property_names()` so nested object/array schemas preserve leaf facts rather than only container names.
- `compile_assistant_instructions()` remains the single prompt writer. It renders a bounded source-capture block through `SourceCaptureField` values.
- The source-capture block is capped at 8 fields, 96 description characters per field, and 900 rendered characters. It skips fields already named in the source-reader instruction.

## Slice 3 Validation

| Command | Result |
|---|---|
| `uv run pytest tests/unittests/flows/ai_builder/test_ai_builder_json_schema_paths.py::test_schema_leaf_property_names_descends_objects_and_array_items tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py::test_compile_create_steps_to_spec_tells_source_reader_downstream_json_needs tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py::test_compile_create_steps_to_spec_does_not_add_source_capture_without_downstream_json tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py::test_compile_create_steps_to_spec_uses_terminal_schema_for_source_capture tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py::test_compile_create_steps_to_spec_uses_nested_terminal_schema_leaves_for_source_capture tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py::test_compile_create_steps_to_spec_does_not_repeat_already_named_source_capture_field tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py::test_compile_create_steps_to_spec_caps_source_capture_fields` | 7 passed |
| `uv run pytest tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py tests/unittests/flows/ai_builder/test_ai_builder_json_schema_paths.py` | 203 passed |
| `uv run pytest tests/unittests/flows/ai_builder` | 2524 passed |
| `uv run ruff check src/eneo/flows/ai_builder/ai_builder_create_compiler.py src/eneo/flows/ai_builder/ai_builder_new_step_compiler.py src/eneo/flows/ai_builder/ai_builder_json_schema_paths.py tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py tests/unittests/flows/ai_builder/test_ai_builder_json_schema_paths.py` | passed |
| `uv run pyright src/eneo/flows/ai_builder/ai_builder_create_compiler.py src/eneo/flows/ai_builder/ai_builder_new_step_compiler.py src/eneo/flows/ai_builder/ai_builder_json_schema_paths.py tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py tests/unittests/flows/ai_builder/test_ai_builder_json_schema_paths.py` | 0 errors |

## Slice 3 Peer Review

| Reviewer | Artifact | Result |
|---|---|---|
| Claude peer loop iteration 1 | `.codex/artifacts/claude-peer-loop-fable-15-capture-contract-plan-20260705T105549Z.md` | `changes_required`; required one instruction writer, explicit token caps, terminal schema support, `ui_language` reuse, and idempotency/bound tests. |
| Claude peer loop iteration 2 | `.codex/artifacts/claude-peer-loop-fable-15-capture-contract-plan-revised-20260705T110227Z.md` | `GREEN_LIGHT: yes`, `MIN_SCORE: 8`; plan approved for implementation. |
| Claude peer loop iteration 3 | `.codex/artifacts/claude-peer-loop-fable-15-capture-contract-implementation-20260705T111634Z.md` | `GREEN_LIGHT: yes`, `MIN_SCORE: 8`; found a non-blocking nested terminal-schema gap, now fixed before commit. |
| Claude peer loop iteration 4 | `.codex/artifacts/claude-peer-loop-fable-15-capture-contract-final-verification-20260705T112248Z.md` | `GREEN_LIGHT: yes`, `MIN_SCORE: 8`; nested terminal-schema fix is commit-ready. |

## Slice 4 Boundaries

Allowed:

- `backend/src/eneo/flows/runtime/step_input_resolution.py`
- `backend/tests/unittests/flows/test_typed_io_executor.py`

Forbidden in slice 4:

- No frontend display or reorder work.
- No prompt/input composition changes.
- No persisted schema or API model changes.
- No new provenance subsystem.
- No `StepDiagnostic` type overhaul.

## Slice 4 Implementation Notes

- The existing prior-input diagnostic block now emits `flow_underlag_summary` with `severity="info"` for substantive implicit `previous_step` and `all_previous_steps` input.
- The info summary is explicitly gated by `not used_question_binding` so explicit question bindings do not double-count diagnostics.
- Byte count uses finalized `input_text`, matching the actual `StepInputValue.text` delivered to the step.
- `all_previous_steps` source counts use the same source collection as the resolved text: `state.completed_by_order.values()` when state exists, otherwise `prior_results`, filtered to earlier step orders.
- Structured-only implicit JSON input is treated as substantive when JSON normalization produces non-empty resolved input text.

## Slice 4 Validation

| Command | Result |
|---|---|
| `rg -n "flow_underlag_summary|empty_prior_step_input|diagnostics == \\[\\]|len\\([^\\n]*diagnostics\\)" backend/tests backend/src/eneo/flows \| head -220` | Confirmed exact diagnostic assertions outside `test_typed_io_executor.py` are unrelated RAG/evidence fixture paths. |
| `uv run pytest tests/unittests/flows/test_typed_io_executor.py::test_resolve_step_input_json_question_binding_overrides_previous_structured tests/unittests/flows/test_typed_io_executor.py::test_resolve_step_input_previous_step_with_content_emits_underlag_summary_info tests/unittests/flows/test_typed_io_executor.py::test_resolve_step_input_all_previous_steps_prefers_state_accumulator tests/unittests/flows/test_typed_io_executor.py::test_resolve_step_input_json_previous_step_structured_only_emits_underlag_summary tests/unittests/flows/test_typed_io_executor.py::test_resolve_step_input_json_previous_step_summary_counts_resolved_input_bytes tests/unittests/flows/test_typed_io_executor.py::test_resolve_step_input_previous_step_missing_prior_returns_empty_text tests/unittests/flows/test_typed_io_executor.py::test_resolve_step_input_all_previous_steps_empty_content_sets_warning` | 7 passed |
| `uv run pytest tests/unittests/flows/test_typed_io_executor.py` | 58 passed |
| `uv run ruff check src/eneo/flows/runtime/step_input_resolution.py tests/unittests/flows/test_typed_io_executor.py` | passed |
| `uv run ruff format --check src/eneo/flows/runtime/step_input_resolution.py tests/unittests/flows/test_typed_io_executor.py` | passed |
| `uv run pyright src/eneo/flows/runtime/step_input_resolution.py tests/unittests/flows/test_typed_io_executor.py` | 0 errors |

## Slice 4 Peer Review

| Reviewer | Artifact | Result |
|---|---|---|
| Claude peer loop iteration 1 | `.codex/artifacts/claude-peer-loop-fable-15-implicit-underlag-diagnostics-plan-20260705T113302Z.md` | `changes_required`; required single predicate owner, coherent all-previous metrics, honest structured JSON scope, and non-brittle tests. |
| Claude peer loop iteration 2 | `.codex/artifacts/claude-peer-loop-fable-15-implicit-underlag-diagnostics-plan-revised-20260705T113949Z.md` | `changes_required`; required byte count from finalized `input_text` and a JSON byte-accuracy test. |
| Claude peer loop iteration 3 | `.codex/artifacts/claude-peer-loop-fable-15-implicit-underlag-diagnostics-plan-final-20260705T114514Z.md` | `changes_required`; required explicit `not used_question_binding` gate and exact-one summary assertion. |
| Claude peer loop iteration 4 | `.codex/artifacts/claude-peer-loop-fable-15-implicit-underlag-diagnostics-plan-green-check-20260705T115100Z.md` | `GREEN_LIGHT: yes`, `MIN_SCORE: 8`; plan approved for implementation. |
| Claude peer loop iteration 5 | `.codex/artifacts/claude-peer-loop-fable-15-implicit-underlag-diagnostics-implementation-20260705T115835Z.md` | `GREEN_LIGHT: yes`, `MIN_SCORE: 8`; implementation is commit-ready. |

## Notes

- The Builder is pre-production, so stale Builder tests that preserve duplicate refs should be flipped or deleted rather than accommodated.
- Existing published/runtime flows must remain runnable; strict uniqueness belongs only at authoring/validation boundaries.
