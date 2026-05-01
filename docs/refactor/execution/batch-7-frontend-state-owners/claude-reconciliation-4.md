# Claude Reconciliation 4 - Flow Run Launch Input State Owner

## Plan Review

Claude first returned `VERDICT: changes_required`, `GREEN_LIGHT: no`, and
`MIN_SCORE: 7`.

Accepted findings and actions:

| Finding | Decision | Action |
|---|---|---|
| The proposed Svelte owner included too many pure helpers. | Accepted. | Moved pure field readers, required checks, reuse computation, review values, and payload construction into `flowRunContract.ts`; kept `FlowRunLaunchInputState` limited to mutable form/freeform values. |
| Duplicate reset wrappers would repeat a weak pattern. | Accepted. | Added and implemented one public `reset()` method only. |
| Function-prop threading into the form was fragile. | Accepted. | Passed `launchInputState` directly into `FlowRunDialogForm.svelte` and imported pure field readers there. |
| The slice needed a measurable value gate. | Accepted. | Added an 80 LOC reduction target for `FlowRunDialog.svelte`; implementation reduced it from 1513 LOC to 1430 LOC. |
| Edge cases around reuse and payload construction needed pins. | Accepted. | Added `flowRunContract.test.ts` coverage for multiselect arrays/strings/nulls, missing keys, stale keys, freeform `text` precedence, and number conversion. |

Claude resumed on the revised plan and returned `VERDICT: green`,
`GREEN_LIGHT: yes`, and `MIN_SCORE: 8`.

## Implementation Review

Claude implementation review returned `VERDICT: green`, `GREEN_LIGHT: yes`,
and `MIN_SCORE: 8`.

Accepted low-cost findings and actions:

| Finding | Decision | Action |
|---|---|---|
| Comma-string multiselect required-field behavior changed from the old inconsistent check and should be explicit. | Accepted. | Added `comma_roles: "admin, editor"` to the required-field test and asserted it is not missing. |
| `formValuesSnapshot` and `applyReusedInput` should protect array values from caller mutation. | Accepted. | Added `copyFormValues`, used it for snapshots and apply, and added tests for returned-array and input-array mutation isolation. |
| `FlowRunDialogForm.svelte` should not rebuild the form-values snapshot at every control read. | Accepted. | Added one `currentFormValues = $derived(launchInputState.formValuesSnapshot)` read and reused it in the form. |

Final Claude verification returned `VERDICT: green`, `GREEN_LIGHT: yes`,
and `MIN_SCORE: 8`.

## Deferred Findings

| Finding | Reason deferred |
|---|---|
| Rename `FlowRunDialogReview` prop `inputText` to `freeformText`. | Review component prop rename is a small follow-up outside this state-owner slice's planned file scope. |
| Normalize naming convention for helper functions in `flowRunContract.ts`. | Cosmetic consistency cleanup; no correctness or ownership risk for this slice. |
| Avoid per-option `readFlowRunFieldMultiValue` calls with a local Svelte `{@const}`. | Micro-optimization only; current code is behaviorally correct and green-lit. |

## Result

Proceed. The slice improves ownership without creating a parallel state path:

- `FlowRunLaunchInputState` owns mutable form/freeform values.
- `flowRunContract.ts` owns pure run-input derivation.
- `FlowRunDialogForm.svelte` renders and invokes the state owner's command.
- `FlowRunDialog.svelte` remains the side-effect adapter.
