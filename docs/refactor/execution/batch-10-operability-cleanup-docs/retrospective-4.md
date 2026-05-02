# Retrospective 4 — Result Tool-Call Metadata Cleanup

## TL;DR

1. Slice 10.4 deletes the duplicate persisted Flow result-row tool-call metadata path.
2. Attempt provenance is the single persisted owner for Flow LLM tool-call evidence.
3. Transient `StepExecutionOutput.tool_calls_metadata` remains because runtime execution still feeds provenance from LLM adapter metadata.
4. Vacuous tests for the deleted result-level field were removed instead of kept as noise.
5. Claude verification returned `GREEN_LIGHT: yes` with minimum score `9`, and focused validation passed.

## Outcome

Implemented the cleanup with:

- migration `20260502_drop_result_tool_calls`
- no `tool_calls_metadata` column on `FlowStepResults`
- no `tool_calls_metadata` field on `FlowStepResult`
- no Flow `ToolCallMetadata` alias or re-export
- no result-row write/reset slot
- no retention select/update/count for the deleted field
- no evidence bundle exclusion guard for a field that no longer exists
- no vacuous evidence/OpenAPI tests for the removed result-level field

## What Stayed Clean

| Area | Result |
|---|---|
| Canonical owner | Persisted Flow tool-call evidence lives in `FlowAttemptProvenance.llm.tool_calls`. |
| Runtime carrier | `StepExecutionOutput.tool_calls_metadata` remains a transient handoff from LLM completion metadata into provenance. |
| Persistence | `FlowRepository.save_step_result` writes only real result-row fields. |
| Rerun reset | `_RERUN_STEP_RESULT_RESET_VALUES` no longer references removed columns. |
| Retention | Debug tombstoning clears remaining persisted debug fields without preserving a dead tool-call branch. |
| Evidence export | Result records dump directly; no result-level tool-call omission rule remains. |
| Tests | Behavior tests still cover attempt provenance, runtime handoff, repository persistence, retention cleanup, rerun reset, and evidence/API contracts. |
| Compatibility | No deprecated Flow field, legacy branch, NULL placeholder, or backwards-compatibility path was kept. |

## Validation

| Command | Result |
|---|---|
| `cd backend && uv run ruff check ...` for Slice 10.4 source/tests | Passed |
| `cd backend && uv run ruff format --check ...` for Slice 10.4 source/tests | Passed |
| `cd backend && uv run pyright ...` for Slice 10.4 source/tests | Passed: `0 errors, 0 warnings, 0 informations` |
| `cd backend && uv run pytest ... -q` for the full targeted unit set | Host-only failure: one PDF artifact case missing WeasyPrint native `libgobject`; `404 passed` before failure |
| `cd backend && uv run pytest ... --deselect tests/unittests/flows/test_typed_io_executor.py::test_document_outputs_generate_downloadable_artifacts[pdf-application/pdf-.pdf] -q` after OpenAPI cleanup | Passed: `403 passed, 1 deselected, 18 warnings` |
| `cd backend && uv run pytest tests/integration/test_flow_runtime_retention_cleanup.py tests/integration/flows/test_flow_repository.py tests/integration/flows/test_flow_evidence_api_contracts.py tests/integration/flows/test_flow_run_rerun_repository.py tests/integration/flows/test_flow_step_file_mapping_contract.py -q` | Passed: `41 passed, 16 warnings` |
| `cd backend && uv run pytest tests/unit/test_flow_openapi_contract.py -q` | Passed: `36 passed, 16 warnings` |
| `cd backend && uv run lint-imports --no-cache` | Passed: `3 kept, 0 broken` |
| `cd backend && uv run alembic heads` | Passed: `20260502_drop_result_tool_calls (head)` |
| `git diff --check -- ...` for Slice 10.4 paths | Passed |
| `./scripts/gate-local/anti_slippage.sh --worktree` | Passed |
| `rg -n "tool_calls_metadata\|ToolCallMetadata" ...` across Flow result/domain/infrastructure/evidence/retention owners | Passed: no output |
| `rg -n "tool_calls_metadata\|ToolCallMetadata" scripts backend/scripts` | Passed: no output |

## Claude Loop

| Iteration | Artifact | Verdict |
|---|---|---|
| Plan review | `.codex/artifacts/claude-peer-loop-batch-10-tool-calls-result-cleanup-plan-20260502T215246Z.md` | `green`, `GREEN_LIGHT: yes` |
| Implementation verification | `.codex/artifacts/claude-peer-loop-batch-10-tool-calls-result-cleanup-implementation-verification-20260502T221058Z.md` | `green`, `GREEN_LIGHT: yes` |

Accepted cleanup:

- deleted the orphan Flow `ToolCallMetadata` alias and re-export
- kept transient runtime metadata rather than broadening the slice into the LLM adapter stack
- deleted the result-level evidence omission test
- deleted the OpenAPI absence test after the result field was fully removed

## Carry Forward

| Item | Owner | Next action |
|---|---|---|
| Alembic downgrade smoke test | Migration validation | Run `upgrade head`, `downgrade -1`, `upgrade head` against a disposable DB or project container before merge if container access becomes available. |
| Transient `StepExecutionOutput.tool_calls_metadata` naming | LLM adapter/runtime cleanup | Consider a separate Assistants/LLM-adapter cleanup if the upstream completion metadata contract is renamed to match `LlmProvenance.tool_calls`. |
| Stale historical docs mentioning result-level `tool_calls_metadata` | Batch 10 docs cleanup | Update or mark superseded in Slice 10.5 when evidence/export/runbook docs are cleaned together. |
| Batch 11 Flow AI Builder reliability | Batch 11 | Read the Batch 11 plan after Batch 10 completes and improve reliability ownership where the plan underspecifies runtime failure modes. |

## Confidence

High. The duplicate persisted evidence owner is gone, the remaining metadata path has a narrow runtime reason to exist, Claude returned green, and the validation gaps are limited to host/container environment constraints rather than source failures.
