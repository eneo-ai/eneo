# T050 Judge: Next Safe Task After Upload-Service Provider Consolidation

## Decision

Choose `T051` as the next safe Worker:

```text
refactor(flows-api): use the run-contract service provider directly
```

This is the symmetric cleanup left by T049. It deletes a one-line Flow API pass-through helper and reuses the existing `Container.flow_run_contract_service` provider directly from the run-contract endpoint.

Revision after Claude plan gate iteration 1:

- Claude returned `GREEN_LIGHT: no`, `MIN_SCORE: 7`.
- Valid blocker: adding a second narrow guard would duplicate the T049 guard scanner. T051 must generalize the existing Flow API provider guard instead.
- Valid blocker: the red protocol must specify the AST predicates that catch the current helper.
- Dirty-worktree clarification: do not stash or alter unrelated user files. Instead require T051 target files to be clean before T051 edits, record the unrelated dirty baseline, and stage only the T051 allowed files.

## Source Evidence

Existing pass-through:

- `backend/src/intric/flows/api/flow_router_common.py:113-114` defines `flow_run_contract_service(container: Container) -> FlowRunContractService` and immediately returns `container.flow_run_contract_service()`.
- `backend/src/intric/main/container/container.py:1263-1269` defines the canonical `flow_run_contract_service = providers.Factory(FlowRunContractService, ...)`.

Current production caller:

- `backend/src/intric/flows/api/flow_upload_router.py:117-119` calls `common.flow_run_contract_service(container).get_run_contract(...)`.

Current test caller:

- `backend/tests/unittests/flows/test_flow_upload_router.py:64-68` monkeypatches `router_common_module.flow_run_contract_service` in `test_get_flow_run_contract_enforces_scope_and_returns_contract`.
- This test should migrate to `container.flow_run_contract_service.return_value = run_contract_service` while preserving `run_contract_service.get_run_contract.assert_awaited_once_with(flow_id=flow_id)`.

Baseline verification:

```bash
cd backend && uv run pyright src/intric/flows/api/flow_router_common.py src/intric/flows/api/flow_upload_router.py tests/unittests/flows/test_flow_upload_router.py
```

Result: pass, `0 errors, 0 warnings, 0 informations`.

FastAPI/API adapter review:

- The candidate touches a Flow API adapter path, not endpoint decorators, request models, response models, dependency declarations, route signatures, OpenAPI, or generated-client code.
- Expected OpenAPI/generated-client impact: none.

## Candidate Classification

### safe_now

`T051`: delete `flow_router_common.flow_run_contract_service(container)` and call `container.flow_run_contract_service()` directly from `get_flow_run_contract`.

Why safe now:

- It removes the same kind of pass-through helper that T049 just deleted.
- It reuses the existing canonical Container provider and `FlowRunContractService`.
- It changes no public API behavior, schema, generated client, persistence, runtime contract, retention, service-key identity, review/rerun policy, or Flow AI Builder behavior.
- The one affected test can migrate at the same provider seam without losing signal.

### follow_up

- Broader Flow API provider-erasure cleanup, including `flow_api_common.py:239-240`, `flow_api_common.py:280-281`, and `flow_run_steps_router.py:82`, should be judged separately.
- A future Container typed-accessor task may remove repeated dependency-injector provider typing pressure at the source.

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
- Do not start it while runtime/API/schema architecture is still actively changing. T051 must preserve owner/consolidation evidence so the final docs Worker can write from implemented reality.

## Proposed T051 Worker

Objective:

```text
refactor(flows-api): use the run-contract service provider directly
```

Allowed files:

- `docs/goals/flows-clean-architecture-2026-05-25/state.yaml`
- `docs/goals/flows-clean-architecture-2026-05-25/notes/t051-run-contract-service-provider.md`
- `backend/src/intric/flows/api/flow_router_common.py`
- `backend/src/intric/flows/api/flow_upload_router.py`
- `backend/tests/unittests/flows/test_flow_architecture_guards.py`
- `backend/tests/unittests/flows/test_flow_upload_router.py`

