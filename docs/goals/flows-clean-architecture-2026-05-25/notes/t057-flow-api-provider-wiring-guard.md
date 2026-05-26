# T057 Worker: Flow API Provider Wiring Guard

## Summary

Clarified the existing Flow API provider wiring guard without touching production
code. The guard now names the full invariant, uses a module-level regex for
`reportUnknownMemberType` ignore detection, and has a focused detector test for
spacing variants plus the no-nearby-provider negative case.

## Scope

Changed:

- `backend/tests/unittests/flows/test_flow_architecture_guards.py`

Not changed:

- Production source.
- FastAPI router behavior, endpoint signatures, response models, OpenAPI, generated
  clients, runtime code, migrations, frontend code, Flow AI Builder, retention,
  service-key identity/review/rerun policy, webhook outbox, or final architecture
  docs.

## Source Evidence

- `_container_provider_any_erasure_offenders` remains the shared detector owner.
- `test_flow_celery_task_provider_wiring_is_not_erased_to_any` still uses that
  detector, so the stricter regex was verified against the Celery task guard.
- `test_flow_api_provider_wiring_uses_typed_container_providers` now covers the
  complete invariant: no `cast(Any, container...)`, no provider
  `reportUnknownMemberType` ignores, no private provider pass-through helpers, and
  no direct Flow service construction.

## Consolidation Effect

- Reused existing owner: `backend/tests/unittests/flows/test_flow_architecture_guards.py`.
- Logic moved from: none.
- Logic deleted: stale pass-through-only guard name and brittle substring detection.
- Duplicate path removed: none; the existing guard and shared detector were deepened.
- New code added: one module-level whitespace-tolerant regex and one focused detector
  test in the existing guard file. The detector test compares offenders as a set so
  it does not depend on collector traversal order.
- Why existing owners were insufficient: existing owner was sufficient; no new owner
  or parallel guard was needed.
- Guard/test preventing duplicate logic from returning:
  `test_flow_api_provider_wiring_uses_typed_container_providers` and
  `test_container_provider_erasure_detector_catches_report_unknown_member_spacing`.
- Net Flow logic surface area: preserved for production, reduced ambiguity in tests.
- If increased, why the increase is necessary: not applicable.

## Naming Gate

- New production names: none.
- New test name:
  `test_flow_api_provider_wiring_uses_typed_container_providers`.
- Architecture axis: API adapter/provider wiring and typed Container ownership.
- Final docs readiness: the name is clear enough for the future
  `docs/flows/architecture.md` guard-test map and "where to change X" table.

## Verification

| Command | Result | Output |
|---|---:|---|
| `cd backend && uv run pytest tests/unittests/flows/test_flow_architecture_guards.py::test_container_provider_erasure_detector_catches_report_unknown_member_spacing tests/unittests/flows/test_flow_architecture_guards.py::test_flow_api_provider_wiring_uses_typed_container_providers tests/unittests/flows/test_flow_architecture_guards.py::test_flow_celery_task_provider_wiring_is_not_erased_to_any -q` | pass | `3 passed in 0.14s` |
| `cd backend && uv run pytest tests/unittests/flows/test_flow_architecture_guards.py -q` | pass | `14 passed in 1.24s` after staging |
| `cd backend && uv run pyright tests/unittests/flows/test_flow_architecture_guards.py` | pass | `0 errors, 0 warnings, 0 informations` |
| `cd backend && uv run ruff check tests/unittests/flows/test_flow_architecture_guards.py` | pass | `All checks passed!` |
| `cd backend && uv run ruff format --check tests/unittests/flows/test_flow_architecture_guards.py` | pass | `1 file already formatted` |
| `rg -n 'test_flow_api_provider_passthrough_helpers_are_not_reintroduced|"pyright: ignore" in line|"reportUnknownMemberType" in line' backend/tests/unittests/flows/test_flow_architecture_guards.py` | pass | No matches. |
| `rg -n 'test_flow_api_provider_passthrough_helpers_are_not_reintroduced' . -g '!frontend/node_modules/**' -g '!node_modules/**' -g '!.git/**'` | pass | Matches are historical task notes/state receipts only; no source/test/CI references remain. |
| source/test planning-vocabulary grep on the guard diff | pass | No source/test planning-vocabulary matches. |
| `scripts/gate-local/anti_slippage.sh` | pass | `anti-slippage: staged diff clean` after staging |
| `git diff --check` | pass | No whitespace errors. |

## Peer Review

Claude implementation gate:

- Iteration 1: `GREEN_LIGHT: yes`, `MIN_SCORE: 8`. Claude reported only P3
  findings.
- Addressed P3 finding: changed the detector test to compare a set of offenders
  instead of relying on collector order, and added an above-provider negative case.
- Iteration 2: `GREEN_LIGHT: yes`, `MIN_SCORE: 8`.
- Artifacts:
  - `.codex/artifacts/claude-peer-loop-t057-flow-api-provider-wiring-guard-implementation-review-20260526T154159Z.md`
  - `.codex/artifacts/claude-peer-loop-t057-flow-api-provider-wiring-guard-implementation-review-iteration-2-20260526T154452Z.md`

Antigravity: skipped by rule; Claude was green and there was no disputed high-risk
API, runtime, schema, or public-contract decision.
