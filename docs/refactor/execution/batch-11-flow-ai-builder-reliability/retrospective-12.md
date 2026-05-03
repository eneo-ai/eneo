# Batch 11.4a Retrospective - Golden Coverage Matrix Harness

## TL;DR

1. Slice 11.4a adds a test-only golden coverage matrix owner.
2. The matrix references canonical owner tests by module/function instead of duplicating fixtures.
3. Owner existence, Pattern Registry ids, FCM tuple legality, edit parity, form-field ratio, and metadata neutrality are now gated.
4. One edit-path multi-reference form-field twin was added to the lifecycle owner.
5. Validation passed, including the full AI Builder unit suite.

## Result

| Area | Outcome |
|---|---|
| Matrix owner | `test_ai_builder_golden_coverage_matrix.py` owns coverage metadata and gates. |
| Behavior owners | Materialization bridge, form-field lifecycle, and edit behavior tests remain the behavior owners. |
| Owner resolution | Static AST lookup avoids importing sibling test modules. |
| Edit parity | Create rows require an edit twin or a retiring exception. |
| Coverage ratios | Initial matrix has 5 owner rows, 4 form-field-chain rows, and 1 edit row. |
| Source scope | No backend source files changed. |

## Acceptance

| Criterion | Status | Evidence |
|---|---|---|
| Matrix rows are typed and centralized. | pass | `GoldenCoverageRow`, `CoverageSurface`, and `CoverageConcern`. |
| Owner rows fail if owner tests disappear. | pass | AST-based owner existence test. |
| Pattern ids stay canonical. | pass | Matrix asserts listed ids exist in `PATTERN_REGISTRY`. |
| FCM tuples and chains stay legal. | pass | Matrix uses `resolve_capability_for_tuple` and `validate_step_chain`. |
| Edit exceptions are expiring, not permanent. | pass | Exceptions require `reason`, `retire_when`, minimum length, and no placeholder words. |
| Metadata neutrality is explicit. | pass | `MUNICIPALITY_ONLY_TOKENS` guard over row metadata. |

## Validation

| Command | Result |
|---|---|
| `uv run pytest tests/unittests/flows/ai_builder/test_ai_builder_golden_coverage_matrix.py tests/unittests/flows/ai_builder/test_ai_builder_form_field_lifecycle.py tests/unittests/flows/ai_builder/test_ai_builder_materialization_bridge.py -q` | Passed: `46 passed`. |
| `uv run pytest tests/unittests/flows/ai_builder -q` | Passed: `1751 passed, 4 skipped`, 12 existing warnings. |
| `uv run pyright tests/unittests/flows/ai_builder/test_ai_builder_golden_coverage_matrix.py tests/unittests/flows/ai_builder/test_ai_builder_form_field_lifecycle.py` | Passed: `0 errors, 0 warnings, 0 informations`. |
| `uv run ruff check tests/unittests/flows/ai_builder/test_ai_builder_golden_coverage_matrix.py tests/unittests/flows/ai_builder/test_ai_builder_form_field_lifecycle.py` | Passed. |
| `uv run ruff format --check tests/unittests/flows/ai_builder/test_ai_builder_golden_coverage_matrix.py tests/unittests/flows/ai_builder/test_ai_builder_form_field_lifecycle.py` | Passed. |
| Claude implementation review | Passed: `green`, minimum score `8`. |

## Follow-Ups

| Item | Owner |
|---|---|
| Add edit twins or expiring exceptions as new create goldens enter the matrix. | Future 11.4 rows |
| Clean municipality-flavoured existing fixture bodies outside matrix metadata. | Later test-neutrality cleanup |
| Expand matrix rows only with same-slice ratio backfill when denominator growth threatens the gates. | Future 11.4 rows |

## Risk

| Risk | Mitigation |
|---|---|
| Matrix metadata could become a second behavior registry. | Rows reference owner tests and do not duplicate fixture bodies. |
| Edit exceptions could become permanent. | `retire_when` is required and placeholder words are rejected. |
| Coverage percentages could erode as rows are added. | Plan requires counterpart backfill instead of lowering gates. |
| Edit twins could point at unrelated coverage. | Matrix now asserts twin concerns are a superset of the create row concerns. |

Confidence: high.
