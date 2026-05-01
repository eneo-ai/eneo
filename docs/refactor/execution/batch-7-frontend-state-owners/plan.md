# Batch 7 - Frontend State Owners

## Slice 1 - AI Builder Driver/Service Mirroring

### TL;DR

- Active scope: AI Builder Driver/Service mirrored mutable state only.
- Canonical mutable owner: `FlowAIBuilderDriver`.
- `FlowAIBuilderService` remains the Svelte context/controller facade, but no
  longer mirrors every Driver field as separate `$state` values.
- Planned implementation: replace Service's per-field mirrored `$state` fields
  and `#applyState` copier with one reactive invalidation counter that makes
  getters re-read `driver.state`.
- No backend, generated-schema, UI redesign, package rename, or broader Flow
  authoring/run/evidence state work is in scope.

### Start Gate

| Check | Result |
|---|---|
| `git log --oneline --max-count=12` | latest commit `351e3592 flows: align ai builder protocol with generated types` |
| `git status --short --branch` | branch `feature/refactor-flows-flowai`; only known unrelated dirty files remain: `frontend/packages/ui/src/icons/types.d.ts`, `scripts/run_codex_review.sh`, `PRODUCT.md` |
| `git diff --cached --name-only` | no staged files |

Known unrelated dirty files remain out of scope and must not be touched:

- `frontend/packages/ui/src/icons/types.d.ts`
- `scripts/run_codex_review.sh`
- `PRODUCT.md`

### Scope

Expected files to change:

- `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderService.svelte.ts`
- `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderService.test.ts`
- `docs/refactor/execution/batch-7-frontend-state-owners/plan.md`
- `docs/refactor/execution/batch-7-frontend-state-owners/journal.md`
- `docs/refactor/execution/batch-7-frontend-state-owners/retrospective-1.md`
- `docs/refactor/execution/batch-7-frontend-state-owners/claude-reconciliation-1.md`

Explicitly out of scope:

- `FlowAIBuilderDriver.ts` behavior changes
- frontend component UI redesign
- Flow authoring, run launch, evidence, or status ownership
- generated schema regeneration
- backend changes
- migrations, Celery, runtime behavior, data model changes
- package rename from `@intric/intric-js`
- `intric.*` to `eneo.*` namespace work

### Ownership Decision

Driver remains the canonical mutable owner for this slice.

Rationale:

- `FlowAIBuilderDriver` already owns all state mutations and behavior
  orchestration in one object (`FlowAIBuilderDriver.ts:96-990`).
- `FlowAIBuilderService` currently duplicates every state field and updates the
  copy in `#applyState` (`FlowAIBuilderService.svelte.ts:30-43`,
  `FlowAIBuilderService.svelte.ts:266-280`).
- Moving all mutation logic from Driver to Service would be a much larger
  behavior refactor. The smaller maintainable step is to delete the mirrored
  mutable fields while preserving Driver behavior and Svelte reactivity.
- Service remains a context facade because components already import
  `getAIBuilderService`/`initAIBuilderService`; deleting that context would
  become a broad component rewrite.

### State Inventory

