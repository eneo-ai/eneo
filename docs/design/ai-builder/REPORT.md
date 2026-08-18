# AI-byggaren redesign — implementation report

Worktree `/private/tmp/eneo-ai-builder-ui`, branch `lane/ai-builder-ui` (base `origin/refactor/flows-clean`
@ 021c22e80). Preview: http://127.0.0.1:3131 (lane API `eneo-ui-lane-api` :8150, worker, redis; DB
developz_devcontainer-db-1). Login user@example.com / Password1!, space "deniyorum".
Never pushed — the orchestrator lands the shas below.

## Plan pass (Codex, xhigh) — session `ai-builder-ui-redesign`, iteration 1

Verdict changes_required, MIN_SCORE 6. Artifact:
`.codex/artifacts/codex-peer-loop-ai-byggaren-ui-redesign-20260816T193825Z-a21d4d1c…md`.
Accepted and folded into the slices: server-side draft query before drafts become list rows (done in slice 1);
keep session creation eager (drop lazy-creation idea); generalize the Driver operation lock to
approve/apply/unpublish/create; keep the current plan visible through review turns and re-arm confirmation only
on a new requirements version; drop the fake "Avbryt" during Bygger (no backend turn cancel exists) and the
staged step-fill animation; classify 409 conflicts centrally for the conflict dialog; no client-only
"recommended" fields; "Jag är osäker — välj åt mig" = a free-text delegation reply (server turns explicit
uncertainty into a visible assumption); one global "Ändra svaren" instead of per-decision structured edits;
conversation sheet + layout e2e rewrite move into the shell slice; stop sending model_id/reasoning from the
composer. Escalated (product): recommended-option preselection needs a backend `recommended_option_id` +
rationale to be truthful — not implemented; reported as a deviation.

## Slice 1 — Flöden list + Skapa dialog — `93cade099` (no separate Codex commit gate; owner asked to gate only where needed)

Diff: 29 files, +1050 / −791.
Screenshots (1440×900): `screenshots/slice1/floden-list-1440x900.png`, `screenshots/slice1/skapa-dialog-1440x900.png`.

| Design element | Implementation |
|---|---|
| Header title + description, Importera (secondary) + Skapa flöde (primary) | `Page.Title description=…` (shared header untouched), existing import dialog, `CreateFlowDialog` trigger |
| Search, filter chips Alla/Publicerade/Utkast, "N poster · sorterat på senast ändrad" | `FlowsTable.svelte` toolbar (Input type=search, outline Buttons with aria-pressed, aria-live count) |
| Table Namn / Status / Ägare / Senast ändrad ▼ / actions; narrow = stacked | shadcn Table, `@container/list` (`@[52rem]`) column collapse |
| Draft rows "Utkast · Eneo förstår uppgiften / Du granskar planen", Fortsätt, ··· Ta bort | `flowListRows.ts` merges flows + drafts; `?session=` resume; discard = cancel session |
| Empty state / no-match / filter-empty | in-table states with Skapa flöde / Rensa sökningen / Visa alla |
| Skapa dialog: two path cards (AI recommended, manual) + footnote | rewritten `CreateFlowDialog.svelte`; manual path shows name field inline |

Deviations: no "Pausad" filter (no such flow state); step count / "ljud in, PDF ut" subtitle not available on
FlowSparse → description or nothing; drafts owner is always "Du" (own sessions); "högst tre frågor" softened
to "några korta frågor" (question budget is server policy, architecture questions can exceed 3).
Backend: `GET /flows/ai-builder/sessions` gained `space_id`, `target_kind`, `drafts_only`, `limit` (schema.d.ts
regenerated with the CI insertion-order pipeline; only the new params changed). Pre-existing drift fixed:
`protocol.ts` lacked `named_result_key_unsupported`, which made `bun run check` fail at HEAD.
Validation: `bun run check` 0 errors, eslint clean, vitest (flows routes, FlowAIBuilder dom, Driver, protocol)
green, backend pytest unit (list_sessions ×9, openapi contract, router) green, i18n parity/dup green,
browser-verified list/filter/search/dialog/resume.

