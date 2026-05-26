# T051 Worker: Run-Contract Service Provider

## Objective

Use the existing `Container.flow_run_contract_service` provider directly from the Flow run-contract endpoint and delete the one-line API pass-through helper.

## Source Precheck

- `backend/src/intric/main/container/container.py:1263-1269` is still the canonical `FlowRunContractService` provider owner.
- `backend/src/intric/flows/api/flow_router_common.py:113-114` was a one-line pass-through helper returning `container.flow_run_contract_service()`.
- `backend/src/intric/flows/api/flow_upload_router.py:117-119` was the only production caller.
- `backend/tests/unittests/flows/test_flow_upload_router.py:64-68` was the only test monkeypatching the helper.
- The four T051 source/test files were clean before implementation; unrelated dirty files existed outside the slice and were left untouched.

## Implementation

Changed:

- Generalized the T049 Flow API provider guard into `test_flow_api_provider_passthrough_helpers_are_not_reintroduced`.
- Renamed `FLOW_API_UPLOAD_PROVIDER_FILES` to `FLOW_API_PROVIDER_PASSTHROUGH_FILES`.
- Added module-level forbidden helper and manual-construction name sets for:
  - `flow_upload_service`
  - `flow_run_contract_service`
  - `FlowFileUploadService`
  - `FlowRunContractService`
- The generalized guard detects both `def` and `async def` pass-through helpers.
- Deleted `flow_router_common.flow_run_contract_service(container)`.
- Removed the now-unused `FlowRunContractService` import from `flow_router_common.py`.
- Replaced `common.flow_run_contract_service(container)` with `container.flow_run_contract_service()` in `get_flow_run_contract`.
- Migrated `test_get_flow_run_contract_enforces_scope_and_returns_contract` to set `container.flow_run_contract_service.return_value = run_contract_service` while preserving `run_contract_service.get_run_contract.assert_awaited_once_with(flow_id=flow_id)`.

Not changed:

- No endpoint path, method, signature, dependency declaration, response model, OpenAPI schema, generated client, persistence, runtime contract, retention, service-key identity/review/rerun, webhook outbox, output-format architecture, final architecture doc, or Flow AI Builder behavior.
- No `Container` provider definition or `FlowRunContractService` constructor change.
- No new production helper, adapter, protocol, manager, processor, service locator, or one-implementation interface.
- Did not stash, reset, clean, stage, or otherwise alter unrelated dirty/untracked files.

## Red Guard Evidence

Guard generalized before production edits:

```bash
cd backend && uv run pytest tests/unittests/flows/test_flow_architecture_guards.py::test_flow_api_provider_passthrough_helpers_are_not_reintroduced -q
```

Expected red result before source edit:

```text
1 failed
offender:
src/intric/flows/api/flow_router_common.py:helper:flow_run_contract_service:113
```

This proved the generalized guard caught the current pass-through helper before the production edit.

## Verification

```bash
git status --short
```

Result: pass. Reported only pre-existing unrelated dirty/untracked files before T051 source edits.

```bash
git diff --name-only -- backend/src/intric/flows/api/flow_router_common.py backend/src/intric/flows/api/flow_upload_router.py backend/tests/unittests/flows/test_flow_architecture_guards.py backend/tests/unittests/flows/test_flow_upload_router.py
```

Result: pass, no output before T051 source edits.

```bash
cd backend && uv run pytest tests/unittests/flows/test_flow_architecture_guards.py::test_flow_api_provider_passthrough_helpers_are_not_reintroduced -q
```

Result: fail red before production edit, then pass after production edit, `1 passed in 0.03s`.

```bash
cd backend && uv run pyright src/intric/flows/api/flow_router_common.py src/intric/flows/api/flow_upload_router.py
```

Result: pass, `0 errors, 0 warnings, 0 informations`.

```bash
cd backend && uv run pytest tests/unittests/flows/test_flow_architecture_guards.py tests/unittests/flows/test_flow_upload_router.py -q
```

Result: pass, `17 passed, 9 warnings in 7.35s`.

