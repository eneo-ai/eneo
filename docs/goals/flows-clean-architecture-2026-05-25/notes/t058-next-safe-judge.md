# T058 Judge: Next Safe Task After Provider Wiring Guard Clarification

## Decision

Choose `T059` as the next safe task:

```text
scout(flows): preflight remaining draft step id-owned persistence
```

This is read-only. Do not start the broad `T012` implementation from the stale
placeholder. Runtime snapshot identity and public runtime result/attempt identity
landed through `T033` through `T040`; the remaining T012 risk is draft authoring
persistence still being order-owned in the request-shape -> repository-sync ->
secret-merge spine.

The concrete correctness driver is the secret-merge reorder bug:
`FlowService._merge_step_secrets` keys stored steps by `step_order`. If two steps
swap order and the incoming update uses secret sentinels, stored encrypted config can
be merged into the wrong step. T059 must make this the first-Worker red test target,
not bury it as generic identity cleanup.

## Board Normalization

- `T055` has a completed receipt and was followed by committed `T056` and `T057`
  work, but its status is still `active`. T058 should mark it `done`.
- Original placeholder `T013` is functionally completed by `T041` through `T045`:
  `T043` implemented durable ref-only webhook outbox and `T045` completed the first
  follow-up consolidation. T058 should close `T013` as completed-by-subtasks so
  final audits do not report a stale queued durable-webhook task.

## Source Evidence

Remaining draft step identity evidence:

- `backend/src/intric/flows/api/flow_models.py:447-556` uses
  `FlowStepCreateRequest` for both create and partial update; the request does not
  carry persisted step id while `FlowStepPublic` exposes `id` at
  `flow_models.py:561-568`.
- `backend/src/intric/flows/infrastructure/flow_repo.py:118-144` omits `step.id`
  from DB row payloads, and `_sync_flow_steps` at `flow_repo.py:745-801` matches,
  updates, and deletes draft steps by `step_order`.
- `backend/src/intric/flows/application/flow_service.py:673-698` merges stored HTTP
  secrets by `step_order`; `flow_service.py:679` builds `stored_by_order`, and
  `flow_service.py:682` uses that order map for incoming steps. A reorder can pair
  sentinel secret values with the wrong stored encrypted config.
- `backend/src/intric/flows/application/flow_draft_materialization.py:145-149`
  creates `existing_step_<step_order>` refs, and
  `flow_draft_materialization_executor.py:241-270` materializes final `FlowStep`
  objects without preserving existing draft step id.
- `frontend/apps/web/src/routes/(app)/spaces/[spaceId]/flows/[flowId]/+page.svelte`
  and Flow editor components still carry several `step_order` fallbacks and keys.

Already completed and should not be repeated:

- Runtime result/attempt step identity migration and non-null domain/API contract:
  `T033`, `T038`, and `T040`.
- Published snapshot preseed fallback deletion and parser-owned published identity:
  `T035` and `T037`.
- Durable webhook outbox: `T041` through `T045`.
- Flow API provider wiring cleanup: `T049` through `T057`.

## Candidate Classification

### safe_now

`T059` read-only Scout: refresh source/frontend/data evidence for the remaining
draft step id-owned persistence tranche and propose the smallest Worker. This
reduces risk before changing API schemas, repository sync, frontend editor state, or
generated clients.

### needs_preflight

- Direct `T012` implementation. The first safe Worker should focus on request shape,
  repository sync, and secret merge. Materialization, frontend editor keys, generated
  client cleanup, and broader graph/editor behavior must remain follow-ups unless
  T059 proves they are required to choose the id semantics.
- `T014` schema invariant migrations. Requires Postgres/Alembic/source-query
  preflight and is not a safe automatic next Worker.
- `T015` API consumer DX. Requires FastAPI/OpenAPI/generated-client preflight and
  should not be bundled with draft persistence.
- `T016` frontend state ownership. Requires backend contract stability and separate
  frontend scope.
- Outbox payload-key literals in delivery result dicts. Previous Judges classified
  them as task payload keys, not DB delivery-status comparisons; they need a narrow
  owner review before changing.

### blocked_on_decision

- Runtime input/file retention.
- Service-key identity model.
- Service-key review/resume/rerun capability policy.
- Materialized encrypted webhook request snapshot storage.

### final_docs_only

