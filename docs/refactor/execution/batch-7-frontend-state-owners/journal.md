# Batch 7 - Frontend State Owners Journal

## Iteration 1 - AI Builder Driver/Service Mirroring

### Start Gate

- Started from commit `351e3592 flows: align ai builder protocol with generated types`.
- Branch state before planning:
  - `frontend/packages/ui/src/icons/types.d.ts` dirty, unrelated and untouched
  - `scripts/run_codex_review.sh` dirty, unrelated and untouched
  - `PRODUCT.md` untracked, unrelated and untouched
  - no staged files
- Scope limited to AI Builder Driver/Service mirrored mutable state.
- Backend source/tests, migrations, generated schemas, package naming, Flow
  authoring, run-launch, evidence/status state, and `intric.*` namespace
  migration were not in scope.

### Plan Evidence

- `FlowAIBuilderDriver.ts:45-59` defines the canonical `FlowAIBuilderState`.
- `FlowAIBuilderDriver.ts:96-990` owns all state mutation and AI Builder
  orchestration behavior.
- `FlowAIBuilderService.svelte.ts:30-43` mirrors every state field as separate
  `$state` fields.
- `FlowAIBuilderService.svelte.ts:266-280` copies every Driver state field into
  the Service mirrors.
- `FlowAIBuilderService.svelte.ts:132-140` duplicates Driver's recoverable draft
  filtering from `FlowAIBuilderDriver.ts:235-243`.

### Planned Direction

- Driver remains the single mutable state owner.
- Service remains the Svelte context facade but uses one reactive invalidation
  token to expose `driver.state` through getters.
- Per-field mirrored Service state and `#applyState` are deleted.
- New Service tests will pin facade reactivity through public getters and Driver
  commands/seed state rather than asserting private helper calls.

### Claude Plan Review

- Claude peer-loop plan review returned body result `VERDICT: green`,
  `GREEN_LIGHT: yes`, and `MIN_SCORE: 7`.
- Artifact:
  `.codex/artifacts/claude-peer-loop-batch-7-ai-builder-driver-service-state-owner-plan-20260430T224136Z.md`.
- Claude confirmed the invalidation-token design is not a mutable domain-state
  mirror if Driver remains the only owner of `FlowAIBuilderState`.
- Accepted guardrails folded into `plan.md` before implementation:
  - every Service getter/derived path must read Driver state through the
    private `#state` accessor, never `this.#driver.state` directly
  - add one short comment near the invalidation token/accessor explaining the
    Svelte tracking invariant
  - add concrete Service tests proving derived values update after Driver-owned
    state changes
  - record Service deletion or a Svelte-aware Driver as later possible end
    states, not this slice

### Implementation Result

- `FlowAIBuilderService` no longer mirrors each Driver state field as separate
  `$state` values.
- Driver remains the single mutable owner of `FlowAIBuilderState`.
- Service now keeps one Svelte invalidation token and exposes Driver state
  through a private `#state` accessor.
- All public getters and derived values read through the `#state` accessor.
- `recoverableCreateDrafts` delegates filtering to Driver instead of
  reimplementing the filter in Service.
- Added `FlowAIBuilderService.test.ts` to pin Service facade reactivity,
  recoverable draft filtering, and phase derivation through public Service
  APIs.
- After Claude verification, added one field-getter smoke test and normalized
  the two getter return types that temporarily used indexed access syntax.

### Validation

Passed:

- `cd frontend/apps/web && bun run test:unit -- src/lib/features/flows/ai-builder/FlowAIBuilderService.test.ts`
  - 1 file, 4 tests passed after the Claude-suggested getter smoke test.
- `cd frontend/apps/web && bun run test:unit -- src/lib/features/flows/ai-builder/FlowAIBuilderService.test.ts src/lib/features/flows/ai-builder/FlowAIBuilderDriver.test.ts src/lib/features/flows/ai-builder/flowAIBuilderReset.test.ts src/lib/features/flows/ai-builder/flowAIBuilderTokenUsage.test.ts`
  - 4 files, 41 tests passed.
- `cd frontend/apps/web && bunx prettier --check src/lib/features/flows/ai-builder/FlowAIBuilderService.svelte.ts src/lib/features/flows/ai-builder/FlowAIBuilderService.test.ts`
- `cd frontend/apps/web && bunx eslint src/lib/features/flows/ai-builder/FlowAIBuilderService.svelte.ts src/lib/features/flows/ai-builder/FlowAIBuilderService.test.ts`
- `git diff --check -- frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderService.svelte.ts frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderService.test.ts docs/refactor/execution/batch-7-frontend-state-owners`
- Anti-slippage grep over Flow AI Builder frontend, PRDs, and the AI Builder
  prompt contract returned no matches.
- Direct Service mirror guard returned only the intended private accessor read:
  `return this.#driver.state`.

Baseline/environment failures recorded:

- `cd frontend/apps/web && bun run test:unit -- src/lib/features/flows/ai-builder`
  failed after six non-jsdom AI Builder test files passed. The failing files
  were `FlowAIBuilderDriver.test.ts` and `FlowAIBuilderService.test.ts` because
  Paraglide compilation failed to remove
  `src/lib/paraglide/messages` during a concurrent validation run and the
  Vitest environment still lacks `jsdom`.
- `cd frontend/apps/web && bun run check` failed with broad existing frontend
  issues, including Paraglide module resolution, missing generated runtime
  declarations, existing `frontend/packages/intric-js` endpoint type drift, and
  unrelated route/component diagnostics. The touched Service files did not add
  a new focused lint or test failure.

### Carry-Forward

- Broad `apps/web` check remains noisy and should be separated from Flow AI
  Builder product regressions before relying on it as the only frontend gate.
- `jsdom` remains unavailable for Vitest component tests in this workspace.
- Service deletion or making Driver itself Svelte-aware remains a later
  frontend-state-owner decision, not part of this slice.
- A grep or lint guard that bans direct `this.#driver.state` reads outside the
  private `#state` accessor would make this facade pattern harder to regress if
  it survives more frontend state-owner slices.

### Claude Verification

- First verification returned `VERDICT: green`, `GREEN_LIGHT: yes`,
  `MIN_SCORE: 7`, with two accepted low-cost improvements.
- After those improvements, final verification returned `VERDICT: green`,
  `GREEN_LIGHT: yes`, `MIN_SCORE: 7`.
- Final artifact:
  `.codex/artifacts/claude-peer-loop-batch-7-ai-builder-service-state-owner-final-verification-20260430T225433Z.md`.