After the async-helper guard tightening, rerun result: pass, `17 passed, 9 warnings in 4.91s`.

```bash
cd backend && uv run pyright src/intric/flows/api/flow_router_common.py src/intric/flows/api/flow_upload_router.py tests/unittests/flows/test_flow_architecture_guards.py tests/unittests/flows/test_flow_upload_router.py
```

Result: pass, `0 errors, 0 warnings, 0 informations`.

```bash
cd backend && uv run ruff check src/intric/flows/api/flow_router_common.py src/intric/flows/api/flow_upload_router.py tests/unittests/flows/test_flow_architecture_guards.py tests/unittests/flows/test_flow_upload_router.py
```

Result: pass, `All checks passed!`.

```bash
cd backend && uv run ruff format --check src/intric/flows/api/flow_router_common.py src/intric/flows/api/flow_upload_router.py tests/unittests/flows/test_flow_architecture_guards.py tests/unittests/flows/test_flow_upload_router.py
```

Result: pass, `4 files already formatted`.

```bash
rg -n 'def flow_run_contract_service|common\.flow_run_contract_service|FlowRunContractService\(' backend/src/intric/flows/api/flow_router_common.py backend/src/intric/flows/api/flow_upload_router.py backend/tests/unittests/flows/test_flow_upload_router.py
```

Result: pass, no matches.

```bash
git grep -nE 'def flow_run_contract_service|common\.flow_run_contract_service|FlowRunContractService\(' -- backend/src
```

Result: pass, no production matches.

```bash
rg -n 'FLOW_API_UPLOAD_PROVIDER_FILES' backend/tests/unittests/flows/test_flow_architecture_guards.py
```

Result: pass, no matches.

```bash
git diff --check
```

Result: pass.

```bash
git diff --staged --name-only
```

Result: pass, no staged files during implementation verification.

## Peer Review

Claude commit gate:

- Artifact: `.codex/artifacts/claude-peer-loop-t051-run-contract-service-provider-implementation-review-20260526T135150Z.md`
- Verdict: `GREEN_LIGHT: yes`, `MIN_SCORE: 8`.
- Valid concern addressed after the gate: widened the helper scanner to catch `ast.AsyncFunctionDef` as well as `ast.FunctionDef`, then reran pytest, pyright, ruff, format-check, greps, and diff checks.

## Consolidation Effect

- Reused existing owner: `Container.flow_run_contract_service` and `FlowRunContractService`.
- Logic moved from: `flow_router_common.flow_run_contract_service` pass-through to direct provider use in `get_flow_run_contract`.
- Logic deleted: the pass-through helper and the `FlowRunContractService` import from `flow_router_common.py`.
- Duplicate path removed: Flow API run-contract wiring no longer has a second helper surface.
- New code added: generalized one existing architecture guard and migrated one test fixture.
- Why existing owners were insufficient: existing owners were sufficient; the API helper only forwarded to them.
- Guard/test preventing duplicate logic from returning: `test_flow_api_provider_passthrough_helpers_are_not_reintroduced` and the migrated run-contract router test.
- Net Flow logic surface area: reduced.
- If increased, why the increase is necessary: not applicable.

## Naming Gate

- New production names: none.
- Renamed test: `test_flow_api_provider_passthrough_helpers_are_not_reintroduced`.
- Renamed constant: `FLOW_API_PROVIDER_PASSTHROUGH_FILES`.
- The names identify the axis: Flow API provider ownership and forbidden pass-through helpers.
- This belongs in the future `docs/flows/architecture.md` guard-test map and "where to change X" table as: run-contract behavior lives in `FlowRunContractService`; the run-contract endpoint calls `container.flow_run_contract_service()`.

## Follow-Ups Left Out Of Scope

- Broader Flow API provider-erasure cleanup, including `flow_api_common.py` and `flow_run_steps_router.py`.
- A future Container typed-accessor task may remove dependency-injector provider erasure pressure at the source.
- Final `docs/flows/architecture.md` remains queued as T901 and must not be written during active refactors.
