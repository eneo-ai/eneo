# Eneo Flows — Plan Review ("Granska innan det skapas") · Engineering Handoff

**Scope:** Screen 4 of the AI flow-creation journey, as designed in turn 2 (artboards 2a–2j) and corrected by the production audit in turn 3 (3a–3h). This is a compilation and precision pass of the signed-off design — nothing in this document introduces new design.

**Source of truth:** `Plan Review — Skärm 4.dc.html`, sections `#t2` and `#t3`. Sign-off: `#3h` (2026-07-11).

**Design system:** Eneo Design System (binding). All colors, type, radii, shadows and component recipes come from the system tokens (`--accent-default`, `--border-input`, `--radius-md`, …). Root font size 15 px; 12 px text floor; Inter 400/500/700.

---

## 1. Layout contract

Normative. All thresholds are **container queries** measured on the page container (the app shell has a collapsible sidebar — never use viewport breakpoints).

### 1.1 Thresholds and pane sizing

| Container width | Layout | Left pane | Plan content | Notes |
|---|---|---|---|---|
| ≥ 1760 px | Split, capped workspace | 480 px (cap) | max-width 840 px | Workspace `max-width: 1760px; margin-inline: auto`. Split border **and both columns stay inside** the centered workspace; outer area is calm empty background. Header and phase-bar content align to the same 1760 px container. |
| ≥ 1400 px | Split | `clamp(380px, 37cqw, 480px)` | max-width 840 px | Growing screens get gutters and whitespace — **not** larger fonts, buttons, or a wider left pane. |
| 1180 – 1399 px | Split | `clamp(380px, 37cqw, 480px)` | max-width 800 px | 1366×768 @ 100 % baseline (artboard 2a). |
| **1040 – 1179 px** | **Split (corrected, B1)** | `clamp(340px, 37cqw, 480px)` | max-width 800 px (fits ≈ 620 at 1093) | Covers 1366×768 @ 125 % OS scaling (container ≈ 1093 px) — the priority municipal-laptop case. Artboard 3b. |
| 768 – 1039 px | Tabs `Uppgift / Plan` | — (becomes Uppgift tab) | max-width 800 px | Phase indicator degrades to text: „Steg 3 av 3 — Granska innan det skapas". Conversation opens as a Sheet. Artboard 2d. |
| < 768 px | Mobile single column, same tabs | — | full width, 16 px padding | Footer: composer + „Ändra dina val" + „Godkänn och skapa" (48 px, full width), `padding-bottom: env(safe-area-inset-bottom)`. Holds at 320 CSS px and 200 % zoom. Artboard 2e. |
| Left pane < 420 px | — | — | — | Syfte/Indata/Resultat switch from label-grid (88 px + 1fr) to stacked label/value pairs. |

### 1.2 Vertical space (height < 640 px, e.g. 1093×614)

Sacrifice order: task clamp 3 → 2 lines · „Varför Eneo föreslår detta upplägg" collapses · vertical gaps 22 → 14 px. **Never sacrificed:** the steps and the action bar. The design does not depend on the whole plan fitting above the fold — the plan pane owns its scroll.

### 1.3 Scroll owners per breakpoint

| Region | Split (≥1040) | Tabs (768–1039) | Mobile (<768) |
|---|---|---|---|
| Page | **Never scrolls** (`overflow:hidden` within shell) | Active tab content owns page scroll | Active tab content owns page scroll |
| Left pane content | Own `ScrollArea`, `tabindex="0"`, `aria-label="Uppgiftspanel"` | Part of Uppgift tab flow | Part of Uppgift tab flow |
| Plan pane content | Own `ScrollArea`, `tabindex="0"`, `aria-label="Planförslag"` | Part of Plan tab flow | Part of Plan tab flow |
| Conversation log | Own scroll, `max-height: min(40cqh, 280px)`, `role="log"`, `tabindex="0"` | Inside Sheet, internal scroll | Inside Uppgift tab, bounded internal scroll |
| Composer | Rests 56–72 px → grows on focus → cap 220 px → **internal** scroll in the text area | Same, in the full-width footer | Same, 44 px pill at rest |
| Dialogs / Sheets | `max-height: 100dvh`, internal content scroll; header + actions fixed inside | same | same |

