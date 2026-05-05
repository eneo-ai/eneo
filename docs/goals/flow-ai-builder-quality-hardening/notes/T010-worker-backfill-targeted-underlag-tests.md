# T010 Worker Receipt — Targeted Underlag Test Backfill

## Objective

Backfill deterministic regression tests for the targeted-underlag behavior shipped in commit `78bf7994`.

This is intentionally a test-backfill slice. It does not change production behavior.

## Files Touched

- `backend/tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py`
- `backend/tests/unittests/flows/ai_builder/test_ai_builder_plan_quality_critic.py`
- `docs/goals/flow-ai-builder-quality-hardening/state.yaml`
- `docs/goals/flow-ai-builder-quality-hardening/notes/T010-worker-backfill-targeted-underlag-tests.md`

## Behavior Pinned

The new/renamed tests pin the distinction introduced by `78bf7994`:

- the soft cap counts text priors, not JSON priors
- many JSON priors with output contracts should still trigger targeted structured references
- under-bound final composers still fail when they drop many relevant JSON predecessors
- existing text-heavy flows can still defer targeted refs when the text-prior cap is exceeded

Each new/renamed targeted-underlag test carries a short `Pins 78bf7994` comment. Long tutorial docstrings and `# type: ignore` casts were removed from the changed hunks.

## Clean Worktree Validation

I created `/tmp/t010-headbaseline` at `HEAD` and ran the full two-file target with the current branch source only:

```bash
cd /tmp/t010-headbaseline/backend
PYTHONPATH=/tmp/t010-headbaseline/backend/src \
  /Users/ccimen/eneo/eneo/backend/.venv/bin/pytest -q \
  tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py \
  tests/unittests/flows/ai_builder/test_ai_builder_plan_quality_critic.py
```

Result: `13 failed, 171 passed`.

Those failures are the existing broader dirty-draft/source-dependent tests in these files, not the T010 target. Because the broad two-file target is already non-green at pure `HEAD`, the product gate for this backfill uses the six T010 tests listed below rather than claiming the full files are green.

I then copied the two selected dirty test files into `/tmp/t010-cleanoverlay` and ran only the T010 tests:

```bash
cd /tmp/t010-cleanoverlay/backend
PYTHONPATH=/tmp/t010-cleanoverlay/backend/src \
  /Users/ccimen/eneo/eneo/backend/.venv/bin/pytest -q \
  tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py::test_auto_bind_targeted_underlag_skips_when_text_priors_exceed_soft_cap \
  tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py::test_auto_bind_targeted_underlag_fires_when_many_json_priors_with_few_text_priors \
  tests/unittests/flows/ai_builder/test_ai_builder_plan_quality_critic.py::TestPreferTargetedUnderlagInvariant::test_render_critic_issues_silent_when_too_many_text_priors \
  tests/unittests/flows/ai_builder/test_ai_builder_plan_quality_critic.py::TestPreferTargetedUnderlagInvariant::test_render_critic_issues_fires_when_many_json_priors_under_text_cap \
  tests/unittests/flows/ai_builder/test_ai_builder_plan_quality_critic.py::TestFinalTextStepReferencesRelevantStructuredOutputs::test_silent_when_too_many_text_priors \
  tests/unittests/flows/ai_builder/test_ai_builder_plan_quality_critic.py::TestFinalTextStepReferencesRelevantStructuredOutputs::test_fires_when_many_json_priors_under_text_cap
```

Result: `6 passed`.

## Revert-Fail Proof

In `/tmp/t010-cleanoverlay`, I ran:

```bash
git revert 78bf7994 --no-commit
```

Then I reran the same six T010 tests. Result: `3 failed, 3 passed`.

Expected failures:

- `test_auto_bind_targeted_underlag_fires_when_many_json_priors_with_few_text_priors`
- `TestPreferTargetedUnderlagInvariant::test_render_critic_issues_fires_when_many_json_priors_under_text_cap`
- `TestFinalTextStepReferencesRelevantStructuredOutputs::test_fires_when_many_json_priors_under_text_cap`

This proves the tests pin the behavior from `78bf7994` rather than only preserving current incidental output.

## Main Worktree Validation

