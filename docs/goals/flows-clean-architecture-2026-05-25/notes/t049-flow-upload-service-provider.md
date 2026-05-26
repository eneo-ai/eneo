# T049 Worker: Flow Upload Service Provider

## Objective

Use the existing `Container.flow_file_upload_service` provider directly from Flow upload endpoints and delete the duplicate API-adapter construction path.

## Source Precheck

- `backend/src/intric/main/container/container.py:1256-1262` is still the canonical `FlowFileUploadService` provider owner.
- `backend/src/intric/flows/flow_file_upload_service.py:159-167` still owns the typed constructor boundary.
- `backend/src/intric/flows/api/flow_router_common.py:115-121` was the duplicate path: `flow_upload_service(container)` manually constructed `FlowFileUploadService` and used three `cast(Any, container.X())` calls plus `reportUnknownMemberType` ignores.
- `backend/src/intric/flows/api/flow_upload_router.py:197-200` and `:297-300` were the only production call sites.

## Implementation

Changed:

- Deleted `flow_router_common.flow_upload_service(container)`.
- Removed now-unused `Any`, `cast`, and `FlowFileUploadService` imports from `flow_router_common.py`.
- Replaced both upload-router call sites with direct `container.flow_file_upload_service()` calls.
- Added `test_flow_api_upload_service_uses_container_provider_without_any_erasure`.
- Reused the new provider-erasure scanner for the existing Celery task wiring guard.
- Refreshed the architecture-guard module docstring so it no longer says the file only covers runtime output-axis dispatch.
- Migrated all three affected upload-router tests:
  - `test_upload_flow_runtime_file_calls_step_upload_service` now returns its existing mock upload service from `container.flow_file_upload_service`.
  - `test_upload_flow_file_rejects_when_flow_input_type_not_file_upload` still runs a real `FlowFileUploadService` from the existing lower-level test doubles and still asserts `BadRequestException` plus `file_service.save_file.assert_not_awaited()`.
  - `test_upload_flow_file_uses_flow_limit_override` still runs a real `FlowFileUploadService` from the existing lower-level test doubles and still asserts `max_size == 31_000_000`.

Not changed:

- No endpoint path, method, signature, dependency declaration, response model, OpenAPI schema, generated client, persistence, runtime contract, retention, service-key identity/review/rerun, webhook outbox, output-format architecture, final architecture doc, or Flow AI Builder behavior.
- No `Container` provider definition or `FlowFileUploadService` constructor change.
- No new production helper, adapter, protocol, manager, processor, service locator, or one-implementation interface.

## Red Guard Evidence

Guard added before production edits:

```bash
cd backend && uv run pytest tests/unittests/flows/test_flow_architecture_guards.py::test_flow_api_upload_service_uses_container_provider_without_any_erasure -q
```

Expected red result before source edit:

```text
1 failed
offenders:
src/intric/flows/api/flow_router_common.py:cast(Any):117
src/intric/flows/api/flow_router_common.py:cast(Any):119
src/intric/flows/api/flow_router_common.py:cast(Any):120
src/intric/flows/api/flow_router_common.py:pyright-ignore:117
src/intric/flows/api/flow_router_common.py:pyright-ignore:119
src/intric/flows/api/flow_router_common.py:pyright-ignore:120
src/intric/flows/api/flow_router_common.py:helper:115
src/intric/flows/api/flow_router_common.py:manual-construction:116
```

This proved the guard caught the current bad pattern before the production edit.

## Verification

```bash
cd backend && uv run pytest tests/unittests/flows/test_flow_architecture_guards.py::test_flow_api_upload_service_uses_container_provider_without_any_erasure -q
```

Result: pass, `1 passed in 0.02s`.

```bash
cd backend && uv run pytest tests/unittests/flows/test_flow_architecture_guards.py -q
```

Result: pass, `13 passed in 1.22s`.

```bash
cd backend && uv run pyright src/intric/flows/api/flow_router_common.py src/intric/flows/api/flow_upload_router.py
```

Result: pass, `0 errors, 0 warnings, 0 informations`.

```bash
cd backend && uv run pytest tests/unittests/flows/test_flow_architecture_guards.py::test_flow_api_upload_service_uses_container_provider_without_any_erasure tests/unittests/flows/test_flow_upload_router.py -q
```

Result: pass, `5 passed, 9 warnings in 3.49s`.

```bash
cd backend && uv run pytest tests/unittests/flows/test_flow_upload_router.py -q
```

Result: pass, `4 passed, 9 warnings in 3.45s`.

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
rg -n 'cast\(\s*Any|pyright: ignore\[reportUnknownMemberType\]|FlowFileUploadService\(|def flow_upload_service' backend/src/intric/flows/api/flow_router_common.py backend/src/intric/flows/api/flow_upload_router.py
```

Result: pass, no matches.

```bash
rg -n 'common\.flow_upload_service|flow_upload_service\(' backend/src/intric/flows backend/tests/unittests/flows -g '*.py'
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

`git diff --name-only` still includes pre-existing unrelated dirty files plus the four T049 source/test files. Those unrelated files were not touched or staged by T049.

## Peer Review

Claude commit gate:

- Artifact: `.codex/artifacts/claude-peer-loop-t049-flow-upload-service-provider-implementation-review-20260526T132112Z.md`
- Verdict: `GREEN_LIGHT: yes`, `MIN_SCORE: 8`.
- Valid concern addressed after the gate: ran the full `test_flow_architecture_guards.py` file because the existing Celery provider-wiring guard now delegates to the extracted helper.
- Non-blocking follow-ups recorded below: broader Flow API provider-erasure cleanup, the remaining one-line `flow_run_contract_service` helper, and possible future Container typed-accessor work.

## Consolidation Effect

- Reused existing owner: `Container.flow_file_upload_service` and `FlowFileUploadService`.
- Logic moved from: duplicate API-adapter construction in `flow_router_common.flow_upload_service` to direct provider use in the existing upload-router endpoints.
- Logic deleted: the `flow_upload_service` helper, three `cast(Any, container.X())` calls, and three provider-call pyright ignores.
- Duplicate path removed: Flow API upload wiring no longer reconstructs `FlowFileUploadService` from lower-level providers.
- New code added: one focused architecture guard and test fixture rewiring only.
- Why existing owners were insufficient: existing owners were sufficient; the adapter bypassed them and erased their type contract.
- Guard/test preventing duplicate logic from returning: `test_flow_api_upload_service_uses_container_provider_without_any_erasure`, the zero-reference grep, and the migrated upload-router tests.
- Net Flow logic surface area: reduced.
- If increased, why the increase is necessary: not applicable.

## Naming Gate

- New production names: none.
- New test name: `test_flow_api_upload_service_uses_container_provider_without_any_erasure`.
- The name identifies the axis: Flow API upload-service provider ownership and typed container-provider wiring.
- This belongs in the future `docs/flows/architecture.md` guard-test map and "where to change X" table as: upload validation/persistence lives in `FlowFileUploadService`; upload routers call `container.flow_file_upload_service()`.

## Follow-Ups Left Out Of Scope

- Broader Flow API provider-erasure cleanup, including `flow_api_common.py` and `flow_run_steps_router.py`.
- `flow_router_common.flow_run_contract_service` remains a one-line provider pass-through; judge separately if consistent API helper cleanup is desired.
- A future Container typing task may remove dependency-injector provider erasure pressure at the source.
- Final `docs/flows/architecture.md` remains queued as T901 and must not be written during active refactors.