Expected implementation:

- Confirm `Container.flow_run_contract_service` is still the existing provider owner.
- Generalize the existing `test_flow_api_upload_service_uses_container_provider_without_any_erasure` guard instead of adding a parallel guard.
- Rename the generalized guard to an axis-level name such as `test_flow_api_provider_passthrough_helpers_are_not_reintroduced`.
- Rename `FLOW_API_UPLOAD_PROVIDER_FILES` to `FLOW_API_PROVIDER_PASSTHROUGH_FILES` or a similarly axis-level name if the guard is generalized in this slice.
- Promote the forbidden helper names and manual construction class names into module-level sets:
  - forbidden helper names must include `flow_upload_service` and `flow_run_contract_service`;
  - forbidden manual construction class names must include `FlowFileUploadService` and `FlowRunContractService`.
- The guard must scan exactly:
  - `backend/src/intric/flows/api/flow_router_common.py`
  - `backend/src/intric/flows/api/flow_upload_router.py`
- The guard must detect:
  - `FunctionDef` named `flow_upload_service` or `flow_run_contract_service`;
  - `Call` where `func.id` is `FlowFileUploadService` or `FlowRunContractService`;
  - `cast(Any, container.X())` on container provider calls;
  - nearby `reportUnknownMemberType` ignores on container provider calls.
- Prove the generalized guard fails red against the current `flow_router_common.py:113-114` helper before production edits. The expected current red offender is the `FunctionDef` named `flow_run_contract_service`; the manual construction predicate is included for future regression but is not expected to trigger on current source.
- Delete `flow_router_common.flow_run_contract_service(container)`.
- Remove now-unused `FlowRunContractService` import from `flow_router_common.py`.
- Replace `common.flow_run_contract_service(container)` with `container.flow_run_contract_service()` in `get_flow_run_contract`.
- Migrate `test_get_flow_run_contract_enforces_scope_and_returns_contract` from monkeypatching the helper to setting `container.flow_run_contract_service.return_value = run_contract_service`.
- Preserve `run_contract_service.get_run_contract.assert_awaited_once_with(flow_id=flow_id)`.
- Leave the pre-existing `container.flow_service.return_value = AsyncMock()` setup line alone unless it becomes directly misleading or fails lint; it is not a T051 behavior change.

Verification commands:

```bash
git status --short
git diff --name-only -- backend/src/intric/flows/api/flow_router_common.py backend/src/intric/flows/api/flow_upload_router.py backend/tests/unittests/flows/test_flow_architecture_guards.py backend/tests/unittests/flows/test_flow_upload_router.py
cd backend && uv run pytest tests/unittests/flows/test_flow_architecture_guards.py::test_flow_api_provider_passthrough_helpers_are_not_reintroduced -q
cd backend && uv run pyright src/intric/flows/api/flow_router_common.py src/intric/flows/api/flow_upload_router.py
cd backend && uv run pytest tests/unittests/flows/test_flow_architecture_guards.py tests/unittests/flows/test_flow_upload_router.py -q
cd backend && uv run pyright src/intric/flows/api/flow_router_common.py src/intric/flows/api/flow_upload_router.py tests/unittests/flows/test_flow_architecture_guards.py tests/unittests/flows/test_flow_upload_router.py
cd backend && uv run ruff check src/intric/flows/api/flow_router_common.py src/intric/flows/api/flow_upload_router.py tests/unittests/flows/test_flow_architecture_guards.py tests/unittests/flows/test_flow_upload_router.py
cd backend && uv run ruff format --check src/intric/flows/api/flow_router_common.py src/intric/flows/api/flow_upload_router.py tests/unittests/flows/test_flow_architecture_guards.py tests/unittests/flows/test_flow_upload_router.py
rg -n 'def flow_run_contract_service|common\.flow_run_contract_service|FlowRunContractService\(' backend/src/intric/flows/api/flow_router_common.py backend/src/intric/flows/api/flow_upload_router.py backend/tests/unittests/flows/test_flow_upload_router.py
git diff --check
git diff --staged --name-only
```

