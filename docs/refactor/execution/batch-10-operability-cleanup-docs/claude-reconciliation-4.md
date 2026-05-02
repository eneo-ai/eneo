# Claude Reconciliation 4 — Result Tool-Call Metadata Cleanup

## TL;DR

1. Claude green-lit the Slice 10.4 plan before implementation with minimum score `8`.
2. The implemented cleanup deletes the duplicate persisted Flow result-row `tool_calls_metadata` path.
3. Attempt provenance is now the only persisted Flow tool-call evidence owner.
4. `StepExecutionOutput.tool_calls_metadata` remains only as transient runtime metadata before provenance capture.
5. Claude implementation verification returned `GREEN_LIGHT: yes` with minimum score `9`.

## Claude Artifacts

| Pass | Artifact | Verdict |
|---|---|---|
| Plan review | `.codex/artifacts/claude-peer-loop-batch-10-tool-calls-result-cleanup-plan-20260502T215246Z.md` | `green`, `GREEN_LIGHT: yes`, minimum score `8` |
| Implementation verification | `.codex/artifacts/claude-peer-loop-batch-10-tool-calls-result-cleanup-implementation-verification-20260502T221058Z.md` | `green`, `GREEN_LIGHT: yes`, minimum score `9` |

## Accepted Findings

| Finding | Decision | Source impact |
|---|---|---|
| The result-row `tool_calls_metadata` field was a duplicate evidence owner after attempt provenance became canonical. | Delete the persisted column, ORM field, domain field, write path, reset path, retention logic, and export guard. | `flow_tables.py`, `domain/flow.py`, `flow_repo.py`, `flow_run_repo.py`, `data_retention_service.py`, `flow_run_evidence_bundle.py`. |
| The Flow `ToolCallMetadata` alias became an orphan after the result field was removed. | Delete the alias and the `intric.flows.flow` re-export. | `domain/flow.py`, `flows/flow.py`. |
| Runtime execution still needs to move LLM adapter metadata into provenance. | Keep `StepExecutionOutput.tool_calls_metadata` as transient runtime state. | `runtime/models.py`, `step_execution_runtime.py`, `executor.py`. |
| The evidence omission test became vacuous once the field no longer existed. | Delete the test that asserted old result-level omission. | `test_flow_run_evidence.py`. |
| The OpenAPI absence test became structurally vacuous after the source field was deleted. | Delete it after Claude's implementation verification. | `test_flow_openapi_contract.py`. |

## Rejected Or Deferred

| Suggestion | Decision | Reason |
|---|---|---|
| Rename transient `StepExecutionOutput.tool_calls_metadata` to `tool_calls` in this slice. | Deferred. | That cleanup touches the upstream LLM adapter and Assistants stack; this slice is scoped to Flow result-row persistence. |
| Freeze `_RERUN_STEP_RESULT_RESET_VALUES` now. | Deferred. | The mutable dict is pre-existing and not part of the duplicate evidence owner cleanup. |
| Preserve a deprecated result field for generated-client compatibility. | Rejected. | Flow and Flow AI Builder are unreleased; preserving compatibility for a never-shipped field would create dead code. |

## Verification Questions

| Question | Answer |
|---|---|
| Does any Flow result/domain/infrastructure/evidence/retention owner still reference `tool_calls_metadata`? | No. The ownership grep across those paths returned no output. |
| Are remaining `tool_calls_metadata` references valid? | Yes. They are in the transient Flow runtime `StepExecutionOutput` path or the non-Flow completion/assistant metadata stack. |
| Did integration validation exercise migration-to-head? | Yes. The targeted integration tests use the repository's testcontainers setup, which runs Alembic migrations to head before the database fixtures are used. |
| Did we run an Alembic downgrade cycle? | No. `alembic heads` passed and integration migration-to-head passed, but a downgrade cycle needs a disposable migration database or container command access. |
| Are developer scripts still passing the removed field? | No. `rg -n "tool_calls_metadata\|ToolCallMetadata" scripts backend/scripts` returned no output. |
| Was the host PDF test failure related to this slice? | No. The full unit run failed only because WeasyPrint could not load native `libgobject` on the host; the same suite passed with that single environment-dependent case deselected. |

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

## Confidence

High. The implementation removes the duplicate persisted evidence owner, keeps the necessary transient runtime carrier, deletes vacuous tests, and leaves no deprecated or compatibility Flow path behind.
