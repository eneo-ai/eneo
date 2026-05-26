# T054 Judge: Next Safe Task After Flow API Provider Pass-Through Cleanup

## Decision

Choose `T055` as the next safe Worker:

```text
refactor(flows-api): remove remaining Flow API provider typing exceptions
```

This is a narrow follow-up to T053. It removes the last Flow API provider
pass-through exception and the four remaining Flow API `reportUnknownMemberType`
provider ignores, then broadens the existing guard so Flow API provider erasure is
checked across all Flow API Python files.

## Source Evidence

Current Flow API provider-typing exceptions:

| File | Current line | Issue |
|---|---:|---|
| `backend/src/intric/flows/api/flow_api_common.py` | 239 | `container.space_service()` has `reportUnknownMemberType` ignore. |
| `backend/src/intric/flows/api/flow_api_common.py` | 240 | `container.actor_manager()` has `reportUnknownMemberType` ignore. |
| `backend/src/intric/flows/api/flow_api_common.py` | 280 | `container.space_service()` has `reportUnknownMemberType` ignore. |
| `backend/src/intric/flows/api/flow_api_common.py` | 281 | `container.actor_manager()` has `reportUnknownMemberType` ignore. |
| `backend/src/intric/flows/api/flow_run_steps_router.py` | 66-67 | `_get_flow_version_repo` only returns `container.flow_version_repo()` with `reportUnknownMemberType` ignore. |

Bounded grep:

```text
rg -n 'pyright: ignore\[reportUnknownMemberType\]|cast\(\s*Any\s*,\s*container\.|def _get_.*\(|return container\.' backend/src/intric/flows backend/tests/unittests/flows -g '*.py'
```

shows these Flow API provider exceptions, plus non-API/runtime/AI Builder matches
that are outside this slice.

Strict-pyright temp-copy preflight:

- In a temporary copy of `backend/src`, remove the four `flow_api_common.py`
  provider ignores.
- In the same temporary copy, remove `_get_flow_version_repo`, remove its
  annotation-only import, and replace its call site with `container.flow_version_repo()`.
- Run from the real backend environment:

```text
cd backend && uv run pyright /private/tmp/<temp>/backend/src/intric/flows/api/flow_api_common.py /private/tmp/<temp>/backend/src/intric/flows/api/flow_run_steps_router.py
```

Result: `0 errors, 0 warnings, 0 informations`.

FastAPI/API adapter review:

- The candidate touches Flow API adapter internals only.
- No endpoint decorators, signatures, request/response models, auth policy, OpenAPI
  metadata, or generated clients should change.

## Candidate Classification

### safe_now

`T055`: remove remaining Flow API provider typing exceptions.

Why safe now:

- Temp-copy pyright proves direct provider access is strict-pyright clean.
- The remaining helper is a one-line pass-through with no policy.
- The remaining provider ignores are on direct provider calls, not domain logic.
- Removing the exception lets the architecture guard become stricter and simpler:
  no Flow API provider pass-through exceptions and no Flow API provider
  `Any`/pyright-ignore erasure.

### needs_preflight

- Runtime/Celery `reportUnknownMemberType` ignores outside Flow API.
- DOCX/template rendering library typing ignores.
- AI Builder provider pass-through helpers; Flow AI Builder is out of scope unless a
  Flow proper file directly depends on the same contract.
- Broader Container typing or dependency-injector typing changes if future source
  proves direct provider calls are not clean.

### blocked_on_decision

- Retention behavior.
- Service-key identity model.
- Review/rerun service-key capability policy.
- Schema migrations, webhook outbox changes, and other product/data decisions not
  currently unblocked.

### final_docs_only

- `T901`: `docs/flows/architecture.md` maintainer map.
- Do not start it during active runtime/API/schema architecture changes.

## Proposed T055 Worker

Objective:

```text
refactor(flows-api): remove remaining Flow API provider typing exceptions
```

Allowed files:

- `docs/goals/flows-clean-architecture-2026-05-25/state.yaml`
- `docs/goals/flows-clean-architecture-2026-05-25/notes/t055-flow-api-provider-typing-exceptions.md`
- `backend/src/intric/flows/api/flow_api_common.py`
- `backend/src/intric/flows/api/flow_run_steps_router.py`
- `backend/tests/unittests/flows/test_flow_architecture_guards.py`

Expected implementation:

- Deepen the existing provider guard; do not add a parallel guard.
- Make provider `Any`/`reportUnknownMemberType` erasure detection scan all Flow API
  Python files.
