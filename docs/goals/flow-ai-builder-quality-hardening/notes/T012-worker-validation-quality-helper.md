# T012 Worker Receipt — Validation Quality Helper Caller

## Objective

Make `lint_unused_form_fields()` use the canonical `find_unused_form_fields()` helper.

## Source Change

`backend/src/intric/flows/ai_builder/ai_builder_validation_quality.py` now delegates unused-form-field detection to `find_unused_form_fields()`.

Deleted from `ai_builder_validation_quality.py`:

- local JSON serialization for template scanning
- local `_iter_step_templates()`
- direct `referenced_form_fields()` usage
- local declared/used form field set arithmetic

Canonical owner:

- `backend/src/intric/flows/ai_builder/ai_builder_form_field_usage.py`

## Scope

No planner prompt behavior, create outline behavior, runtime output rendering, repair behavior, or structured field path behavior changed in this slice.

## Validation

```bash
cd backend && uv run pytest -n 4 -q \
  tests/unittests/flows/ai_builder/test_ai_builder_form_field_usage.py \
  tests/unittests/flows/ai_builder/test_ai_builder_validator.py
```

Result: `74 passed`.

```bash
cd backend && uv run pyright \
  src/intric/flows/ai_builder/ai_builder_validation_quality.py \
  src/intric/flows/ai_builder/ai_builder_form_field_usage.py \
  tests/unittests/flows/ai_builder/test_ai_builder_form_field_usage.py \
  tests/unittests/flows/ai_builder/test_ai_builder_validator.py
```

Result: `0 errors, 0 warnings, 0 informations`.

```bash
cd backend && uv run ruff check \
  src/intric/flows/ai_builder/ai_builder_validation_quality.py \
  tests/unittests/flows/ai_builder/test_ai_builder_form_field_usage.py \
  tests/unittests/flows/ai_builder/test_ai_builder_validator.py
```

Result: passed.

```bash
cd backend && uv run ruff format --check \
  src/intric/flows/ai_builder/ai_builder_validation_quality.py \
  tests/unittests/flows/ai_builder/test_ai_builder_form_field_usage.py
```

Result: passed after formatting the allowed touched source file. `test_ai_builder_validator.py` is not included in format check because it is an existing untouched baseline file and ruff reported it would reformat.

```bash
cd backend && uv run lint-imports --no-cache
```

Result: all contracts kept.

```bash
git diff --check -- \
  backend/src/intric/flows/ai_builder/ai_builder_validation_quality.py \
  docs/goals/flow-ai-builder-quality-hardening/state.yaml \
  docs/goals/flow-ai-builder-quality-hardening/notes/T011-judge-validation-quality-helper-slice.md \
  docs/goals/flow-ai-builder-quality-hardening/notes/T012-worker-validation-quality-helper.md
```

Result: passed.

## Peer Review

`[no-peer-review]` was used for this Worker because Claude peer review was unavailable in practice during the immediately preceding T010/T011 gates after repeated timeouts. This slice is a small caller migration to an already committed, tested helper and does not change production behavior beyond deleting duplicate local implementation.

## Self-Review

Correctness: this delegates to the helper committed in `48edf292`; the selected tests cover the helper and validator behavior.

Maintainability: duplicate template-scanning logic is deleted from `ai_builder_validation_quality.py`, leaving one canonical owner for form-field usage scanning.

Architecture: no planner, prompt, runtime, or repair boundary changes were made.

Type contracts: pyright passes on the touched source and relevant tests.

Scope: intentionally narrow. Broader planner-context dirty files remain held.

Production ready: yes for this caller migration.

Would merge: yes, as a small source cleanup.

Could be cleaner: the broader branch still needs a decision on the held planner-context changes, but this specific caller migration is the cleaner direction.