| state field | current Driver owner | current Service mirror | readers | writers | canonical owner | action |
|---|---|---|---|---|---|---|
| `session` | `FlowAIBuilderDriver.ts:45-46`, writes at `200`, `257`, `297`, `401`, `509`, `530`, `803` | `FlowAIBuilderService.svelte.ts:30`, copied at `267` | Service getters, PlanPane, Input, Chat, root component | Driver methods only | Driver | Service getter reads `this.#state.session`; delete mirrored field. |
| `messages` | `FlowAIBuilderDriver.ts:45-47`, writes at `276`, `342`, `770-782`, `880` | `FlowAIBuilderService.svelte.ts:31`, copied at `268` | Chat/root components, phase derivation | Driver methods only | Driver | Service getter reads `this.#state.messages`; delete mirrored field. |
| `currentPlan` | `FlowAIBuilderDriver.ts:45-48`, writes at `167`, `277`, `345`, `397`, `494`, `528`, `610`, `967`, `980` | `FlowAIBuilderService.svelte.ts:32`, copied at `269` | PlanPane, Chat/root, canApprove/canApply | Driver methods only | Driver | Service getter reads `this.#state.currentPlan`; delete mirrored field. |
| `isStreaming` | `FlowAIBuilderDriver.ts:45-49`, writes at `316`, `446`, `454`, `473`, `724` | `FlowAIBuilderService.svelte.ts:33`, copied at `270` | Chat, root, input, plan pane, canSendMessage | Driver methods only | Driver | Service getter reads `this.#state.isStreaming`; delete mirrored field. |
| `isInitializing` | `FlowAIBuilderDriver.ts:45-50`, writes at `134`, `154` | `FlowAIBuilderService.svelte.ts:34`, copied at `271` | root component | Driver methods only | Driver | Service getter reads `this.#state.isInitializing`; delete mirrored field. |
| `error` | `FlowAIBuilderDriver.ts:45-51`, writes at `128`, `207`, `250`, `314`, `437`, `439`, `469`, `483`, `497`, `506`, `543`, `545`, `622` | `FlowAIBuilderService.svelte.ts:35`, copied at `272` | Chat | Driver methods only | Driver | Service getter reads `this.#state.error`; delete mirrored field. |
| `applyError` | `FlowAIBuilderDriver.ts:45-52`, writes at `162`, `169`, `541`, `628` | `FlowAIBuilderService.svelte.ts:36`, copied at `273` | PlanPane, Chat | Driver methods only | Driver | Service getter reads `this.#state.applyError`; delete mirrored field. |
| `applyResult` | `FlowAIBuilderDriver.ts:45-53`, writes at `172`, `278`, `346`, `527` | `FlowAIBuilderService.svelte.ts:37`, copied at `274` | PlanPane, Chat, canContinueEditing | Driver methods only | Driver | Service getter reads `this.#state.applyResult`; delete mirrored field. |
| `isConflict` | `FlowAIBuilderDriver.ts:45-54`, writes at `161`, `168`, `279`, `315`, `507`, `542` | `FlowAIBuilderService.svelte.ts:38`, copied at `275` | PlanPane, Chat/root | Driver methods only | Driver | Service getter reads `this.#state.isConflict`; delete mirrored field. |
| `statusMessage` | `FlowAIBuilderDriver.ts:45-55`, writes at `171`, `280`, `398`, `427`, `441`, `447` | `FlowAIBuilderService.svelte.ts:39`, copied at `276` | PlanPane, Chat/root, phase derivation | Driver methods only | Driver | Service getter reads `this.#state.statusMessage`; delete mirrored field. |
| `availableModels` | `FlowAIBuilderDriver.ts:45-56`, writes at `753` | `FlowAIBuilderService.svelte.ts:40`, copied at `277` | PlanPane, Input | Driver methods only | Driver | Service getter reads `this.#state.availableModels`; delete mirrored field. |
| `selectedModelId` | `FlowAIBuilderDriver.ts:45-57`, writes at `177`, `754` | `FlowAIBuilderService.svelte.ts:41`, copied at `278` | Input, send-message request body | Driver methods only | Driver | Service getter reads `this.#state.selectedModelId`; delete mirrored field. |
| `modelsLoaded` | `FlowAIBuilderDriver.ts:45-58`, writes at `755` | `FlowAIBuilderService.svelte.ts:42`, copied at `279` | Input | Driver methods only | Driver | Service getter reads `this.#state.modelsLoaded`; delete mirrored field. |
| `draftSessions` | `FlowAIBuilderDriver.ts:45-59`, writes at `224`, `271` | `FlowAIBuilderService.svelte.ts:43`, copied at `280` | root component, draft recovery | Driver methods only | Driver | Service delegates `recoverableCreateDrafts` to Driver; delete mirrored field and duplicated filter. |

### Implementation Plan

1. Add a single reactive invalidation token to `FlowAIBuilderService`:

   ```ts
   #stateVersion = $state(0);
   ```

2. Add a private state accessor that reads the token and returns the Driver's
   read-only state:

   ```ts
   get #state(): Readonly<FlowAIBuilderState> {
     void this.#stateVersion;
     return this.#driver.state;
   }
   ```

   Hard rule: every Service getter or derived value must read Driver state only
   through this private accessor. Do not read `this.#driver.state` directly from
   a public getter, because bypassing `#state` silently drops Svelte tracking.

3. Replace the Driver listener's `#applyState(state)` callback with an
   invalidation callback:

   ```ts
   this.#driver = new FlowAIBuilderDriver(transport, spaceId, flowId, () => {
     this.#stateVersion += 1;
   });
   ```

4. Replace all Service mirrored-field getters and derived values with reads from
   `this.#state`.

5. Replace duplicated Service `recoverableCreateDrafts` filtering with Driver's
   existing `getRecoverableCreateDrafts()` after touching `this.#state` for
   Svelte invalidation.

6. Delete:
   - all per-field `$state` mirrors in Service
   - `#applyState`
   - the constructor call to `createInitialFlowAIBuilderState()`
   - now-unused protocol type imports in Service

7. Add a non-jsdom Service unit test that proves the facade reactivity follows
   Driver updates:
   - `service.seedState({ session })` updates `service.session`
   - `service.canSendMessage` updates from Driver-owned session/streaming state,
     including a flip from `true` to `false` when `isStreaming` changes
   - `service.phase` updates from Driver-owned plan/message state
   - `service.recoverableCreateDrafts` delegates Driver's filter
   - the test uses public Service APIs only; it does not assert private helper
     calls

8. Add exactly one short implementation comment near the invalidation token or
   `#state` accessor explaining the Svelte tracking invariant. Do not scatter
   `void`-read comments through every getter.

### Behavior Pins

Existing behavior pins that must keep passing:

- `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderDriver.test.ts`
  covers create/recover/resume/stream/approve/apply/revise behavior.
- `frontend/apps/web/src/lib/features/flows/ai-builder/flowAIBuilderReset.test.ts`
  covers reset visibility derived from AI Builder state flags.
- `frontend/apps/web/src/lib/features/flows/ai-builder/flowAIBuilderTokenUsage.test.ts`
  covers telemetry shape and display derivation.

New behavior pin:

- `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderService.test.ts`
  covers Service facade reactivity without testing private helper calls.

### Validation Commands

Targeted service/driver tests:

```bash
cd frontend/apps/web && bun run test:unit -- \
  src/lib/features/flows/ai-builder/FlowAIBuilderService.test.ts \
  src/lib/features/flows/ai-builder/FlowAIBuilderDriver.test.ts \
  src/lib/features/flows/ai-builder/flowAIBuilderReset.test.ts \
  src/lib/features/flows/ai-builder/flowAIBuilderTokenUsage.test.ts
```