```bash
cd backend && uv run pytest -n 4 -q \
  tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py::test_auto_bind_targeted_underlag_skips_when_text_priors_exceed_soft_cap \
  tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py::test_auto_bind_targeted_underlag_fires_when_many_json_priors_with_few_text_priors \
  tests/unittests/flows/ai_builder/test_ai_builder_plan_quality_critic.py::TestPreferTargetedUnderlagInvariant::test_render_critic_issues_silent_when_too_many_text_priors \
  tests/unittests/flows/ai_builder/test_ai_builder_plan_quality_critic.py::TestPreferTargetedUnderlagInvariant::test_render_critic_issues_fires_when_many_json_priors_under_text_cap \
  tests/unittests/flows/ai_builder/test_ai_builder_plan_quality_critic.py::TestFinalTextStepReferencesRelevantStructuredOutputs::test_silent_when_too_many_text_priors \
  tests/unittests/flows/ai_builder/test_ai_builder_plan_quality_critic.py::TestFinalTextStepReferencesRelevantStructuredOutputs::test_fires_when_many_json_priors_under_text_cap
```

Result: `6 passed`.

```bash
cd backend && uv run pyright \
  tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py \
  tests/unittests/flows/ai_builder/test_ai_builder_plan_quality_critic.py
```

Result: `0 errors, 0 warnings, 0 informations`.

```bash
cd backend && uv run ruff check \
  tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py \
  tests/unittests/flows/ai_builder/test_ai_builder_plan_quality_critic.py
cd backend && uv run ruff format --check \
  tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py \
  tests/unittests/flows/ai_builder/test_ai_builder_plan_quality_critic.py
```

Result: ruff passed; format check passed.

```bash
cd backend && uv run lint-imports --no-cache
```

Result: all contracts kept.

```bash
git diff --check -- \
  backend/tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py \
  backend/tests/unittests/flows/ai_builder/test_ai_builder_plan_quality_critic.py \
  docs/goals/flow-ai-builder-quality-hardening/state.yaml \
  docs/goals/flow-ai-builder-quality-hardening/notes/T009-judge-next-slice.md \
  docs/goals/flow-ai-builder-quality-hardening/notes/T010-worker-backfill-targeted-underlag-tests.md
```

Result: passed.

## Claude Peer Review

The Claude peer-review command timed out three times before returning a verdict:

- session `flow-ai-builder-quality-hardening-t010`, full skeptical commit gate, 180 seconds
- session `flow-ai-builder-quality-hardening-t010-fast`, diff-only skeptical commit gate, 120 seconds
- session `flow-ai-builder-quality-hardening-t010-fast-sonnet`, diff-only skeptical commit gate with lighter model override, 90 seconds

Artifacts:

- `.codex/artifacts/claude-peer-loop-t010-targeted-underlag-test-backfill-implementation-review-20260505T084217Z.md`
- `.codex/artifacts/claude-peer-loop-t010-fast-commit-gate-20260505T084441Z.md`
- `.codex/artifacts/claude-peer-loop-t010-fast-commit-gate-20260505T084624Z.md`

`[no-peer-review]` final verdict was used only because the peer-review tool was unavailable in practice for this narrow test-only backfill. The phase makes no production source change and has direct revert-fail evidence against `78bf7994`.

## Self-Review

Correctness: the tests cover the intended `78bf7994` behavior directly and prove failure when that commit is reverted. They do not rely on live LLM output.

Maintainability: this is not a new abstraction. The change removes two `# type: ignore` uses from touched hunks and makes the cap distinction explicit in test names.

Architecture: no production owner changed. The tests exercise the existing backend-owned dataflow/critic mechanics rather than moving responsibility into prompt prose.

Type contracts: pyright passes on the touched tests. The casts are explicit local test casts from string literals into existing domain literal types.

Duplication: the tests share existing factories and patterns in the target files. No new test helper or fixture was added.

Scope: this phase is deliberately narrow. It does not fix the broader dirty-draft source-dependent tests that still fail at pure `HEAD`.

Easy flows: unchanged. This test-backfill only pins JSON-heavy fan-in behavior and text-prior cap behavior.

Output quality impact: indirect but real. The tests protect the behavior that lets JSON-heavy multi-section flows avoid falling back to broad body fan-in or dropping structured priors.

## Merge Readiness

Production ready: yes for this test-backfill slice.

Would merge: yes, as a narrow regression-test commit.

Could it be cleaner: the broader files still contain failing source-dependent draft tests at pure `HEAD`. The cleaner next move is a source slice, not more test-only backfill.

Out of scope:

- fixing form-field hint filtering
- fixing audio artifact body-step fan-in source behavior
- committing broader dirty AI Builder source/test drafts
- live API smoke testing

## Next Required Slice

The next task should be a source implementation slice selected by Judge. Another tests-only slice should require new evidence that source implementation is unsafe.
