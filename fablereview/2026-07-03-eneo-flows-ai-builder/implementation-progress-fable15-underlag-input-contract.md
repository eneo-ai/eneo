# Fable 15 Implementation Progress - Underlag/Input Contract

## TL;DR

- Goal: make Flow AI Builder's `underlag till text`, input fields, prompts, and typed `source_refs` coherent without dumping unnecessary context.
- Current slice: remove duplicate semantic `source_refs` in the Builder authoring path while keeping runtime tolerant for old duplicate-bearing flows.
- Do not treat this as a UI-only bug; the root owner is the Builder compiler/normalizer and authoring validation contract.
- Do not implement upstream capture-contract prompt changes until a golden proves current source-reader detail loss.
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
| 3. Upstream capture contract | Pending, gated | Derived downstream-needs contract near Builder compiler/planning state | A golden first proves current source-reader detail loss. Only then add bounded downstream needs to the raw-source-reading step; no broad prompt stuffing. |
| 4. Implicit-underlag diagnostics | Pending | Runtime input-resolution diagnostics | Bindings-less previous-step input gets diagnostic parity with explicit underlag for evidence/debug transparency. |
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

## Notes

- The Builder is pre-production, so stale Builder tests that preserve duplicate refs should be flipped or deleted rather than accommodated.
- Existing published/runtime flows must remain runnable; strict uniqueness belongs only at authoring/validation boundaries.
