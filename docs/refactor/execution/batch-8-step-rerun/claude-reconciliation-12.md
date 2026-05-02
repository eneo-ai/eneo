# Claude Reconciliation 12 — API Contract And Recoverable Dispatch Implementation

## Claude Verdict

- Implementation review artifact: `.codex/artifacts/claude-peer-loop-batch-8-step-rerun-api-dispatch-implementation-20260502T130441Z.md`
- Implementation verdict: green
- Post-nit verification artifact: `.codex/artifacts/claude-peer-loop-batch-8-step-rerun-api-dispatch-implementation-verification-20260502T131101Z.md`
- Post-nit verification verdict: green content, but the peer-loop parser rejected Claude's compressed header format.
- Parser-clean verification artifact: `.codex/artifacts/claude-peer-loop-batch-8-step-rerun-api-dispatch-implementation-verification-exact-20260502T131211Z.md`
- Parser-clean verification verdict: green
- Green light: yes
- Minimum score: 9

## Accepted Changes

| Claude point | Codex action | Evidence |
|---|---|---|
| Public dispatch helpers had identical signatures but different failure policies. | Added one-line docstrings that explain the terminalizing create-run policy and the recoverable rerun policy. | `backend/src/intric/flows/application/flow_dispatch.py` |
| Rerun 400 docs omitted reason-specific service error codes. | Added `flow_run_rerun_reason_required` and `flow_run_rerun_reason_too_long` to the rerun endpoint 400 description. | `backend/src/intric/flows/api/flow_run_execution_router.py` |
| The recoverable dispatch helper should be reachable through the canonical lazy application package export if it is a first-class application helper. | Added the lazy export and startup import assertion. | `backend/src/intric/flows/application/__init__.py`, `backend/tests/unit/test_server_startup_imports.py` |
| `FlowRunPublic.revision` should not become a hidden optional response field. | Made `revision` required in `FlowRunPublic` and pinned that in OpenAPI. | `backend/src/intric/flows/api/flow_models.py`, `backend/tests/unit/test_flow_openapi_contract.py` |

## Verification

- `docker exec -w /workspace/backend eneo-41ae93-eneo-1 .venv/bin/pytest tests/unittests/flows/test_flow_router.py -k 'rerun_flow_run_step or recoverably_after_commit or dispatch_after_commit_wrappers_share_dispatch_core' -q` — passed
- `docker exec -w /workspace/backend eneo-41ae93-eneo-1 .venv/bin/pytest tests/unit/test_flow_openapi_contract.py -k 'rerun or revision' -q` — passed
- `docker exec -w /workspace/backend eneo-41ae93-eneo-1 .venv/bin/pytest tests/unit/test_server_startup_imports.py -q` — passed
- Targeted `ruff check` over the Slice 8.7 source and test files listed in `journal.md` — passed
- Targeted `pyright --pythonpath .venv/bin/python` over the same Slice 8.7 source and test files — passed
- `git diff --check` — passed
- `rg -n "FlowRunPublic\\(" backend/src backend/tests` — only the class definition matched
- diff-only forbidden compatibility/phase-language greps — no matches

## Decision

Slice 8.7 is ready to commit. The endpoint remains in the run execution router, the service and repository remain the canonical rerun command owners, replay does not schedule dispatch, and dispatch failure after accepted rerun stays recoverable.
