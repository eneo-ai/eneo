# Enterprise Skills rollout

## Objective

Deliver the agreed Enterprise Skills roadmap as a sequence of reviewable,
behavior-tested pull requests, with explicit administration, permission,
runtime selection, provenance, and context-budget behavior.

## Goal Kind

`specific`

## Current Tranche

Finish Task #553 in bounded dormant-to-visible slices, close execution-block
integrity, consolidate typed lifecycle conflicts, and then deliver the explicit
organisation revision-rollout operation for Assistants, Personal Chat, and
Apps. O2 editable Space copies follow. S2 still waits for the Flow package
vertical to land on `develop`, and external Marketplace distribution remains
last.

Each implementation merge requires proportionate local verification, green
required CI, a clean fresh `/review`, the applicable peer gate, and a final PM
audit. Fable is planning-only for genuinely large or disputed direction
changes; it is not a routine implementation or merge gate.

## Non-Negotiable Constraints

- Follow `docs/enterprise-skills-roadmap.md`, the ADR, and the current Goal
  Maker board.
- Keep one canonical owner for each lifecycle, permission, runtime, and UI
  concept; delete superseded paths instead of retaining compatibility branches.
- Organisation Skill lifecycle management is admin-only. `Manage Skills`
  remains local Space authoring; `Use Skills` remains catalogue consumption.
- Non-admin builders with `Use Skills` can preview the exact published revision
  before attaching it to an Assistant or App.
- Runtime execution remains separate from authoring permission and records the
  exact Skill revision used.
- Prefer behavior tests at stable service, API, and user-flow interfaces.
- Do not merge on stale review evidence, red/unknown required checks, or an
  unresolved applicable peer gate.
- Do not mix unrelated user-owned worktree changes into roadmap commits.

## Stop Rule

Stop only when the full accepted roadmap has passed its final audit, all safe
local work is blocked, or continuing requires product authority or credentials
that the board cannot infer. Do not stop merely because a PR review or CI run is
pending when safe preparation for the next dependency is available.

## Canonical Board

Machine truth lives at:

`docs/goals/enterprise-skills-rollout/state.yaml`

If this charter and `state.yaml` disagree, `state.yaml` wins for task status,
active task, receipts, verification freshness, and completion truth.

## Run Command

```text
/goal Follow docs/goals/enterprise-skills-rollout/goal.md through the first safe verified implementation slice. Do not stop after planning unless blocked.
```

## PM Loop

1. Read this charter, the board, and the accepted roadmap.
2. Work only inside the active task's scope.
3. Record compact receipts with exact revisions and validation commands.
4. Prepare the next dependency while external checks run, but do not publish it
   against a base that has not been merged.
5. Merge only after CI, a fresh `/review`, the applicable peer gate, and PM
   audit are all green.
6. Activate the next task immediately unless a stop condition applies.