`scroll-padding-block-end` on every scroll region = height of its fixed region + 16 px.

### 1.4 Sticky regions

| Region | Behavior |
|---|---|
| Action bar (footer) | Split: stuck to bottom of the **plan pane**. Tabs/mobile: full-width bottom. Opaque background, 1 px top border (`--border-default`), **no blur/transparency**, safe-area inset. |
| Composer | Stuck to bottom of the left pane (split) / part of bottom footer (tabs & mobile). |
| Phase bar | Stuck below the page header at all widths (text form < 1040… text form is used in the tab/mobile layouts; the full 3-step bar is used in split). |
| Focused elements | Never obscured: all focusables get `scroll-margin-block-end` equal to the fixed-region height. |

### 1.5 Collapse behavior per threshold

| Threshold | What collapses / changes |
|---|---|
| ≥ 1040 | Nothing. Antaganden + Konversation collapsed by default; task clamped to 3 lines (2 below 640 px height). |
| 768 – 1039 | Left pane → Uppgift tab · conversation → Sheet · global top nav folds into the shell menu · footer absorbs the composer. |
| < 768 | „Varför Eneo föreslår detta upplägg" collapses · Enkel/Avancerad moves to the ⋮ DropdownMenu · task rows stack · diagram nodes full width. |
| All widths | Long compounds break: `overflow-wrap: break-word; hyphens: auto` with `lang="sv"`. **Never horizontal page scroll.** Titles and step names wrap freely — never clipped. Only the task summary is clamped, and it always has an expander with the character count. Filenames: end-ellipsis + full name in tooltip/`title`. |

---

## 2. Component map

Status legend: **existing** = use the Eneo/shadcn primitive as-is · **composed** = assembled from primitives on this screen · **new pattern** = build once, reusable across the journey.

