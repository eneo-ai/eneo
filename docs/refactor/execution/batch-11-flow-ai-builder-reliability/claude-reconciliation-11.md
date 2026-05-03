# Batch 11.3b Claude Reconciliation - Form-Field Lifecycle Goldens

## TL;DR

1. Claude rejected the first 11.3b plan because the scenario assertions and discovery owner were under-specified.
2. The accepted plan made 11.3b test-only, path-discoverable, and explicit about exact post-conditions.
3. Implementation added lifecycle goldens without source behavior changes.
4. The Pattern Registry guard became a canonical-owner invariant for `runtime_metadata_fields`.
5. Claude green-lit the implementation with minimum score `8`.

## Plan Review

| Iteration | Artifact | Verdict | Green light | Minimum score | Outcome |
|---:|---|---|---|---:|---|
| 1 | `.codex/artifacts/claude-peer-loop-batch-11-3b-form-field-lifecycle-plan-20260503T064226Z.md` | `changes_required` | `no` | 6 | Tighten assertions, path ownership, edit carry-forward, and test-only scope. |
| 2 | `.codex/artifacts/claude-peer-loop-batch-11-3b-form-field-lifecycle-plan-verification-20260503T064602Z.md` | `green` | `yes` | 8 | Accepted the revised test-only lifecycle plan. |

## Accepted Plan Findings

| Finding | Resolution |
|---|---|
| Chain scenario post-conditions were too loose. | Plan pins intermediate use, final-step non-reference, structured previous-field binding, and valid compiled spec. |
| Pattern Registry guard duplicated membership tests. | Replaced with single-owner invariants for required slots and question template ids. |
| Goldens in the large create-compiler test file would be hard for 11.4 to discover. | Added dedicated `test_ai_builder_form_field_lifecycle.py`. |
| Edit-path parity was implicit. | Carried edit twins to 11.4. |
| Source-change exception could expand scope. | 11.3b is test-only; source bugs become separate slices. |

## Final Shape

| Concept | Owner |
|---|---|
| Form-field lifecycle goldens | `test_ai_builder_form_field_lifecycle.py`. |
| Pattern Registry runtime metadata owner invariant | `test_pattern_registry.py`. |
| Source behavior | Existing compiler and outline code; no 11.3b source changes. |
| Edit parity | 11.4 matrix slice. |

## Implementation Review

| Iteration | Artifact | Verdict | Green light | Minimum score | Outcome |
|---:|---|---|---|---:|---|
| 3 | `.codex/artifacts/claude-peer-loop-batch-11-3b-form-field-lifecycle-implementation-20260503T065235Z.md` | `green` | `yes` | 8 | Accepted test-only implementation; no blockers. |

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

## Carry-Forward

| Item | Owner |
|---|---|
| Edit-path twin for declare-only, chain, and multi-reference lifecycle goldens. | 11.4 |
| Matrix harness discovery of `test_ai_builder_form_field_lifecycle.py`. | 11.4 |
| Any source bug exposed by future lifecycle tests. | Separate bug slice |

Confidence: high.
