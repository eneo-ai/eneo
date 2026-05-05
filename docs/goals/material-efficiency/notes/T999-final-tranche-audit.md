# T999 Final Tranche Audit

## Verdict

Not complete. The deterministic source-material slice is production-ready and committed, but the full tranche cannot be marked complete because live eval could not reach plan IDs and the form-field lifecycle slice needs concrete eval/product evidence before production changes.

## Completed

- Source-material loss was reproduced for text-terminal report composers crossing JSON boundaries.
- The fix was implemented in the canonical source-material owner.
- Normalizer, linter, create compiler, and deterministic scoring now share the same source-material boundary semantics.
- Material-efficiency assertions now cover binding byte size, fan-in width, whole-output refs, source duplication, structured-field refs, and `all_previous_steps` count for a longer section chain.
- Live API smoke verified that sessions and flow-list endpoints are reachable for all five eval spaces.

## Commits

- `381547f2 Improve flow builder source material routing`
- `8399208a Add flow builder material efficiency assertions`
- `dee9c734 Record flow builder form field follow-up evidence`
- `b12b7a0c Record flow builder live eval blocker`

## Verification

Source-material implementation:

- `uv run --directory backend pytest tests/unittests/flows/ai_builder/test_ai_builder_step_transition_policy.py tests/unittests/flows/ai_builder/test_ai_builder_validator.py tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py tests/integration/flows/ai_builder/benchmark/test_manual_api_scoring.py -q`
  - `210 passed, 16 warnings`
- `uv run --directory backend ruff check ...`
  - passed
- `uv run --directory backend ruff format --check ...`
  - passed
- `uv run --directory backend pyright ...`
  - `0 errors, 0 warnings, 0 informations`

Metrics follow-up:

- `uv run --directory backend pytest tests/unittests/flows/ai_builder/test_ai_builder_step_transition_policy.py -q -k material_metrics`
  - `1 passed, 26 deselected`
- ruff, format check, and pyright passed for the changed test file.

Live eval:

- `python3 docs/goals/material-efficiency/run_flow_ai_builder_live_eval.py --smoke`
  - passed API reachability checks
- `python3 docs/goals/material-efficiency/run_flow_ai_builder_live_eval.py --all --runs 3 --apply`
  - blocked: 30/30 runs returned `no_plan`

## Claude Review

Claude commit-gate review was run for the production slice.

- Iteration 1: `GREEN_LIGHT: no`; requested staging discipline, boundary-scope documentation, dead-field cleanup, and source-preference documentation.
- Iteration 2: `GREEN_LIGHT: yes`; production slice cleared for commit.

Artifacts:

- `.codex/artifacts/claude-peer-loop-claude-peer-loop-20260505T184230Z.md`
- `.codex/artifacts/claude-peer-loop-claude-peer-loop-20260505T184644Z.md`

[no-peer-review] This final audit adds no new technical proposal beyond reporting blockers already covered by the Claude-reviewed implementation and committed receipts.

## Merge Readiness

Partially merge-ready.

The committed deterministic source-material implementation is merge-ready. The broader material-efficiency goal is not complete because the live eval harness/API sequence could not produce plans and therefore could not score generated flow quality.

## Remaining Work

- Fix or adapt the live eval runner so it can answer structured clarification questions and continue after `architecture_committed` when required.
- Re-run V1-V5 and C1-C5 and manually score actual plans/flows.
- Promote any live eval form-field lifecycle failures into deterministic tests before changing production form-field routing.
- Consolidate `source_material.question_binding` with `validation_quality._question_binding`.
- Add broader cost assertions if longer generated section chains show repeated transcript bloat.

## Dirty Worktree

Unrelated dirty files remain outside the committed phases:

- `M scripts/run_codex_review.sh`
- `?? PRODUCT.md`
- `?? docs/refactor/flow-ai-builder-material-efficiency-review-handoff.md`
- `?? docs/refactor/goals.md`
- `?? docs/refactor/new/`
- `?? docs/refactor/runtime-hang-and-builder-rootcause.md`
- `?? flow_ai_builder_prd.md`
- `?? flow_ai_builder_review.md`
- `?? utvecklingssamtal.mp3`

These were not staged or committed.
