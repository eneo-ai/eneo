# T014 Worker Receipt — Structured Field Path Runtime Alignment

## Objective

Align AI Builder draft structured-field path validation with runtime list resolution.

## Source Change

`missing_draft_field_path()` now accepts a path ending on an array field, while still rejecting traversal past an array without a numeric index.

## Runtime Alignment

`FlowVariableResolver.resolve_path()` already returns a list when the path ends on a list value and raises when the caller tries to read a field from a list without an index. This slice adds direct tests for that runtime behavior.

## Validation

Red check:

```bash
rm -rf /tmp/t014-redcheck
git worktree add --detach /tmp/t014-redcheck HEAD
cp backend/.env /tmp/t014-redcheck/backend/.env
cp backend/tests/unittests/flows/ai_builder/test_ai_builder_structured_field_paths.py \
  /tmp/t014-redcheck/backend/tests/unittests/flows/ai_builder/test_ai_builder_structured_field_paths.py
cp backend/tests/unittests/flows/test_variable_resolver.py \
  /tmp/t014-redcheck/backend/tests/unittests/flows/test_variable_resolver.py
cd /tmp/t014-redcheck/backend
PYTHONPATH=/tmp/t014-redcheck/backend/src \
  /Users/ccimen/eneo/eneo/backend/.venv/bin/pytest -q \
  tests/unittests/flows/ai_builder/test_ai_builder_structured_field_paths.py::test_missing_draft_field_path_requires_array_index \
  tests/unittests/flows/test_variable_resolver.py::test_resolve_path_returns_list_when_path_ends_on_list_value \
  tests/unittests/flows/test_variable_resolver.py::test_resolve_path_requires_numeric_index_to_read_list_item_field
```

Result: `1 failed, 2 passed`. The runtime resolver tests passed; the AI Builder draft-path test failed on old source because `risker` returned missing path `"risker"`.

Main validation:

```bash
cd backend && uv run pytest -n 4 -q \
  tests/unittests/flows/ai_builder/test_ai_builder_structured_field_paths.py \
  tests/unittests/flows/test_variable_resolver.py
```

Result: `24 passed`.

```bash
cd backend && uv run pyright \
  src/intric/flows/ai_builder/ai_builder_structured_field_paths.py \
  tests/unittests/flows/ai_builder/test_ai_builder_structured_field_paths.py \
  tests/unittests/flows/test_variable_resolver.py
```

Result: `0 errors, 0 warnings, 0 informations`.

```bash
cd backend && uv run ruff check \
  src/intric/flows/ai_builder/ai_builder_structured_field_paths.py \
  tests/unittests/flows/ai_builder/test_ai_builder_structured_field_paths.py \
  tests/unittests/flows/test_variable_resolver.py
cd backend && uv run ruff format --check \
  src/intric/flows/ai_builder/ai_builder_structured_field_paths.py \
  tests/unittests/flows/ai_builder/test_ai_builder_structured_field_paths.py \
  tests/unittests/flows/test_variable_resolver.py
```

Result: passed.

```bash
cd backend && uv run lint-imports --no-cache
```

Result: all contracts kept.

```bash
git diff --check -- \
  backend/src/intric/flows/ai_builder/ai_builder_structured_field_paths.py \
  backend/tests/unittests/flows/ai_builder/test_ai_builder_structured_field_paths.py \
  backend/tests/unittests/flows/test_variable_resolver.py \
  docs/goals/flow-ai-builder-quality-hardening/state.yaml \
  docs/goals/flow-ai-builder-quality-hardening/notes/T013-judge-structured-field-path-slice.md \
  docs/goals/flow-ai-builder-quality-hardening/notes/T014-worker-structured-field-path-runtime-alignment.md
```

Result: passed.

## Self-Review

Correctness: the draft validator now mirrors runtime behavior for list leaf paths. Ending on `risker` is valid; traversing `risker.rubrik` is invalid; `risker.0.rubrik` remains valid.

Maintainability: this keeps draft-path validation aligned with the canonical runtime resolver rather than adding an AI Builder-specific special case.

Architecture: no runtime source changed. The AI Builder validator adapts to existing runtime semantics.

Type contracts: pyright passes on the touched source and tests.

Scope: no planner prompt, create outline, repair, or runtime output style changes were included.

Production ready: yes for this focused alignment.

Would merge: yes.

Could be cleaner: the docstring is acceptable because it records the non-obvious runtime-alignment invariant. If this grows, the invariant should move to a shared path-resolution policy test.
