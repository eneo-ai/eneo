# T028 Edit Structured-Field Normalizer

## Problem

E1 edit eval exposed a strict parse failure where `edit_flow` add-step payloads could include `output_fields` with `field_type="object"` but no nested `fields`. `StructuredFieldDraft` is correct to reject that shape. The missing piece was that edit add-step parsing did not reuse the loose structured-field normalization already used by create-mode outline parsing.

## Change

- Added `backend/src/intric/flows/ai_builder/ai_builder_structured_field_normalizer.py` as the canonical owner for loose LLM-shaped structured-field coercion.
- Updated create-mode outline parsing to import the shared normalizer and removed the duplicate private helper cluster from `ai_builder_create_outline.py`.
- Renamed edit pre-parse cleanup to `normalize_loose_edit_arguments` with no compatibility wrapper.
- Normalized `add_payload.output_fields` for edit add operations before strict `FlowEditDraft` parsing.
- Kept modify patch payloads out of structured-field normalization scope.
- Preserved strict `StructuredFieldDraft` validation; malformed loose objects are downgraded before the strict boundary.
- Added structured observability for object downgrades and whole field-list drops without logging raw prompt/source/description content.

## Verification

- Red evidence: `uv run --directory backend pytest -n 4 tests/unittests/flows/ai_builder/test_ai_builder_edit_normalizer.py -q` initially failed because `normalize_loose_edit_arguments` did not exist.
- `uv run --directory backend pytest -n 4 tests/unittests/flows/ai_builder/test_ai_builder_edit_normalizer.py -q` -> 8 passed.
- `uv run --directory backend pytest -n 4 tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py -q -k 'malformed_array_item_fields or output_fields'` -> 3 passed.
- `uv run --directory backend pytest -n 4 tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py -q -k 'edit_flow or normalizes_loose_add_payload_output_fields'` -> 3 passed.
- `uv run --directory backend pyright ...` -> 0 errors, 0 warnings.
- `uv run --directory backend ruff check ... && uv run --directory backend ruff format --check ...` -> passed.
- `uv run --directory backend pytest -n 4 tests/unittests/flows/ai_builder -q` -> 2021 passed, 4 skipped, 42 warnings.

## Live Eval

- C1 applied and published once: `/tmp/material-efficiency-live-eval/20260506-043752-t028-c1-base/summary.json`, flow `41fe5954-f3af-4e7b-82ea-35fa57d70e21`.
- E1 against that published flow failed apply with `flow_is_published`; setup issue, not a builder parse result.
- C1 unpublished first attempt failed before plan generation with `invalid_session_transition: cancelled -> awaiting_approval`; live/session flake, not tied to structured-field parsing.
- C1 unpublished retry applied: `/tmp/material-efficiency-live-eval/20260506-044206-t028-c1-unpublished-base-retry/summary.json`, flow `87ac9665-575a-47e4-9ab0-65593ef78bd7`.
- E1 3-run against the draft flow: `/tmp/material-efficiency-live-eval/20260506-044605-t028-e1-edit-normalizer-retry/summary.json` -> statuses `http_error`, `http_error`, `applied`.
- The two E1 HTTP errors were 500s with error IDs `b730ee9c` and `2ef2bcf3`; artifacts contained no `Object fields must declare`, no `self_correction_invalid_payload`, and no edit parse failure. One E1 run applied successfully.

## Claude

- `.codex/artifacts/claude-peer-loop-t028-implementation-review-20260506T030237Z.md` -> GREEN_LIGHT yes, MIN_SCORE 8.
- `.codex/artifacts/claude-peer-loop-t028-implementation-review-follow-up-20260506T030620Z.md` -> GREEN_LIGHT yes, MIN_SCORE 8.

## Follow-Ups

- Triage the remaining E1 HTTP 500s as a separate runtime/apply reliability issue.
- Add a one-line docstring to `looks_like_structured_field_spec` when the file is next touched.