Full AI Builder targeted suite, with known jsdom caveat:

```bash
cd frontend/apps/web && bun run test:unit -- src/lib/features/flows/ai-builder
```

Broad frontend check, expected to retain known baseline failures:

```bash
cd frontend/apps/web && bun run check
```

Touched-file lint/format:

```bash
cd frontend/apps/web && bunx prettier --check \
  src/lib/features/flows/ai-builder/FlowAIBuilderService.svelte.ts \
  src/lib/features/flows/ai-builder/FlowAIBuilderService.test.ts
```

```bash
cd frontend/apps/web && bunx eslint \
  src/lib/features/flows/ai-builder/FlowAIBuilderService.svelte.ts \
  src/lib/features/flows/ai-builder/FlowAIBuilderService.test.ts
```

Diff and text hygiene:

```bash
git diff --check -- \
  frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderService.svelte.ts \
  frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderService.test.ts \
  docs/refactor/execution/batch-7-frontend-state-owners
```

```bash
rg --pcre2 -n "A\\.[0-9](?![0-9])|P0\\.|Phase [0A-G]|/tmp/ai_builder|plan/(phases|progress|briefs|intents|reviews|codex|architecture_plan)|state-owner slice|Batch 7|as any|@ts-ignore|@ts-expect-error" \
  frontend/apps/web/src/lib/features/flows/ai-builder \
  docs/refactor/prd \
  docs/refactor/ai-builder-prompt-contract.md
```

Expected: no new matches. Existing `as never` in
`test-harnesses/FlowAIBuilderHarness.svelte` is a known pre-existing test
harness cast and is not touched by this slice.

### Claude Plan Review

- Claude plan review returned body result `VERDICT: green`,
  `GREEN_LIGHT: yes`, and `MIN_SCORE: 7`.
- Accepted guardrails from Claude:
  - the invalidation-token design is not a domain-state mirror if Driver remains
    the only mutable state owner
  - `#state` must be the only Service read path to Driver state
  - Service tests must prove `$derived` values update after Driver-owned state
    changes
  - the invalidation token needs one short why-comment because its read is
    load-bearing
  - deleting Service entirely or making Driver a `.svelte.ts` state owner are
    possible later end states, but too broad for this slice

### Non-Goals

- Do not make Service the full mutation owner in this slice.
- Do not move transport/SSE parsing out of Driver in this slice.

- Do not change component state/read paths beyond the Service facade.
- Do not add a new global state library.
- Do not introduce helper/common/shared/store modules.
- Do not fix unrelated broad app check baseline issues.

### Carry-Forward

- Service deletion remains a possible later end state, but this slice only
  removes mirrored mutable state.
- Converting `FlowAIBuilderDriver` itself to a Svelte rune owner may be cleaner
  later, but would change test setup and listener semantics; defer until there
  is a separate human-approved frontend state slice.

## Slice 2 - AI Builder Plan Visibility Latch

### TL;DR

- Active scope: Flow AI Builder component state readers around the
  Service/Driver boundary.
- Canonical owner: `FlowAIBuilderService` owns the UI workflow latch that says a
  plan has been seen during the current AI Builder session.
- Planned implementation: replace three component-local `hadPlanBefore` latches
  with one Service-owned latch. Keep the root-only plan-pane visibility
  aggregate local to `FlowAIBuilder.svelte`.
- No backend, generated-schema, component redesign, package rename, authoring,
  run-launch, evidence/status, or Batch 8/9 runtime work is in scope.

### Start Gate

| Check | Result |
|---|---|
| `git log --oneline --max-count=8` | latest commit `90e688a9 flows: remove ai builder service state mirror` |
| `git status --short --branch` | branch `feature/refactor-flows-flowai`; only known unrelated dirty files remain: `frontend/packages/ui/src/icons/types.d.ts`, `scripts/run_codex_review.sh`, `PRODUCT.md` |
| `git diff --cached --name-only` | no staged files |

Known unrelated dirty files remain out of scope and must not be touched:

- `frontend/packages/ui/src/icons/types.d.ts`
- `scripts/run_codex_review.sh`
- `PRODUCT.md`

### Scope

Expected files to change:

- `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderService.svelte.ts`
- `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderService.test.ts`
- `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilder.svelte`
- `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderChat.svelte`
- `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderPlanPane.svelte`
- `docs/refactor/execution/batch-7-frontend-state-owners/plan.md`
- `docs/refactor/execution/batch-7-frontend-state-owners/journal.md`
- `docs/refactor/execution/batch-7-frontend-state-owners/retrospective-2.md`
- `docs/refactor/execution/batch-7-frontend-state-owners/claude-reconciliation-2.md`

Explicitly out of scope:

- `FlowAIBuilderDriver.ts` behavior changes
- deleting `FlowAIBuilderService`
- making Driver a Svelte rune owner
- AI Builder protocol/generated type changes
- component UI redesign or CSS/layout changes
- Flow authoring, run launch, evidence, or status ownership
- backend changes, migrations, Celery, runtime behavior, data model changes
- package rename from `@intric/intric-js`
- `intric.*` to `eneo.*` namespace work

### State Reader Inventory