Expected pre-edit target-file diff result: no changes in the four T051 source/test files before T051 starts. Unrelated dirty files may exist and must remain untouched.

Expected grep result after T051: no matches for `def flow_run_contract_service`, `common.flow_run_contract_service`, or `FlowRunContractService(` in the bounded files.

Stop if:

- Direct `container.flow_run_contract_service()` call fails strict pyright.
- The generalized guard does not fail red against the current helper before production edits.
- The guard is implemented as a parallel test instead of deepening the existing Flow API provider guard, unless a concrete source-evidence reason is added to this Judge note first.
- The router test stops asserting `run_contract_service.get_run_contract.assert_awaited_once_with(flow_id=flow_id)`.
- The fix requires changing endpoint signatures, response models, dependencies, OpenAPI, generated clients, or Flow run-contract behavior.
- The fix requires changing `Container` provider definitions or `FlowRunContractService` constructor semantics.
- The fix requires `Any`, `cast(Any)`, `dict[str, Any]`, a pyright ignore, a generic helper, manager, processor, service locator, fake interface, or one-implementation protocol.
- The task expands into retention, service-key identity/review/rerun, schema migrations, webhook outbox, output-format architecture, final architecture docs, or Flow AI Builder.
- Staged files include anything outside the T051 allowed files.
- Any unrelated pre-existing dirty file is staged, stashed, reset, cleaned, or otherwise modified.

## Consolidation Effect

- Reused existing owner: `Container.flow_run_contract_service` and `FlowRunContractService`.
- Logic moved from: a one-line `flow_router_common.flow_run_contract_service` pass-through to direct provider use in `get_flow_run_contract`.
- Logic deleted: the pass-through helper and `FlowRunContractService` import from `flow_router_common.py`.
- Duplicate path removed: Flow API run-contract wiring no longer has a second helper surface.
- New code added: one focused architecture guard and one test fixture migration.
- Why existing owners were insufficient: they are sufficient; the API helper only forwards to the real owner.
- Guard/test preventing duplicate logic from returning: generalized Flow API provider pass-through guard plus the migrated run-contract router test.
- Net Flow logic surface area: reduced.
- If increased, why the increase is necessary: not applicable.

## Naming Gate

- New module/class/type/status/file names expected: none.
- Proposed generalized test name: `test_flow_api_provider_passthrough_helpers_are_not_reintroduced`.
- The name identifies the axis: Flow API provider ownership and forbidden pass-through helpers.
- This belongs in the future `docs/flows/architecture.md` guard-test map and "where to change X" table as: run-contract behavior lives in `FlowRunContractService`; the run-contract endpoint calls `container.flow_run_contract_service()`.

## Peer Review Plan

Run Claude plan gate before activating T051 because this touches a Flow API adapter boundary.

Use `--timeout-seconds 1200`, `--require-green`, and `--required-min-score 8`.

Claude iteration 1 artifact:

- `.codex/artifacts/claude-peer-loop-t050-next-safe-flow-task-judge-20260526T132940Z.md`
- Verdict: `GREEN_LIGHT: no`, `MIN_SCORE: 7`.
- Valid blockers addressed in this revision: generalized guard instead of parallel guard, explicit AST red predicates, and dirty-worktree handling that preserves unrelated user files.

Claude iteration 2 artifact:

- `.codex/artifacts/claude-peer-loop-t050-next-safe-flow-task-judge-iteration-2-20260526T133246Z.md`
- Verdict: `GREEN_LIGHT: yes`, `MIN_SCORE: 8`.
- Non-blocking tightening accepted into T051: rename the API provider file-list constant to match the generalized pass-through guard, and keep the guard assertion message at the invariant level.

Antigravity is not required unless Claude and Codex disagree. This is not a public contract, schema, data migration, runtime reliability, or disputed architecture decision.
