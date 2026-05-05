# T006 Judge Decision

## Decision

Activate a recovery Worker before continuing create/dataflow fan-in work.

The next slice is:

```text
Make the current branch loadable by committing the missing narrow form-field
usage predicate module that HEAD already imports, with focused deterministic
tests and cleanup of the module public surface/readability.
```

## Why This Comes Before Dataflow Work

Claude plan review found and Codex verified that committed `HEAD` imports
`intric.flows.ai_builder.ai_builder_form_field_usage` from
`ai_builder_critic_invariants.py`, but the module file is not tracked in
`HEAD`. With the worktree file temporarily removed, importing
`intric.flows.ai_builder.ai_builder_critic_invariants` fails with
`ModuleNotFoundError`.

Committing further dataflow work on top of an unloadable branch would compound
the defect. The missing module is a branch-integrity recovery slice.

## Accepted Claude Findings

- Do not stage the broader dirty dataflow draft as one unit.
- Commit the missing helper instead of reverting/inlining because the next
  form-field lifecycle slice is the planned second consumer.
- Keep the helper narrow: public export is only `find_unused_form_fields`.
- Rename `iter_step_templates` to `_iter_step_templates`.
- Trim docstrings so they do not claim uncommitted callers already exist.
- Use a focused new test file plus import smoke; do not validate through the
  broader dirty `test_ai_builder_plan_quality_critic.py`.
- Include `ai_builder_critic_invariants.py` in pyright so the consumer is
  typechecked.

## Worker Scope

Allowed files:

- `backend/src/intric/flows/ai_builder/ai_builder_form_field_usage.py`
- `backend/tests/unittests/flows/ai_builder/test_ai_builder_form_field_usage.py`
- `docs/goals/flow-ai-builder-quality-hardening/state.yaml`
- `docs/goals/flow-ai-builder-quality-hardening/notes/T007-worker-form-field-usage-owner.md`

Forbidden for this Worker:

- `backend/src/intric/flows/ai_builder/ai_builder_create_outline.py`
- `backend/src/intric/flows/ai_builder/ai_builder_prompts.py`
- `backend/src/intric/flows/ai_builder/ai_builder_create_feedback.py`
- `backend/src/intric/flows/ai_builder/ai_builder_validation_quality.py`
- `backend/src/intric/flows/ai_builder/ai_builder_structured_field_paths.py`
- `backend/src/intric/flows/runtime/step_execution_runtime.py`
- devcontainer files, scripts, product docs, broad refactor docs, local MP3s,
  API keys, eval output, caches, screenshots, or temporary files.

## Required Evidence

Before implementation cleanup, record:

- the import failure when the helper file is absent;
- that the helper file is restored after the probe;
- focused test coverage for `find_unused_form_fields`;
- import smoke success after the fix;
- pyright/ruff/format/diff-check success.

## Claude Result

Claude session `flow-ai-builder-quality-hardening-t006`:

- iteration 1: `changes_required`
- iteration 2: `changes_required`
- iteration 3: `GREEN_LIGHT: yes`, `MIN_SCORE: 7`

Artifacts are under `.codex/artifacts/claude-peer-loop-t006-*`.
