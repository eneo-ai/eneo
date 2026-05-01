# Claude Reconciliation 8 - Flow Step Mutation Commands

## Plan Review

Claude first returned `VERDICT: changes_required`, `GREEN_LIGHT: no`, and
`MIN_SCORE: 6`.

Accepted findings and actions:

| Finding | Decision | Action |
|---|---|---|
| Invalid index behavior was underspecified. | Accepted. | Defined valid indexes as finite integers in `[0, steps.length)` and required invalid calls to no-op. |
| Failure propagation and active-step timing were unclear. | Accepted. | Required `removeStepAtIndex(...)` to propagate remap failures and update `activeStepId` only after remap succeeds. |
| Route removal had an in-place renumbering aliasing risk. | Accepted. | Required clone-before-renumber behavior before delegating to `applyStepsWithSafeOrderRemap(...)`. |
| Tests needed last-step, only-step, invalid-index, and failure-path coverage. | Accepted. | Added all four categories to the implementation checklist. |
| Positive disappearance checks were too narrow. | Accepted. | Added direct `$update.steps` disappearance and broader `.steps =` assignment guards. |

Plan verification returned `VERDICT: green`, `GREEN_LIGHT: yes`, and
`MIN_SCORE: 8`.

## Implementation Review

Claude implementation review returned `VERDICT: green`, `GREEN_LIGHT: yes`, and
`MIN_SCORE: 8`.

Verified outcomes:

| Outcome | Evidence |
|---|---|
| Route step-array writers were removed. | Disappearance grep over `frontend/apps/web/src` returned no `$update.steps[...] =` or `$update.steps =` matches. |
| `FlowEditor` owns replacement/removal commands. | `replaceStepAtIndex(...)` and `removeStepAtIndex(...)` live on the exported `FlowEditor` object. |
| Clone-before-renumber behavior landed. | `removeStepAtIndex(...)` maps surviving steps into new objects before assigning new `step_order` values. |
| Behavior pins cover the command boundary. | `FlowEditor.test.ts` covers replacement, invalid indexes, removal fallback behavior, and failure propagation. |
| No scope expansion occurred. | No backend, generated schema, package rename, namespace migration, or Batch 8 runtime work was touched. |

## Deferred Findings

| Finding | Reason deferred |
|---|---|
| `Math.min(index, nextSteps.length - 1)` is dense. | It is covered by next-step, previous-step, and only-step tests; extracting a helper would add indirection without changing ownership. |
| Assistant prompt remap failure can leave steps changed before assistant save failure. | This is inherited `applyStepsWithSafeOrderRemap(...)` behavior; fixing it requires a separate transactional design, not a route ownership cleanup. |
| `FlowEditor.state.update` remains externally writable. | This slice removed the known route step writers. Enforcing a narrower store surface needs its own plan and broader call-site audit. |

## Result

Proceed. The slice closes the remaining known route-owned step mutation path
without adding another state layer:

- `FlowEditor` owns indexed step replacement and removal.
- route callbacks translate UI events and delegate mutation behavior.
- removal avoids in-place renumbering of store-owned step objects.
- tests pin invalid indexes, active-step fallback, order preservation, and
  failure propagation.
