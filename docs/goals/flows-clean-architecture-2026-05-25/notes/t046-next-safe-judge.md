# T046 Next Safe Judge

## Objective

Choose the next smallest safe Flow clean-architecture task after T045, while applying the maintainer-map and naming gate. This is read-only: no source edits, tests, migrations, frontend, OpenAPI, or `docs/flows/architecture.md` changes.

## Current Board State

- Active task: T046.
- Recently completed: T043 durable webhook outbox, T044 next-task Judge, T045 outbox delivery-status vocabulary.
- Queued but not automatically safe: T012, T014, T015, T016.
- Blocked by product/data decisions: T009, T010, T011.
- Final docs task queued: T901, final-only, not active during runtime/API/schema work.

## Candidate Classification

| Candidate | Classification | Reason |
|---|---|---|
| Remove `cast(Any)` / `pyright: ignore` from Flow task `template_asset_service` executor wiring | safe_now | Narrow typed-boundary cleanup in Flow runtime task wiring; no product decision, migration, API, frontend, or behavior change required. |
| Replace outbox delivery result payload keys `"delivered"` / `"dead_lettered"` with `FlowOutboxDeliveryStatus` values | follow_up | The literals are task payload keys rather than delivery-status comparisons. Importing the DB-table enum into application/runtime result payloads could worsen ownership unless a Worker explicitly justifies the boundary. |
| Name webhook worker wrapper timeout and add deterministic deadline guard tests | follow_up | Useful runtime clarity, but touches timeout behavior/tests and has lower immediate ROI than removing `cast(Any)`. |
| Deployment smoke/check instructions for webhook beat task | follow_up | Operational docs/checks only; not the next highest maintainability issue. |
| T012 draft step id-owned persistence | needs_preflight | Large source/API/schema persistence tranche; do not start from a small follow-up Judge without refreshed Worker scope. |
| T014 schema invariants | needs_preflight | Migration/schema work requires Postgres/Alembic preflight and is not safe as an automatic next Worker. |
| T015 API consumer DX | needs_preflight | Public API/docs/generated-client impacts; requires source preflight and FastAPI/OpenAPI gate before implementation. |
| T016 frontend state ownership | needs_preflight | Frontend ownership work; requires UI/frontend scope, generated types, and separate review. |
| T901 maintainer architecture map | final_docs_only | Required before merge, but must wait until runtime/API/schema architecture is stable enough to document as source reality. |
| T009/T010/T011 retention/service-key/review/rerun | blocked_on_decision | State still records these as blocked pending owner product/data decisions. |

## Source Evidence

- `backend/src/intric/flows/runtime/tasks.py:143-146` passes `template_asset_service=cast(Any, container.flow_template_asset_service())` with a pyright unknown-member ignore.
- `backend/src/intric/flows/runtime/executor.py:386` already expects `template_asset_service: FlowTemplateAssetService`.
- `backend/src/intric/main/container/container.py:1248-1254` defines `flow_template_asset_service` as a factory for `FlowTemplateAssetService`.
- `backend/src/intric/flows/application/flow_run_audit_outbox_delivery.py:37,39` and `backend/src/intric/flows/runtime/flow_webhook_delivery.py:68,70` use delivered/dead_lettered as task payload keys; this is noted but not selected because those keys are not DB delivery-status comparisons.
- `docs/goals/flows-clean-architecture-2026-05-25/state.yaml` keeps T009/T010/T011 blocked and T901 queued final-only.

## Decision

Activate T047 as the next Worker:

`refactor(flows-runtime): type Flow task template asset service wiring`

### Allowed Files

- `docs/goals/flows-clean-architecture-2026-05-25/state.yaml`
- `docs/goals/flows-clean-architecture-2026-05-25/notes/t047-flow-task-template-asset-wiring.md`
- `backend/src/intric/flows/runtime/tasks.py`
- `backend/tests/unittests/flows/test_flow_architecture_guards.py`
- `backend/tests/unittests/flows/test_celery_runtime.py`

### Expected Worker Output

- Remove `cast(Any, container.flow_template_asset_service())` and the pyright ignore tied to that provider call.
- Try plain removal first; do not add a helper or typed cast unless pyright proves it is needed.
- If plain removal fails pyright, prefer a typed local assignment. A typed `cast(FlowTemplateAssetService, ...)` is allowed only as a contract-preserving fallback. `Any`, `cast(Any)`, and pyright ignores are forbidden.
- Keep `FlowRunExecutor` receiving a concrete `FlowTemplateAssetService`; do not introduce a protocol, adapter, generic provider helper, manager, or service locator.
- Add or extend a guard test that fails if Flow runtime task wiring erases container provider calls to `Any` again.
- Preserve runtime behavior and container ownership.

### Verify