## Iteration 2 - AI Builder Plan Visibility Latch

### Start Gate

- Started from commit `90e688a9 flows: remove ai builder service state mirror`.
- Branch state before planning:
  - `frontend/packages/ui/src/icons/types.d.ts` dirty, unrelated and untouched
  - `scripts/run_codex_review.sh` dirty, unrelated and untouched
  - `PRODUCT.md` untracked, unrelated and untouched
  - no staged files
- Scope limited to duplicated Flow AI Builder component state readers around the
  Service/Driver boundary.
- Backend source/tests, migrations, Celery/runtime behavior, data model changes,
  generated schemas, package naming, broad UI redesign, and `intric.*`
  namespace migration were not in scope.

### Plan Evidence

- `FlowAIBuilder.svelte:26-43` owns a `hadPlanBefore` latch used only to keep
  plan content visible while a re-plan stream temporarily clears
  `currentPlan`.
- `FlowAIBuilderChat.svelte:52-59` owns a second `hadPlanBefore` latch to
  choose "updating plan" vs "generating" copy.
- `FlowAIBuilderPlanPane.svelte:96-104` owns a third `hadPlanBefore` latch to
  choose the same progress copy.
- `FlowAIBuilderService.svelte.ts` is now the single facade over Driver-owned
  AI Builder state and is the right owner for a cross-component UI workflow
  latch.

### Planned Direction

- Add a Service-owned `hasSeenPlanInSession` latch updated at the existing
  Driver notification boundary.
- Keep the root shell's `hasPlanContent` aggregate local because it has only
  one consumer.
- Delete the three component-local `hadPlanBefore` latches.
- Keep translations, layout, input focus state, draft auto-resume, and
  approve/apply in-flight state in their current components for this slice.

### Claude Plan Review

- Claude plan review returned `VERDICT: changes_required`, `GREEN_LIGHT: no`,
  `MIN_SCORE: 7`.
- Accepted findings:
  - `hasPlanContent` should stay local to `FlowAIBuilder.svelte`; only the
    duplicated latch should move to Service.
  - latch update precedence must be explicit: session-null reset wins before
    current-plan set.
  - `#syncViewState` was too generic; use `#updatePlanSeenLatch`.
  - add a precedence behavior pin for `currentPlan !== null` with
    `session === null`.
  - document the `jsdom` component-test caveat in the plan.
- Plan updated before source/test implementation.
- Claude resumed on the revised plan and returned `VERDICT: green`,
  `GREEN_LIGHT: yes`, `MIN_SCORE: 8`.
- Low-severity precision requests were accepted into the plan:
  - write the Driver listener closure explicitly and pass the callback `state`
    into `#updatePlanSeenLatch`
  - keep `#updatePlanSeenLatch` from reading `this.#driver.state` or
    `this.#state`
  - document `hasSeenPlanInSession` as a read-only boolean getter with no
    setter
  - name the streaming behavior pin around Service primitive inputs rather than
    a nonexistent Service `hasPlanContent` aggregate

### Implementation Result

- `FlowAIBuilderService` now owns a single `hasSeenPlanInSession` UI workflow
  latch.
- The latch updates at the existing Driver notification boundary and receives
  the Driver callback state directly.
- Session-null reset wins before the current-plan set path, so an impossible
  `session === null` plus `currentPlan !== null` state clears the latch instead
  of resurrecting a stale plan.
- `FlowAIBuilder.svelte` keeps the root-only `hasPlanContent` aggregate local
  and now reads `service.hasSeenPlanInSession` for the transient re-plan stream
  case.
- `FlowAIBuilderChat.svelte` and `FlowAIBuilderPlanPane.svelte` now read
  `service.hasSeenPlanInSession` for generating/updating copy.
- The three component-local `hadPlanBefore` latches were deleted.
- `FlowAIBuilderService.test.ts` fixture shapes were synchronized to the
  current generated-backed protocol types for `ApplyError`, `ApplyResult`, and
  `AIBuilderModel`; this was necessary for touched-file validation and was not
  a product behavior change.
- The unrelated dirty files stayed untouched:
  `frontend/packages/ui/src/icons/types.d.ts`, `scripts/run_codex_review.sh`,
  and `PRODUCT.md`.

### Validation

Passed:

- `cd frontend/apps/web && bun run test:unit -- src/lib/features/flows/ai-builder/FlowAIBuilderService.test.ts`
  - 1 file, 6 tests passed.
- `cd frontend/apps/web && bun run test:unit -- src/lib/features/flows/ai-builder/FlowAIBuilderService.test.ts src/lib/features/flows/ai-builder/FlowAIBuilderDriver.test.ts src/lib/features/flows/ai-builder/flowAIBuilderReset.test.ts src/lib/features/flows/ai-builder/flowAIBuilderTokenUsage.test.ts`
  - 4 files, 43 tests passed.
- `cd frontend/apps/web && bunx prettier --check src/lib/features/flows/ai-builder/FlowAIBuilderService.svelte.ts src/lib/features/flows/ai-builder/FlowAIBuilderService.test.ts src/lib/features/flows/ai-builder/FlowAIBuilder.svelte src/lib/features/flows/ai-builder/FlowAIBuilderChat.svelte src/lib/features/flows/ai-builder/FlowAIBuilderPlanPane.svelte`
- `cd frontend/apps/web && bunx eslint src/lib/features/flows/ai-builder/FlowAIBuilderService.svelte.ts src/lib/features/flows/ai-builder/FlowAIBuilderService.test.ts src/lib/features/flows/ai-builder/FlowAIBuilder.svelte src/lib/features/flows/ai-builder/FlowAIBuilderChat.svelte src/lib/features/flows/ai-builder/FlowAIBuilderPlanPane.svelte`
- `git diff --check -- frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderService.svelte.ts frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderService.test.ts frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilder.svelte frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderChat.svelte frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderPlanPane.svelte docs/refactor/execution/batch-7-frontend-state-owners`
- Anti-slippage grep over Flow AI Builder frontend, PRDs, and the AI Builder
  prompt contract returned no matches.
- `rg -n "hadPlanBefore" frontend/apps/web/src/lib/features/flows/ai-builder`
  returned no matches.
- Direct Service state-read guard showed the only direct `this.#driver.state`
  read remains the private `#state` accessor.

Baseline/environment failures recorded:

- `cd frontend/apps/web && bun run test:unit -- src/lib/features/flows/ai-builder/FlowAIBuilder.test.ts`
  failed before collecting tests because the Vitest component environment still
  cannot resolve `jsdom`.