- Remove the `_get_flow_version_repo` exception from the pass-through guard.
- Prove the guard fails red before source edits with exactly six offenders:
  four `flow_api_common.py` pyright-ignore lines, the
  `_get_flow_version_repo` pyright-ignore line, and the `_get_flow_version_repo`
  pass-through helper record.
- Remove the four provider ignores in `flow_api_common.py`.
- Delete `_get_flow_version_repo`, remove the now-unused `FlowVersionRepository`
  import, and call `container.flow_version_repo()` directly.
- Reproduce the pyright proof in place after the source edits by running pyright
  from `backend/` against the real edited files, not only against the temporary
  preflight copy.
- Do not create a typed-accessor/helper/protocol unless the direct-provider source
  edit unexpectedly fails strict pyright.

Verification commands:

```text
cat /Users/ccimen/.codex/overnight-watchdog/flows-clean-architecture-watchdog.json
cd backend && uv run pytest tests/unittests/flows/test_flow_architecture_guards.py::test_flow_api_provider_passthrough_helpers_are_not_reintroduced -q
cd backend && uv run pyright src/intric/flows/api/flow_api_common.py src/intric/flows/api/flow_run_steps_router.py tests/unittests/flows/test_flow_architecture_guards.py
cd backend && uv run pyright src/intric/flows/api
cd backend && uv run pytest tests/unittests/flows/test_flow_architecture_guards.py tests/unittests/flows/test_flow_scope_errors.py tests/unittests/flows/test_flow_run_execution_router.py tests/unittests/flows/test_flow_evidence_router.py -q
cd backend && uv run ruff check src/intric/flows/api/flow_api_common.py src/intric/flows/api/flow_run_steps_router.py tests/unittests/flows/test_flow_architecture_guards.py
cd backend && uv run ruff format --check src/intric/flows/api/flow_api_common.py src/intric/flows/api/flow_run_steps_router.py tests/unittests/flows/test_flow_architecture_guards.py
rg -n 'pyright: ignore\[reportUnknownMemberType\]|cast\(\s*Any\s*,\s*container\.|def _get_.*\(|return container\.' backend/src/intric/flows/api backend/tests/unittests/flows/test_flow_architecture_guards.py -g '*.py'
git diff --unified=0 -- backend/src/intric/flows/api | rg '^[+-].*(@router|operation_id|response_model|status_code|summary=|description=)'
git diff --check
git diff --staged --name-only
```

Expected post-change grep: no Flow API `reportUnknownMemberType` provider erasure,
no `cast(Any, container...)`, no Flow API `_get_*` provider pass-through helpers,
and no remaining `return container.<provider>()` pass-through line.

Stop if:

- Watchdog reports a halt-worthy blocker.
- Red guard reports anything other than six offenders before source edits.
- Direct provider calls introduce pyright errors.
- The fix requires a new helper, protocol, typed accessor, or Container provider
  definition change.
- The fix requires changing endpoint decorators, signatures, response models,
  OpenAPI, generated clients, auth policy, behavior, or non-Flow API files.
- The task expands into retention, service-key identity/review/rerun policy, schema
  migrations, webhook outbox, output-format architecture, final architecture docs,
  or Flow AI Builder.
- Staged files include anything outside the T055 allowed files.

## Consolidation Effect

- Reused existing owner: `Container.flow_version_repo`, `Container.space_service`,
  and `Container.actor_manager`.
- Logic moved from: `_get_flow_version_repo` helper to direct provider call.
- Logic deleted: `_get_flow_version_repo`, its annotation-only import, four provider
  pyright-ignore comments, the helper's provider pyright-ignore comment, and the
  guard's provider-typing exception mechanism.
- Duplicate path removed: no Flow API provider pass-through exception remains.
- New code added: guard scan scope broadens to all Flow API Python files; no
  production code abstraction.
- Why existing owners were insufficient: existing owners are sufficient; temp-copy
  pyright proves direct provider calls are clean.
- Guard/test preventing duplicate logic from returning: structural provider
  pass-through and provider-erasure guard over Flow API Python files.
- Net Flow logic surface area: reduced.
- If increased, why the increase is necessary: not applicable.

## Naming Gate

- New production names: none.
- New/renamed test constants should state the exact Flow API provider-erasure rule.
- Future `docs/flows/architecture.md` can document that Flow API has no provider
  pass-through helpers and no provider `Any`/pyright-ignore erasure.

## Peer Review Plan

Run Claude plan gate before activating T055 because this touches Flow API adapter
guard boundaries.

Antigravity is not required unless Claude and Codex disagree.
