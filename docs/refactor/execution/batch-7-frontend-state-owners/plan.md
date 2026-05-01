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
