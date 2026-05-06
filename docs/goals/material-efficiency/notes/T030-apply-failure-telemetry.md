TL;DR:
T030 adds typed, privacy-safe apply-failure telemetry for Flow AI Builder apply failures.
The change classifies failures as `compile_changeset` or `execute_changeset` and records bounded materializer progress counts.
It does not change apply behavior, materializer compensation, global 500 error-id ownership, or generated flow planning.
Local verification passed, including the full AI Builder unit suite with `-n 4`.
Latest live E1 edit eval applied 3/3 against a fresh unpublished C1 flow; earlier E1 HTTP 500s remain historical evidence for why the telemetry slice was needed.

# T030 Receipt

## Problem

E1 edit live evals reached plan approval and then intermittently failed at `POST /api/v1/flows/ai-builder/plans/{plan_id}/apply` with HTTP 500. Before this slice, `AIBuilderPlanLifecycle.apply_plan` wrapped `compile_changeset` and `execute_changeset` in one failure boundary, rolled back the session, and re-raised. That preserved state but did not classify whether the failure came from compilation or materialization.

## Canonical Owner

- Failure trigger and rollback boundary: `backend/src/intric/flows/ai_builder/ai_builder_plan_lifecycle.py`
- Structured telemetry payload shape: `backend/src/intric/flows/ai_builder/ai_builder_proposal_telemetry.py`
- Bounded materializer high-water mark: `backend/src/intric/flows/ai_builder/ai_builder_materializer.py`

## Changes

- Added apply-specific telemetry constants and typed payload models:
  - `APPLY_TELEMETRY_LOG_KEY`
  - `APPLY_TELEMETRY_SCHEMA_VERSION`
  - `ChangesetCountSummary`
  - `MaterializerProgressSnapshot`
  - `ApplyFailureTelemetryPayload`
  - `log_apply_failed`
- Split `apply_plan` failure handling into:
  - `phase="compile_changeset"` with no changeset counts or materializer progress
  - `phase="execute_changeset"` with changeset counts and last materializer progress snapshot
- Added an optional synchronous `progress_callback` to `execute_changeset`.
- Emitted progress only as stage/count booleans. Progress snapshots do not include assistant IDs, flow IDs, step IDs, prompts, bindings, specs, or source material.
- Kept global 500 `error_id` ownership unchanged.

## Red Evidence

The first focused runs failed before implementation because the new telemetry symbols and materializer `progress_callback` did not exist:

- `test_ai_builder_proposal_telemetry.py`: missing `APPLY_TELEMETRY_LOG_KEY`
- `test_ai_builder_plan_lifecycle.py`: missing `MaterializerProgressSnapshot`
- `test_ai_builder_materializer.py`: missing `MaterializerProgressSnapshot`

## Verification

| Command | Result |
|---|---|
| `uv run --directory backend pytest -n 4 tests/unittests/flows/ai_builder/test_ai_builder_plan_lifecycle.py -q -k apply` | `10 passed` |
| `uv run --directory backend pytest -n 4 tests/unittests/flows/ai_builder/test_ai_builder_proposal_telemetry.py tests/unittests/flows/ai_builder/test_ai_builder_materializer.py -q -k 'telemetry or progress_callback or execute_changeset'` | `13 passed` |
| `uv run --directory backend pytest -n 4 tests/unittests/flows/ai_builder -q` | `2030 passed, 4 skipped, 42 warnings` |
| `uv run --directory backend pyright src/intric/flows/ai_builder/ai_builder_plan_lifecycle.py src/intric/flows/ai_builder/ai_builder_materializer.py src/intric/flows/ai_builder/ai_builder_proposal_telemetry.py tests/unittests/flows/ai_builder/test_ai_builder_plan_lifecycle.py tests/unittests/flows/ai_builder/test_ai_builder_proposal_telemetry.py tests/unittests/flows/ai_builder/test_ai_builder_materializer.py` | `0 errors, 0 warnings, 0 informations` |
| `uv run --directory backend ruff check src/intric/flows/ai_builder/ai_builder_plan_lifecycle.py src/intric/flows/ai_builder/ai_builder_materializer.py src/intric/flows/ai_builder/ai_builder_proposal_telemetry.py tests/unittests/flows/ai_builder/test_ai_builder_plan_lifecycle.py tests/unittests/flows/ai_builder/test_ai_builder_proposal_telemetry.py tests/unittests/flows/ai_builder/test_ai_builder_materializer.py` | `All checks passed` |
| `uv run --directory backend ruff format --check src/intric/flows/ai_builder/ai_builder_plan_lifecycle.py src/intric/flows/ai_builder/ai_builder_materializer.py src/intric/flows/ai_builder/ai_builder_proposal_telemetry.py tests/unittests/flows/ai_builder/test_ai_builder_plan_lifecycle.py tests/unittests/flows/ai_builder/test_ai_builder_proposal_telemetry.py tests/unittests/flows/ai_builder/test_ai_builder_materializer.py` | `6 files already formatted` |