| Region | Primitive | Variant / size | States | Responsive | A11y semantics | Status |
|---|---|---|---|---|---|---|
| Page skeleton (header / phase / aside / plan / footer) | **semantic custom layout** (flex) | — | — | §1 thresholds | `header` `nav` `aside` `section` `footer` landmarks | new pattern |
| Enkel/Avancerad toggle | RadioGroup (segmented) | 13 px / 500, in page header, right | checked, focus-visible | ⋮ DropdownMenu on mobile | `role="radiogroup" aria-label="Läge"`; arrow keys; **mode switch loses no state** | existing |
| Phase indicator | custom `nav > ol` | check-circle 20 px · active dot ring · quiet number | done / active / upcoming | text form „Steg 3 av 3 — …" < 1040 | `aria-label="Förlopp"`, `aria-current="step"` on active `li`; not focusable | new pattern |
| Task summary + expander | custom + Collapsible trigger | 14 px body, 3-line clamp | collapsed / expanded | 2-line clamp < 640 h | expander is a `button aria-expanded`; focus stays on the button on toggle | composed |
| Syfte/Indata/Resultat, Beslut rows | custom definition grid (`dl`-style) | 13 px labels / 14 px values, 88 px + 1fr | — | stacks < 420 px pane | plain text; Avancerad adds mono field names | composed |
| Antaganden · Konversation · Varför (mobile) · Tekniska antaganden | **Collapsible** (one each — *not* Accordion; sections are independent, may be open simultaneously) | heading-style trigger 14 px/700 + count | collapsed / expanded | — | `button aria-expanded` + region | existing |
| Conversation log | ScrollArea + custom log | bounded `min(40cqh, 280px)` | has-new („NYTT" divider + „1 nytt" count) | Sheet 768–1039; inside Uppgift tab < 768 | `role="log" aria-label="Konversation med Eneo" tabindex="0"`; „NYTT" is DOM text; latest anchored; „Visa äldre (n)" loads back; no autoscroll while user scrolled up | new pattern („BoundedLog") |
| Refinement composer | Textarea + Label + Button + attachment list | rest 56–72 px, cap 220 px | rest / focus / counter (≥ 3 500) / error (4 000) / disabled (creating) | pill row on tabs/mobile | visible `<label>` ≥ 1040, else `aria-label="Be om en ändring"`; `aria-invalid` + `aria-describedby` on error; Ctrl/Cmd+Enter submits; draft + attachments persist per conversation (survive tab switch, mode switch, failures, reload) | new pattern („RefinementComposer") |
| Attachment rows | custom `ul > li` | 32 px row: file icon, name (end-ellipsis), size, remove | — | — | remove = 24×24 px button with descriptive `aria-label` | composed |
| Plan header | Badge + text | Badge info „AI-utkast" 11 px/700; meta 13 px | — | — | Badge is decorative-plus-text; trust copy is plain text | existing |
| Diagram/Detaljer switch | **Tabs** | segmented 12–13 px | active/inactive | — | roving tabindex, arrow keys; **`forceMount` + `hidden`** so both views keep state | existing |
| Step list (both views) | custom `ol > li` | node: 1 px border, radius 8, 24 px number chip (`--accent-dimmer`/`--accent-stronger`) | — | full-width nodes < 768 | it is a **list**, not cards; connector lines/arrows `aria-hidden` | new pattern („StepList") |
| Action bar | custom `footer` | secondary 36 px outline · primary 44 px (48 px mobile) | idle / creating (all disabled) / failed | full-width < 1040 | status span `aria-live="polite"`; buttons `white-space:nowrap` per DS recipe | composed |
| Failure banners | **Alert** | 1i: neutral surface + warning icon · 3c: `alert-warning` recipe | persistent | — | `role="status"` — no focus steal | existing |
| Creation confirmation | **Sonner** | single toast, green check + text | transient | — | `role="status"`; the **only** use of Sonner | existing |
| Mode-toggle explainer | Tooltip | first-visit hint | — | — | `aria-describedby` linkage | existing |
| Region boundaries | Separator | composer top edge, footer top edge | — | — | decorative | existing |
| Mobile overflow | DropdownMenu (⋮) | low-priority actions incl. mode toggle | — | < 768 only | menu semantics from primitive | existing |

**Must NOT be a Card:** the split panes, the phase bar, the diagram/step nodes, the action bar, the attachment rows, and any grouping that exists only to create spacing — use heading + whitespace + at most one Separator.

**ResizablePanelGroup is excluded.** Fixed clamped split. It may only be reintroduced with proven full keyboard support (focusable handle, arrow-key resizing, `aria-valuenow`) — not part of this build.

---

## 3. Semantics and focus

### 3.1 Heading tree

```
h1  AI-byggaren                          (page header)
├─ h2  Din uppgift                       (aside)
├─ h2  Beslut från dina svar             (aside)
├─ h2  Antaganden (4)                    (aside, Collapsible trigger)
├─ h2  Konversation (n meddelanden)      (aside, Collapsible trigger)
└─ h2  Beslutsunderlag som PDF           (plan title — NOT h1)
   ├─ h3  Så fungerar flödet
   ├─ h3  Varför Eneo föreslår detta upplägg
   └─ h3  Tekniska antaganden (3)        (Avancerad only)
```

No skipped levels. `aside` is `aria-labelledby` → „Din uppgift"; plan `section` is `aria-labelledby` → the plan title.

### 3.2 Tab order (split view)

1 Tillbaka · 2 Läge (radiogroup) · 3 left ScrollArea · 4 Ändra · 5 Visa hela beskrivningen · 6 Antaganden · 7 Konversation trigger · 8 conversation log · 9 Textarea · 10 Bifoga · 11 Skicka · 12 plan ScrollArea · 13 Diagram/Detaljer tabs · 14 Ändra dina val · 15 Godkänn och skapa.

The phase bar is **not** focusable (no interaction). No keyboard traps: Tab always exits a scroll region; the three scroll regions are themselves focusable and arrow-scrollable (B6). Sheet returns focus to its opener on close; Esc closes. Optional enhancement: F6/Shift+F6 pane cycling (left ↔ plan ↔ footer).

### 3.3 Labeling and roles

- Composer: visible `<label>Be om en ändring</label>` ≥ 1040 px; otherwise `aria-label="Be om en ändring"` (B4). Error text linked via `aria-describedby`.
- Conversation: `role="log"` — „NYTT" divider and the „1 nytt" count are DOM text, announced like any content (never color alone).
- Phase indicator: `aria-current="step"` on the active item, in both the full bar and the text form.
- Focus indicator everywhere: 3 px ring `border-stronger/50%` + darker border (≥ 3:1). Never `outline: none` without replacement.

### 3.4 Live regions (no-duplicate rule)

| Event | Mechanism | Politeness | Text |
|---|---|---|---|
| Plan updated after refinement | footer status span | polite | „Planen är uppdaterad" (visual: „Uppdaterad nyss" in plan header) |
| Wait-state phase advances | narration list container | polite | the phase line itself |
| Creating | footer status span (button text change announced via the same region) | polite | „Flödet skapas utifrån planen du godkände." |
| Generation / creation failure | Alert `role="status"` | (status) | banner title + body |
| Flow created | Sonner `role="status"` | (status) | „Flödet skapades. Du är nu i byggaren …" |

**Rule:** one event = exactly one announcement. Sonner is used only for creation success and never together with another announcement of the same event. Plan updates never steal keyboard focus or scroll position.

---

## 4. State diagram

```
[Flöden: Skapa]
   │  task text entered (≤ 4 000)         "Bygg manuellt" = secondary exit → manual builder
   ▼
(S1) CREATE DIALOG ──Fortsätt──► (S2) AI-BUILDER
                                   │ the dialog task text IS the first message —
                                   │ auto-submitted, never re-entered, no re-submission screen
                                   ▼
(S3) CLARIFICATION (0..n rounds) ── radio answers or free text via composer
   │ answers complete
   ▼
(S4) INTERPRETATION CONFIRM ("Så här har Eneo förstått uppgiften")
   │ „Ja, bygg planen"          ◄── „Ändra" loops within S3/S4
   ▼
(S5) PLAN GENERATING — wait state (artboard 1h)
   │  narrated substates mapped 1:1 to REAL backend phases:
   │  read → har läst · select → väljer steg · verify → kontrollerar · explain → skriver förklaring
   │  (a phase the backend cannot distinguish is NOT displayed; no simulated progress)
   │  composer stays open: text entered here is included in the plan
   ├─── failure ──► (E1) GENERATION FAILED — 1i banner, role="status"
   │                  „Planen kunde inte färdigställas" · draft + answers intact
   │                  [Försök igen] → S5 (late-abort footnote: parts may be redone)
   │                  [Visa konversationen] · composer as recovery path → S3
   ▼ success (plan fades in, 200 ms)
(S6) PLAN REVIEW (this screen) ◄────────────────────────────┐
   │                                                        │
   ├─ composer „Skicka" ──► (S7) PLAN UPDATING ── polite announce, no focus steal ──┘
   │     (approve is DISABLED while S7 runs — accidental approval impossible;
   │      refinement failure returns to S6 with composer text INTACT)
   ├─ „Ändra dina val" ──► reopens structured questions (S3 subset) ──► S7
   ├─ „Ändra uppgift" (Ändra) ──► edit original task ──► S7
   ▼
   „Godkänn och skapa" — THE single creation action (no „Tillämpa", no confirm dialog)
   ▼
(S8) CREATING — atomic approve+create
   │  button → „Skapar flödet …" · ALL inputs disabled · double-submit impossible
   ├─── failure ──► (E2) CREATION FAILED — 3c banner
   │                  „Flödet kunde inte skapas · Ingenting sparades."
   │                  creation is atomic: whole flow or nothing — no partial drafts
   │                  plan + composer draft + conversation untouched
   │                  footer primary becomes [Försök igen] (retry creates no duplicates) → S8
   ▼ success
(S9) DRAFT CREATED ──► transition to builder (200 ms fade, focus moves to flow title)
                        Sonner: „Flödet skapades. Du är nu i byggaren …"
```

Guards, restated: **no intermediate duplicate prompt submission** (S1 → S2 auto-submit) · **no second „Tillämpa"** during initial creation („Tillämpa ändringar" exists only later, for modifications to an existing flow) · **composer text is never discarded** on any failure edge · **approve is unreachable while a refinement generation is in progress**.

---

## 5. Copy table

All user-visible Swedish strings. Voice: Eneo speaks as „vi"/„Eneo", never „jag". Where Avancerad differs it is noted; otherwise identical.

### Header & phases

| Location | Svenska (Enkel) | Avancerad | English |
|---|---|---|---|
| Page title | AI-byggaren | = | The AI builder |
| Mode label + options | Läge · Enkel · Avancerad | = | Mode · Simple · Advanced |
| Phase 1 / 2 / 3 | Vi förstår din uppgift · Vi utformar lösningen · Granska innan det skapas | = | We understand your task · We design the solution · Review before it's created |
| Phase, narrow form | Steg 3 av 3 — Granska innan det skapas | = | Step 3 of 3 — Review before it's created |

### Left pane

| Location | Svenska (Enkel) | Avancerad | English |
|---|---|---|---|
| Section heading | Din uppgift | = | Your task |
| Edit-task action | Ändra | = | Edit |
| Task expander | Visa hela beskrivningen (3 984 tecken) | = | Show the full description (3,984 characters) |
| Definition labels | Syfte · Indata · Resultat | + mono field names, e.g. „(flow_input: text)", „(output: pdf)" | Purpose · Input · Result |
| Section heading | Beslut från dina svar | = | Decisions from your answers |
| Decision rows | Slutresultat: PDF-dokument · Omfattning: Ett underlag per körning | = | Final result: PDF document · Scope: One document per run |
| Collapsed sections | Antaganden (4) · Konversation (5 meddelanden) | = | Assumptions (4) · Conversation (5 messages) |
| New-message signals | 1 nytt · NYTT · Visa äldre (12) | = | 1 new · NEW · Show older (12) |

### Composer

| Location | Svenska (Enkel) | Avancerad | English |
|---|---|---|---|
| Label | Be om en ändring | = | Ask for a change |
| Placeholder | T.ex. «Lägg till en sammanfattning på första sidan» | = | E.g. "Add a summary on the first page" |
| Actions | Bifoga filer · Skicka | + model chip, e.g. „gpt-5.4-mini" | Attach files · Send |
| Hint | Ctrl + Retur skickar · Eneo uppdaterar planen, inget skapas. | = | Ctrl + Enter sends · Eneo updates the plan, nothing is created. |
| Counter (from 3 500) | 2 014 / 4 000 · Ctrl + Retur skickar | = | 2,014 / 4,000 · Ctrl + Enter sends |
| Over-limit error | 4 032 / 4 000 tecken — korta ned för att kunna skicka | = | 4,032 / 4,000 characters — shorten to be able to send |
| Over-limit tip | Tips: långa instruktioner kan också bifogas som fil. | = | Tip: long instructions can also be attached as a file. |
| Draft persistence note | Utkastet sparas lokalt — det överlever flikbyte, lägesbyte och misslyckade försök. | = | The draft is saved locally — it survives tab switches, mode switches and failed attempts. |

### Plan pane

| Location | Svenska (Enkel) | Avancerad | English |
|---|---|---|---|
| Badge + meta | AI-utkast · 3 steg · Ingenting är skapat ännu | + „3,9 tn tokens" | AI draft · 3 steps · Nothing has been created yet |
| Plan title + description | Beslutsunderlag som PDF — Tar emot en text vid körning och levererar ett beslutsunderlag som PDF med samlad översikt, rekommendation och vägval. | = | Decision memo as PDF — Receives a text at runtime and delivers a decision memo as a PDF with an overview, recommendation and options. |
| Section + intro sentence | Så fungerar flödet — Flödet bearbetar underlaget i tre steg och skapar därefter en PDF. | = | How the flow works — The flow processes the material in three steps and then creates a PDF. |
| View toggle | Diagram · Detaljer | = | Diagram · Details |
| Steps (plain language) | 1 Läs och strukturera underlaget · Text → Strukturerad information — 2 Skriv beslutsunderlaget · Strukturerad information → Textresultat — 3 Skapa PDF · Textresultat → PDF | + per step: model name (gpt-5-6-terra, pdf-renderer), raw types „Indata · Flödesindata → text • Utdata · json (schema: underlag_v1)", „(render_verbatim)", link „Visa prompt och kontrakt" | 1 Read and structure the material · Text → Structured information — 2 Write the decision memo · Structured information → Text result — 3 Create PDF · Text result → PDF |
| Rationale | Varför Eneo föreslår detta upplägg — Underlaget behöver först struktureras. · Fakta och bedömningar behöver hållas isär. · Resultatet ska vara ett läsbart PDF-dokument. | = | Why Eneo proposes this approach — The material needs structuring first. · Facts and judgments must be kept apart. · The result should be a readable PDF document. |
| Technical assumptions | — (not shown) | Tekniska antaganden (3) | Technical assumptions (3) |
| Update receipt | Uppdaterad nyss | = | Updated just now |

### Action bar & approve sequence

| Location | Svenska | English |
|---|---|---|
| Trust microcopy | Inget skapas förrän du godkänner. | Nothing is created until you approve. |
| Secondary / primary | Ändra dina val · Godkänn och skapa | Change your answers · Approve and create |
| Creating | Skapar flödet … · Flödet skapas utifrån planen du godkände. | Creating the flow… · The flow is being created from the plan you approved. |
| Live announce (refinement) | Planen är uppdaterad | The plan has been updated |
| Success toast | Flödet skapades. Du är nu i byggaren och kan testa eller justera. | The flow was created. You are now in the builder and can test or adjust. |

### Wait state („Vi utformar lösningen", artboard 1h)

| Location | Svenska | English |
|---|---|---|
| Title + expectation | Vi utformar lösningen — Brukar ta under en minut. Planen visas här när den är klar. | We are designing the solution — Usually takes under a minute. The plan will appear here when ready. |
| Phase lines (map 1:1 to backend) | Eneo har läst din uppgift och dina svar. · Eneo väljer steg och ordning (Prövar ett upplägg i tre steg — strukturera, sammanställ, skapa PDF.) · Eneo kontrollerar att stegen hänger ihop. · Eneo skriver förklaringen i klarspråk. | Eneo has read your task and answers. · Eneo is choosing steps and order (Trying a three-step approach — structure, compile, create PDF.) · Eneo is checking that the steps fit together. · Eneo is writing the plain-language explanation. |
| Composer during wait | Lägg till krav medan Eneo arbetar … · Det du skriver nu tas med i planen. | Add requirements while Eneo works… · What you write now is included in the plan. |
| Footer note | Du kan fortsätta skriva till vänster under tiden — inget skapas förrän du har granskat och godkänt. | You can keep writing on the left meanwhile — nothing is created until you have reviewed and approved. |

### Failure states

| Location | Svenska | English |
|---|---|---|
| Generation failure (1i) | Planen kunde inte färdigställas — Kontakten med AI-tjänsten bröts medan planen togs fram. Din beskrivning och dina svar finns kvar — inget har gått förlorat, och inget flöde har skapats. · [Försök igen] [Visa konversationen] · Om avbrottet skedde sent kan delar av arbetet göras om vid ett nytt försök. Det påverkar inte innehållet i planen. · Du kan också förtydliga uppgiften innan du försöker igen. | The plan could not be completed — The connection to the AI service was interrupted while the plan was being prepared. Your description and answers remain — nothing is lost, and no flow has been created. · [Try again] [Show the conversation] · If the interruption happened late, parts of the work may be redone on retry. It does not affect the plan's content. · You can also clarify the task before trying again. |
| Creation failure (3c) | Flödet kunde inte skapas — **Ingenting sparades.** Skapandet görs i ett steg — antingen skapas hela flödet eller inget alls, så det finns inget halvfärdigt flöde i listan. Planen och dina svar är kvar precis som du lämnade dem. · Ett nytt försök skapar inte dubbletter. Kvarstår felet, kontakta systemförvaltningen och ange tidpunkten. · footer: Planen är oförändrad. · [Ändra dina val] [Försök igen] | The flow could not be created — **Nothing was saved.** Creation happens in one step — either the whole flow is created or nothing at all, so there is no half-finished flow in the list. The plan and your answers remain exactly as you left them. · A retry creates no duplicates. If the error persists, contact system administration with the timestamp. · footer: The plan is unchanged. · [Change your answers] [Try again] |

### Tabs & mobile

| Location | Svenska | English |
|---|---|---|
| Tab labels | Uppgift · Plan | Task · Plan |
| Compact meta (mobile) | 3 steg · Inget är skapat | 3 steps · Nothing created |

**Glossary (old → new), already applied:** „Så här tolkade jag det" → „Så här har Eneo förstått uppgiften" · „Därför föreslås denna plan" → „Därför/Varför Eneo föreslår detta upplägg" · „Rendera PDF" → „Skapa PDF" · „Tillämpa" → „Godkänn och skapa" (at initial creation) · „AI-UTKAST" → „AI-utkast" · „Föreslå planändring" → removed (the composer is that path) · „Granska krav" → „Ändra dina val".

---

## 6. Enkel/Avancerad matrix

**The page structure is identical in both modes.** Avancerad reveals in place; nothing moves, appears in a new location, or reorders. Mode is global and persists across the journey; switching loses no state (drafts, scroll, open sections).

| Element | Enkel | Avancerad |
|---|---|---|
| Tokens chip („3,9 tn tokens", plan header) | hidden | shown |
| Model names per step (gpt-5-6-terra, pdf-renderer) | hidden | shown (mono, right of step) |
| Raw types & routing („Flödesindata → text", „Utdata · json", „render_verbatim") | hidden — plain-language types only („Text → Strukturerad information") | shown in step meta |
| Schema references („schema: underlag_v1") | hidden | shown |
| „Visa prompt och kontrakt" per step | hidden | shown |
| Tekniska antaganden (3) — plan side | hidden | shown (collapsed) — the **only** assumptions section besides the left pane's „Antaganden (4)"; never two sections with the same label |
| Composer model picker chip | hidden | shown |
| Technical field names in task rows („flow_input: text") | hidden | shown |
| Everything else (layout, headings, actions, steps, rationale, trust copy, states) | identical | identical |

---

## 7. Implementation conditions (from sign-off 3h — travel with this spec)

> Designen är redo för implementation på tre villkor:
> 1. Reglerna R1–R10 (§1, §3 här) och komponentkartan 3g (§2 här) behandlas som **bindande, inte vägledande**.
> 2. Väntlägets skeden kopplas till **verkliga backend-faser** och skapandet bekräftas **atomiskt i API-kontraktet** — annars faller väntläget (1h) respektive felbannern (3c). Ett skede som inte kan särskiljas visas inte; ingen simulerad framdrift. Om atomiskt skapande inte kan garanteras måste felbannern i stället säga exakt vad som skapades och länka till det — den varianten kräver nytt designbeslut, gissa aldrig.
> 3. Placeholder-kontrasten (`--text-placeholder`, under 4,5:1) eskaleras till designsystemets ägare som **separat ärende** — den ändras inte i denna leverans och ingen obligatorisk information får bäras av placeholders.

Villkor 1–2 är implementationsdisciplin, inte öppna designfrågor.

---

## 8. Asset list — which artboard to reference

All in `Plan Review — Skärm 4.dc.html` (anchor ids):

| Build part | Reference artboards |
|---|---|
| Split-view baseline, spacing, hierarchy | **2a** (1366×768 Enkel — primary implementation baseline), 2b (1440 — whitespace scaling) |
| Corrected 125 %-scaling split (B1) + vertical sacrifice order | **3b** (1093×614) — normative over 2a where they differ |
| Ultrawide workspace cap | 2c (2560×1440) |
| Tab layout (768–1039) | 2d (1024) |
| Mobile | 2e (390) |
| Content stress: long task, 6 steps, 12 assumptions, scroll ownership | 2f |
| Conversation expanded (BoundedLog) + composer focus growth | 2g |
| Composer stress: 2 000 chars + attachments (B5) | 3d |
| Avancerad reveal-in-place | 2h (1440 Avancerad) |
| Approve sequence (click → creating → builder) | 2i |
| Creation-failure banner (B2) | 3c |
| Generation wait state | 1h |
| Generation failure | 1i |
| Validation error (over limit) | 1f |
| Semantics, tab order, live regions | 3e |
| Layout + interaction rules | 2j + 3f (merged as §1/§3 here) |

---

*End of handoff. Questions that surface during implementation which touch structure, copy, or state semantics go back to design — do not improvise within the bound areas.*