- `cd frontend/apps/web && bun run check` failed with 43 errors and 7 warnings
  in 14 files. The remaining diagnostics are the known broad frontend baseline
  categories in `frontend/packages/intric-js` endpoint typing,
  spaces/chat/dashboard/flows route typing, and existing AI Builder harness
  Svelte warnings. The touched Service test fixture type errors that surfaced
  during the first broad check were fixed before this journal entry.

### Claude Verification

- Final verification returned `VERDICT: green`, `GREEN_LIGHT: yes`,
  `MIN_SCORE: 8`.
- Accepted low-severity findings:
  - add one short invariant comment at the canonical latch owner so future
    readers do not simplify away the transient re-plan behavior
  - make the reset-and-new-session lifecycle explicit in the Service test
  - record the test fixture protocol synchronization as non-behavioral
    validation cleanup
- Deferred low-severity stylistic finding: replacing
  `hasSeenPlanInSession = $derived(...)` with a getter is reasonable but not
  required for this slice and would not change the ownership boundary.

### Carry-Forward

- Broad `apps/web` check remains too noisy to act as the sole product gate for
  small Flow AI Builder frontend slices.
- `jsdom` remains unavailable for component tests in this workspace.
- Draft auto-resume, pending edit context, approve/apply in-flight flags, and
  input attachment state remain component-owned pending separate small slices.
- If the Service-owned latch pattern survives more frontend state-owner work,
  consider adding a static guard that bans direct Driver state reads outside the
  private `#state` accessor.

## Iteration 3 - Flow Run File Input State Owner

### Start Gate

- Started from commit `6a35d3da flows: harden audio recording sessions`.
- Branch state before planning:
  - `frontend/packages/ui/src/icons/types.d.ts` dirty, unrelated and untouched
  - `scripts/run_codex_review.sh` dirty, unrelated and untouched
  - `PRODUCT.md` untracked, unrelated and untouched
  - no staged files
- Scope limited to Flow run launch runtime file input state inside
  `FlowRunDialog.svelte`.
- Backend runtime, migrations, Celery, data model, generated schemas, package
  naming, Flow authoring, evidence/status state, and Batch 8 rerun work were
  not in scope.

### Plan Evidence

- `FlowRunDialog.svelte` was 1663 LOC before this slice and owned runtime file
  maps, upload flags, local recorded files, drag state, resume prompt state, and
  recording session phase state directly.
- `flowRunRecordingSession.ts` already owned segment filename composition,
  IndexedDB persistence, recoverable-session scanning, session purge/detach
  helpers, and pure `RecordingSessionState` transitions.
- `RecordingSession` already owned the per-step recorder lifecycle and retry
  state machine.
- The planned owner boundary therefore became: move mutable runtime file input
  view state into a Svelte state owner while keeping API calls, toasts, recorder
  refs, `RecordingSession` objects, and IndexedDB helpers outside it.

### Claude Plan Review

- First Claude review returned `VERDICT: changes_required`,
  `GREEN_LIGHT: no`, `MIN_SCORE: 6`.
- Accepted findings:
  - the initial method list was too close to a per-field setter bag
  - the plan needed separate reset call sites for dialog close and accepted run
  - tests needed multi-field invariants, not mostly single-field setter checks
  - instantiation lifecycle and helper reuse needed to be explicit
- Revised plan replaced field setters with domain operations such as
  `beginStepUpload`, `removeUploadedFile`, `prepareRecordedSegment`,
  `discardStepRecording`, `attachRecoveredSession`, and separate reset methods.
- Second review still returned `changes_required`, with specification-level
  gaps around read-surface getters and `SessionState` mapping ownership.
- Final plan verification returned `VERDICT: green`, `GREEN_LIGHT: yes`,
  `MIN_SCORE: 7`.
- Final artifact:
  `.codex/artifacts/claude-peer-loop-flow-run-file-input-state-owner-plan-verification-2-20260501T091802Z.md`.

### Implementation Result

- Added `FlowRunFileInputState.svelte.ts` as the canonical mutable owner for
  runtime file input state: uploaded files, preserved recorded files, recorder
  reset tokens, upload/recording notices, skipped messages, upload/recording
  active steps, drag hover, recoverable-session view state, and session phase.
- `FlowRunDialog.svelte` now reads file-input state through snapshots and
  per-step getters and mutates it through domain operations.
- `FlowRunDialog.svelte` still owns side effects and browser boundaries:
  `intric` API calls, toasts, DOM file picker creation, recorder refs, and live
  `RecordingSession` object lifecycle.
- `flowRunRecordingSession.ts` remains the persistence/resume helper owner; the
  new state class reuses its pure transition helpers instead of duplicating
  them.
- The accepted-run path now reads the session-id snapshot, purges persisted
  sessions, then calls `resetAfterRunAccepted()`.
- `FlowRunDialog.svelte` decreased from 1663 LOC to 1513 LOC, meeting the
  planned 150-line reduction gate exactly.

### Validation

Passed:

- `cd frontend/apps/web && bun run test:unit -- src/lib/features/flows/components/FlowRunFileInputState.test.ts src/lib/features/audio/flowRunRecordingSession.test.ts src/lib/features/audio/recordingSession.test.ts src/lib/features/flows/flowRunWizard.test.ts`
  - 4 files, 53 tests passed.
- `cd frontend/apps/web && bun run test:unit -- src/lib/features/audio`
  - 6 files, 54 tests passed.
- `cd frontend/apps/web && bunx prettier --check src/lib/features/flows/components/FlowRunDialog.svelte src/lib/features/flows/components/FlowRunFileInputState.svelte.ts src/lib/features/flows/components/FlowRunFileInputState.test.ts`
- `cd frontend/apps/web && bunx eslint src/lib/features/flows/components/FlowRunDialog.svelte src/lib/features/flows/components/FlowRunFileInputState.svelte.ts src/lib/features/flows/components/FlowRunFileInputState.test.ts`
- `git diff --check -- frontend/apps/web/src/lib/features/flows/components/FlowRunDialog.svelte frontend/apps/web/src/lib/features/flows/components/FlowRunFileInputState.svelte.ts frontend/apps/web/src/lib/features/flows/components/FlowRunFileInputState.test.ts docs/refactor/execution/batch-7-frontend-state-owners`
- Touched-file anti-slippage grep returned no matches.
- `wc -l` confirmed `FlowRunDialog.svelte` at 1513 LOC and
  `FlowRunFileInputState.svelte.ts` at 331 LOC.

