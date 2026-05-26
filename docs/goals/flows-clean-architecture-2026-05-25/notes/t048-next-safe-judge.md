# T048 Judge: Next Safe Flow Task After Typed Task Wiring

## Decision

Choose `T049` as the next safe Worker:

```text
refactor(flows-api): use the Flow upload service provider directly
```

This is a small consolidation slice. It reuses the existing container-owned `FlowFileUploadService` provider instead of preserving duplicate manual service construction in the Flow API adapter.

Revision after Claude plan gate iteration 1:

- Claude returned `GREEN_LIGHT: no`, `MIN_SCORE: 6`.
- Valid blocker: two `test_flow_upload_router.py` tests currently rely on `flow_router_common.flow_upload_service()` rebuilding a real `FlowFileUploadService` from lower-level mocks. If T049 switches to `container.flow_file_upload_service()` without migrating those fixtures, the tests can degrade into `MagicMock` glue and stop proving real upload-service validation.
- Valid improvement: decide whether to keep the pass-through `flow_upload_service(container)` helper or inline the provider calls.
- Revised decision: delete the pass-through helper and call `container.flow_file_upload_service()` directly at the two upload-router call sites. The helper no longer earns its existence once it stops owning construction, and direct provider use makes the canonical owner clearer.

Revision after Claude plan gate iteration 2:

- Claude returned `GREEN_LIGHT: no`, `MIN_SCORE: 7`.
- Valid blocker: a third test, `test_upload_flow_runtime_file_calls_step_upload_service`, monkeypatches the helper that T049 will delete.
- Revised migration scope: three upload-router tests require fixture updates, not two.

## Source Evidence

Current duplicate wiring:

- `backend/src/intric/flows/api/flow_router_common.py:115` defines `flow_upload_service(container: Container) -> FlowFileUploadService`.
- `backend/src/intric/flows/api/flow_router_common.py:116-120` manually constructs `FlowFileUploadService`.
- `backend/src/intric/flows/api/flow_router_common.py:117`, `:119`, and `:120` erase container providers through `cast(Any, container.X())` plus `pyright: ignore[reportUnknownMemberType]`.

Existing canonical owner:

- `backend/src/intric/main/container/container.py:1256-1262` already defines `flow_file_upload_service = providers.Factory(FlowFileUploadService, ...)`.
- `backend/src/intric/flows/flow_file_upload_service.py:159-167` already owns the typed constructor boundary for `flow_service`, `file_service`, `settings_service`, and `flow_version_repo`.

Current API callers:

- `backend/src/intric/flows/api/flow_upload_router.py:197-200` calls `common.flow_upload_service(container).upload_file_for_flow(...)`.
- `backend/src/intric/flows/api/flow_upload_router.py:297-300` calls `common.flow_upload_service(container).upload_runtime_file_for_step(...)`.

Existing tests that require fixture migration:

- `backend/tests/unittests/flows/test_flow_upload_router.py:107-156` verifies runtime-file upload routing, audit logging, and response shape. It currently monkeypatches `router_common_module.flow_upload_service` at `:117-119`; after helper deletion it should set `container.flow_file_upload_service.return_value = upload_service` and keep `upload_service.upload_runtime_file_for_step.assert_awaited_once()`.
- `backend/tests/unittests/flows/test_flow_upload_router.py:187-190` wires lower-level container providers for the rejection-path test.
- `backend/tests/unittests/flows/test_flow_upload_router.py:205-212` asserts `BadRequestException` and `file_service.save_file.assert_not_awaited()`.
- `backend/tests/unittests/flows/test_flow_upload_router.py:259-262` wires lower-level container providers for the limit-override test.
- `backend/tests/unittests/flows/test_flow_upload_router.py:291-293` asserts the saved file id, `file_service.save_file.assert_awaited_once()`, and `max_size == 31_000_000`.
- T049 must preserve the assertion-heavy rejection and limit-override signal by wiring `container.flow_file_upload_service` to a real `FlowFileUploadService` instance built from the existing test doubles. Do not replace those tests with a mocked upload-service result unless equivalent real-service coverage is moved or cited in the same Worker.
- The runtime-file router test is already intentionally mock-driven at the service seam; keep it mock-driven by returning its existing `upload_service` from `container.flow_file_upload_service`.

