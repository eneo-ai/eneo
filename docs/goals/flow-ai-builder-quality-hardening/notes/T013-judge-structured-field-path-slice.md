# T013 Judge Decision — Structured Field Path Runtime Alignment

## Decision

Activate a source Worker for the structured-field path relaxation only if it includes runtime resolver alignment tests.

## Why This Slice

The dirty `ai_builder_structured_field_paths.py` change is small and potentially correct:

- `risker.0.rubrik` should be valid.
- `risker.rubrik` should be invalid because runtime list traversal requires a numeric index.
- `risker` should be valid because runtime resolution can return the whole list and render it.

The current dirty test only covers AI Builder draft-path validation. The missing proof is runtime alignment through `FlowVariableResolver.resolve_path()`.

## Allowed Files

- `backend/src/intric/flows/ai_builder/ai_builder_structured_field_paths.py`
- `backend/tests/unittests/flows/ai_builder/test_ai_builder_structured_field_paths.py`
- `backend/tests/unittests/flows/test_variable_resolver.py`
- `docs/goals/flow-ai-builder-quality-hardening/state.yaml`
- `docs/goals/flow-ai-builder-quality-hardening/notes/T013-judge-structured-field-path-slice.md`
- `docs/goals/flow-ai-builder-quality-hardening/notes/T014-worker-structured-field-path-runtime-alignment.md`

## Held Dirty Clusters

Do not include:

- create-mode prompt/input-field redesign
- unreferenced-form-field backstop deletion
- `all_previous_steps` repair feedback removal
- runtime prose-over-bullets nudge
- devcontainer files
- `scripts/run_codex_review.sh`, `PRODUCT.md`, `utvecklingssamtal.mp3`
- broad docs deletion or untracked refactor docs

## Worker Gates

- Add or preserve runtime resolver tests proving list leaf access succeeds and list field traversal without numeric index fails.
- Prove the AI Builder draft validator mirrors that runtime behavior.
- Run focused tests, pyright, ruff, format check, lint-imports, and diff check.