Baseline/existing failures recorded:

- Broad `cd frontend/apps/web && bun run check` still fails with the known
  baseline categories in `frontend/packages/intric-js`, spaces/chat/dashboard
  route typing, Flow route links, and AI Builder harness Svelte warnings. No
  touched `FlowRunDialog` or `FlowRunFileInputState` diagnostic appeared.
- Broad anti-slippage grep over all Flow component files still finds existing
  `as any` usage in HTTP config helpers/tests outside this slice. The same grep
  over touched files returned no matches.

### Carry-Forward

- `FlowRunDialog.svelte` still owns broader run-launch workflow state:
  form values, freeform text, current page, contract loading, idempotency, and
  submit orchestration.
- `FlowRunFileInputState` deliberately aggregates transient file-input state
  and recoverable recording-session view state. If future resume work grows, a
  separate recording-session view owner may become worthwhile.
- Broad frontend check remains too noisy to use as the sole gate for small
  frontend slices until the existing generated-client and route typing baseline
  is resolved.
- Batch 8 step rerun has not started.

## Iteration 4 - Flow Run Launch Input State Owner

### Start Gate

- Started from commit `16f92c19 flows: centralize run file input state`.
- Branch state before planning:
  - `frontend/packages/ui/src/icons/types.d.ts` dirty, unrelated and untouched
  - `scripts/run_codex_review.sh` dirty, unrelated and untouched
  - `PRODUCT.md` untracked, unrelated and untouched
  - no staged files
- Scope limited to Flow run launch form/freeform input state inside
  `FlowRunDialog.svelte`.
- Backend runtime, migrations, Celery, data model, generated schemas, package
  naming, Flow authoring, evidence/status state, and Batch 8 rerun work were
  not in scope.

### Plan Evidence

- `FlowRunDialog.svelte` still owned freeform text, form values,
  required-field checks, last-input reuse, review field text, and input payload
  construction after the file-input owner landed.
- `FlowRunDialogForm.svelte` duplicated field value and multiselect
  normalization.
- `flowRunContract.ts` already owned pure run-contract shaping and was the
  canonical home for pure form/freeform payload helpers.

### Claude Plan Review

- First Claude review returned `VERDICT: changes_required`,
  `GREEN_LIGHT: no`, `MIN_SCORE: 7`.
- Accepted findings:
  - the initial state owner absorbed too many pure helpers
  - dual reset wrappers should not be copied from the previous file-input owner
  - closure-prop threading into `FlowRunDialogForm` was fragile
  - the slice needed an explicit LOC gate and positive disappearance greps
  - edge cases for number parsing, multiselect reuse, stale form values, and
    freeform text precedence needed to be pinned
- Revised plan moved pure helpers to `flowRunContract.ts`, kept
  `FlowRunLaunchInputState` limited to mutable values, added a single `reset()`,
  direct form owner prop, an 80 LOC gate, and positive greps.
- Claude verification returned `VERDICT: green`, `GREEN_LIGHT: yes`,
  `MIN_SCORE: 8`.
- Accepted clarifications folded into the plan before implementation:
  - `computeReusedFlowRunInput` returns full replacement values
  - `applyReusedInput` replaces state instead of merging partial patches
  - `hasDirtyInput` preserves the existing over-eager close-confirmation
    approximation
  - form receives `missingRequiredFields` from the dialog rather than
    recomputing it
  - owner and pure-helper tests have separate responsibilities

### Implementation Result

- Added `FlowRunLaunchInputState.svelte.ts` as the mutable owner for form values
  and freeform text.
- Added `FlowRunLaunchInputState.test.ts` for defaults, field/freeform writes,
  replacement semantics, dirty semantics, defensive snapshots, and reset.
- Extended `flowRunContract.ts` with pure helpers for field reading,
  multiselect reading, required-field detection, review field text, last-input
  reuse computation, and input payload construction.
- Expanded `flowRunContract.test.ts` to pin the pure helper behavior, including
  stale keys, multiselect `null`, comma-delimited multiselect strings, freeform
  `text` precedence, number conversion for `"0"` and `"-3.14"`, and
  whitespace-only number fields.
- After Claude implementation review, tightened the slice further by making
  state snapshots and applied reuse values copy array values, pinning
  comma-string multiselect required-field behavior, and reading one derived
  form-values snapshot in the form component.
- Updated `FlowRunDialog.svelte` to compose the launch input state owner,
  pure contract helpers, `FlowRunFileInputState`, and existing side effects.
- Updated `FlowRunDialogForm.svelte` to render through `launchInputState` and
  imported pure helpers instead of owning local normalization copies.
- Removed the remaining trivial file-count pass-through wrappers from the
  dialog while keeping file input ownership in `FlowRunFileInputState`.
- `FlowRunDialog.svelte` decreased from 1513 LOC to 1430 LOC, passing the
  80-line gate.

### Validation

Passed:

- `cd frontend/apps/web && bun run test:unit -- src/lib/features/flows/components/FlowRunLaunchInputState.test.ts src/lib/features/flows/components/FlowRunFileInputState.test.ts src/lib/features/flows/flowRunWizard.test.ts src/lib/features/flows/flowRunContract.test.ts`
  - 4 files, 30 tests passed.
- `cd frontend/apps/web && bun run test:unit -- src/lib/features/audio`
  - 6 files, 54 tests passed. The expected stderr from the mocked
    `purgeSession` delete failure remains part of a passing test.
- `cd frontend/apps/web && bunx prettier --check ...` over touched frontend files.
- `cd frontend/apps/web && bunx eslint ...` over touched frontend files.
- `git diff --check -- ...` over touched frontend/docs paths.
- Anti-slippage grep over touched frontend files, PRDs, and the AI Builder
  prompt contract returned no matches.
- Positive disappearance greps for old dialog/form ownership paths returned no
  matches.
- `wc -l frontend/apps/web/src/lib/features/flows/components/FlowRunDialog.svelte`
  returned `1430`.

### Claude Verification

- Implementation review returned `VERDICT: green`, `GREEN_LIGHT: yes`,
  `MIN_SCORE: 8`, with low-cost tightening findings.
- Accepted findings were fixed:
  - comma-string multiselect required-field behavior is explicitly pinned
  - snapshots and applied reuse values copy arrays defensively
  - `FlowRunDialogForm.svelte` reads a single derived form-values snapshot
- Final verification returned `VERDICT: green`, `GREEN_LIGHT: yes`,
  `MIN_SCORE: 8`.
