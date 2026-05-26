# T056 Judge: Next Safe Task After Flow API Provider Typing Cleanup

## Decision

Choose revised `T057` as the next safe Worker:

```text
test(flows): clarify Flow API provider wiring guard
```

This is a small guard-quality slice. T055 made the Flow API provider guard enforce
three related rules across all Flow API files: no provider pass-through helpers, no
provider `Any`/pyright-ignore erasure, and no direct construction of service classes.
The current test name still says only "pass-through helpers", so the guard is harder
to understand when it fails.

## Source Evidence

- `backend/tests/unittests/flows/test_flow_architecture_guards.py:226` defines
  `_container_provider_any_erasure_offenders`.
- `backend/tests/unittests/flows/test_flow_architecture_guards.py:249-258` detects
  `reportUnknownMemberType` ignores via plain substring checks.
- `backend/tests/unittests/flows/test_flow_architecture_guards.py:665` uses the same
  provider erasure detector for the Flow Celery task wiring guard.
- `backend/tests/unittests/flows/test_flow_architecture_guards.py:674` names the
  guard `test_flow_api_provider_passthrough_helpers_are_not_reintroduced`, but the
  test now enforces provider erasure, pass-through helpers, and manual construction.
- Current Flow API grep has no matches:

```text
rg -n 'pyright: ignore\[reportUnknownMemberType\]|cast\(\s*Any\s*,\s*container\.|def _get_.*\(|return container\.' backend/src/intric/flows/api -g '*.py'
```

## Candidate Classification

### safe_now

`T057`: rename and clarify the Flow API provider guard, make
`reportUnknownMemberType` ignore detection whitespace-tolerant, and add a small
detector test proving the formatting variants are caught.

Why safe now:

- Test-only architecture guard cleanup.
- No production source, API behavior, OpenAPI, generated client, runtime, data, or
  frontend impact.
- Improves human reviewability: future guard failures describe the full invariant.
- Strengthens the guard without adding a new guard or parallel rule.
- The shared detector also tightens the existing Celery task provider wiring guard;
  this is expected and should remain green.

### needs_preflight

- Runtime/Celery/library typing ignores in `flows/runtime/*`; these are library-stub
  issues and need source-specific preflight before any cleanup.
- Flow AI Builder provider pass-through helpers; out of Flows proper scope unless a
  Flow proper file directly depends on the same contract.
- Any broader test-boundary rewrite or guard reorganization.

### blocked_on_decision

- Retention behavior.
- Service-key identity model.
- Review/rerun service-key capability policy.
- Schema migrations, webhook outbox changes, and other product/data decisions not
  recorded as unblocked.

### final_docs_only

- `T901`: `docs/flows/architecture.md` maintainer map.
- Do not start it during active runtime/API/schema work.

## Proposed T057 Worker

Objective:

```text
test(flows): clarify Flow API provider wiring guard
```

Allowed files:

- `docs/goals/flows-clean-architecture-2026-05-25/state.yaml`
- `docs/goals/flows-clean-architecture-2026-05-25/notes/t057-flow-api-provider-wiring-guard.md`
- `backend/tests/unittests/flows/test_flow_architecture_guards.py`

Expected implementation:

- Rename `test_flow_api_provider_passthrough_helpers_are_not_reintroduced` to a
  positive invariant name that covers all three axes, for example
  `test_flow_api_provider_wiring_uses_typed_container_providers`.
- Update the assertion message to mention all enforced Flow API provider-wiring
  violations: `cast(Any, container...)`, provider `reportUnknownMemberType` ignores,
  private provider pass-through helpers, and direct service construction.
- Replace the substring `pyright: ignore` / `reportUnknownMemberType` detection with
  a whitespace-tolerant regex so formatting variations do not bypass the guard.
- Add a focused test for `_container_provider_any_erasure_offenders` using a temp
  file or equivalent fixture to prove the regex catches:
  `pyright:ignore[reportUnknownMemberType]`,
  `pyright: ignore[reportUnknownMemberType]`,
  `pyright:  ignore [ reportUnknownMemberType ]`, and
  `pyright: ignore[reportGeneralTypeIssues, reportUnknownMemberType]`, while keeping
  the existing provider-call proximity window.
- Hoist the regex to module scope; do not compile it inside the file/line loop.
- Do not change production code.
- Do not add a new parallel guard.
- Do not broaden into runtime/Celery/library ignores.

Verification commands:

```text
cd backend && uv run pytest tests/unittests/flows/test_flow_architecture_guards.py::test_container_provider_erasure_detector_catches_report_unknown_member_spacing tests/unittests/flows/test_flow_architecture_guards.py::test_flow_api_provider_wiring_uses_typed_container_providers tests/unittests/flows/test_flow_architecture_guards.py::test_flow_celery_task_provider_wiring_is_not_erased_to_any -q
cd backend && uv run pytest tests/unittests/flows/test_flow_architecture_guards.py -q
cd backend && uv run pyright tests/unittests/flows/test_flow_architecture_guards.py
cd backend && uv run ruff check tests/unittests/flows/test_flow_architecture_guards.py
cd backend && uv run ruff format --check tests/unittests/flows/test_flow_architecture_guards.py
rg -n 'test_flow_api_provider_passthrough_helpers_are_not_reintroduced|\"pyright: ignore\" in line|\"reportUnknownMemberType\" in line' backend/tests/unittests/flows/test_flow_architecture_guards.py
git diff --check
git diff --staged --name-only
```

Stop if:

- The guard cleanup requires production source edits.
- The rename breaks test discovery or any architecture guard.
- The regex change creates false positives against current Flow API source.
- The detector test cannot prove the whitespace variants without weakening the
  provider-call proximity window.
- The task expands into runtime/Celery/library typing cleanup, Flow AI Builder,
  product/data gates, or final architecture docs.
- Staged files include anything outside T057 allowed files.

## Consolidation Effect

- Reused existing owner: `test_flow_architecture_guards.py` remains the owner of
  Flow architecture guard tests.
- Logic moved from: none.
- Logic deleted: stale/narrow test name and brittle substring detection.
- Duplicate path removed: none; the existing guard is deepened, not duplicated.
- New code added: one module-level whitespace-tolerant regex and one focused detector
  test in the existing guard file.
- Why existing owners were insufficient: existing owner is sufficient; no new owner
  needed.
- Guard/test preventing duplicate logic from returning: the existing Flow API
  provider wiring guard.
- Net Flow logic surface area: preserved for production, reduced ambiguity in tests.
- If increased, why the increase is necessary: not applicable.

## Naming Gate

- New production names: none.
- New test name must reveal the architecture axis: Flow API provider wiring and type
  preservation.
- The guard name should be clear enough for the future `docs/flows/architecture.md`
  guard-test map.

## Peer Review Plan

Claude plan gate is optional for such a small test-only cleanup, but this is an
architecture guard, so run Claude once before activation to confirm it is worth doing
and not churn.

Antigravity is not required.