- First local edit check: remove the `cast(Any, ...)` and pyright ignore without replacement, then run `cd backend && uv run pyright src/intric/flows/runtime/tasks.py`.
- Mutation sanity check: temporarily reintroduce `cast(Any, container.flow_template_asset_service())` or a `reportUnknownMemberType` ignore on a container provider call and verify the new guard fails; revert before committing.
- `cd backend && uv run pytest tests/unittests/flows/test_flow_architecture_guards.py::test_flow_celery_task_provider_wiring_is_not_erased_to_any tests/unittests/flows/test_celery_runtime.py -q`
- `cd backend && uv run pyright src/intric/flows/runtime/tasks.py tests/unittests/flows/test_flow_architecture_guards.py tests/unittests/flows/test_celery_runtime.py`
- `cd backend && uv run ruff check src/intric/flows/runtime/tasks.py tests/unittests/flows/test_flow_architecture_guards.py tests/unittests/flows/test_celery_runtime.py`
- `git diff --check`
- `rg -n 'cast\\(\\s*Any|pyright: ignore\\[reportUnknownMemberType\\]|template_asset_service=cast' backend/src/intric/flows/runtime/tasks.py`

### Stop If

- A correct fix requires changing `FlowRunExecutor` constructor semantics, container provider definitions, or files outside the allowed list.
- Strict pyright cannot be kept green after plain removal or a typed contract-preserving fallback.
- The fix still needs `Any`, `cast(Any)`, or a pyright ignore around container provider calls.
- The implementation requires a generic provider helper, manager, processor, fake interface, or one-implementation protocol.
- The task expands into webhook timing, task payload keys, API/frontend, schema migration, retention, service-key identity/review/rerun, or Flow AI Builder.

## Consolidation Effect For T047

- Reused existing owner: `Container.flow_template_asset_service` factory and `FlowRunExecutor` constructor type.
- Logic moved from: untyped task wiring in `tasks.py` to a concrete typed boundary in the same runtime task module.
- Logic deleted: `cast(Any)` and the provider-call pyright ignore.
- Duplicate path removed: no parallel service construction; still uses the canonical container factory.
- New code added: only a narrow local typed retrieval/boundary if needed, plus guard test.
- Why existing owners were insufficient: the owners exist, but the task adapter currently erases the concrete service to `Any` before calling the typed executor.
- Guard/test preventing duplicate logic from returning: architecture guard forbids `cast(Any)`/pyright-ignore around `flow_template_asset_service` task wiring.
- Net Flow logic surface area: reduced.
- If increased, why the increase is necessary: N/A.

## Naming Gate For T047

- No new module/class/status names expected.
- If a local function is needed, it must name the domain boundary, e.g. `_flow_template_asset_service_from_container`, not `helper`, `manager`, or `provider_helper`.
- Any new name should be clear in the future `docs/flows/architecture.md` where-to-change table as Flow task/runtime dependency wiring.

## Commands Run

- `python3 -m json.tool /Users/ccimen/.codex/overnight-watchdog/flows-clean-architecture-watchdog.json`
  - Result: pass; `status: ok`, no blockers.
- `ruby -e 'require "yaml"; ...'`
  - Result: pass; active task T046 and only T046 active after the T045 status fix.
- `rg -n '"delivered"|"dead_lettered"|FlowOutboxDeliveryStatus' backend/src/intric/flows/application/flow_run_audit_outbox_delivery.py backend/src/intric/flows/runtime/flow_webhook_delivery.py backend/tests/unittests/flows backend/tests/integration/flows -g '*.py'`
  - Result: pass; confirmed four task-payload key literals and test enum usage.
- `rg -n 'cast\\(Any|from typing import Any|typing import .*Any|deadline|timeout|claim_ttl|webhook.*beat|beat.*webhook|delivery.*timeout' backend/src/intric/flows/runtime backend/src/intric/flows/infrastructure backend/src/intric/main/container/container.py backend/tests/unittests/flows backend/tests/integration/flows -g '*.py'`
  - Result: pass; broad lead scan, manually narrowed to task wiring cast.
- `rg -n 'cast\\(' backend/src/intric/flows/runtime/tasks.py backend/src/intric/flows/runtime/executor.py`
  - Result: pass; confirmed `tasks.py:143-146` contains the selected `cast(Any)` site.
- `cd backend && uv run pyright src/intric/flows/runtime/tasks.py`
  - Result: pass; baseline is green with the existing `cast(Any)` and ignore. T047 must verify whether plain deletion is also green before adding any fallback.

## Peer Review

- Claude Judge review: `.codex/artifacts/claude-peer-loop-t046-next-safe-flow-task-judge-20260526T123911Z.md`
  - Verdict: `GREEN_LIGHT yes`, `MIN_SCORE 8`.
  - Valid clarifications applied:
    - Try plain deletion before any fallback.
    - Allow only typed contract-preserving fallback, never `Any`/`cast(Any)`/pyright ignore.
    - Broaden the guard to provider-call `Any` erasure in `flows/runtime/tasks.py`, not only `flow_template_asset_service`.
    - Require a mutation-style red check proving the guard fails against the original bad pattern.
