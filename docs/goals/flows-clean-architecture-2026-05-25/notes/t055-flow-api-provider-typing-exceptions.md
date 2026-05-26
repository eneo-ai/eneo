# T055 Worker: Remove Remaining Flow API Provider Typing Exceptions

## Objective

Remove the remaining Flow API provider typing exceptions and make the architecture
guard enforce the rule across all Flow API Python files.

## Implementation

- Removed four `reportUnknownMemberType` ignores from `flow_api_common.py`.
- Deleted `_get_flow_version_repo` from `flow_run_steps_router.py`.
- Removed the now-unused `FlowVersionRepository` import.
- Replaced `_get_flow_version_repo(container)` with `container.flow_version_repo()`.
- Deleted the provider-typing exception mechanism from the architecture guard.
- Deleted the bounded provider-erasure file tuple and made the guard scan every Flow
  API Python file.

No endpoint decorators, signatures, response models, auth policy, OpenAPI metadata,
generated clients, or endpoint behavior were changed.

## Red/Green Evidence

Red guard after broadening the guard and before source edits:

```text
cd backend && uv run pytest tests/unittests/flows/test_flow_architecture_guards.py::test_flow_api_provider_passthrough_helpers_are_not_reintroduced -q
```

Result: failed with exactly six offender records:

- `flow_run_steps_router.py:pyright-ignore:67`
- `flow_run_steps_router.py:helper:_get_flow_version_repo:flow_version_repo:66`
- `flow_api_common.py:pyright-ignore:239`
- `flow_api_common.py:pyright-ignore:240`
- `flow_api_common.py:pyright-ignore:280`
- `flow_api_common.py:pyright-ignore:281`

Green checks after source edits:

```text
cd backend && uv run pytest tests/unittests/flows/test_flow_architecture_guards.py::test_flow_api_provider_passthrough_helpers_are_not_reintroduced -q
```

Result: `1 passed`.

```text
cd backend && uv run pyright src/intric/flows/api/flow_api_common.py src/intric/flows/api/flow_run_steps_router.py tests/unittests/flows/test_flow_architecture_guards.py
```

Result: `0 errors, 0 warnings, 0 informations`.

```text
cd backend && uv run pyright src/intric/flows/api
```

Result: `0 errors, 0 warnings, 0 informations`.

```text
cd backend && uv run pytest tests/unittests/flows/test_flow_architecture_guards.py tests/unittests/flows/test_flow_scope_errors.py tests/unittests/flows/test_flow_run_execution_router.py tests/unittests/flows/test_flow_evidence_router.py -q
```

Result: `83 passed, 9 warnings`.

```text
cd backend && uv run ruff check src/intric/flows/api/flow_api_common.py src/intric/flows/api/flow_run_steps_router.py tests/unittests/flows/test_flow_architecture_guards.py
```

Result: `All checks passed!`

```text
cd backend && uv run ruff format --check src/intric/flows/api/flow_api_common.py src/intric/flows/api/flow_run_steps_router.py tests/unittests/flows/test_flow_architecture_guards.py
```

Result: `3 files already formatted`.

```text
rg -n 'pyright: ignore\[reportUnknownMemberType\]|cast\(\s*Any\s*,\s*container\.|def _get_.*\(|return container\.' backend/src/intric/flows/api backend/tests/unittests/flows/test_flow_architecture_guards.py -g '*.py'
```

Result: no matches.

```text
git diff --unified=0 -- backend/src/intric/flows/api | rg '^[+-].*(@router|operation_id|response_model|status_code|summary=|description=)'
```

Result: no matches.

## Consolidation Effect

- Reused existing owner: `Container.flow_version_repo`, `Container.space_service`,
  and `Container.actor_manager`.
- Logic moved from: `_get_flow_version_repo` helper to direct provider call.
- Logic deleted: `_get_flow_version_repo`, its annotation-only import, five provider
  pyright-ignore records, the provider-typing exception mechanism, and the bounded
  provider-erasure file tuple.
- Duplicate path removed: no Flow API provider pass-through or provider-erasure
  exception remains.
- New code added: no production code; guard scan scope now uses the existing Flow API
  file discovery.
- Why existing owners were insufficient: existing owners were sufficient; direct
  provider calls pass in-place strict pyright.
- Guard/test preventing duplicate logic from returning: structural provider
  pass-through and provider-erasure guard over Flow API Python files.
- Net Flow logic surface area: reduced.
- If increased, why the increase is necessary: not applicable.

## Naming Gate

- New production names: none.
- Removed test exception names instead of adding or preserving placeholder names.
- Future `docs/flows/architecture.md` can state that Flow API provider wiring has no
  private pass-through helpers and no provider `Any`/pyright-ignore erasure.