| duplicated state/reader | current locations | readers | writers | canonical owner | action |
|---|---|---|---|---|---|
| `hadPlanBefore` / plan-seen latch | `FlowAIBuilder.svelte:26-43`, `FlowAIBuilderChat.svelte:52-59`, `FlowAIBuilderPlanPane.svelte:96-104` | root shell plan-pane visibility, chat generating/updating copy, plan pane progress copy | component `$effect` blocks watching `service.currentPlan` and `service.hasSession` | `FlowAIBuilderService` | Add one Service-owned `hasSeenPlanInSession` latch updated from Driver notifications; delete the three component-local latches. |
| plan-pane visibility aggregate | `FlowAIBuilder.svelte:38-43` | root shell layout | root `$derived` from `service.currentPlan`, `service.isConflict`, `service.statusMessage`, `hadPlanBefore && service.isStreaming` | `FlowAIBuilder.svelte` | Keep local because this aggregate has one consumer; replace only the latch input with `service.hasSeenPlanInSession`. |
| generating vs updating copy decision | `FlowAIBuilderChat.svelte:57-59`, `FlowAIBuilderPlanPane.svelte:695-698` | chat stream badge and plan pane progress copy | component-local `hadPlanBefore` latch | `FlowAIBuilderService` owns the latch; components own translation copy | Components use `service.hasSeenPlanInSession` and keep translation/rendering local. |

### Ownership Decision

`FlowAIBuilderService` remains the Svelte context/controller facade and is the
right owner for this UI workflow latch because:

- The value is not backend/domain state and does not belong in Driver's
  canonical `FlowAIBuilderState`.
- The value is not component-local once three components need the same latch.
- The value is derived from Driver-owned state transitions and reset when the
  Driver has no active session, so Service can update it at the Driver
  notification boundary without adding a parallel state mirror.

This slice deliberately does not move translations, layout, or component-only
user intent state such as `userReferenceOpen`, `pendingEditContext`,
`isApproving`, or `isApplying`.

This slice also deliberately keeps `hasPlanContent` local to
`FlowAIBuilder.svelte` because it is root-shell layout state with one consumer.
Moving only the duplicated latch avoids turning Service into a generic view
aggregate owner.

### Behavior Pins Before Deletion

Add or update `FlowAIBuilderService.test.ts` before deleting component latches:

- `hasSeenPlanInSession` starts false.
- seeding a `currentPlan` makes `hasSeenPlanInSession` true.
- clearing `currentPlan` while the session remains active keeps
  `hasSeenPlanInSession` true.
- setting `session` to `null` resets `hasSeenPlanInSession` false.
- the precedence case `currentPlan !== null` and `session === null` resets
  `hasSeenPlanInSession` false.
- `hasSeenPlanInSession` remains true while streaming after a plan was cleared
  and while the root component's local aggregate sees
  `currentPlan === null`.

Existing pins that must keep passing:

- `FlowAIBuilderService.test.ts`
- `FlowAIBuilderDriver.test.ts`
- `flowAIBuilderReset.test.ts`
- `flowAIBuilderTokenUsage.test.ts`
- `FlowAIBuilder.test.ts` where the environment can run jsdom

### Implementation Plan

1. Add Service-owned UI latch state:

   ```ts
   #hasSeenPlanInSession = $state(false);
   ```

2. Add a private latch update method that receives Driver state inside the
   existing Driver notification boundary:

   ```ts
   #updatePlanSeenLatch(state: Readonly<FlowAIBuilderState>): void {
     if (state.session === null) {
       this.#hasSeenPlanInSession = false;
       return;
     }
     if (state.currentPlan !== null) this.#hasSeenPlanInSession = true;
   }
   ```

   The method updates only the latch, not mirrored copies of Driver fields. The
   reset-before-set precedence is load-bearing and must be tested.

3. Call `#updatePlanSeenLatch` from the Driver callback after incrementing
   `#stateVersion`, using the state argument the Driver listener already
   receives:

   ```ts
   this.#driver = new FlowAIBuilderDriver(transport, spaceId, flowId, (state) => {
     this.#stateVersion += 1;
     this.#updatePlanSeenLatch(state);
   });
   ```

   `#updatePlanSeenLatch` reads only its `state` parameter; it must not read
   `this.#driver.state` or `this.#state`.

4. Add public read-only Service getter `hasSeenPlanInSession: boolean`. Do not
   add a setter.

5. Update `FlowAIBuilder.svelte`:

   - delete local `hadPlanBefore` `$state`
   - delete the related `$effect`
   - keep the local `hasPlanContent` `$derived`
   - replace `(hadPlanBefore && service.isStreaming)` with
     `(service.hasSeenPlanInSession && service.isStreaming)`

6. Update `FlowAIBuilderChat.svelte`:

   - delete local `hadPlanBefore` `$state`
   - delete the related `$effect`
   - derive generating/updating text from `service.hasSeenPlanInSession`

7. Update `FlowAIBuilderPlanPane.svelte`:

   - delete local `hadPlanBefore` `$state`
   - delete the related `$effect`
   - use `service.hasSeenPlanInSession` for progress copy only

8. Do not introduce helper/common/shared/store modules. Do not add new
   comments unless the Service latch synchronization needs one short invariant
   comment.

### Validation Commands

Targeted Service/Driver tests:

```bash
cd frontend/apps/web && bun run test:unit -- \
  src/lib/features/flows/ai-builder/FlowAIBuilderService.test.ts \
  src/lib/features/flows/ai-builder/FlowAIBuilderDriver.test.ts \
  src/lib/features/flows/ai-builder/flowAIBuilderReset.test.ts \
  src/lib/features/flows/ai-builder/flowAIBuilderTokenUsage.test.ts
```

Component test from the Batch 7 row, with known `jsdom` caveat:

```bash
cd frontend/apps/web && bun run test:unit -- src/lib/features/flows/ai-builder/FlowAIBuilder.test.ts
```

Broad app check from the Batch 7 row, expected to retain known baseline
failures until the frontend baseline is fixed:

```bash
cd frontend/apps/web && bun run check
```

Touched-file lint/format:

```bash
cd frontend/apps/web && bunx prettier --check \
  src/lib/features/flows/ai-builder/FlowAIBuilderService.svelte.ts \
  src/lib/features/flows/ai-builder/FlowAIBuilderService.test.ts \
  src/lib/features/flows/ai-builder/FlowAIBuilder.svelte \
  src/lib/features/flows/ai-builder/FlowAIBuilderChat.svelte \
  src/lib/features/flows/ai-builder/FlowAIBuilderPlanPane.svelte
```

```bash
cd frontend/apps/web && bunx eslint \
  src/lib/features/flows/ai-builder/FlowAIBuilderService.svelte.ts \
  src/lib/features/flows/ai-builder/FlowAIBuilderService.test.ts \
  src/lib/features/flows/ai-builder/FlowAIBuilder.svelte \
  src/lib/features/flows/ai-builder/FlowAIBuilderChat.svelte \
  src/lib/features/flows/ai-builder/FlowAIBuilderPlanPane.svelte
```

Diff and text hygiene:

```bash
git diff --check -- \
  frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderService.svelte.ts \
  frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderService.test.ts \
  frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilder.svelte \
  frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderChat.svelte \
  frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderPlanPane.svelte \
  docs/refactor/execution/batch-7-frontend-state-owners
```

```bash
rg --pcre2 -n "A\\.[0-9](?![0-9])|P0\\.|Phase [0A-G]|/tmp/ai_builder|plan/(phases|progress|briefs|intents|reviews|codex|architecture_plan)|state-owner slice|Batch 7|as any|@ts-ignore|@ts-expect-error" \
  frontend/apps/web/src/lib/features/flows/ai-builder \
  docs/refactor/prd \
  docs/refactor/ai-builder-prompt-contract.md
```

```bash
rg -n "hadPlanBefore" frontend/apps/web/src/lib/features/flows/ai-builder
```

Expected after implementation: no `hadPlanBefore` matches.

### Component Test Caveat

`FlowAIBuilder.test.ts` is still listed because Batch 7's validation row calls
for frontend component tests. In this workspace it may fail for the known
missing-`jsdom`/Paraglide environment baseline. That failure is acceptable only
if the moved logic is fully pinned in `FlowAIBuilderService.test.ts` and the
focused non-jsdom Service/Driver tests pass.

### Claude Plan Review

- Claude plan review returned `VERDICT: changes_required`, `GREEN_LIGHT: no`,
  `MIN_SCORE: 7`.
- Accepted changes:
  - keep `hasPlanContent` local to `FlowAIBuilder.svelte` because it has only
    one consumer
  - rename the generic `#syncViewState` plan to `#updatePlanSeenLatch`
  - make session-null reset precedence explicit
  - add a precedence behavior pin for `currentPlan !== null` with
    `session === null`
  - document why component-test environment failure is acceptable only when the
    moved latch behavior is pinned in Service tests
- Claude resumed on the revised plan and returned `VERDICT: green`,
  `GREEN_LIGHT: yes`, `MIN_SCORE: 8`.
- Accepted precision updates from the green review:
  - write out the Driver listener closure and pass the callback `state` into
    `#updatePlanSeenLatch`
  - prevent `#updatePlanSeenLatch` from reading `this.#driver.state` or
    `this.#state`
  - document `hasSeenPlanInSession` as a read-only boolean getter with no setter
  - name the streaming behavior pin around Service primitive inputs rather than
    a nonexistent Service `hasPlanContent` aggregate

### Non-Goals

- Do not move draft auto-resume into Service in this slice.
- Do not move pending edit context or input attachment state.
- Do not move approve/apply in-flight flags.
- Do not alter component markup or styling except replacing the state reads.
- Do not fix broad `apps/web` check baseline failures.

### Carry-Forward

- Draft auto-resume orchestration remains in `FlowAIBuilder.svelte`; it can be
  evaluated as a separate small controller slice if this slice lands cleanly.
- Chat pending edit context remains component-owned because it is tied to input
  focus and local user intent.
- Plan pane approve/apply in-flight flags remain component-owned until a
  dedicated action-state slice proves a better owner.
- If this Service-owned latch pattern survives more slices, add a grep or lint
  guard that prevents direct Driver state reads outside the existing Service
  access/update boundary.

## Iteration 3 - Flow Run File Input State Owner

### TL;DR

- Active scope: Flow run launch runtime file input state inside `FlowRunDialog.svelte`.
- Canonical owner: a domain-specific `FlowRunFileInputState` Svelte state class.
- The dialog remains the UI/orchestration adapter for browser events, API upload calls, toasts, and recorder refs.
- `flowRunRecordingSession.ts` remains the persistence/resume helper owner; it does not gain Svelte mutable state.
- No backend, generated schema, package naming, broad UI redesign, Flow authoring, evidence/status, Batch 8 runtime work, or unrelated dirty files are in scope.

### Start Gate