Current baseline verification:

- `cd backend && uv run pyright src/intric/flows/api/flow_router_common.py`
  - Result: pass, `0 errors, 0 warnings, 0 informations`.
  - Note: this proves the existing file is green only with the current `cast(Any)` and pyright ignores; T049 must prove direct provider use is green without type erasure.

FastAPI/API adapter review:

- The candidate touches Flow API adapter code, not endpoint decorators, request models, response models, dependency declarations, or route signatures.
- Expected OpenAPI/generated-client impact: none.
- Router behavior should remain: parse/dependency/scope enforcement in routers, then call the application service. T049 should only change how the upload service is obtained.

## Candidate Classification

### safe_now

`T049`: delete the pass-through `flow_router_common.flow_upload_service` helper and call `Container.flow_file_upload_service` directly from the Flow upload router.

Why safe now:

- It removes duplicate service construction instead of adding a second owner.
- It deletes `cast(Any)` and pyright-ignore provider erasure in Flow API upload wiring.
- It removes a now-unneeded pass-through helper instead of preserving another Flow API adapter hop.
- It does not change endpoint signatures, request/response schemas, OpenAPI, generated clients, persistence, runtime contract, retention, service-key identity, review/rerun policy, or Flow AI Builder.
- The existing provider and typed service constructor already exist.

### follow_up

- Broader Flow API provider-erasure cleanup outside upload wiring, including remaining pyright ignores in `flow_api_common.py` and router-local casts, should be judged separately.
- `flow_router_common.flow_run_contract_service` is now a similar one-line provider pass-through at `backend/src/intric/flows/api/flow_router_common.py:124-125`; defer any consistent-pattern cleanup to a separate Judge task.
- T047's guard line-window heuristic may be tightened if generalized beyond the runtime task file.
- Webhook payload-key literals remain a separate owner-review follow-up and should not be bundled into T049.
- A future Container typing task may be worth judging if repeated dependency-injector provider typing gaps keep creating `cast(Any, container.X())` pressure.

### needs_preflight

- Draft step id-owned persistence and runtime step identity schema follow-ups.
- Schema migrations, JSONB ownership, and index/lock changes.
- Runtime output-mode/output-type movement when the active task reaches the output-format tranche.
- Frontend state ownership or generated client cleanup outside a dedicated frontend Worker.

### blocked_on_decision

- Retention behavior.
- Service-key identity model.
- Review/rerun service-key capability.
- Any schema or API change that depends on those product/data decisions.

### final_docs_only

- `T901`: `docs/flows/architecture.md` maintainer map.
- Do not start it while runtime/API/schema architecture is still actively changing. T049 must preserve owner/consolidation evidence so the final docs Worker can write from implemented reality.

## Proposed T049 Worker

Objective:

```text
refactor(flows-api): use the Flow upload service provider directly
```

Allowed files:

- `docs/goals/flows-clean-architecture-2026-05-25/state.yaml`
- `docs/goals/flows-clean-architecture-2026-05-25/notes/t049-flow-upload-service-provider.md`
- `backend/src/intric/flows/api/flow_router_common.py`
- `backend/src/intric/flows/api/flow_upload_router.py`
- `backend/tests/unittests/flows/test_flow_architecture_guards.py`
- `backend/tests/unittests/flows/test_flow_upload_router.py`

State update expectation:

- On activation, mark T048 done and T049 active.
- On T049 completion, close T049 with a compact receipt, verification commands, consolidation effect, naming gate, and next-task recommendation.

Expected implementation:

- Confirm `Container.flow_file_upload_service` is still the existing provider owner.
- Delete `flow_router_common.flow_upload_service(container)` because after consolidation it would only be a pass-through helper.
- Replace the two upload-router call sites with direct `container.flow_file_upload_service()` calls:
  - `upload_flow_file(...)`
  - `upload_flow_runtime_file(...)`