- `T901`: `docs/flows/architecture.md` maintainer map. Do not start it during active
  runtime/API/schema/frontend refactors.

## Proposed T059 Scout

Objective:

```text
scout(flows): preflight remaining draft step id-owned persistence
```

Allowed files:

- `docs/goals/flows-clean-architecture-2026-05-25/state.yaml`
- `docs/goals/flows-clean-architecture-2026-05-25/notes/t059-draft-step-id-preflight.md`

Expected output:

- Concept inventory table:

| Concept | Current locations | Behavior differences | Canonical owner | Merge/delete path |
|---|---|---|---|---|

  Keep the inventory capped to one row per file the first Worker will touch unless
  extra rows are needed to prove a stop rule.

- Source evidence for the first Worker spine: backend API request shape, repository
  sync, secret merge, directly coupled tests, and any persisted data preflight needed
  before implementation.
- Bounded read-only notes on materialization, frontend editor state, and generated
  client type usage only where required to decide whether the first Worker can stay
  backend-only. Otherwise defer them explicitly to later Workers.
- Explicit first Worker recommendation with allowed files, red tests, verification
  commands, stop rules, consolidation effect, and naming-gate answers.
- Decision on whether the first Worker can be backend-only, backend plus generated
  client, or must include frontend state changes.
- Required red test target: reorder two existing steps that use stored secret
  sentinels and assert the stored encrypted values remain attached to the same
  persisted step identity, not the same `step_order`.
- Naming/API-shape decision: evaluate whether the update path should reuse
  `FlowStepCreateRequest` with `id: UUID | None` or split a draft-update-specific
  request schema. Reject vague generic names and explain how the chosen name would
  appear in `docs/flows/architecture.md` and the where-to-change-X table.
- State-board invariant: verify no task has `receipt.result == done` while
  `status != done`, so the T055-style drift does not return.
- State-board enforcement recommendation: propose where that invariant should live
  longer term, for example in a local board validator or watchdog check.

Stop if:

- Implementation is required to answer the Scout questions.
- The first Worker requires product decisions for retention or service-key identity.
- Persisted data or frontend caller evidence is insufficient to choose id semantics.
- The clean path requires schema migration or OpenAPI/generated-client changes before
  a Judge approves exact scope.
- The plan would add a parallel step identity path instead of deepening the
  canonical Flow authoring/API/repository owners.

## Consolidation Effect

- Reused existing owner: no source owner changed in this Judge; T059 must identify
  the draft authoring and repository owners before any Worker.
- Logic moved from: none.
- Logic deleted: stale board statuses for T055 and T013 will be normalized in state.
- Duplicate path removed: none yet.
- New code added: none.
- Why existing owners were insufficient: existing source owners may be sufficient,
  but T059 must prove the first safe move along the request -> repository -> secret
  merge spine before implementation.
- Guard/test preventing duplicate logic from returning: to be defined by T059.
- Net Flow logic surface area: preserved.
- If increased, why the increase is necessary: not applicable.

## Naming Gate

- New production names: none.
- Proposed task names use the architecture axis explicitly: draft step id-owned
  persistence, not generic "step cleanup".
- T059 should reject vague new identity names such as `step_handle`, `step_ref`, or
  `step_key`; prefer the existing domain name `FlowStep.id` or a draft-update schema
  name that describes the authoring axis.
- T059 should preserve enough ownership evidence for the future
  `docs/flows/architecture.md` Draft Flow / Published Flow Version / Run map and
  where-to-change-X table.

## Peer Review

Claude:

- Iteration 1: `GREEN_LIGHT: yes`, `MIN_SCORE: 8`; valid scope tightenings.
- Iteration 2: `GREEN_LIGHT: yes`, `MIN_SCORE: 8`; valid P3 refinements.
- Final iteration: `GREEN_LIGHT: yes`, `MIN_SCORE: 9`.
- Artifacts:
  - `.codex/artifacts/claude-peer-loop-t058-next-safe-flow-task-judge-20260526T155418Z.md`
  - `.codex/artifacts/claude-peer-loop-t058-next-safe-flow-task-judge-revised-20260526T155702Z.md`
  - `.codex/artifacts/claude-peer-loop-t058-next-safe-flow-task-judge-final-20260526T155838Z.md`

Antigravity: skipped by rule; Claude was green and no high-risk disputed
architecture decision remained.
