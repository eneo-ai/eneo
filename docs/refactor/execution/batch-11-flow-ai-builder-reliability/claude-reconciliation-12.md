# Batch 11.4a Claude Reconciliation - Golden Coverage Matrix Harness

## TL;DR

1. Claude rejected the first 11.4a plan because neutrality scope, denominator math, exception retirement, and owner lookup were under-specified.
2. The accepted plan uses coverage-owner rows, enum concerns, AST owner lookup, scoped metadata neutrality, and expiring edit exceptions.
3. Implementation added a test-only matrix owner and one edit lifecycle twin.
4. Validation passed locally, including the full AI Builder unit suite.
5. Claude green-lit the implementation with minimum score `8`.

## Plan Review

| Iteration | Artifact | Verdict | Green light | Minimum score | Outcome |
|---:|---|---|---|---:|---|
| 1 | `.codex/artifacts/claude-peer-loop-batch-11-4a-golden-coverage-matrix-plan-20260503T065957Z.md` | `changes_required` | `no` | 7 | Tighten domain-neutrality scope, denominator, exception retirement, owner lookup, and concern typing. |
| 2 | `.codex/artifacts/claude-peer-loop-batch-11-4a-golden-coverage-matrix-plan-verification-20260503T070329Z.md` | `green` | `yes` | 8 | Accepted revised matrix-owner plan. |

## Accepted Plan Findings

| Finding | Resolution |
|---|---|
| Domain-neutrality scope was ambiguous. | Scope is matrix metadata and new lifecycle test names; existing fixture-body cleanup is a follow-up. |
| 30% form-field-chain denominator was undefined. | Initial denominator is 5 owner rows, with 4 form-field-chain rows. |
| Edit exceptions could rot. | Exceptions require `reason`, `retire_when`, minimum length, and no placeholder words. |
| Owner resolution could import sibling test modules. | Matrix uses `find_spec` plus AST inspection. |
| `concerns` would be stringly typed. | Matrix uses `CoverageConcern` enum values. |

## Final Shape

| Concept | Owner |
|---|---|
| Golden coverage metadata and gates | `test_ai_builder_golden_coverage_matrix.py`. |
| Form-field lifecycle behavior | `test_ai_builder_form_field_lifecycle.py`. |
| Pattern Registry / FCM archetype behavior | `test_ai_builder_materialization_bridge.py`. |
| Source behavior | Existing source; no source changes in 11.4a. |

## Implementation Review

| Iteration | Artifact | Verdict | Green light | Minimum score | Outcome |
|---:|---|---|---|---:|---|
| 3 | `.codex/artifacts/claude-peer-loop-batch-11-4a-golden-coverage-matrix-implementation-20260503T071148Z.md` | `green` | `yes` | 8 | Accepted implementation; suggested minor maintainability polish. |

Accepted polish:

| Finding | Resolution |
|---|---|
| AST owner lookup should support async tests. | Added `ast.AsyncFunctionDef` support. |
| Edit twin/exception XOR readability could improve. | Added named booleans and an assertion message. |
| Percentage thresholds should be named. | Added named percentage constants. |
| Edit twins should not drift to unrelated concerns. | Added a twin concern superset assertion. |

## Validation

| Command | Result |
|---|---|
| `uv run pytest tests/unittests/flows/ai_builder/test_ai_builder_golden_coverage_matrix.py tests/unittests/flows/ai_builder/test_ai_builder_form_field_lifecycle.py tests/unittests/flows/ai_builder/test_ai_builder_materialization_bridge.py -q` | Passed: `46 passed`. |
| `uv run pytest tests/unittests/flows/ai_builder -q` | Passed: `1751 passed, 4 skipped`, 12 existing warnings. |
| `uv run pyright tests/unittests/flows/ai_builder/test_ai_builder_golden_coverage_matrix.py tests/unittests/flows/ai_builder/test_ai_builder_form_field_lifecycle.py` | Passed: `0 errors, 0 warnings, 0 informations`. |
| `uv run ruff check tests/unittests/flows/ai_builder/test_ai_builder_golden_coverage_matrix.py tests/unittests/flows/ai_builder/test_ai_builder_form_field_lifecycle.py` | Passed. |
| `uv run ruff format --check tests/unittests/flows/ai_builder/test_ai_builder_golden_coverage_matrix.py tests/unittests/flows/ai_builder/test_ai_builder_form_field_lifecycle.py` | Passed. |
| Claude implementation review | Passed: `green`, minimum score `8`. |

## Carry-Forward

| Item | Owner |
|---|---|
| Add matrix rows only with same-slice ratio backfill. | Future 11.4 rows |
| Clean existing municipality-flavoured fixture bodies outside matrix metadata. | Later test-neutrality cleanup |
| Promote additional create/edit parity rows as behavior goldens are added. | Future 11.4 rows |

Confidence: high.
