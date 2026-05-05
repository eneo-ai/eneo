# T016 Worker Receipt: Create Feedback Not-Actionable Rule

## Change

Removed the create quality-feedback repair rule that appended a second instruction when quality feedback mentioned `input_source="all_previous_steps"`.

## Why

Create-mode outline planning does not expose `input_source` authoring to the model, and stale client/model payloads are stripped before compile. The removed rule therefore asked the model not to author a backend-owned field it cannot productively author in the active create contract. The original critic feedback now passes through unchanged unless another actionable repair rule, such as terminal DOCX/PDF correction, applies.

## Tests

- `test_format_create_quality_feedback_does_not_redirect_input_source_authoring`
- existing terminal artifact repair feedback coverage
- existing create-outline schema and stale-mechanics stripping tests from the owner modules

## Validation

- `cd backend && uv run pytest -n 4 -q tests/unittests/flows/ai_builder/test_ai_builder_create_feedback.py tests/unittests/flows/ai_builder/test_ai_builder_tools.py::TestBuildToolSchema::test_outline_schema_hides_backend_owned_mechanics tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py::test_parse_outline_flow_ignores_stale_backend_owned_step_mechanics` — passed, 6 tests.
- `cd backend && uv run pyright src/intric/flows/ai_builder/ai_builder_create_feedback.py tests/unittests/flows/ai_builder/test_ai_builder_create_feedback.py` — passed, 0 errors.
- `cd backend && uv run ruff check src/intric/flows/ai_builder/ai_builder_create_feedback.py tests/unittests/flows/ai_builder/test_ai_builder_create_feedback.py` — passed.
- `cd backend && uv run ruff format --check src/intric/flows/ai_builder/ai_builder_create_feedback.py tests/unittests/flows/ai_builder/test_ai_builder_create_feedback.py` — passed.
- `cd backend && uv run lint-imports --no-cache` — passed, 3 contracts kept.
- `git diff --check` — passed for source, test, and board receipt files.
- Claude peer loop — iteration 1 returned `changes_required`; accepted duplicate-test and carry-forward findings. Iteration 2 returned `GREEN_LIGHT: yes`, `MIN_SCORE: 8`.

## Self-Review

- Correctness: the change removes only contradictory create-mode repair guidance; validation feedback for true JSON/all-previous incompatibility remains.
- Maintainability: the active contract is clearer because repair feedback no longer references a hidden backend-owned create field as a planner action item.
- Architecture: no new owner or abstraction was added; create-mode mechanics remain owned by outline parsing/compilation.
- Type safety: no untyped production surface was added; tests use existing typed parse/compile entry points.
- Scope: intentionally does not touch planner-context redesign, prompt vocabulary, runtime output style, or devcontainer changes.
- Merge readiness: mergeable if Claude commit gate remains green and final validation stays green.

## Carry-Forward

The broader planner-context redesign remains held pending live eval evidence. Runtime prose style and unrelated local files remain out of scope. The next AI Builder quality slice should rewrite create-mode critic remediations that still name backend-owned mechanics into semantic guidance.
