# T009 Judge Decision

## Decision

Activate a test-backfill Worker for behavior shipped in:

```text
78bf7994 ai_builder: scale targeted-underlag soft cap to text priors only
```

This is not generic regression pinning. The shipped commit message referenced
coverage for JSON-prior fan-in and text-prior soft-cap behavior, but the tests
were not committed with that change. The next slice backfills that coverage
before source work resumes.

## Worker Scope

Allowed files:

- `backend/tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py`
- `backend/tests/unittests/flows/ai_builder/test_ai_builder_plan_quality_critic.py`
- `docs/goals/flow-ai-builder-quality-hardening/state.yaml`
- `docs/goals/flow-ai-builder-quality-hardening/notes/T010-worker-backfill-targeted-underlag-tests.md`

Forbidden:

- source files;
- unrelated dirty files;
- broad docs;
- devcontainer files;
- scripts/product/local files.

## Required Gates

- Clean temp worktree with only the two selected dirty test files copied in must
  pass targeted pytest.
- Revert-check temp worktree with only the two selected dirty test files copied
  in must fail at least one new/renamed targeted-underlag test after
  `git revert 78bf7994 --no-commit`.
- New/renamed tests must avoid long tutorial docstrings and `# type: ignore`.
- Staging must contain only the allowed files.
- After this test backfill, the next slice must be a source slice unless a new
  Judge decision proves otherwise.

## Claude Result

Claude session `flow-ai-builder-quality-hardening-t009`:

- iteration 1: `changes_required`
- iteration 2: `GREEN_LIGHT: yes`, `MIN_SCORE: 7`

Artifacts are under `.codex/artifacts/claude-peer-loop-t009-*`.
