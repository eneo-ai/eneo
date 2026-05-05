# T015 Judge Receipt: Create-Feedback Disposition

## Decision

Select a narrow source slice for the remaining `ai_builder_create_feedback.py` change only.

## Evidence

- The create-mode outline schema hides backend-owned step mechanics including `input_source`, `input_type`, and `input_bindings`.
- The outline parser/compiler strips stale backend-owned step mechanics before materializing the create draft.
- The removed quality-feedback redirect told the create-mode planner not to author `input_source`, but create-mode already withholds and strips that field. That made the redirect contradictory rather than actionable.

## Worker Scope

Allowed files:

- `backend/src/intric/flows/ai_builder/ai_builder_create_feedback.py`
- `backend/tests/unittests/flows/ai_builder/test_ai_builder_create_feedback.py`
- `docs/goals/flow-ai-builder-quality-hardening/state.yaml`
- `docs/goals/flow-ai-builder-quality-hardening/notes/T015-judge-create-feedback-disposition.md`
- `docs/goals/flow-ai-builder-quality-hardening/notes/T016-worker-create-feedback-unreachable-rule.md`

Held out:

- planner-context redesign files
- runtime prose-over-bullets prompt change
- broad architecture doc deletion
- devcontainer files
- `scripts/run_codex_review.sh`
- `PRODUCT.md`
- `utvecklingssamtal.mp3`
- untracked local review/PRD artifacts

## Validation Required

- `cd backend && uv run pytest -n 4 -q tests/unittests/flows/ai_builder/test_ai_builder_create_feedback.py tests/unittests/flows/ai_builder/test_ai_builder_tools.py::TestBuildToolSchema::test_outline_schema_hides_backend_owned_mechanics tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py::test_parse_outline_flow_ignores_stale_backend_owned_step_mechanics`
- `cd backend && uv run pyright src/intric/flows/ai_builder/ai_builder_create_feedback.py tests/unittests/flows/ai_builder/test_ai_builder_create_feedback.py`
- `cd backend && uv run ruff check src/intric/flows/ai_builder/ai_builder_create_feedback.py tests/unittests/flows/ai_builder/test_ai_builder_create_feedback.py`
- `cd backend && uv run ruff format --check src/intric/flows/ai_builder/ai_builder_create_feedback.py tests/unittests/flows/ai_builder/test_ai_builder_create_feedback.py`
- `cd backend && uv run lint-imports --no-cache`
- `git diff --check -- backend/src/intric/flows/ai_builder/ai_builder_create_feedback.py backend/tests/unittests/flows/ai_builder/test_ai_builder_create_feedback.py docs/goals/flow-ai-builder-quality-hardening/state.yaml docs/goals/flow-ai-builder-quality-hardening/notes/T015-judge-create-feedback-disposition.md docs/goals/flow-ai-builder-quality-hardening/notes/T016-worker-create-feedback-unreachable-rule.md`

## Stop Conditions

- Need planner prompt, create outline production code, runtime code, devcontainer, or unrelated local files.
- Cannot prove the removed repair instruction is unreachable or not actionable.
- Validation fails.
- Claude commit gate finds a blocker that requires product or architectural decision.
