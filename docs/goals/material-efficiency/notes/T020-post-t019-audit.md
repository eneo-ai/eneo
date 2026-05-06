# T020 Post-T019 Audit

## Verdict

Not complete. T019 improved topology reliability, but the tranche still lacks automated live-eval material metrics, so live summaries cannot quantify whether later changes improve context cost without manual artifact inspection.

## Completion Criteria Checked

| Requirement | Evidence | Result |
|---|---|---|
| Explicit material routing and source preservation improve through canonical owners | T003, T011, T013, T014, T016, and T019 receipts; latest committed slice `a57ea556` | Improved |
| Avoid broad `all_previous_steps` as source-loss band-aid | T011 and T019 deterministic tests plus live inspections show targeted routes for covered cases | Improved |
| Keep direct text transforms minimal | T015 receipt and N1 live/runtime proof | Improved |
| Run deterministic tests and live eval after changes | T019 receipt includes `pytest -n 4` suite and Q1/N1/C5 live evals | Met for T019 |
| Record and compare material-efficiency metrics | Runner still emits `metrics_implementation: manual_review_required` and all metric values `None` for live results | Missing |
| Keep board and dirty state reviewable | Board had no active task after T019; dirty files remain outside committed phases | Missing |

## Evidence

- `docs/goals/material-efficiency/flow-ai-builder-material-efficiency-goal.md:58` requires binding byte size, fan-in width, structured field count, whole-output reference count, source duplication count, and `all_previous_steps` count.
- `docs/goals/material-efficiency/run_flow_ai_builder_live_eval.py:69` defines those metric fields but initializes them to `None`.
- `docs/goals/material-efficiency/run_flow_ai_builder_live_eval.py:624` marks metric implementation as deferred/manual.
- Latest post-T019 live summaries still report `metrics_implementation: manual_review_required` for applied Q1/N1/C5 results.
- The existing deterministic `_question_metrics` helper is private to `backend/tests/unittests/flows/ai_builder/test_ai_builder_step_transition_policy.py`, so live eval cannot reuse it.

## Dirty Files

Unrelated or pre-existing dirty files remain and were not touched by T020:

- `backend/src/intric/flows/ai_builder/ai_builder_framework_policy.py`
- `backend/src/intric/flows/ai_builder/ai_builder_planner_pattern_signals.py`
- `backend/tests/unittests/flows/ai_builder/test_ai_builder_framework_policy.py`
- `scripts/run_codex_review.sh`
- `PRODUCT.md`
- `docs/refactor/flow-ai-builder-material-efficiency-review-handoff.md`
- `docs/refactor/goals.md`
- `docs/refactor/new/`
- `docs/refactor/runtime-hang-and-builder-rootcause.md`
- `flow_ai_builder_prd.md`
- `flow_ai_builder_review.md`
- `utvecklingssamtal.mp3`

## Claude Review

Claude reviewed the next-slice plan in three iterations:

- `.codex/artifacts/claude-peer-loop-t020-next-slice-audit-live-eval-material-metrics-20260506T004601Z.md`: changes required; blocked runner-local parser and undefined source duplication semantics.
- `.codex/artifacts/claude-peer-loop-t020-next-slice-audit-shared-live-eval-material-metrics-20260506T005030Z.md`: changes required; requested a tighter source-surfacing rule, runner import decision, and concrete helper contract.
- `.codex/artifacts/claude-peer-loop-t020-next-slice-audit-shared-live-eval-material-metrics-final-amendment-20260506T005446Z.md`: green, `GREEN_LIGHT: yes`, `MIN_SCORE: 8`.

## Next Worker

Activate T021: promote material-efficiency metrics into a shared typed helper that reuses the canonical template parser, then wire live eval summaries to emit automated numeric metrics for planned/applied cases while preserving manual score axes.