- If direct provider calls pass pyright, keep them.
- If direct provider calls do not pass pyright, stop and return to Judge; do not add `Any`, pyright ignores, generic provider helpers, fake interfaces, service locators, or a second construction path.
- Remove no API route, schema, dependency declaration, or generated-client code.
- Extend the architecture guard with a Flow API upload-provider check named `test_flow_api_upload_service_uses_container_provider_without_any_erasure`.
- The guard must scan exactly:
  - `backend/src/intric/flows/api/flow_router_common.py`
  - `backend/src/intric/flows/api/flow_upload_router.py`
- The guard must forbid:
  - `cast(Any, container.X())` on container provider calls;
  - nearby `reportUnknownMemberType` ignores on container provider calls;
  - manual `FlowFileUploadService(...)` construction in Flow API code;
  - reintroducing `def flow_upload_service(...)` as a pass-through or constructor path in `flow_router_common.py`.
- Prove the guard fails red against the unmodified current `flow_router_common.py:115-121` bad pattern before production edit. Stop if it does not.
- Migrate all three upload-router test fixtures that depend on the deleted helper:
  - `test_upload_flow_runtime_file_calls_step_upload_service`: replace the helper monkeypatch with `container.flow_file_upload_service.return_value = upload_service`; keep `upload_service.upload_runtime_file_for_step.assert_awaited_once()`.
  - `test_upload_flow_file_rejects_when_flow_input_type_not_file_upload`: use a real `FlowFileUploadService` built from the existing lower-level test doubles.
  - `test_upload_flow_file_uses_flow_limit_override`: use a real `FlowFileUploadService` built from the existing lower-level test doubles.
- For the two real-service tests:
  - use the existing lower-level test doubles;
  - wire `container.flow_file_upload_service.side_effect` or an equivalently explicit fixture to return a real `FlowFileUploadService(...)`;
  - keep the `BadRequestException` rejection assertion;
  - keep `file_service.save_file.assert_not_awaited()` in the rejection path;
  - keep the `max_size == 31_000_000` assertion in the limit-override path.

Verification commands:

```bash
cd backend && uv run pytest tests/unittests/flows/test_flow_architecture_guards.py::test_flow_api_upload_service_uses_container_provider_without_any_erasure -q
cd backend && uv run pyright src/intric/flows/api/flow_router_common.py src/intric/flows/api/flow_upload_router.py
cd backend && uv run pytest tests/unittests/flows/test_flow_architecture_guards.py::test_flow_api_upload_service_uses_container_provider_without_any_erasure tests/unittests/flows/test_flow_upload_router.py -q
cd backend && uv run pyright src/intric/flows/api/flow_router_common.py src/intric/flows/api/flow_upload_router.py tests/unittests/flows/test_flow_architecture_guards.py tests/unittests/flows/test_flow_upload_router.py
cd backend && uv run ruff check src/intric/flows/api/flow_router_common.py src/intric/flows/api/flow_upload_router.py tests/unittests/flows/test_flow_architecture_guards.py tests/unittests/flows/test_flow_upload_router.py
cd backend && uv run ruff format --check src/intric/flows/api/flow_router_common.py src/intric/flows/api/flow_upload_router.py tests/unittests/flows/test_flow_architecture_guards.py tests/unittests/flows/test_flow_upload_router.py
rg -n 'cast\(\s*Any|pyright: ignore\[reportUnknownMemberType\]|FlowFileUploadService\(|def flow_upload_service' backend/src/intric/flows/api/flow_router_common.py backend/src/intric/flows/api/flow_upload_router.py
rg -n 'common\.flow_upload_service|flow_upload_service\(' backend/src/intric/flows backend/tests/unittests/flows -g '*.py'
git diff --check
git diff --name-only
git diff --staged --name-only
```

Expected `rg` result after T049: no matches for `common.flow_upload_service` or `flow_upload_service(` in Flow source/tests.

Expected diff file hygiene:

- Before staging, `git diff --name-only` for the T049 patch must be limited to the T049 allowed files, plus existing unrelated dirty files must be left unstaged.
- Before committing, `git diff --staged --name-only` must be a strict subset of the T049 allowed files.

Stop if:

- Direct `container.flow_file_upload_service()` calls fail strict pyright.
- The new guard does not fail red against the current pre-edit bad pattern.
- The runtime-file router test stops asserting `upload_service.upload_runtime_file_for_step.assert_awaited_once()`.
- Migrated upload-router tests no longer exercise real `FlowFileUploadService` validation logic.
- The rejection-path test stops asserting `BadRequestException` and `file_service.save_file.assert_not_awaited()`.
- The limit-override test stops asserting `file_service.save_file.await_args.kwargs["max_size"] == 31_000_000`.
- The fix requires changing endpoint signatures, response models, dependencies, OpenAPI, generated clients, or Flow upload behavior.
- The fix requires changing `Container` provider definitions or `FlowFileUploadService` constructor semantics.
- The fix requires `Any`, `cast(Any)`, `dict[str, Any]`, a pyright ignore, a generic helper, manager, processor, service locator, fake interface, or one-implementation protocol.
- The task expands into retention, service-key identity/review/rerun, schema migrations, webhook outbox, output-format architecture, final architecture docs, or Flow AI Builder.
- Staged files include anything outside the T049 allowed files.

## Consolidation Effect

- Reused existing owner: `Container.flow_file_upload_service` and `FlowFileUploadService`.
- Logic moved from: manual API adapter construction in `flow_router_common.flow_upload_service` to direct provider ownership at the existing upload-router call sites.
- Logic deleted: duplicate constructor call, `cast(Any)`/pyright-ignore provider erasure, and the pass-through `flow_upload_service` helper.
- Duplicate path removed: the API adapter stops rebuilding the upload service from lower-level providers, and there is no one-line helper left as a second place to reason about upload-service ownership.
- New code added: one focused architecture guard and minimal test-fixture rewiring; no production helper or abstraction expected.
- Why existing owners were insufficient: they are sufficient; the problem is the API adapter bypassing the existing provider owner and erasing types.
- Guard/test preventing duplicate logic from returning: `test_flow_api_upload_service_uses_container_provider_without_any_erasure` plus the migrated upload-router tests that still exercise real `FlowFileUploadService` validation.
- Net Flow logic surface area: reduced.
- If increased, why the increase is necessary: not expected.

## Naming Gate

- New module/class/type/status/file names expected: none.
- New test name: `test_flow_api_upload_service_uses_container_provider_without_any_erasure`.
- The concept would appear clearly in `docs/flows/architecture.md` under API adapter wiring and architecture guard tests.
- The concept would appear clearly in the "where to change X" table as: upload validation and persistence live in `FlowFileUploadService`; upload routers should call `container.flow_file_upload_service()` and not reconstruct dependencies.

## Peer Review Plan

Run Claude plan gate before activating T049 because this touches a Flow API adapter boundary, even though it is behavior-preserving.

Use `--timeout-seconds 1200`, `--require-green`, and `--required-min-score 8`.

Claude iteration 1 artifact:

- `.codex/artifacts/claude-peer-loop-t048-next-safe-flow-task-judge-20260526T130119Z.md`
- Verdict: `GREEN_LIGHT: no`, `MIN_SCORE: 6`.
- Valid blockers addressed in this revision: explicit test-fixture migration, concrete guard red protocol, and inline-vs-keep-helper decision.

Claude iteration 2 artifact:

- `.codex/artifacts/claude-peer-loop-t048-next-safe-flow-task-judge-iteration-2-20260526T130823Z.md`
- Verdict: `GREEN_LIGHT: no`, `MIN_SCORE: 7`.
- Valid blocker addressed in this revision: the third upload-router test fixture that monkeypatches the deleted helper.

Resume the same Claude session for a green plan gate before activating T049.

Antigravity is not required for T048 unless Claude and Codex disagree after the revision. This is not a public contract, schema, data migration, runtime reliability, or disputed architecture decision; using the scarce second-opinion reviewer would be routine rather than high leverage.
