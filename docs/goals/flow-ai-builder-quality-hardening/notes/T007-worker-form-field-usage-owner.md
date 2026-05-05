# T007 Worker Receipt

## Result

`done`

## Objective

Make the branch loadable by committing the missing narrow form-field usage
predicate module that committed `HEAD` already imports.

## Red / Recovery Evidence

Before implementation cleanup, Codex temporarily moved
`backend/src/intric/flows/ai_builder/ai_builder_form_field_usage.py` out of the
worktree and ran:

```bash
cd backend && uv run python -c "import intric.flows.ai_builder.ai_builder_critic_invariants"
```

Result:

```text
ModuleNotFoundError: No module named 'intric.flows.ai_builder.ai_builder_form_field_usage'
import_exit=1
```

The file was restored after the probe and remained untracked before this Worker
made it commit-ready.

## Changes

- Added the missing canonical predicate module
  `ai_builder_form_field_usage.py`.
- Kept the helper narrow: the public export is only
  `find_unused_form_fields`.
- Kept template walking private as `_iter_step_templates`.
- Kept form-field reference semantics aligned with committed runtime behavior:
  bare references such as `{{ audience }}` count as used; scoped
  `{{ form_fields.audience }}` does not count yet because runtime resolution
  does not currently provide a `form_fields` context object.
- Added focused tests for no declarations, instruction references,
  `input_bindings.question`, JSON-serialized `output_config`, unreferenced
  declarations, sorted unused output, whitespace-only names, multi-step scans,
  and the unsupported scoped syntax staying unused.

## Validation

```bash
cd backend && uv run pytest tests/unittests/flows/ai_builder/test_ai_builder_form_field_usage.py -q
```

Result: `8 passed`.

```bash
cd backend && uv run python -c "import intric.flows.ai_builder.ai_builder_critic_invariants"
```

Result: passed.

```bash
cd backend && uv run pyright src/intric/flows/ai_builder/ai_builder_form_field_usage.py src/intric/flows/ai_builder/ai_builder_critic_invariants.py tests/unittests/flows/ai_builder/test_ai_builder_form_field_usage.py
```

Result: `0 errors, 0 warnings, 0 informations`.

```bash
cd backend && uv run ruff check src/intric/flows/ai_builder/ai_builder_form_field_usage.py tests/unittests/flows/ai_builder/test_ai_builder_form_field_usage.py
```

Result: passed.

```bash
cd backend && uv run ruff format --check src/intric/flows/ai_builder/ai_builder_form_field_usage.py tests/unittests/flows/ai_builder/test_ai_builder_form_field_usage.py
```

Result: passed after formatting the new test file.

```bash
cd backend && uv run lint-imports --no-cache
```

Result: all contracts kept.

```bash
git diff --check -- backend/src/intric/flows/ai_builder/ai_builder_form_field_usage.py backend/tests/unittests/flows/ai_builder/test_ai_builder_form_field_usage.py docs/goals/flow-ai-builder-quality-hardening/state.yaml docs/goals/flow-ai-builder-quality-hardening/notes/T007-worker-form-field-usage-owner.md
```

Result: passed.

## Self-Review

- Correctness and edge cases: The predicate now handles no fields, unused fields,
  bare refs, `input_bindings`, `output_config`, sorted unused output,
  whitespace-only declarations, multi-step scans, and unsupported scoped refs.
- Maintainability and readability: The module is intentionally small and keeps
  only one public function. Template walking remains private.
- Clean architecture: This is a narrow AI Builder domain helper consumed by an AI
  Builder critic; no HTTP, runtime, persistence, or frontend concerns were added.
- Type contracts: Uses concrete `FlowDraftSpecCore`, `StepSpec`, and
  `TemplateReference` types. Pyright passed on the helper, test, and importer.
- Duplication: `validation_quality.py` still has an inline duplicate predicate
  in committed `HEAD`. That is intentionally left for the next form-field
  lifecycle slice so this recovery commit stays small.
- Scope: The change is deliberately narrow. It fixes branch loadability; it does
  not attempt the larger dataflow fan-in work.
- Easy flows: No flow compilation behavior changes in this slice.
- Output quality: This phase does not directly improve generated flow quality,
  but it restores a required quality-critic dependency so later quality checks
  can run reliably.

## Merge Readiness

- Production-ready for this recovery slice: yes.
- Would merge this phase: yes.
- Could this have been cleaner or smarter: Inlining would be smaller today, but
  it would be undone by the imminent validation-quality reuse slice. Keeping the
  helper is the cleaner branch-recovery choice.
- Intentionally out of scope: create/dataflow fan-in, terminal artifact
  correctness, `validation_quality.py` reuse, prompt copy, runtime prompt prose,
  structured field path behavior, frontend/live smoke tests.