| Check | Result |
|---|---|
| `git log --oneline --max-count=8` | latest commit `6a35d3da flows: harden audio recording sessions` |
| `git status --short --branch` | branch `feature/refactor-flows-flowai`; only known unrelated dirty files remain: `frontend/packages/ui/src/icons/types.d.ts`, `scripts/run_codex_review.sh`, `PRODUCT.md` |
| `git diff --cached --name-only` | no staged files |

Known unrelated dirty files remain out of scope and must not be touched:

- `frontend/packages/ui/src/icons/types.d.ts`
- `scripts/run_codex_review.sh`
- `PRODUCT.md`

### Scope

Expected files to change:

- `frontend/apps/web/src/lib/features/flows/components/FlowRunDialog.svelte`
- `frontend/apps/web/src/lib/features/flows/components/FlowRunFileInputState.svelte.ts`
- `frontend/apps/web/src/lib/features/flows/components/FlowRunFileInputState.test.ts`
- `docs/refactor/execution/batch-7-frontend-state-owners/plan.md`
- `docs/refactor/execution/batch-7-frontend-state-owners/journal.md`
- `docs/refactor/execution/batch-7-frontend-state-owners/retrospective-3.md`
- `docs/refactor/execution/batch-7-frontend-state-owners/claude-reconciliation-3.md`

Explicitly out of scope:

- backend runtime, migrations, Celery, data model, and Batch 8 rerun work
- Flow authoring editor state
- evidence/status page state
- generated schema changes
- package rename from `@intric/intric-js`
- `intric.*` to `eneo.*` namespace migration
- broad Flow run dialog UI redesign
- replacing `RecordingSession`, `recordingSessionStore`, or IndexedDB persistence
- moving API upload calls, toast calls, DOM file picker creation, or recorder imperative refs into the state owner

### Reuse-Before-Inventing Decision

| Candidate | Existing responsibility | Why insufficient for this slice | Decision |
|---|---|---|---|
| `FlowRunDialog.svelte` | Full run launch UI, contract loading, wizard navigation, upload orchestration, recording session callbacks, submit orchestration | Currently owns every mutable runtime-file and recording state field directly, making the component the state owner and UI adapter at once | Move the cohesive runtime file input state cluster out of the component. |
| `flowRunRecordingSession.ts` | Segment filename composition, IndexedDB persistence, recoverable-session scanning, session purge/detach helpers | Pure helper module; it should not gain Svelte `$state`, UI drag/upload flags, or component view state | Keep as persistence/resume helper owner. Reuse its `RecordingSessionState` and pure transition helpers inside the new state owner. |
| `RecordingSession` | Per-step recorder lifecycle state machine and media retry lifecycle | Owns recorder lifecycle, not dialog upload files, errors, wizard blockers, resume prompt view state, or drag/upload flags | Keep unchanged and controlled by the dialog through existing callbacks. |
| `flowRunWizard.ts` | Pure wizard pages, blockers, and review summary derivation | It consumes runtime file/upload/recording state but does not own mutable UI state | Keep unchanged. |
| New `FlowRunFileInputState.svelte.ts` | One Svelte state owner for runtime file input view/session state | This is the missing canonical owner; it deletes the component's scattered `$state` fields instead of adding a parallel mirror | Create with a narrow domain-specific name and behavior-focused tests. |

### State Inventory

| state field | current owner | readers | writers | canonical owner | action |
|---|---|---|---|---|---|
| `runtimeFilesByStepId` | `FlowRunDialog.svelte:103` | blockers/review/current step/submission/resume | upload success, remove, discard, resume reattach, submit reset | `FlowRunFileInputState` | Move state and file list transitions into class. Dialog still calls upload API. |
| `recordedFilesByStepId` | `FlowRunDialog.svelte:104` | dirty state/current step/retry/download/discard | recording done, upload success, discard, submit reset | `FlowRunFileInputState` | Move state and preserve-file/clear transitions into class. |
| `recorderResetTokensByStepId` | `FlowRunDialog.svelte:105` | current runtime step prop | discard/reset | `FlowRunFileInputState` | Move with recorded-file reset invariant. |
| `uploadErrorsByStepId` | `FlowRunDialog.svelte:106` | runtime step prop/retry | upload start/failure/discard/retry/reset | `FlowRunFileInputState` | Move with explicit clear/set methods. |
| `recordingNoticesByStepId` | `FlowRunDialog.svelte:107` | runtime step prop | upload start/remove/discard/recording done/retry/reset | `FlowRunFileInputState` | Move with explicit clear/set methods. |
| `skippedMessagesByStepId` | `FlowRunDialog.svelte:108` | runtime step prop | upload start/max-files/remove/discard/reset | `FlowRunFileInputState` | Move with explicit clear/set methods. |
| `uploadingStepIds` | `FlowRunDialog.svelte:109` | blockers/current step | upload start/finally/reset | `FlowRunFileInputState` | Move with idempotent active flag method. |
| `recordingStepIds` | `FlowRunDialog.svelte:110` | blockers/dirty/beforeunload | recorder state callback/reset | `FlowRunFileInputState` | Move with idempotent active flag method. |
| `draggingStepId` | `FlowRunDialog.svelte:111` | runtime step prop | drag/drop/leave/reset | `FlowRunFileInputState` | Move as transient file-input UI state. |
| `recordingSessionState` | `FlowRunDialog.svelte:115` | resume prompt/storage degraded/submission purge/recording counters | scan, record, resume, purge, discard, submit reset | `FlowRunFileInputState` | Move state and provide explicit transition methods while reusing `flowRunRecordingSession.ts` helpers. |
| `sessionPhaseByStepId` | `FlowRunDialog.svelte:130` | runtime step prop | `RecordingSession` state callback/dispose/reset | `FlowRunFileInputState` | Move view phase state. |
| `recordingSessionsByStepId` | `FlowRunDialog.svelte:128` | recorder lifecycle only | ensure/dispose/retry callbacks | `FlowRunDialog.svelte` | Keep in dialog because it stores imperative session objects bound to recorder component refs. |
| `recorderRefsByStepId` | `FlowRunDialog.svelte:129` | session retry/start/stop callbacks | child ref effect | `FlowRunDialog.svelte` | Keep in dialog because it is an imperative component ref registry, not durable run-launch state. |
| `formValues`, `inputText`, `currentPageIndex`, `runContract`, `isSubmitting` | `FlowRunDialog.svelte:96-112` | broader run launch wizard | broader wizard/submit flow | deferred | Leave for later run-launch slice; moving them with file inputs would exceed this narrow slice. |