- Final artifact:
  `.codex/artifacts/claude-peer-loop-flow-run-launch-input-state-owner-final-verification-20260501T101142Z.md`.

Baseline/existing failures recorded:

- `cd frontend/apps/web && bun run check` still fails with 43 errors and 7
  warnings in 14 files. The errors are the known broad frontend baseline
  categories in `frontend/packages/intric-js`, spaces/chat/dashboard route
  typing, Flow route path typing, and existing AI Builder harness warnings. No
  touched file diagnostic appeared.

### Carry-Forward

- `FlowRunDialog.svelte` still owns contract loading, page navigation/focus,
  submit side effects, recorder side effects, and broader run-launch
  orchestration.
- A broader run-launch session/controller may be useful later, but it should
  start with a fresh inventory and success gate rather than absorbing all
  dialog behavior at once.
- Broad frontend check remains too noisy to use as the sole gate for small
  frontend slices until the existing generated-client and route typing baseline
  is resolved.
- Batch 8 step rerun has not started.

## Iteration 5 - Flow Run Evidence Status Presentation Owner

### Start Gate

- Started from commit `7fa76637 flows: centralize run launch input state`.
- Branch state before planning:
  - `frontend/packages/ui/src/icons/types.d.ts` dirty, unrelated and untouched
  - `scripts/run_codex_review.sh` dirty, unrelated and untouched
  - `PRODUCT.md` untracked, unrelated and untouched
  - no staged files
- Scope limited to Flow frontend status/evidence presentation ownership.
- Backend runtime, migrations, Celery, data model, generated schemas, package
  naming, namespace migration, Flow authoring, and Batch 8 rerun work were not
  in scope.

### Plan Evidence

- `FlowRunEvidence.svelte` owned three status callback wrappers and passed them
  into `FlowRunEvidenceStepCard.svelte`.
- `FlowRunProgressStepCard.svelte` separately composed status label, text
  color, dot color, and running-pulse behavior inline.
- `FlowRunStatusBadge.svelte` already existed as the status visual owner used
  by the runs table.
- `FlowRunEvidence.svelte` owned `expandedInputSteps` and `toggleInputExpand`,
  but `FlowRunEvidenceStepCard.svelte` ignored the corresponding props and
  owned its own `inputOpen` state.

### Claude Plan Review

- First review returned `VERDICT: changes_required`, `GREEN_LIGHT: no`,
  `MIN_SCORE: 6`.
- Accepted findings:
  - the initial plan did not pin exact badge `showDot`/`size` behavior by call
    site
  - rendered-output pins were too thin
  - `FlowRunProgressStepCard.svelte` would have kept a second status-rendering
    path
  - the new status aggregate needed to become the canonical public API or be
    skipped
- The plan was revised to move both evidence and progress step-card status
  rendering to `FlowRunStatusBadge`, add exact per-call-site badge contracts,
  add `FlowRunStatusBadge.test.ts`, and make status primitives private after
  migration.
- Second review returned `VERDICT: changes_required`, `GREEN_LIGHT: no`,
  `MIN_SCORE: 7` because the plan would have lost the current
  running-expanded no-pulse behavior in `FlowRunProgressStepCard.svelte`.
- The plan was revised again so `FlowRunStatusView` carries `pulseDot` as typed
  data and `FlowRunStatusBadge` accepts `pulsing?: boolean`, with the progress
  card passing `pulsing={isRunning && !expanded}`.
- Final plan verification returned `VERDICT: green`, `GREEN_LIGHT: yes`,
  `MIN_SCORE: 8`.

### Implementation Result

- `flowRunStatusPresentation.ts` now exposes `getFlowRunStatusView(...)` and a
  typed `FlowRunStatusView` with `label`, `textClass`, `dotClass`, and
  `pulseDot`.
- Status color and dot helpers are now private implementation details.
- `animate-pulse` is no longer embedded in the running dot class; the pulse is
  modeled as `pulseDot`.
- `FlowRunStatusBadge.svelte` now owns status rendering for:
  - runs table rows
  - evidence toolbar
  - evidence summary
  - evidence step cards
  - progress step cards
- Evidence toolbar and summary call the badge with `showDot={false}` and
  `size="md"` to preserve their text-only status treatment.
- Evidence and progress step cards call the badge with `size="xs"` to preserve
  compact step-header status typography.
- `FlowRunProgressStepCard.svelte` preserves the existing behavior where a
  running expanded step does not pulse by passing
  `pulsing={isRunning && !expanded}`.
- `FlowRunEvidence.svelte` no longer owns the unused
  `expandedInputSteps`/`toggleInputExpand` mirror.
- `FlowRunEvidenceStepCard.svelte` keeps its local `inputOpen` state, matching
  current user-visible behavior.
- Removed the restating layout comment from `FlowRunEvidenceToolbar.svelte`.

### Validation

Passed:

- `cd frontend/apps/web && bun run test:unit -- src/lib/features/flows/components/flowRunStatusLabel.test.ts src/lib/features/flows/components/flowRunStatusPresentation.test.ts src/lib/features/flows/components/FlowRunStatusBadge.test.ts`
  - 3 files, 15 tests passed.
- `cd frontend/apps/web && bun run test:unit -- src/lib/features/flows/components/FlowRunLaunchInputState.test.ts src/lib/features/flows/components/FlowRunFileInputState.test.ts src/lib/features/flows/flowRunContract.test.ts src/lib/features/flows/flowRunWizard.test.ts`
  - 4 files, 30 tests passed.
- `cd frontend/apps/web && bunx prettier --check ...` over touched frontend files.
- `cd frontend/apps/web && bunx eslint ...` over touched frontend files.
- `git diff --check -- ...` over touched frontend/docs paths.
- Anti-slippage grep over touched frontend files, PRDs, and the AI Builder
  prompt contract returned no matches.
- Positive disappearance grep over the touched evidence/progress/status files
  returned no matches for the deleted status wrappers, localized wrapper, and
  ignored evidence input-expansion mirror.

Baseline/existing failures recorded:

- The first `FlowRunStatusBadge.test.ts` attempt used `@testing-library/svelte`
  with `jsdom`, but this workspace does not currently resolve `jsdom` for that
  package. The test was rewritten to use `svelte/server` rendering, which still
  pins rendered markup and avoids a new environment dependency.
- `cd frontend/apps/web && bun run check` still fails with the known broad
  frontend baseline: generated-client issues in `frontend/packages/intric-js`,
  spaces/chat/dashboard/flows route typing, and existing AI Builder harness
  warnings. No touched-file diagnostic appeared.