## Slice 2 — Phase shell + Ny uppgift + Frågor + Samtal sheet — `d43f060e2` + `d8a71a683`

Codex commit gates (session ai-builder-ui-redesign): it.2 changes_required 7 → 5 blockers fixed (failed generation
keeps its one failure/retry surface, cold saved-step launch waits for the composer, model-name reads owned by
session identity + `modelLoadStatus` deleted, unsure exposed for field questions, non-vacuous reduced-motion e2e,
rail phase 2 disabled once done); it.3/it.4 changes_required 7 on one narrowing race (cold launch vs. resumed
session) → d8a71a683 defers the launch decision until bootstrap and treats `latest_plan_id` as ongoing; both
regression tests added. Playwright ai-builder-layout.spec 7/7 against the lane stack.

Screenshots (1440×900): `screenshots/slice2/ny-uppgift-1440x900.png`, `fragor-1440x900.png`,
`samtal-sheet-1440x900.png`, `bekrafta-interim-1440x900.png` (old card inside the new phase frame; slice 3
replaces it), `edit-tab-1440x900.png` (same shell inside the flow editor's AI-byggaren tab).

| Design element | Implementation |
|---|---|
| Phase rail (3 pips, done ✓ / active ● / upcoming n, connectors; one-line form on narrow) | `BuilderPhaseRail.svelte` (container query @40rem, `aria-current="step"`, done phases clickable = "peek") |
| Saved-state chip ("nytt utkast" / "utkastet sparas automatiskt") + Samtal button with count | shell header row in `FlowAIBuilder.svelte` |
| Ny uppgift: title, intro, composer, model note, Vanliga uppgifter chips, drafts/manual footer | `BuilderTaskScreen.svelte` (reuses `FlowAIBuilderInput` — attachments, char limit, draft persistence intact; model/reasoning selects deleted) |
| Frågor: "Fråga n", question, "Därför frågar jag: …", option cards with description, custom row, "Jag är osäker — välj åt mig", "Bekräfta svaret", footnote; answered chips with Ändra | `BuilderQuestionScreen.svelte` + restyled `FlowAIBuilderQuestion.svelte` (all shapes: single, multi, custom text, runtime-field editor, schema_direction filter); every shape now selects then confirms |
| Samtal (Sheet): "Samtalet — Ändra ett svar utan att börja om", transcript, "Ändra det här svaret", footnote | `BuilderConversationSheet.svelte` + slimmed `FlowAIBuilderChat.svelte` (transcript + optional composer); pending question is read-only there, summaries compact |
| Bygger interim (skeleton + narration from real status events) | `BuilderBuildScreen.svelte` (slice 4 completes) |
| Reply/wait state (assistant prose without a question) | `BuilderReplyScreen.svelte` (not in the design; needed for prose turns) |
| Turn recovery / stream error alert (kept from old chat) | `BuilderTurnAlert.svelte` on every screen |

Deviations (with reasons): no "Eneo föreslår" preselection (no recommendation field in the contract);
"Jag är osäker — välj åt mig" sends a free-text delegation reply — the server records explicit uncertainty
and turns its default into a visible assumption in Bekräfta; "Fråga n" without "av N" (question budget is
server-owned and architecture questions can exceed 3); the planner model/reasoning selectors are gone and
the client no longer sends model_id (server default) nor gates sending on the model list; a new empty
builder visit no longer resumes drafts (the Flöden list owns drafts; `?session=` resumes one).
Deleted: FlowAIBuilderTaskPane, BoundedLog, PhaseIndicator, DraftRecovery, ModelSelect, ReasoningSelect
(+ their tests and 30 orphaned message keys). `tests/ai-builder-layout.spec.ts` rewritten for the new shell
(rail, peek, sheet, task composer, 375 px rail, reduced motion) — to be run against the e2e stack in slice 5.

## Slice 3 — Bekräfta (contract card, re-arm, attachments) — `f9868e55a`

Screenshot: `screenshots/slice2/bekrafta-interim-1440x900.png` is superseded; new card verified in the browser
(chips → card → confirm → build → plan → peek back shows the confirmed read-only card).

| Design element | Implementation |
|---|---|
| Accent header "Så här har Eneo förstått uppgiften" + lead | `BuilderConfirmScreen.svelte` header |
| "Uppdaterad — bekräfta igen" warning | `stale` (an earlier version confirmed, latest not) |
| "Inga frågor behövdes — allt fanns i din beskrivning." | `noQuestions` |
| Summary paragraph, "Du bad om" quote, "Beslut från dina svar" dl + Indata/Utdata + Bifogade filer | dl rows; attachments from `session.attachments` |
| Antaganden (n) collapsed with first line | collapsible |
| Footer "Inget skapas i det här steget." + [Ändra svaren] [Stämmer — utforma planen]; confirmed state "Bekräftad" | footer; read-only after the build starts |
| Bygger: "Bekräftad uppgift: … Visa" recap + slow note | `BuilderBuildScreen` (`confirmedLine`, 45 s slow note) |

Deviations: per-row "Ändra" (inline select) is not possible — key_decisions are prose with no structured
edit payload; instead the answered-question chips above the card reopen a question, and "Ändra svaren" opens
the Samtal composer with a hint (a prose change re-discloses a new version). "Innehåll som rapporten ska bevara"
field chips (add/remove) omitted — `resolved_requirements` carries slot ids without human labels and no edit
payload. **"Jag är osäker — välj åt mig" removed** after live verification: the server re-asked the same
question (no delegation semantics for architecture-impact questions) → a backend follow-up
(`recommended_option_id` + delegation) is needed before this affordance can be truthful.
Driver: `isRequirementsSummaryConfirmed` no longer revokes on later prose; only a new requirements_version
re-arms (test updated). Deleted FlowAIBuilderRequirementsSummary(+test) and 8 keys.

## Slice 4 — Granska (+ Driver op-lock, plan preservation, conflict) — `011a8110a` (+ mobile pass `aeda8738f`, journeys `24990eb58`, edit-side e2e `3608c3b44`)

Built by an Opus implementer in lane/ai-builder-review (769107658), judged and cherry-picked onto the lane;
merged lane validated: `bun run check` 0 errors, eslint clean, vitest 21 files / 252 tests, i18n parity.
Screenshots: `screenshots/slice4/01–09` (fixture plan at 1440 + 375), `screenshots/responsive/*` (7 breakpoints).

| Design element | Implementation |
|---|---|
| Review card (AI-UTKAST pill, n steg, title, description) | `BuilderReviewScreen.svelte` |
| Three disclosures incl. tokens under "Körning och begränsningar" | disclosure snippet + `buildAIBuilderTokenUsageView` |
| Diagram / Detaljer, IN → nodes → UT, markers Granskning / per fil / artifact / Uppdaterat, model chip | `BuilderStepNode.svelte`, `BuilderStepDetails.svelte` |
| "N steg pausar för granskning" chips | reveals the step in Detaljer |
| Be om en ändring box (scope chip, Ctrl+Retur, Skicka) | `BuilderChangeRequest.svelte` → sendMessage with edit_context |
| Pending overlay + locked footer / "Planen uppdaterad" / decline banner "Uppfattat" | `service.isRevisingPlan`, revision diff, `service.latestReviewNote` |
| Sticky footer + [Ändra dina val] [Godkänn och skapa] → "Skapa flödet nu?" dialog | `BuilderApproveDialog.svelte`; create = one atomic call, toast, onapplied |
| Conflict card ("Utkastet ändrades någon annanstans") | `aiBuilderConflict.ts` → `service.conflict` (7 codes incl. stale_plan_revision on the SSE frame) |

Driver: `pendingOperation` generalized (creating/approving/applying/unpublishing) — every session-mutating command
blocked while any op is pending; `currentPlan` preserved through review turns (replaced only by a plan event; a
no-plan turn refreshes so latest_plan_id decides); `flowAIBuilderPlanRevisionDiff.ts` (name+content match —
plan_step_ref is positional per backend). Deleted PlanPane/StepCard/Canvas/TokenUsage (+tests).
Live-verified against :8150 (2026-08-17 00:00): plan renders; change request → pending overlay + locked footer;
the backend answered with a quality-check error → the plan STAYED visible with the error banner (plan
preservation confirmed live). Not yet verified live: "Godkänn och skapa" → toast → landing on the flow page (the
button was not found in the footer after the error banner — check whether the footer hides the primary while
`service.error` is set; do first thing tomorrow), a successful real change request, and the typed decline (edit
lane not on this base). No Codex commit gate for slice 4 (past the 00:10 launch cutoff) — run it tomorrow:
session `ai-builder-ui-redesign`, iteration 5, phase commit-gate, `git show 011a8110a`.

## Slice 4 follow-through (2026-08-17 morning) — `eb50f4519`, `355375abc`, `070ef535a`, polish `f288729c0`

Live-verified on :3131 against :8150 — "Godkänn och skapa" → alert dialog "Skapa flödet nu?" → "Skapa flödet" →
toast + landed on the new flow page with Publicera in the header (approval outcome as designed). Whole-plan
change requests still fail server-side on this base (quality checks); the UI keeps the plan and now explains
why the approve button is gone (`eb50f4519`, footer note `ai_builder_footer_plan_needs_update`).

Codex commit gate it.5 for `011a8110a` (high): changes_required, min 6 — three P1s, all verified and fixed in
`355375abc`:
- Backend never clears `latest_plan_id`; a reopened requirements flow discloses a new summary next to the old
  plan → `derivePhase` lets an unconfirmed disclosure outrank a loaded plan (plan stays loaded so reload lands
  on the same screen). The typed-decline half (session left `chatting`, approve unavailable) is backend-owned —
  the edit-lane's `decline_flow_change` must restore `awaiting_approval`; UI already projects it truthfully.
- The four plan operations now refuse to start while a turn streams (Driver-level `#planOperationBlocked`).
- Conflict recovery is one Driver op `recoverFromConflict()`: reload session + plan, then drop the conflict only
  on success (a persisted stream conflict was rehydrated by every refresh, so "Uppdatera" never cleared it).
Tests: fabricated plan-clearing test replaced by the real transition; held-stream test; recovery end-state
tests (Driver + DOM). e2e: edit apply goes through its alert dialog; layout fixture confirms its disclosure
(`070ef535a`). Polish batch (Opus, lane/ai-builder-polish 480afff05 → `f288729c0`): contrast tokens
(accent-stronger for 12–13 px links + focus rings), single-choice radiogroup roving tabindex + arrows/Home/End,
polite live region + heading focus per screen change, header column = review card width, chip/Samtal aria
labels, file input out of tab order, singular counts, copy table, `model.` prefix stripped as fallback.
Merged lane: check 0 errors, eslint clean, vitest 21 files / 260 tests, i18n parity 6280/6280;
Playwright journeys 3 + layout 8 + edit 4 (see run below).

Codex gate it.6 (verifying the it.5 fixes): changes_required, min 5 — two P1s and two P2s, all real, fixed in
`b374f3f9e`:
- the server can ask one more question during a review turn while keeping the plan → `derivePhase` follows an
  unanswered last question before summary/plan (the shell then picks the question screen);
- `recoverFromConflict` cleared the conflict when the session reloaded but the plan it named did not → it now
  requires `currentPlan.plan_id === session.latest_plan_id`;
- `revisePlan` bypassed the operation lock → new `revising` kind on the same lock;
- the header called a recorded-but-failed turn "not saved" → only a network error, worded as uncertainty
  ("Osäkert om det senaste svaret sparades"); the turn alert owns recoverable turns.
Deferred to the backend (unchanged, correctly owned there): a typed `decline_flow_change` must restore
`awaiting_approval` while keeping the plan; until then the review footer explains the missing approve action,
and now stays quiet when Eneo answered in prose (`latestReviewNote`).

Owner feedback landed in `b374f3f9e`: "Beskriv vad som ska ändras" on the confirmation opened the Samtal panel
on the right; the change box now sits inline under the summary card, the same component as under the plan
(one `BuilderChangeRequest` with per-surface title/example/placeholder/hint).

Rebased onto the new head 04f57b139 on 2026-08-17 09:15 (clean, no conflicts; the only schema.d.ts delta is
still this lane's `list_ai_builder_sessions` query params). Lane commit order for landing:
c1293412b · a85878518 · f6897ccd0 · 405cd551d · 1e653c977 · 927299989 · 4340e51fe · c2cde9004 · 5863709ae ·
4879d4d8c · e33b08220 · 1e10d8b38 · 6eaa67248 · 882179c29
(pre-rebase shas kept on backup/ai-builder-ui-pre-rebase).
Merged-lane validation on the new base: check 0 errors (3505 files), eslint clean, vitest 21 files / 262 tests
(ai-builder + flows routes), parity ok, Playwright journeys 3 + layout 8 + edit 4 = 14 green.

## Design sweep — every screen and all 15 Tillstånd (2026-08-17 11:20)

Walked the prototype state rail against the build: Skala · Skelett · Långsam · Misslyckades · Bekräfta igen ·
Ändring pågår · Ändrad plan · Nekad ändring · Detaljer · Bifogad fil · Inga frågor · Tom lista · Konflikt ·
Osparat · Normalläge, and the screens Flöden · Skapa · Ny uppgift · Frågor · Bekräfta · Bygger · Granska ·
Mobil. All are implemented. Column widths come from the design source (`width:min(100%,Npx)`): task 650,
frågor/reply 660, bekräfta/bygger 700, granska 860, header rail 1020, page cap 1600 — one step up above 1536px
because the prototype was drawn in a 1010px frame.

### Deviations, each with the reason

| Design element | What we do instead | Why |
|---|---|---|
| "Fråga 2 av 3" + progress meter | "Fråga N", no meter | `question_total` was dropped by the backend gate: any total undercounts (re-asked questions keep their index; some slots are decided outside the ask queue) |
| "—" rows for unsettled requirements | not shown | `key_decisions` only carries settled ones; `open_requirements` is queued as its own backend slice (confirmation-stability risk) |
| Steps fill in progressively during Bygger | skeleton → finished plan | the planner produces the whole proposal in one provider call; there is nothing truthful to stream per step |
| "Pausad" status + "Pausade" filter | three filters (Alla · Publicerade · Utkast) | no paused state exists in the product model — a flow is a draft or has a `published_version`. Prototype fiction; faking it would invent a state |
| "5 steg · ljud in, PDF ut" row subtitle | flow description | `FlowSparsePublic` has no step count or input/output type — backend adding `step_count`/`input_type`/`output_type` |
| «Du skrev "…"» quote on the recommended option | not shown yet | `recommended_option_evidence` lands with the UI-contract commit |
| "Innehåll som rapporten ska bevara" chip list | not shown yet | `named_content_fields` lands with the same commit, read-only (no add/remove contract yet) |
| Per-row "Ändra" on decisions | answer chips only | linking a row to its question by matching answer text can open the wrong question (Codex it.7 P1); `question_id`/`is_derived` lands with the same commit |
| "Avbryt" during Bygger | no cancel | no backend turn-cancel endpoint |
| "Högst tre frågor" on the task screen | "några korta frågor" | the budget is 0/1/3 and architecture questions may exceed it |
| Confirmation "Ändra" opens a select in the row | opens the question card above the summary | works for every question shape (multi-select, free text, file), which a row-level select does not |
| Samtal as a right-hand Sheet | a phase screen with "Tillbaka" | owner rejected the side-panel modal; the transcript is where you read and change an answer, so nothing behind it stays half visible |

### Accessibility

An audit runs against every builder screen (task, question, confirmation, plan, transcript) checking unnamed
controls, unlabelled fields, duplicate ids, dangling aria references, heading jumps, missing alt text and
role/state mismatches. It reports clean. Fixed along the way: the confirm action stays keyboard-reachable while
unavailable (a disabled button dropped the user out of the page), the single-choice group is one tab stop with
arrow keys and a screen-reader hint, the custom-answer row no longer names a panel that is not rendered, screen
changes are announced and take focus, and the app's own top-bar collapse control finally has a name
(`445a699d2`, outside the builder, kept separate so it can land alone).

## Contract wiring + polish (2026-08-17 midday)

The backend landed the four fields it owed (`6f315fee0`) and the sparse flow summary (`a20eebaeb`). Wired:

| Design detail | Field | Where |
|---|---|---|
| Per-row "Ändra" on the confirmation | `KeyDecisionPayload.question_id` / `is_derived` | reopens exactly that question, newest wording when it was asked twice |
| «Du skrev "…"» under the recommendation | `StructuredQuestionPayload.recommended_option_evidence` | below the option's description, only on the recommended row |
| "Fråga N" | `StructuredQuestionPayload.question_index` | no client fallback: a record without it has no number |
| "Innehåll som resultatet ska bevara" | `RequirementsSummaryPayload.named_content_fields` | read-only, no add/remove (no contract for it) |
| "5 steg · ljud in, PDF ut" row subtitle | `FlowSparsePublic.step_count/input_type/output_type` | falls back to steps alone, then to the description |

Codex gate it.8 blocked two of these until they were honest: the client was reconstructing a question number
that compaction can invalidate, and the named-content lead promised missing-value behaviour the payload does not
own. Both removed. It also caught `z.number()` accepting 0/1.5/−1 where the server requires an integer ≥ 1.

Polish pass (`a2d2e244c`): 22 strings rewritten out of the em-dash habit into plain Swedish (the design's own
dashes stay); the evidence quote moved below the option description; heading focus no longer scrolls its
container sideways; the canvas keeps the page inset below 640px, where cancelling it slid under the app shell's
rounded edge and clipped the first characters of every line. Impeccable detector clean; all seven animations
carry `prefers-reduced-motion`; no horizontal overflow at 375/1440; zero console errors; shadcn only.

## Every row of the contract is correctable (2026-08-17 evening)

Now based on `b251b080e`. Today's contract work is `aa0cabfe9`, `220fa15fb`, `1f1868e70`,
`c2236145a`, `83cd72e40`, `d8ab0de6e`, `af8174db1`, `a889518a7`, `eb31c8a42`; the Codex gate
`ai-builder-ui-it10` ran eight passes and ended **green, MIN_SCORE 8**. (Shas move whenever the lane
rebases; the commit subjects are stable.)

Byggspec §7 items 7 and 8. Found by running the design's own scenario against the live backend rather than
reading the code: when the classifier settles every slot from the description (no questions asked at all), the
confirmation card rendered four derived rows, **none** with an Ändra, under a heading that read "Beslut från
dina svar" three lines below "Inga frågor behövdes". The card's lead promises "Rätta direkt i listan om något
är fel" and the list had nothing to press.

| Design item | Now | Note |
| --- | --- | --- |
| §7.8 all three answers get Ändra | every decision row plus the input/output rows | answered rows reopen their question; derived rows open the change box scoped to that topic |
| §7.8 «följer av dina svar» only where derived | under the value it explains, and only when some row was answered | in the topic column it read as part of the topic ("Slutresultat följer av dina svar") |
| §7.7 no duplicate rows | chips render only for answers no decision links back to | `key_decisions[].question_id` is null on many rows, so chips and rows are not the same set |
| §3 Svarschip h 30 · pad 0 11 · 12.5px, fältchip h 26 · pad 0 10 | applied | |
| Chip label ("Indata · Ljud") | from the decision the server links to the question | never parsed from the question wording |

The scoped correction keeps the user's words: the topic is a chip beside the box (the affordance the plan
screen already uses for a step), the textarea starts empty and Send stays disabled until the user types, and
`FlowAIBuilderDriver` composes the one message — "Jag vill ändra {topic}: {feedback}". An earlier attempt
prefilled the textarea; the Codex gate (session `ai-builder-ui-it10`, MIN_SCORE 5) was right that this makes
Eneo's words look like the user's and lets Send fire on text nobody wrote.

Two bugs surfaced while fixing it, both pre-existing:

- **Cancelling a question opened from the card destroyed the card.** `handleEditAnswer` sets `peekPhase = 0`
  and the confirm branch required `peekPhase === null`, so Avbryt fell through to the reply composer with the
  contract nowhere in sight.
- **`isEdit` never reached the confirmation screen**, so a question reopened from a decision row lost
  `current_option_id` — the safety property that keeps a live flow on the option it runs on today.

Edit mode otherwise wired: `current_option_id` (backend `8694ab341`) preselects the running option and marks
it "Används i dag".

The gate ran three passes (session `ai-builder-ui-it10`, xhigh; MIN_SCORE 5, 5, then pass 3). What it caught,
all verified in source before changing anything:

- **Prefilling the change box put Eneo's words in the user's mouth.** Send was enabled before the user typed,
  the starter survived into the next row's correction, and the driver wrapped it again into "Jag vill ändra:
  Ändra Planerad bearbetning till …". The topic became a chip beside the box instead, the draft stays the
  user's, and the driver composes one scoped message.
- **Correction state was split across parent and child.** A draft written under one row could be relabelled as
  another; the footer button and the box's own opener could leave a question editor open beside them. One
  owner now transitions `{open, topic, draft}` together and clears the words whenever the scope changes.
- **`isEdit` never reached the confirmation screen**, so a question reopened from a decision row lost
  `current_option_id` — the whole point of that field.
- **Cancelling that question destroyed the card** (pre-existing): opening it peeks at phase 0 and the confirm
  branch refused to render while a peek was set, so Avbryt landed on the composer.
- **A blank required fact was filtered out of the list**, letting the user confirm a contract with a hole in
  it. The row now says "saknas i sammanfattningen" and the confirm button refuses. The backend types those
  fields as plain `str`; the non-empty invariant was requested from its owner rather than mirrored blind in
  zod, where it would drop the whole event and take the card down.
- **The lead over-promised.** The attachment row has no honest action (a change request cannot remove a file,
  and the task screen is unreachable once the conversation starts), so the lead now says "Använd Ändra på
  raden, eller beskriv ändringen nedan".

- **A question the server asked again was never shown** (pre-existing, found by the gate refusing a fixture
  that dodged the real chronology). `isQuestionAnswered` counted any historical answer with that id, so after
  ask → answer → ask the client filed the new asking under the old answer: the question screen never
  rendered and discovery would wait on a question the user could not see. The backend models that sequence
  deliberately. An answer now answers the asking it followed. One layer out, the same failure: a refused
  question only forced the authoritative refresh when the turn carried a structured answer, so a re-ask
  provoked by a free-text correction ("Jag vill ändra: …") had nowhere to appear. Any refused question now
  settles against the server.

Also found by running the full frontend suite on this head: `INVALID_FILENAME` was renumbered to 9058 while
its message stayed on 9056 (`RESOURCE_GONE`), so an expired resource told the user to rename their file.
Remapped in the same slice.

## Two defects the owner hit while clicking through (2026-08-17, evening) — `21f216ab6`, `762a305e0`, `37b69b24c`, `e28006c0d`

Gate `ai-builder-ui-it11`: four passes, **green, MIN_SCORE 8**.

- **Sending a correction looked like nothing happened.** The box closed and the card sat there with
  disabled buttons; the screen stays on the confirmation for the whole turn, so there was no progress
  signal at all. The waiting state now takes the place of the box, with the builder's own skeleton and
  waiting language. It renders only when a correction is actually in flight — streaming plus a user turn
  after the newest summary — because `isStreaming` alone announced "Eneo räknar om sammanfattningen" while
  the *first* summary was still arriving, which describes a correction nobody made.
- **The last card sat flush against the bottom edge.** Not a padding value: 60px was declared and none of
  it reached the scroll. Each phase screen is a flex item in the stage column with default shrink, so it
  was squashed to the stage height (584px measured) while its content was 819px and spilled past its own
  padding box. `shrink-0` on all five screens; the confirmation screen measures 59px after its last card.

The same evening, the backend owner's question-ordinal durability commit turned out to raise inside
question dispatch for any session whose questions were stamped by an older build, killing every turn on
it (`planner_stream_failed` / `ValueError: a question already put to the user carries no number`). Found in
this preview's own logs from the owner's session, reported with the request id, fixed in `b251b080e`, and
verified: the dead session takes turns again with unnumbered questions, which the UI already renders
without inventing a number.

## Field naming and the fields the user defined (2026-08-17, late) — `4f5df9731`

- **"Tekniskt namn" fills itself from the label**, through `getSuggestedFlowFormFieldRuntimeKey` — the helper
  the flow's own field editor already uses, so the builder and the editor produce the same key, including
  reserved-word prefixing (`Text` → `user_text`) and de-duplication. Typing in the name takes it over.
- **The card now shows the fields the user defined.** The decision row could only say "Lägg till rikare
  metadatafält"; `Personnummer (prsnnmr)`, number, required sat unseen in the answer. They render as their own
  section under the decisions. Not hung off a decision row on purpose: in the session this came from, every
  `key_decisions` entry has `question_id: null`, so picking a row would have been a guess.

Still read-only: the design's × and "+ Lägg till fält" on `named_content_fields`. The backend owner is
building a typed `named_content_fields_edit` (full set plus the shown `requirements_version`, dedupe, cap 12,
stale-version refusal, `origin: "described" | "user"` on the projection, no planner call, new version). An
interim that prefilled the change box was offered and declined in favour of the real contract, so the chips
stay read-only rather than gaining a decorative affordance. The metadata area is also being redesigned; the
payload was kept at id/label so it can extend.

## Byggspec §14–17, the metadata slice (2026-08-17, night) — `4b64dc820`, `5d3ee8858`, `6e64054da`, `a52219284`

The designer's audit found the builder reinventing naming that already exists in `FlowFormSchemaEditor`.

- **§14** — the runtime name derives from the label through `getSuggestedFlowFormFieldRuntimeKey`, the flow
  editor's own helper (reserved heads, å/ä/ö, `_2` on collision). It shows as a copyable `{{ token }}`; the
  input to type one by hand lives behind "Visa tekniska namn", off by default — this screen's `power_user`
  gate. The flow editor's five name rules block confirmation with its own messages. The chip row no longer
  prints a runtime name.
- **§15.3** — the purpose dropdown has a visible label ("Hur fältet används"); options were already limited
  to list types.
- **§15.4 / §15.6** — the fields the answer created have their own section on the contract card, with the
  count, a chip per field carrying type and required, "det är inte något Eneo tar fram" to separate them
  from report content, and a way back into the question. Read from the answer that produced the summary
  being displayed; the durable source is the backend's queued `runtime_input_fields` projection (#67).
- **§16, partly** — chip walls capped (6 / 10) and the confirm button carries the list's count.
- **The row's Ändra opens its question.** A decision the server left unlinked finds its question through the
  slot label both carry (`topic`). The backend added that label to the field-collection question the same
  night so the metadata row is reachable.

Backend items from the same handoff landed on their side: the metadata question is now "Vad ska den som kör
flödet fylla i?" and its rationale says what the fields become, instead of repeating the question.

**Not built:** the rest of §16 — the collapsed row form with one row expanded at a time, search with a
"10 av 50 visas" counter, and paste-a-list / import-from-another-flow. A coherent slice with its own
interaction model, better gated on its own. The design's removable content chips wait on the
`named_content_fields_edit` contract being written now.

## Remaining

One design detail waits on a field the backend owner has queued: the attachment purpose on the file chip.
Everything else the design asks for is wired to a real contract field.

`StructuredQuestionPayload.topic` landed (`b3fcc447b`) and is rendered: an answer chip names what it settled
("Indata vid körning · Dokument · Ändra") from the first question, instead of waiting for the summary that
does not exist during discovery. `question_index` is now persisted at stamp time rather than recomputed from
message order, so a re-asked question keeps its number across compaction.

`RequirementsDisclosureContent.input_description` / `output_description` are non-empty at the model
(`5dacf5682`) and mirrored with `.min(1)` in the runtime schema. The blank-value presentation built earlier
in the day was deleted rather than kept: the contract forbids the state, so a violation is a loud parse
failure instead of a card that quietly explains itself.

`open_requirements` was descoped by the backend owner as always-empty by construction: the summary is only
emitted on a ConfirmRequirements decision, which is only allowed with an empty ask queue, so anything
unsettled is already an assumption. The card renders those under "Antaganden (N)".

Note for whoever lands these: "Give the correction one owner, and stop hiding a blank contract row" carries
one unrelated frontend repair alongside the builder work —
`INVALID_FILENAME` was renumbered to 9058 while its message stayed on 9056 (`RESOURCE_GONE`). It is named at
the end of that commit message.
