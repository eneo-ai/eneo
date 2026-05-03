# Batch 11.3b Retrospective - Form-Field Lifecycle Goldens

## TL;DR

1. Slice 11.3b is test-only; no source behavior changed.
2. Form-field lifecycle coverage now has a dedicated test file for 11.4 matrix discovery.
3. Declare-only, intermediate-chain, and multi-reference form-field behavior are pinned.
4. `runtime_metadata_fields` now has a single Pattern Registry owner invariant.
5. Validation passed, including the full AI Builder unit suite.

## Result

| Area | Outcome |
|---|---|
| Lifecycle goldens | Added `test_ai_builder_form_field_lifecycle.py` as the canonical test owner. |
| Declare-only fields | A user-declared field with no explicit step use attaches to the final step and renders once. |
| Intermediate chains | A form field used by an intermediate JSON-producing step flows forward through structured previous-step output, not by final-step re-reference. |
| Multi-reference fields | One declared field can feed two step bindings, once in each binding string. |
| Pattern Registry ownership | `form_field_runtime_inputs` is the only positive owner of `runtime_metadata_fields` in required slots and question template ids. |

## Acceptance

| Criterion | Status | Evidence |
|---|---|---|
| 11.3b stayed test-only. | pass | No `backend/src` files changed in this slice. |
| Lifecycle goldens are discoverable by path. | pass | `backend/tests/unittests/flows/ai_builder/test_ai_builder_form_field_lifecycle.py`. |
| Declare-only field behavior is pinned. | pass | `test_declared_input_field_without_step_use_attaches_to_final_step`. |
| Intermediate chain behavior is pinned. | pass | `test_intermediate_form_field_use_flows_through_structured_previous_field`. |
| Multi-reference behavior is pinned. | pass | `test_one_input_field_can_feed_two_step_bindings_once_each`. |
| Pattern Registry canonical owner is pinned. | pass | Required-slot and question-template owner tests in `test_pattern_registry.py`. |

## Validation

| Command | Result |
|---|---|
| `uv run pytest tests/unittests/flows/ai_builder/test_ai_builder_form_field_lifecycle.py tests/unittests/flows/ai_builder/test_pattern_registry.py tests/unittests/flows/ai_builder/test_ai_builder_edit_validator.py -q` | Passed: `90 passed`. |
| `uv run pytest tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py -q` | Passed: `75 passed`. |
| `uv run pytest tests/unittests/flows/ai_builder -q` | Passed: `1743 passed, 4 skipped`, 12 existing warnings. |
| `uv run pyright tests/unittests/flows/ai_builder/test_ai_builder_form_field_lifecycle.py tests/unittests/flows/ai_builder/test_pattern_registry.py` | Passed: `0 errors, 0 warnings, 0 informations`. |
| `uv run ruff check tests/unittests/flows/ai_builder/test_ai_builder_form_field_lifecycle.py tests/unittests/flows/ai_builder/test_pattern_registry.py` | Passed. |
| `uv run ruff format --check tests/unittests/flows/ai_builder/test_ai_builder_form_field_lifecycle.py tests/unittests/flows/ai_builder/test_pattern_registry.py` | Passed. |
| `./scripts/gate-local/anti_slippage.sh --worktree` | Passed. |
| `git diff --check -- <11.3b touched paths>` | Passed. |
| Docker focused smoke | Blocked before Docker ran by tool policy; local `uv` validation is the recorded gate. |
| Claude implementation review | Passed: `green`, minimum score `8`. |

## Follow-Ups

| Item | Owner |
|---|---|
| Edit-path twins for lifecycle goldens and matrix coverage percentage. | 11.4 |
| Matrix harness path discovery for `test_ai_builder_form_field_lifecycle.py`. | 11.4 |
| Source fix if a later lifecycle golden exposes a compiler bug. | Separate bug slice |

## Risk

| Risk | Mitigation |
|---|---|
| The lifecycle file could drift from the future matrix harness. | 11.4 owns path-based discovery. |
| Pattern Registry could gain a duplicate runtime metadata owner. | Single-owner tests now fail loudly. |
| Create-path only coverage could be mistaken for edit parity. | Edit twins are explicitly carried to 11.4. |

Confidence: high.
