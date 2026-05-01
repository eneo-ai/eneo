# Retrospective 8 - Flow Step Mutation Commands

## A. Plan adherence

- [x] pass - Ran `/plan` first, accepted Claude's plan findings, revised the
  plan, and got green before implementation.
- [x] pass - Kept scope limited to `FlowEditor` step replacement/removal
  commands, route call-site replacement, behavior tests, and Batch 7 docs.
- [x] pass - No backend/runtime/schema/package/namespace work was started.
- [x] pass - Did not touch unrelated dirty files.

## B. Acceptance criteria

- [x] pass - PRD-006 frontend state-owner direction is improved: the route no
  longer owns direct step-array replacement or removal writes.
- [x] pass - `FlowEditor` is the canonical owner for step replacement,
  deletion, safe remapping delegation, and active-step fallback.
- [x] pass - The in-place route renumbering bug was removed by cloning
  surviving steps before assigning new `step_order` values.

## C. Behavior pins and validation

- [x] pass - Extended `FlowEditor.test.ts` for step replacement, invalid
  replacement indexes, removal, last-step fallback, only-step clearing, invalid
  removal indexes, and remap failure propagation.
- [x] pass - Ran focused `FlowEditor` tests and previous Batch 7 smoke tests.
- [x] pass - Ran touched-file Prettier/ESLint, `git diff --check`,
  anti-slippage grep, positive disappearance grep, and broader `.steps =`
  assignment guard.
- [x] pass - Broad `cd frontend/apps/web && bun run check` still fails only
  with known baseline categories; no touched-file diagnostic appeared.

## D. Pre-production deletion discipline

- [x] n/a - No backend Tier A/Tier B deletion was in scope.
- [x] pass - Replaced route direct writes without adding compatibility
  wrappers.
- [x] pass - Did not add `any`, `as any`, `@ts-ignore`, or `@ts-expect-error`.

## E. Single source of truth

- [x] pass - `FlowEditor` now owns step replacement and removal mutations.
- [x] pass - The route now translates component events and delegates mutations
  instead of manipulating the editor store directly.
- [x] partial - The external `state.update` store remains writable, so the
  boundary is improved but not mechanically enforced.

## F. File splits and naming

- [x] pass - No new files or generic helpers were created.
- [x] pass - Command names describe concrete Flow authoring actions.
- [x] pass - No interface, controller, manager, store, or compatibility shim was
  introduced.

## G. Comments and readability

- [x] pass - Added no production comments.
- [x] pass - The route step handlers are shorter and no longer know step-array
  write details.
- [x] pass - The clone-before-renumber decision is documented in the plan and
  journal rather than as a restating source comment.

## H. Test quality

- [x] pass - Tests assert behavior through the public `FlowEditor` object.
- [x] pass - Tests protect user-visible editor behavior and remap failure
  propagation, not private helper calls.
- [x] pass - No snapshot tests or mock-call-only tests were added.

## I. Boundary discipline

- [x] pass - UI event handlers remain in the route and domain-specific mutation
  rules moved to `FlowEditor`.
- [x] pass - Existing assistant-remap behavior remains in
  `applyStepsWithSafeOrderRemap(...)`; no duplicate remapping logic was added.

## J. Scope and risk

- [x] pass - Touched only Flow frontend authoring files and Batch 7 docs.
- [x] pass - Documented remaining writable-store and assistant-remap
  transactional carry-forward risks.
- [x] pass - Batch 8 step rerun has not started.

## Final gate

YELLOW - 0 fails, 1 partial carry-forward for structural writable-store
enforcement.