## Live Eval

| Eval | Result | Summary |
|---|---|---|
| Smoke: sessions + five flow-list spaces | Passed | `/tmp/material-efficiency-live-eval/20260506-043029-user-requested-smoke-rerun/summary.json` |
| Full create + supplemental, 3 runs, apply + publish | 20 applied, 21 clarification-required, 1 no-plan, 6 skipped edit probes | `/tmp/material-efficiency-live-eval/20260506-043103-user-requested-full-3run-apply-publish/summary.json` |
| C1 create, unpublished, apply | Applied flow `aadf96b2-7864-4569-9e4d-0d6e16643cc2` | `/tmp/material-efficiency-live-eval/20260506-053523-t030-c1-unpublished/summary.json` |
| E1 edit x3 against unpublished C1 flow | 3/3 applied | `/tmp/material-efficiency-live-eval/20260506-054021-t030-e1-apply-telemetry/summary.json` |
| V2 runtime smoke with `utvecklingssamtal.mp3` | Step 1 transcribed, run stuck at step 2 for 10 minutes, then cancelled | `/tmp/material-efficiency-live-eval/20260506-051824-user-requested-v2-runtime-run/` |

Latest E1 edit eval:

| Run | Status | Flow |
|---|---|---|
| 1 | applied | `aadf96b2-7864-4569-9e4d-0d6e16643cc2` |
| 2 | applied | `aadf96b2-7864-4569-9e4d-0d6e16643cc2` |
| 3 | applied | `aadf96b2-7864-4569-9e4d-0d6e16643cc2` |

Material-efficiency observations from the same eval pass:

- Full create suite produced no `all_previous_steps` in applied create flows.
- E1 edit introduced `all_previous_steps_count=1` in each run, which is acceptable only if the added review step truly needs broad review context; this remains a follow-up quality signal.
- C3 applied all 3 runs but underbuilt the requested multi-document comparison; it produced shallow flows with near-zero material routing metrics. This is a quality follow-up, not a T030 telemetry concern.
- The V2 runtime smoke showed a separate runtime stall: transcription completed, step 2 remained running with no prompt/provenance/output after a bounded 10-minute poll.

## Claude Review

Claude plan review first returned `changes_required` and required typed payloads, telemetry-owner reuse, a privacy test, and bounded materializer progress. The revised plan was green. Implementation review must be rerun after this updated receipt before committing.

Existing artifacts:

- `.codex/artifacts/claude-peer-loop-t029-judge-next-worker-after-e1-apply-500s-20260506T031632Z.md`
- `.codex/artifacts/claude-peer-loop-t029-judge-next-worker-revised-apply-failure-slice-20260506T032030Z.md`
- `.codex/artifacts/claude-peer-loop-t030-implementation-review-apply-failure-telemetry-20260506T034631Z.md`

## Follow-Up

- T031 should investigate the V2 runtime stall where step 1 completed transcription but step 2 remained running.
- C3 needs a separate topology/material-routing quality slice because the generated flow does not implement the requested multi-document comparison.
- If future E1 apply failures recur, join the HTTP error id with `ai_builder_apply_telemetry` rows to classify `compile_changeset` vs `execute_changeset` and materializer progress.

Confidence: high.