### Ownership Design

Create `FlowRunFileInputState.svelte.ts` as the one mutable owner for runtime file input view state.

It owns state, not side effects:

- uploaded file lists
- preserved recorded file per step
- recorder reset tokens
- upload/recording/skipped messages
- uploading and recording active step ids
- drag hover state
- recoverable recording-session view state
- session phase display state

It does not own:

- API calls through `intric`
- toasts
- DOM file input creation
- recorder imperative refs
- `RecordingSession` object lifecycle
- run creation/idempotency
- wizard page definitions or blocker rules

Public surface must be domain-shaped, not a generic setter bag. The state owner
will expose coarser operations that match the dialog's existing state clusters:

- `getUploadedFiles(stepId)`
- `beginStepUpload(stepId, { clearRecordingNotice })`
- `recordUploadedFile(stepId, file)`
- `recordUploadFailure(stepId, message)`
- `recordSkippedFiles(stepId, message)`
- `retryRequested(stepId)`
- `finishStepUpload(stepId)`
- `removeUploadedFile(stepId, fileId)` returning the current session id for
  best-effort ledger detach
- `dragEnteredStep(stepId)` / `dragLeftStep(stepId)` / `clearDrag()`
- `recordingStarted(stepId)` / `recordingStopped(stepId)`
- `prepareRecordedSegment(stepId)` returning `{ sessionId, segmentIndex }`
- `recordSegmentPersistence({ stepId, file, notice, degraded })`
- `clearPreservedRecording(stepId)`
- `discardStepRecording(stepId)`
- `beginResumeAction(stepId)` / `finishResumeAction()`
- `applyResumeScan(hints, promptStepId)`
- `attachRecoveredSession(stepId, sessionId, segmentCount)`
- `discardRecoveredSession(stepId)`
- `dismissResumePrompt()`
- `syncSessionPhase(stepId, recordingState)`
- `forgetSessionPhase(stepId)`
- `resetForDialogClose()`
- `resetAfterRunAccepted()`

The class may expose read-only getters for derived values:

- `localRecordingStepIds`
- `hasLocalRecordedFiles`
- `hasRuntimeFiles`
- `hasActiveRecording`
- `runtimeFilesSnapshot`
- `uploadingStepIdsSnapshot`
- `recordingStepIdsSnapshot`
- `isStorageDegraded`

It also exposes per-step read methods for component props:

- `isStepUploading(stepId)`
- `isStepRecording(stepId)`
- `isDraggingStep(stepId)`
- `getRecordedFile(stepId)`
- `getRecorderResetToken(stepId)`
- `getUploadError(stepId)`
- `getRecordingNotice(stepId)`
- `getSkippedMessage(stepId)`
- `getResumeHint(stepId)`
- `isResumePromptForStep(stepId)`
- `isResumeBusyForStep(stepId)`
- `getSessionPhase(stepId)`

The dialog will consume these getters for blockers, dirty state, beforeunload,
current-step props, and submission payload. `flowRunWizard.ts` and
`buildStepInputsPayload` keep their current signatures in this slice; the
dialog passes owner-provided snapshots into those existing pure helpers.

`resetForDialogClose()` and `resetAfterRunAccepted()` reset in-memory dialog
state only. They do not clear IndexedDB; persistence cleanup stays explicit in
the dialog through `purgeSession`/`purgeAllSessions`.

Instantiation is local to the dialog module instance:

```ts
const fileInputState = new FlowRunFileInputState();
```

It is not a singleton, context object, or global store. Dialog close and
run-accepted paths must reset this local owner through one of the named reset
methods instead of rebuilding per-field maps inline.

`resetForDialogClose()` and `resetAfterRunAccepted()` clear the same in-memory
fields. They are separate methods for call-site clarity, not behavioral
divergence. In the run-accepted path, `resetAfterRunAccepted()` must run only
after the dialog reads `sessionIdsByStepId` and calls `purgeAllSessions`.

`FlowRunFileInputState` will continue to call these existing
`flowRunRecordingSession.ts` transition helpers, so they remain load-bearing and
are not duplicated:

- `emptyRecordingSessionState`
- `ensureSessionIdInState`
- `bumpSegmentCountInState`
- `clearStepSessionInState`

`syncSessionPhase(stepId, recordingState)` accepts `SessionState` from
`recordingSession.ts`; the new owner owns the `RecordingSession` lifecycle state
to runtime-step view phase mapping.