### Claude Verification

- Implementation review returned `VERDICT: green`, `GREEN_LIGHT: yes`,
  `MIN_SCORE: 8`.
- Claude verified:
  - `pulsing ?? view.pulseDot` preserves default running pulses and honors
    explicit `false`
  - progress step cards preserve the old running-expanded no-pulse behavior
  - toolbar/summary keep text-only status rendering through
    `showDot={false}`
  - status primitives are private and visual rendering converges on
    `FlowRunStatusBadge`
  - evidence input-expansion dead props and parent mirror are gone
- Accepted low-cost test tightening after review:
  - non-running badge cases assert no `animate-pulse`
  - no-dot badge rendering asserts no dot-specific class
  - `class` forwarding is pinned for the progress-card `shrink-0` use case

### Carry-Forward

- `FlowRunEvidence.svelte` still owns evidence fetch/load/error state, step
  expansion, copy timer state, step attempt grouping, RAG lookup, transcription
  parsing, duration formatting, and copy/download side effects.
- Evidence view-model extraction remains possible but should start as its own
  inventory and success-gated slice.
- Flow authoring state ownership remains the main open Batch 7 area.
- Batch 8 step rerun has not started.

## Iteration 6 - Flow Metadata Authoring Commands

### Start Gate

- Started from commit `4c5bc9bc flows: centralize run status presentation`.
- Branch state before planning:
  - `frontend/packages/ui/src/icons/types.d.ts` dirty, unrelated and untouched
  - `scripts/run_codex_review.sh` dirty, unrelated and untouched
  - `PRODUCT.md` untracked, unrelated and untouched
  - no staged files
- Scope limited to Flow frontend metadata authoring around the
  `FlowEditor`/route/component boundary.
- Backend runtime, migrations, Celery, data model, generated schemas, package
  naming, namespace migration, Batch 8 rerun, and broad UI workflow redesign
  were not in scope.

### Plan Evidence

- `FlowFormSchemaEditor.svelte` wrote
  `$update.metadata_json.form_schema` directly while also owning local draft
  form field state.
- The flow route wrote wizard metadata directly through local
  `setTranscriptionEnabled(...)` and `setWizardMeta(...)` functions.
- `FlowEditor.ts` already owned Flow authoring commands for steps,
  assistant saves, safe step order remapping, and variable reference rewrites.
- `flowFormSchema.ts` already owned form-field normalization and persisted
  field shape, so it was the correct home for pure form-schema metadata
  helpers.

### Claude Plan Review

- First review returned `VERDICT: changes_required`, `GREEN_LIGHT: no`, and
  `MIN_SCORE: 6`.
- Accepted findings:
  - moving only `form_schema` writes would leave the route with a parallel
    wizard metadata writer
  - the plan needed to pin the exact `editor.state.update.update(...)`
    primitive used by the new commands
  - command-boundary tests should exercise `FlowEditor`, not only pure helpers
  - the explicit empty form schema shape needed to be pinned
  - command naming should make replacement semantics clear
- The plan was revised to add `replaceFormSchemaFields(...)`,
  `setWizardMetadata(...)`, and `setTranscriptionEnabled(...)` to
  `FlowEditor`, with route and component direct metadata writes removed.
- Plan verification returned `VERDICT: green`, `GREEN_LIGHT: yes`, and
  `MIN_SCORE: 8`.

### Implementation Result

- `FlowEditor.ts` now exposes:
  - `replaceFormSchemaFields(fields)`
  - `setWizardMetadata(patch)`
  - `setTranscriptionEnabled(enabled)`
  - `createFlowEditor(data)` for behavior tests without Svelte context
  - `getFlowWizardMetadata(metadata)` for canonical wizard metadata reads
- `initFlowEditor(data)` remains the Svelte context initializer and delegates
  to `createFlowEditor(data)`.
- `FlowFormSchemaEditor.svelte` now calls
  `flowEditor.replaceFormSchemaFields(fields)` instead of assigning
  `$update.metadata_json`.
- The flow route now calls `flowEditor.setTranscriptionEnabled(...)` and
  `flowEditor.setWizardMetadata(...)` instead of local metadata writer
  functions.
- `flowFormSchema.ts` now owns:
  - `buildFlowFormSchemaMetadata(...)`
  - `getFlowFormSchemaMetadata(...)`
  - `getFlowFormSchemaFields(...)`
- Route and component form-schema reads now use the canonical
  `flowFormSchema.ts` helpers instead of inline casts.
- `FlowEditor.test.ts` pins metadata command behavior, including invalid
  persisted wizard metadata.

### Validation

Passed:

- `cd frontend/apps/web && bun run test:unit -- src/lib/features/flows/flowFormSchema.test.ts src/lib/features/flows/FlowEditor.test.ts`
  - 2 files, 15 tests passed.
- `cd frontend/apps/web && bun run test:unit -- src/lib/features/flows/components/FlowRunLaunchInputState.test.ts src/lib/features/flows/components/FlowRunFileInputState.test.ts src/lib/features/flows/flowRunContract.test.ts src/lib/features/flows/flowRunWizard.test.ts`
  - 4 files, 30 tests passed.
- `cd frontend/apps/web && bunx prettier --check ...` over touched frontend
  files.
- `cd frontend/apps/web && bunx eslint ...` over touched frontend files.
- `git diff --check -- ...` over touched frontend/docs paths.
- Anti-slippage grep over touched frontend files, PRDs, and the AI Builder
  prompt contract returned no matches.
- Positive disappearance grep over `FlowFormSchemaEditor.svelte` and the flow
  route returned no `$update.metadata_json =` matches.

Baseline/existing failures recorded:

- `cd frontend/apps/web && bun run check` still fails with 43 errors and 7
  warnings in 14 files. The errors are the known broad frontend baseline
  categories in `frontend/packages/intric-js`, spaces/chat/dashboard route
  typing, Flow route path typing, and existing AI Builder harness warnings. No
  touched-file diagnostic appeared after the final revision.

### Claude Verification

- Implementation review returned `VERDICT: green`, `GREEN_LIGHT: yes`, and
  `MIN_SCORE: 7`.
- Accepted findings after green:
  - duplicate wizard metadata type/read shapes should be centralized
  - form-schema route reads should use a pure helper instead of an inline cast
  - invalid persisted wizard metadata should be guarded and tested
  - the dead echo implementation in the test client mock should be removed
  - municipal/case-specific test fixture vocabulary should not be cemented in
    new tests
