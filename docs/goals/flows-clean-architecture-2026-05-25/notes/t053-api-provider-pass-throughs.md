# T053 Worker: Delete Typed Flow API Provider Pass-Through Helpers

## Objective

Delete typed one-line Flow API provider helpers and make endpoint handlers call the
canonical `Container` providers directly.

## Source Evidence

The red guard found 11 current typed pass-through helpers:

| File | Helper | Provider |
|---|---|---|
| `backend/src/intric/flows/api/flow_template_router.py` | `_get_flow_template_asset_service` | `flow_template_asset_service` |
| `backend/src/intric/flows/api/flow_assistant_router.py` | `_get_flow_service` | `flow_service` |
| `backend/src/intric/flows/api/flow_assistant_router.py` | `_get_assistant_assembler` | `assistant_assembler` |
| `backend/src/intric/flows/api/flow_authoring_router.py` | `_get_flow_service` | `flow_service` |
| `backend/src/intric/flows/api/flow_run_execution_router.py` | `_get_flow_run_service` | `flow_run_service` |
| `backend/src/intric/flows/api/flow_run_execution_router.py` | `_get_flow_run_review_checkpoint_service` | `flow_run_review_checkpoint_service` |
| `backend/src/intric/flows/api/flow_run_execution_router.py` | `_get_flow_run_rerun_service` | `flow_run_rerun_service` |
| `backend/src/intric/flows/api/flow_run_evidence_router.py` | `_get_flow_run_evidence_service` | `flow_run_evidence_service` |
| `backend/src/intric/flows/api/flow_run_steps_router.py` | `_get_flow_run_service` | `flow_run_service` |
| `backend/src/intric/flows/api/flow_run_steps_router.py` | `_get_flow_run_evidence_service` | `flow_run_evidence_service` |
| `backend/src/intric/flows/api/flow_run_steps_router.py` | `_get_flow_service` | `flow_service` |

The only retained provider helper is `_get_flow_version_repo` in
`backend/src/intric/flows/api/flow_run_steps_router.py`; it remains because direct
provider access currently needs `reportUnknownMemberType`.

## Implementation

- Replaced each typed helper call with a direct `container.<provider>()` call.
- Deleted the now-unused service/assembler imports.
- Reworked `test_flow_api_provider_passthrough_helpers_are_not_reintroduced` from a
  file/name-scoped helper ban into a structural AST check over Flow API Python
  files.
- Kept the existing direct service-construction guard.
- Kept the existing provider `Any` erasure guard bounded to the router files already
  cleaned in earlier slices because known provider-typing blockers still exist in
  other API files.
- Added only required `FlowRunStepPublic` fixture fields in
  `test_flow_evidence_router.py` after the broad verification bundle proved those
  two fixtures were stale.

## Red/Green Evidence

Red guard before source edits:

```text
cd backend && uv run pytest tests/unittests/flows/test_flow_architecture_guards.py::test_flow_api_provider_passthrough_helpers_are_not_reintroduced -q
```

Result: failed with exactly 11 offenders and did not report `_get_flow_version_repo`.

Green checks after source edits:

```text
cd backend && uv run pytest tests/unittests/flows/test_flow_architecture_guards.py::test_flow_api_provider_passthrough_helpers_are_not_reintroduced -q
```

Result: `1 passed`.

```text
cd backend && uv run pytest tests/unittests/flows/test_flow_evidence_router.py::test_flow_run_steps_alias_surfaces_diagnostics_dicts_only tests/unittests/flows/test_flow_evidence_router.py::test_flow_run_steps_alias_handles_non_list_diagnostics -q
```

Result: `2 passed, 9 warnings`.

```text
cd backend && uv run pytest tests/unittests/flows/test_flow_architecture_guards.py tests/unittests/flows/test_flow_router.py tests/unittests/flows/test_flow_template_router.py tests/unittests/flows/test_flow_run_execution_router.py tests/unittests/flows/test_flow_evidence_router.py tests/unittests/flows/test_flow_scope_errors.py -q
```

Result: `85 passed, 9 warnings`.

```text
cd backend && uv run pyright src/intric/flows/api/flow_template_router.py src/intric/flows/api/flow_assistant_router.py src/intric/flows/api/flow_authoring_router.py src/intric/flows/api/flow_run_execution_router.py src/intric/flows/api/flow_run_evidence_router.py src/intric/flows/api/flow_run_steps_router.py tests/unittests/flows/test_flow_architecture_guards.py tests/unittests/flows/test_flow_evidence_router.py
```

Result: `0 errors, 0 warnings, 0 informations`.

```text
cd backend && uv run ruff check src/intric/flows/api/flow_template_router.py src/intric/flows/api/flow_assistant_router.py src/intric/flows/api/flow_authoring_router.py src/intric/flows/api/flow_run_execution_router.py src/intric/flows/api/flow_run_evidence_router.py src/intric/flows/api/flow_run_steps_router.py tests/unittests/flows/test_flow_architecture_guards.py tests/unittests/flows/test_flow_evidence_router.py
```

Result: `All checks passed!`

```text
cd backend && uv run ruff format --check src/intric/flows/api/flow_template_router.py src/intric/flows/api/flow_assistant_router.py src/intric/flows/api/flow_authoring_router.py src/intric/flows/api/flow_run_execution_router.py src/intric/flows/api/flow_run_evidence_router.py src/intric/flows/api/flow_run_steps_router.py tests/unittests/flows/test_flow_architecture_guards.py tests/unittests/flows/test_flow_evidence_router.py
```

Result: `8 files already formatted`.

```text
rg -n '^def _get_.*\(|return container\.' backend/src/intric/flows/api -g '*.py'
```

Result: only `_get_flow_version_repo` and its retained `return container.flow_version_repo()` line remain.

## Consolidation Effect

- Reused existing owner: `Container` providers and the corresponding application
  services/assembler.
- Logic moved from: private one-line Flow API `_get_*` provider helpers to direct
  endpoint-handler provider calls.
- Logic deleted: 11 typed provider pass-through helper functions and their
  annotation-only imports.
- Duplicate path removed: Flow API service wiring no longer has a parallel typed
  helper family.
- New code added: structural architecture guard predicate and one explicit
  provider-typing exception for `_get_flow_version_repo`.
- Why existing owners were insufficient: existing owners were sufficient; the
  helpers only forwarded to them.
- Guard/test preventing duplicate logic from returning: structural Flow API provider
  pass-through guard over Flow API Python files.
- Net Flow logic surface area: reduced.
- If increased, why the increase is necessary: not applicable.

## Temporary Path Remaining

- Owner: `_get_flow_version_repo` in `flow_run_steps_router.py`.
- Reason: direct `container.flow_version_repo()` access currently requires
  `reportUnknownMemberType`.
- Migration/deletion trigger: a provider-typing or Container typed-accessor preflight
  proves direct access is strict-pyright clean without `Any`, casts, or ignores.
- Test/preflight proving continued need: current source line has the pyright ignore;
  future deletion must prove pyright clean and rerun graph/run-step tests.

## Naming Gate

- New production names: none.
- New test names are specific to Flow API provider pass-through detection.
- Future `docs/flows/architecture.md` can state: Flow API endpoint handlers call
  canonical `Container` providers directly; private provider pass-through functions
  are blocked by the architecture guard except documented provider-typing blockers.
