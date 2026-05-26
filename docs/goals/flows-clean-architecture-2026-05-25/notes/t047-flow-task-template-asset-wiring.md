# T047 Flow Task Template Asset Wiring Worker

## Objective

Remove the `Any`-erased Flow Celery task wiring for `template_asset_service` while preserving the existing `Container.flow_template_asset_service` provider and `FlowRunExecutor` constructor type.

## Source Precheck

- `backend/src/intric/flows/runtime/executor.py:386` already requires `template_asset_service: FlowTemplateAssetService`.
- `backend/src/intric/main/container/container.py:1248-1254` defines `flow_template_asset_service` as the canonical `FlowTemplateAssetService` factory.
- `backend/src/intric/flows/runtime/tasks.py:143-146` passed `template_asset_service=cast(Any, container.flow_template_asset_service())` with `pyright: ignore[reportUnknownMemberType]`.

## Implementation

- Added an architecture guard that fails on:
  - `cast(Any, container.<provider>())` inside `backend/src/intric/flows/runtime/tasks.py`;
  - `reportUnknownMemberType` pyright ignores attached to nearby container provider calls.
- Proved the guard failed red against the existing bad pattern before changing production code.
- Removed the `cast(Any, ...)` and provider-call pyright ignore from `tasks.py`.
- Kept plain provider wiring because pyright passed without a helper, typed local, or typed cast.
- Did not change `FlowRunExecutor`, `Container`, API, frontend, migrations, webhook behavior, task payload keys, service-key policy, retention, or `docs/flows/architecture.md`.

## Consolidation Effect

- Reused existing owner: `Container.flow_template_asset_service` factory and `FlowRunExecutor` constructor type.
- Logic moved from: no runtime logic moved; the task adapter stopped erasing the existing typed owner.
- Logic deleted: `cast(Any)` and the provider-call pyright ignore in `tasks.py`.
- Duplicate path removed: no parallel service construction or fallback provider path exists.
- New code added: one architecture guard test. No production helper, interface, adapter, manager, or typed cast was needed.
- Why existing owners were insufficient: the owners were sufficient; the defect was an adapter call site that erased their type contract before passing it to the executor.
- Guard/test preventing duplicate logic from returning: `test_flow_celery_task_provider_wiring_is_not_erased_to_any`.
- Net Flow logic surface area: reduced.
- If increased, why the increase is necessary: N/A.

## Naming Gate

- No new Flow module, class, type, status, or file names were added.
- The new guard name is specific to Flow Celery task provider wiring and would map cleanly to the final `docs/flows/architecture.md` guard-test section and "where to change X" table under runtime task dependency wiring.
- No vague helper/manager/processor/common/misc names were introduced.

## Verification

- Red guard check before production edit:
  - `cd backend && uv run pytest tests/unittests/flows/test_flow_architecture_guards.py::test_flow_celery_task_provider_wiring_is_not_erased_to_any -q`
  - Result: fail as expected, offenders `cast(Any):143, pyright-ignore:146`.
- Plain-removal pyright check:
  - `cd backend && uv run pyright src/intric/flows/runtime/tasks.py`
  - Result: pass, `0 errors, 0 warnings, 0 informations`.
- Focused guard check after production edit:
  - `cd backend && uv run pytest tests/unittests/flows/test_flow_architecture_guards.py::test_flow_celery_task_provider_wiring_is_not_erased_to_any -q`
  - Result: pass, `1 passed`.
- Full T047 test bundle:
  - `cd backend && uv run pytest tests/unittests/flows/test_flow_architecture_guards.py::test_flow_celery_task_provider_wiring_is_not_erased_to_any tests/unittests/flows/test_celery_runtime.py -q`
  - Result: pass, `17 passed, 9 warnings in 17.36s`.
- T047 pyright bundle:
  - `cd backend && uv run pyright src/intric/flows/runtime/tasks.py tests/unittests/flows/test_flow_architecture_guards.py tests/unittests/flows/test_celery_runtime.py`
  - Result: pass, `0 errors, 0 warnings, 0 informations`.
- Ruff:
  - `cd backend && uv run ruff check src/intric/flows/runtime/tasks.py tests/unittests/flows/test_flow_architecture_guards.py tests/unittests/flows/test_celery_runtime.py`
  - Result: pass, `All checks passed!`.
- Ruff format check:
  - `cd backend && uv run ruff format --check src/intric/flows/runtime/tasks.py tests/unittests/flows/test_flow_architecture_guards.py tests/unittests/flows/test_celery_runtime.py`
  - Result: pass, `3 files already formatted`.
- Anti-regression search:
  - `rg -n 'cast\\(\\s*Any|pyright: ignore\\[reportUnknownMemberType\\]|template_asset_service=cast' backend/src/intric/flows/runtime/tasks.py`
  - Result: pass, no matches.
- Whitespace:
  - `git diff --check`
  - Result: pass.

## Peer Review

- Claude commit gate: `.codex/artifacts/claude-peer-loop-t047-flow-task-template-asset-wiring-implementation-review-20260526T124946Z.md`
  - Verdict: `GREEN_LIGHT yes`, `MIN_SCORE 8`.
  - Valid non-blocking findings:
    - Stage only T047 files because the worktree has unrelated dirty/untracked files.
    - Similar `cast(Any, container.X())` patterns exist outside this Worker, including Flow API router common wiring; this should be handled only through a future allowed-files task.
    - The provider-ignore guard uses a small line-window heuristic; acceptable for T047 because it catches the original bad pattern and avoids the Celery decorator ignores.