Implementation comments tied to moved state invariants move with the state.
Comments tied to `RecordingSession` object lifecycle, API calls, DOM file input,
or recorder imperative refs stay in `FlowRunDialog.svelte`.

### Behavior Pins Before/With Refactor

Use behavior-focused unit tests for `FlowRunFileInputState`, not
component-private helper assertions. At least 40% of the new tests must pin
multi-field invariants rather than one-field setters:

- starts with empty runtime files, no preserved recordings, no active upload/recording, no resume prompt
- appending/removing uploaded files keeps other steps untouched
- upload start clears prior upload/skipped state and upload finish clears active uploading without changing files
- preserving then clearing recorded files bumps the recorder reset token only for that step
- `prepareRecordedSegment` reuses the same session id for subsequent segments and increments segment indices from `0`
- `discardStepRecording` removes session ids, segment counts, hints, prompt, and busy state for the step without touching other steps
- resume scan applies hints and first prompt step
- recovered session attach records session id/count and clears the prompt for that step
- discard recovered session clears the step hints, prompt, and busy state together
- remove uploaded file clears recording notice and skipped message while returning the session id for ledger detach
- discard step recording clears preserved file, reset token, upload error, recording notice, skipped message, runtime files, and in-memory session view together
- storage degraded is sticky until a reset method is called
- `resetForDialogClose()` clears file, upload, recording, drag, resume, and session-phase state
- `resetAfterRunAccepted()` clears the same in-memory owner after the dialog explicitly purges persisted sessions
- per-step getters return stable defaults for unknown steps: empty files, `null`
  preserved file/error/notice/skipped/resume hint, `0` reset token, `false`
  uploading/recording/drag/resume busy/prompt, and `"idle"` session phase
- the state owner instance survives dialog open toggles; `resetForDialogClose()`
  is the canonical clear path between opens
- concurrent upload flags stay independent across steps, and finishing one step
  does not clear another step's upload-in-progress state

Post-implementation owner checks:

```bash
rg -n "uploadingStepIds|recordingStepIds|runtimeFilesByStepId|recordedFilesByStepId|uploadErrorsByStepId|recordingNoticesByStepId|skippedMessagesByStepId|draggingStepId|sessionPhaseByStepId|recorderResetTokensByStepId|recordingSessionState" \
  frontend/apps/web/src/lib/features/flows/components/FlowRunDialog.svelte
```

Expected: no direct state-field matches outside `fileInputState.*` reads and
method calls.

```bash
wc -l frontend/apps/web/src/lib/features/flows/components/FlowRunDialog.svelte
```

Target: reduce `FlowRunDialog.svelte` by at least 150 LOC from the current 1663
LOC. If implementation cannot meet that without weakening behavior, stop and
record a no-go rather than shipping a shallow relocation.

Existing behavior pins that must keep passing:

- `frontend/apps/web/src/lib/features/audio/flowRunRecordingSession.test.ts`
- `frontend/apps/web/src/lib/features/audio/recordingSession.test.ts`
- `frontend/apps/web/src/lib/features/flows/flowRunWizard.test.ts`

### Validation Commands

Targeted state-owner tests:

```bash
cd frontend/apps/web && bun run test:unit -- \
  src/lib/features/flows/components/FlowRunFileInputState.test.ts \
  src/lib/features/audio/flowRunRecordingSession.test.ts \
  src/lib/features/audio/recordingSession.test.ts \
  src/lib/features/flows/flowRunWizard.test.ts
```

Full audio targeted suite:

```bash
cd frontend/apps/web && bun run test:unit -- src/lib/features/audio
```

Broad frontend check, expected to retain known baseline failures:

```bash
cd frontend/apps/web && bun run check
```

Touched-file lint/format:

```bash
cd frontend/apps/web && bunx prettier --check \
  src/lib/features/flows/components/FlowRunDialog.svelte \
  src/lib/features/flows/components/FlowRunFileInputState.svelte.ts \
  src/lib/features/flows/components/FlowRunFileInputState.test.ts
```

```bash
cd frontend/apps/web && bunx eslint \
  src/lib/features/flows/components/FlowRunDialog.svelte \
  src/lib/features/flows/components/FlowRunFileInputState.svelte.ts \
  src/lib/features/flows/components/FlowRunFileInputState.test.ts
```

Diff and text hygiene:

```bash
git diff --check -- \
  frontend/apps/web/src/lib/features/flows/components/FlowRunDialog.svelte \
  frontend/apps/web/src/lib/features/flows/components/FlowRunFileInputState.svelte.ts \
  frontend/apps/web/src/lib/features/flows/components/FlowRunFileInputState.test.ts \
  docs/refactor/execution/batch-7-frontend-state-owners
```

```bash
rg --pcre2 -n "A\\.[0-9](?![0-9])|P0\\.|Phase [0A-G]|/tmp/ai_builder|plan/(phases|progress|briefs|intents|reviews|codex|architecture_plan)|state-owner slice|Batch 7|as any|@ts-ignore|@ts-expect-error" \
  frontend/apps/web/src/lib/features/flows/components \
  docs/refactor/prd \
  docs/refactor/ai-builder-prompt-contract.md
```

Expected: no new matches.

### Non-Goals

- Do not extract the entire `FlowRunDialog` workflow in this slice.
- Do not move upload side effects into the state owner.
- Do not move `RecordingSession` object lifecycle or recorder refs into the state owner.
- Do not change file upload behavior, resume behavior, translated copy, or UI layout.
- Do not start Batch 8.
