# T011 Judge Decision — Validation Quality Helper Slice

## Decision

Activate a narrow source Worker for the `ai_builder_validation_quality.py` caller migration to `find_unused_form_fields`.

## Why This Slice

The broad dirty worktree is not commit-ready. The planner-context changes around `input_fields`, `uses_input_fields`, prompt hints, and form-field backstop removal need live eval evidence before they can be trusted.

This slice is different:

- `find_unused_form_fields` is already the canonical owner committed in `48edf292`.
- `ai_builder_validation_quality.py` still contains the duplicate template-walking logic.
- Replacing that duplicate with the helper is a small source cleanup with one clear responsibility.
- It does not change planner prompts, repair behavior, source-material binding, runtime rendering, or live model behavior.

## Allowed Files

- `backend/src/intric/flows/ai_builder/ai_builder_validation_quality.py`
- `docs/goals/flow-ai-builder-quality-hardening/state.yaml`
- `docs/goals/flow-ai-builder-quality-hardening/notes/T011-judge-validation-quality-helper-slice.md`
- `docs/goals/flow-ai-builder-quality-hardening/notes/T012-worker-validation-quality-helper.md`

## Held Dirty Clusters

Do not include these in this source slice:

- create-mode `input_fields` / `uses_input_fields` prompt redesign
- removal of the unreferenced-form-field final-step backstop
- `all_previous_steps` repair feedback removal
- structured field path relaxation
- runtime prose-over-bullets typed-output nudge
- devcontainer files
- `scripts/run_codex_review.sh`, `PRODUCT.md`, `utvecklingssamtal.mp3`
- broad docs deletion or untracked refactor docs

## Claude Status

The dirty-worktree disposition peer review timed out twice before returning a verdict. The timeout artifacts were saved under `.codex/artifacts/claude-peer-loop-dirty-worktree-disposition-*`.

`[no-peer-review]` is acceptable for this specific selected Worker because it is a tiny source deduplication against a helper that already has focused tests and no planner/runtime behavior change.

## Worker Validation

Run:

```bash
cd backend && uv run pytest -n 4 -q \
  tests/unittests/flows/ai_builder/test_ai_builder_form_field_usage.py \
  tests/unittests/flows/ai_builder/test_ai_builder_validator.py
```

```bash
cd backend && uv run pyright \
  src/intric/flows/ai_builder/ai_builder_validation_quality.py \
  src/intric/flows/ai_builder/ai_builder_form_field_usage.py \
  tests/unittests/flows/ai_builder/test_ai_builder_form_field_usage.py \
  tests/unittests/flows/ai_builder/test_ai_builder_validator.py
```

```bash
cd backend && uv run ruff check \
  src/intric/flows/ai_builder/ai_builder_validation_quality.py \
  tests/unittests/flows/ai_builder/test_ai_builder_form_field_usage.py \
  tests/unittests/flows/ai_builder/test_ai_builder_validator.py
cd backend && uv run ruff format --check \
  src/intric/flows/ai_builder/ai_builder_validation_quality.py \
  tests/unittests/flows/ai_builder/test_ai_builder_form_field_usage.py
```

```bash
cd backend && uv run lint-imports --no-cache
```

```bash
git diff --check -- \
  backend/src/intric/flows/ai_builder/ai_builder_validation_quality.py \
  docs/goals/flow-ai-builder-quality-hardening/state.yaml \
  docs/goals/flow-ai-builder-quality-hardening/notes/T011-judge-validation-quality-helper-slice.md \
  docs/goals/flow-ai-builder-quality-hardening/notes/T012-worker-validation-quality-helper.md
```