- The implementation was updated accordingly.
- Final verification returned `VERDICT: green`, `GREEN_LIGHT: yes`, and
  `MIN_SCORE: 8`.
- Accepted final low-cost cleanup:
  - `FlowFormSchemaEditor.svelte` was updated to use
    `getFlowFormSchemaMetadata(...)` for its read path.

### Carry-Forward

- `FlowEditor.state.update` remains writable, so direct mutation is still
  possible by convention. Closing that escape hatch belongs with the planned
  step-array command slice because name/description/data-retention and step
  edits still bind through the writable store.
- Flow route step-array mutation paths remain open:
  - direct step assignments in the route
  - component callbacks that still pass raw step objects back to the route
  - name/description/data-retention two-way bindings
- `FlowFormFieldType | string` remains pre-existing weak typing in
  `flowFormSchema.ts`; tightening it should start with a persisted/legacy input
  audit.
- Empty-state form-field examples still use domain-specific copy. This is UI
  copy cleanup, not state ownership.
- Batch 8 step rerun has not started.

## Iteration 7 - Flow Basic Settings Commands

### Start Gate

- Started from commit `8f21fd50 flows: centralize flow metadata authoring`.
- Branch state before planning:
  - `frontend/packages/ui/src/icons/types.d.ts` dirty, unrelated and untouched
  - `scripts/run_codex_review.sh` dirty, unrelated and untouched
  - `PRODUCT.md` untracked, unrelated and untouched
  - no staged files
- Scope limited to Flow basic settings scalar writes in the frontend route and
  `FlowEditor`.
- Backend runtime, migrations, Celery, data model, generated schemas, package
  naming, namespace migration, Batch 8 rerun, and step-array mutation were not
  in scope.

### Plan Evidence

- The route had the only direct writers for scalar basic settings:
  - `$update.name = event.currentTarget.value`
  - `$update.description = event.currentTarget.value`
  - `$update.data_retention_days = val`
- `FlowEditor.ts` already owned the resource update store and had just become
  the owner for Flow metadata writes.
- `rg -n '\$update\.(name|description|data_retention_days)\s*=' frontend/apps/web/src`
  confirmed there were no other writers outside the route.

### Claude Plan Review

- First review returned `VERDICT: changes_required`, `GREEN_LIGHT: no`, and
  `MIN_SCORE: 6`.
- Accepted findings:
  - `setDescription(string | null)` was speculative because the route only
    produces strings
  - tests needed cross-field preservation pins rather than single-field setter
    assertions
  - the commands needed one real invariant to avoid cosmetic indirection
  - `data_retention_days` needed explicit `0`/`null`/`NaN` behavior
  - empty string behavior for name/description needed to be documented
- The plan was revised so:
  - `setDescription(description: string)` accepts only strings
  - `setDataRetentionDays(days)` normalizes non-finite values to `null`
  - tests pin preservation of neighboring fields
  - tests pin empty-string name/description acceptance
  - tests pin `0`, `null`, and `NaN` retention behavior
- Plan verification returned `VERDICT: green`, `GREEN_LIGHT: yes`, and
  `MIN_SCORE: 7`.

### Implementation Result

- `FlowEditor.ts` now exposes:
  - `setName(name)`
  - `setDescription(description)`
  - `setDataRetentionDays(days)`
- `setDataRetentionDays(...)` normalizes non-finite values to `null`, closing
  the prior route path where invalid number input could write `NaN` into the
  resource update store.
- The route basic settings inputs now call `flowEditor` commands instead of
  assigning `$update.name`, `$update.description`, or
  `$update.data_retention_days` directly.
- `FlowEditor.test.ts` now pins:
  - neighboring fields survive each scalar command
  - empty name and description strings remain valid draft values
  - `0` is distinct from `null`
  - `NaN` normalizes to `null`
  - returning to the original `null` retention value clears dirty state through
    existing `ResourceEditor` diff semantics

### Validation

Passed:

- Baseline before source edits:
  - `cd frontend/apps/web && bun run test:unit -- src/lib/features/flows/FlowEditor.test.ts`
    - 1 file, 4 tests passed.
  - `rg -n '\$update\.(name|description|data_retention_days)\s*=' frontend/apps/web/src`
    - found the three planned route writers only.
- Final focused tests:
  - `cd frontend/apps/web && bun run test:unit -- src/lib/features/flows/FlowEditor.test.ts`
    - 1 file, 8 tests passed.
- Previous Batch 7 smoke:
  - `cd frontend/apps/web && bun run test:unit -- src/lib/features/flows/flowFormSchema.test.ts src/lib/features/flows/components/FlowRunLaunchInputState.test.ts src/lib/features/flows/components/FlowRunFileInputState.test.ts src/lib/features/flows/flowRunContract.test.ts src/lib/features/flows/flowRunWizard.test.ts`
    - 5 files, 41 tests passed.
- `cd frontend/apps/web && bunx prettier --check ...` over touched frontend
  files.
- `cd frontend/apps/web && bunx eslint ...` over touched frontend files.
- `git diff --check -- ...` over touched frontend/docs paths.
- Anti-slippage grep over touched frontend files, PRDs, and the AI Builder
  prompt contract returned no matches.
- Positive disappearance grep over `frontend/apps/web/src` returned no
  `$update.name =`, `$update.description =`, or
  `$update.data_retention_days =` matches.

Baseline/existing failures recorded:

- `cd frontend/apps/web && bun run check` still fails with 43 errors and 7
  warnings in 14 files. The errors are the known broad frontend baseline
  categories in `frontend/packages/intric-js`, spaces/chat/dashboard route
  typing, Flow route path typing, and existing AI Builder harness warnings. No
  touched-file diagnostic appeared.

### Claude Verification

- Implementation review returned `VERDICT: green`, `GREEN_LIGHT: yes`, and
  `MIN_SCORE: 8`.
- Claude verified:
  - the three route writers were removed
  - preservation tests are stronger than existence-only setter tests
  - `NaN` normalization is the real command invariant
  - `0`, `null`, and dirty-state round-trip behavior are pinned
- Accepted optional polish:
  - simplified the finite-number guard in `setDataRetentionDays(...)`
  - added a non-empty description assertion before the empty-string assertion

### Carry-Forward

- Step-array mutation remains the main open Flow authoring owner issue.
- `editor.state.update` remains writable until the step-command slice can
  replace or narrow direct step/name/description/data-retention writes more
  structurally.
- `createResourceEditor.editableFields` and explicit `FlowEditor` commands now
  overlap as mutation allow-lists. Revisit this after step commands land and
  the external store surface can be narrowed.
- Batch 8 step rerun has not started.

## Iteration 8 - Flow Step Mutation Commands

### Starting State

- Started from commit `6c982182 flows: centralize basic settings authoring`.
- Branch state before planning:
  - `frontend/packages/ui/src/icons/types.d.ts` dirty, unrelated and untouched
  - `scripts/run_codex_review.sh` dirty, unrelated and untouched
  - `PRODUCT.md` untracked, unrelated and untouched
  - no staged files
- Scope limited to Flow step replacement/removal commands in `FlowEditor`, the
  route call site, behavior tests, and Batch 7 docs.
- Backend runtime, migrations, Celery, data model, generated schemas, package
  naming, namespace migration, and Batch 8 step rerun were not in scope.

### Plan Evidence

- The route still owned two step-array mutations:
  - `onStepChanged` assigned `$update.steps[index] = step` and then
    `$update.steps = $update.steps`
  - `onRemoveStep` filtered `$update.steps`, renumbered `step_order` in place,
    delegated to `applyStepsWithSafeOrderRemap(...)`, and set active-step
    fallback directly
- `FlowEditor.ts` already owned step creation, insertion, safe order remapping,
  assistant prompt remapping, validation, save scheduling, and active-step
  state.
- The route removal path had a real ownership bug: it renumbered surviving step
  objects in place before `applyStepsWithSafeOrderRemap(...)` could compare
  previous orders, because the filtered array retained object references from
  the editor store.

### Claude Plan Review

- First review returned `VERDICT: changes_required`, `GREEN_LIGHT: no`, and
  `MIN_SCORE: 6`.
- Accepted findings:
  - invalid index behavior needed exact semantics
  - failure propagation and active-step timing needed to be explicit
  - removal needed clone-before-renumber behavior to avoid mutating store
    objects before deleted-reference detection
  - tests needed last-step, only-step, invalid-index, and failure-path pins
  - disappearance checks needed to cover direct route step writes and broader
    `.steps =` assignments
- The plan was revised so:
  - valid indexes are finite integers in `[0, steps.length)`
  - replacement preserves the existing step order
  - removal clones surviving steps before renumbering
  - `activeStepId` changes only after safe remap succeeds
  - invalid replace/remove calls are no-ops
  - failure propagation is pinned without adding a compatibility fallback
- Plan verification returned `VERDICT: green`, `GREEN_LIGHT: yes`, and
  `MIN_SCORE: 8`.

### Implementation Result

- `FlowEditor.ts` now exposes:
  - `replaceStepAtIndex(index, step)`
  - `removeStepAtIndex(index)`
- `replaceStepAtIndex(...)` clones the step array, replaces one target step,
  preserves the existing `step_order`, and leaves invalid indexes unchanged.
- `removeStepAtIndex(...)` clones surviving steps before renumbering, delegates
  to `applyStepsWithSafeOrderRemap(...)`, and updates active-step fallback only
  after the remap succeeds.
- The route now delegates step replacement/removal to `FlowEditor` and keeps
  only event translation plus toast/error translation.
- `FlowEditor.test.ts` now pins:
  - replacement preserves neighboring step references and the existing order
  - invalid replacement indexes are no-ops
  - removal renumbers survivors and selects the next step
  - removing the last step falls back to the previous step
  - removing the only step clears the active step
  - invalid removal indexes are no-ops
  - remap/save failures propagate and leave active-step selection unchanged

### Validation

Passed:

- `cd frontend/apps/web && bun run test:unit -- src/lib/features/flows/FlowEditor.test.ts`
  - 1 file, 15 tests passed.
- `cd frontend/apps/web && bun run test:unit -- src/lib/features/flows/flowFormSchema.test.ts src/lib/features/flows/components/FlowRunLaunchInputState.test.ts src/lib/features/flows/components/FlowRunFileInputState.test.ts src/lib/features/flows/flowRunContract.test.ts src/lib/features/flows/flowRunWizard.test.ts`
  - 5 files, 41 tests passed.
- `cd frontend/apps/web && bunx prettier --check ...` over touched frontend
  files.
- `cd frontend/apps/web && bunx eslint ...` over touched frontend files.
- `git diff --check -- ...` over touched frontend/docs paths.
- Anti-slippage grep over touched frontend files, PRDs, and the AI Builder
  prompt contract returned no matches.
- Positive disappearance grep over `frontend/apps/web/src` returned no
  `$update.steps[...] =` or `$update.steps =` matches.
- Broader `.steps =` assignment guard over routes and Flow feature code found
  only `FlowEditor.ts:65`, the existing canonical API-call sanitizer in
  `cleanChangesBeforeUpdate(...)`.

Baseline/existing failures recorded:

- `cd frontend/apps/web && bun run check` still fails with 43 errors and 7
  warnings in 14 files. The errors are the known broad frontend baseline
  categories in `frontend/packages/intric-js`, spaces/chat/dashboard route
  typing, Flow route path typing, and existing AI Builder harness warnings. No
  touched-file diagnostic appeared.

### Claude Verification

- Implementation review returned `VERDICT: green`, `GREEN_LIGHT: yes`, and
  `MIN_SCORE: 8`.
- Claude verified:
  - the route no longer mutates `$update.steps` directly
  - clone-before-renumber behavior fixes the identified route aliasing issue
  - tests cover invalid index handling, step-order preservation, active-step
    fallback, and failure propagation
  - no compatibility shim, fake interface, frontend redesign, backend runtime
    work, or Batch 8 behavior was introduced
- Claude noted two non-blocking observations:
  - fallback-step calculation is dense but covered by tests
  - partial failure semantics remain inherited from
    `applyStepsWithSafeOrderRemap(...)`; this slice pins active-step behavior
    but does not redesign assistant-remap transactions

### Carry-Forward

- `FlowEditor.state.update` remains externally writable. After route step
  writes are closed, a future review can decide whether to expose a narrower
  read/update surface or leave the writable store as an intentional editor
  draft boundary.
- `createResourceEditor.editableFields` and explicit `FlowEditor` commands
  still overlap as mutation allow-lists. Revisit only if narrowing the external
  store surface becomes a dedicated frontend architecture slice.
- Assistant prompt remap failure can still leave step edits applied before a
  downstream assistant-save failure. That is pre-existing behavior now
  documented and should not be changed without a separate transactional design.
- Batch 8 step rerun has not started.
