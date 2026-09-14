---
name: Eneo web
description: Nordic-clean product UI for Swedish public-sector AI work, recorded from the shipped flows and AI Builder screens.
colors:
  civic-blue: "oklch(46.98% 0.225 266.04)"
  civic-blue-deep: "oklch(41.56% 0.215 264.51)"
  civic-blue-wash: "oklch(95.43% 0.014 264.5)"
  paper: "oklch(100% 0 0)"
  linen: "oklch(95.06% 0.005 67.76)"
  linen-deep: "oklch(85.06% 0.01 72.65)"
  ink: "oklch(0% 0 0)"
  ink-secondary: "oklch(50.05% 0.005 78.28)"
  ink-placeholder: "oklch(56% 0.005 78.28)"
  rule: "oklch(20.02% 0 89.88 / 0.15)"
  rule-strong: "oklch(20.02% 0 89.88 / 0.25)"
  rule-faint: "oklch(20.02% 0 89.88 / 0.05)"
  moss-positive: "oklch(42.91% 0.125 144.03)"
  moss-positive-deep: "oklch(35.54% 0.095 143.84)"
  moss-positive-wash: "oklch(97.75% 0.021 134.08)"
  ochre-warning: "oklch(53.59% 0.11 78.05)"
  ochre-warning-deep: "oklch(46.42% 0.096 58.54)"
  ochre-warning-wash: "oklch(98.02% 0.041 101.07)"
  brick-negative: "oklch(55.99% 0.205 26.35)"
  brick-negative-deep: "oklch(47.49% 0.19 29.9)"
  brick-negative-wash: "oklch(96.34% 0.015 12.42)"
typography:
  headline:
    fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1.375rem"
    fontWeight: 800
    lineHeight: 1.25
    letterSpacing: "-0.025em"
  title:
    fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1.0625rem"
    fontWeight: 700
    lineHeight: 1.3
    letterSpacing: "-0.015em"
  question:
    fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1.1875rem"
    fontWeight: 700
    lineHeight: 1.375
    letterSpacing: "-0.02em"
  body:
    fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.9375rem"
    fontWeight: 400
    lineHeight: 1.6
    letterSpacing: "normal"
  section:
    fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.8125rem"
    fontWeight: 700
    lineHeight: 1.4
    letterSpacing: "normal"
  secondary:
    fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.8125rem"
    fontWeight: 400
    lineHeight: 1.6
    letterSpacing: "normal"
  label:
    fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.8rem"
    fontWeight: 500
    lineHeight: 1.25
    letterSpacing: "normal"
  pill:
    fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.8rem"
    fontWeight: 600
    lineHeight: 1.25
    letterSpacing: "normal"
rounded:
  sm: "0.375rem"
  md: "0.5rem"
  callout: "9px"
  lg: "0.75rem"
  pill: "9999px"
spacing:
  xs: "0.25rem"
  sm: "0.5rem"
  md: "0.75rem"
  lg: "1.125rem"
  xl: "1.375rem"
  section: "1.5rem"
  column-narrow: "41.25rem"
  column: "43.75rem"
  column-wide: "53.75rem"
components:
  button-primary:
    backgroundColor: "{colors.civic-blue}"
    textColor: "{colors.paper}"
    typography: "{typography.label}"
    rounded: "{rounded.md}"
    height: "2rem"
    padding: "0 0.625rem"
  button-primary-hover:
    backgroundColor: "{colors.civic-blue-deep}"
    textColor: "{colors.paper}"
  button-outline:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.md}"
    height: "2rem"
    padding: "0 0.625rem"
  button-outline-hover:
    backgroundColor: "{colors.linen-deep}"
    textColor: "{colors.ink}"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.md}"
    height: "2rem"
    padding: "0 0.625rem"
  button-link:
    backgroundColor: "transparent"
    textColor: "{colors.civic-blue-deep}"
    typography: "{typography.label}"
  chip-answer:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    typography: "{typography.secondary}"
    rounded: "{rounded.pill}"
    height: "1.875rem"
    padding: "0 0.625rem"
  chip-field:
    backgroundColor: "{colors.linen}"
    textColor: "{colors.ink}"
    typography: "{typography.secondary}"
    rounded: "{rounded.pill}"
    height: "1.625rem"
    padding: "0 0.625rem"
  card:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.lg}"
    padding: "1.125rem 1.25rem 1.25rem"
  card-contract-header:
    backgroundColor: "{colors.civic-blue-wash}"
    textColor: "{colors.ink}"
    typography: "{typography.title}"
    padding: "0.875rem 1.25rem"
  input:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.md}"
    height: "2rem"
    padding: "0.25rem 0.625rem"
  callout-status:
    backgroundColor: "{colors.ochre-warning-wash}"
    textColor: "{colors.ochre-warning-deep}"
    typography: "{typography.secondary}"
    rounded: "{rounded.callout}"
    padding: "0.625rem 0.875rem"
  callout-receipt:
    backgroundColor: "{colors.civic-blue-wash}"
    textColor: "{colors.civic-blue-deep}"
    typography: "{typography.secondary}"
    rounded: "{rounded.callout}"
    padding: "0.625rem 0.875rem"
  option-row:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "10px"
    padding: "0.75rem"
  option-row-selected:
    backgroundColor: "oklch(46.98% 0.225 266.04 / 0.07)"
    textColor: "{colors.ink}"
---

# Design System: Eneo web

## Overview

**Creative North Star: "The Well-Run Reception Desk"**

Eneo's interface behaves like the front desk of a well-run Swedish public
institution: light, orderly, unhurried, and never showing off. Every screen is
one white sheet of work laid on a warm linen desk. The blue is civic, not
electric; it appears only where the reader has to act or where Eneo speaks in
its own voice (the contract card header, the recommended option, the primary
button). Everything else is ink on paper with hairline rules.

Density is moderate: a 15px root, a tight 12px floor, and short measured
paragraphs. Hierarchy comes from weight and hairline rules, not from size
jumps or colour. Progressive disclosure is structural: the Användare /
Avancerad split, collapsed chapters in the flow editor, and expandable
assumptions on the confirm card all keep the default view readable for a
first-time AI user while everything remains reachable.

Motion is a single scale of tokens and a single authored moment per state
change (the failure card opening, the created check drawing itself). Nothing
animates on a frequent action, and the OS reduced-motion preference wins
everywhere.

**Key Characteristics:**

- Paper on linen: white cards on a warm off-white page, separated by hairlines.
- One civic blue, used on well under a tenth of any screen.
- Weight-driven hierarchy inside a narrow type scale (12px to 22px).
- Content columns capped at 41 to 54rem and centred; no full-bleed dashboards.
- Status is said in words next to its colour; colour alone never carries meaning.
- Motion tokens from one scale; one authored moment per state change.

## Colors

A warm neutral ground carries one civic blue and three quiet semantic hues.

### Primary

- **Civic Blue** (`civic-blue`): the only brand accent. Primary button fill,
  the active phase pip, selected option borders, the recommended pill, the
  caret and text selection. Its deeper step (`civic-blue-deep`) is the text
  colour for links and link-buttons and the hover fill of the primary button.
  Its wash (`civic-blue-wash`) tints the contract card header, the "plan
  updated" receipt and the recommendation pill background.

### Neutral

- **Paper** (`paper`): every card, input and the app header. The working sheet.
- **Linen** (`linen`): the page ground behind the Builder screens and the
  secondary fill for chips, hover rows and the confirm card footer.
- **Linen Deep** (`linen-deep`): disabled surfaces and the outline-button hover.
- **Ink** (`ink`): body and heading text.
- **Ink Secondary** (`ink-secondary`): captions, row labels, helper text; the
  `text-secondary` utility, about 6:1 on paper.
- **Ink Placeholder** (`ink-placeholder`): placeholder text only, about 4.6:1.
- **Rule / Rule Strong / Rule Faint** (`rule`, `rule-strong`, `rule-faint`):
  the hairline family at 15%, 25% and 5% of dark grey. Faint rules divide
  rows inside a card; default rules bound cards; strong rules mark the
  contract card and the pips of unreached phases.

### Semantic

- **Moss Positive** (`moss-positive`, `-deep`, `-wash`): saved, confirmed,
  created, published. Always paired with a check icon and a word.
- **Ochre Warning** (`ochre-warning`, `-deep`, `-wash`): stale confirmation,
  quality warnings, published-lock banners, the failure card icon. The wash
  is the band colour of "Publicerad – kan inte redigeras".
- **Brick Negative** (`brick-negative`, `-deep`, `-wash`): destructive
  actions and hard errors only; never used for warnings.

### Named Rules

**The One Voice Rule.** Civic blue means "Eneo acts or recommends here". It
never decorates a heading, a divider or an icon that is not actionable.

**The Wash Rule.** A tinted surface (`*-wash`) always carries its own deep
text colour and a word; a tinted surface with grey text or with colour as the
only signal is a defect.

## Typography

**Display Font:** Inter (self-hosted, weights 300 to 800)
**Body Font:** Inter
**Label/Mono Font:** ui-monospace, only for runtime field tokens and file sizes

**Character:** One neutral grotesk at a 15px root. Hierarchy is carried by
weight (400 / 500 / 700 / 800) and by hairline rules rather than by size;
headings are tracked slightly tight, body stays at normal tracking.

### Hierarchy

- **Headline** (800, 1.375rem, -0.025em): the plan title on the review screen.
- **Title** (700, 1.0625rem, -0.015em): card headers such as the contract
  card; the page title "AI-byggaren" sits one step up at 1.25rem.
- **Question** (700, 1.1875rem, -0.02em): the one question on the question
  card; balanced with `text-pretty`.
- **Body** (400, 0.9375rem, 1.6): the summary sentence, assistant prose;
  measure capped at 64 to 72ch.
- **Section** (700, 0.8125rem): h3 inside cards ("Så här tolkade Eneo
  uppgiften"); the same size as secondary text, bolder.
- **Secondary** (400, 0.8125rem, 1.6): row labels, captions, footnotes.
- **Label** (500, 0.8rem or 0.875rem): button labels, chip text, form labels.
- **Pill** (600, 0.8rem, sentence case): the draft/change status pill on the
  review screen; step chips and recommendation tags sit on the same 0.8rem
  floor at 500 to 700.

### Named Rules

**The Twelve Pixel Floor.** No text renders under 12px; `text-xs` is remapped
to 0.8rem for that reason.

**The Weight Not Size Rule.** Adjacent levels differ by weight first; a size
step is added only when the reader must find the element from across the
screen (the question, the plan title).

## Layout

The app shell is a fixed left rail (about 17rem) with a white header row; the
work area scrolls. Builder and flow screens centre one column whose width is
per screen: 41.25rem for a question, 43.75rem for the conversation and the
contract card, 53.75rem for the plan review, each widened about 10% at the
2xl breakpoint. Horizontal page padding is 1.75rem, dropping to 1.25rem and
1rem at the lg and md breakpoints.

Inside a card: header 0.875rem by 1.25rem, body 1.125rem top and 1.25rem
sides and bottom, rows 0.625rem vertical with a faint rule above each, label
column fixed at 12.5rem from the sm breakpoint and stacked below it. Cards are
separated by 0.75rem to 0.875rem; sections inside a card by 1rem to 1.125rem.

Status rows (save state, conversation button) sit on the page title row.
The phase rail is a container query: three pips with labels above 40rem, a
single "steg n av 3" line below. On narrow widths the question card's action
row becomes a bar pinned to the bottom and touch targets grow to 44px.

## Elevation & Depth

Flat by default. Depth is tonal: paper cards on the linen ground, bounded by
hairline rules. Shadows are reserved for surfaces that float over content.

### Shadow Vocabulary

- **Rest** (`box-shadow: 0 1px 2px 0 rgba(0,0,0,.08)`, `shadow-xs`): the
  contract card, so the confirmation reads as the one sheet that matters.
- **Float** (`shadow-sm` / `shadow-md`): popovers, dropdown menus, the
  revising-overlay pill, the pinned action bar on narrow screens (upward
  blur).
- **Overlay**: dialogs use the 60% black overlay token, not a shadow.

### Named Rules

**The Flat-By-Default Rule.** Surfaces are flat at rest. A shadow marks
either the single most important sheet on the screen or something floating.

## Shapes

Softly rounded, never pill-shaped except for chips and pips. Buttons and
inputs use 0.5rem; cards, the question panel and dialogs use 0.75rem; inline
callouts and the diagram nodes use 9px to 10px so they nest visibly inside a
0.75rem card. Chips, pips, count badges and recommendation tags are full
pills. Borders are 1px hairlines; the selected option row adds a 1px inset
ring in civic blue rather than a thicker border. No coloured left borders; the
only left rule is the 2px neutral quote rule on "Du bad om".

## Components

### Buttons

- **Shape:** 0.5rem corners; heights 2rem default, 1.75rem small, 1.5rem xs.
- **Primary:** civic blue fill, white 0.8rem medium label, deep blue on hover;
  one per screen, right-aligned in the card footer or the sticky bar.
- **Outline:** paper fill, hairline border, ink label; the "Ändra" row
  action and secondary bar actions.
- **Ghost:** transparent, linen on hover; icon-only actions such as remove.
- **Link:** deep blue text, underline on hover; inline "Visa" / "Avbryt".
- **Destructive:** brick text on a 10% brick wash; never a solid red fill.
- **Focus:** 3px ring at 50% of the strong rule colour plus a ring-coloured
  border; custom controls use a 2px deep blue outline with 1 to 2px offset.
- **Active:** 1px downward translate; disabled at 50% opacity.

### Chips

- **Answer chip:** 1.875rem pill, outline, topic in secondary, answer in
  bold ink, a deep-blue "Ändra" word at the end; the one being edited fades
  to 60%.
- **Field chip:** 1.625rem pill, linen fill, ink label, type in 70% ink;
  required fields swap to the blue wash with deep blue text.
- **Count badge:** 1.125rem pill, linen-deep fill, bold 0.8rem.

### Cards / Containers

- **Corner Style:** 0.75rem.
- **Background:** paper on the linen page.
- **Shadow Strategy:** none, except the contract card (Rest).
- **Border:** hairline `rule`; the contract card uses `rule-strong`.
- **Internal Padding:** header 0.875rem × 1.25rem; body 1.125rem / 1.25rem.
- **Contract header:** blue wash background with a 25% blue bottom rule,
  title in ink and a one-line lead in deep blue.
- **Footer:** linen fill, hairline top rule, note on the left, primary on the
  right.

### Inputs / Fields

- **Style:** transparent fill, 1px `input` border (grey-300, about 3.7:1),
  0.5rem corners, 2rem tall, 0.875rem text.
- **Focus:** ring-coloured border plus a 3px 50% ring.
- **Error / Disabled:** brick border and 20% brick ring; disabled at 50%
  opacity on a linen fill.
- **Textarea:** same border language, 4rem minimum, 0.8125rem text inside the
  question card.

### Option rows (question card)

Radio or checkbox cards: 10px corners, hairline border, 0.75rem padding,
a 1.1875rem indicator (circle for single, rounded square for multi). Hover
turns the border strong and the fill linen; selected turns the border and
inset ring civic blue over a 7% blue wash. A recommended option carries a
blue-wash pill and, when available, the user's own words as evidence in a
quiet italic line with a 35% blue left rule.

### Callouts

Inline status blocks at 9px corners with 0.625rem × 0.875rem padding, a bold
lead word and a plain sentence: blue wash for receipts ("Planen är
uppdaterad"), ochre wash for stale or warning states, moss wash for success.
Text is always the wash's own deep colour.

### Navigation

- **Phase rail:** three 1.375rem pips joined by hairline rules; done and
  active pips fill civic blue (check / dot), upcoming pips are paper with a
  strong rule; labels 0.8125rem medium, bold when active, ink when
  reachable, secondary otherwise. Reachable pips get a linen hover and a 2px
  deep-blue focus outline.
- **Tabs:** the shadcn tab list at 2rem height, 0.8rem labels, used for
  Diagram / Detaljer and Byggare / Historik / AI-byggaren.
- **Editor stepper:** numbered 1.75rem pips with the active one filled blue,
  Föregående / Nästa on the right.

### Signature: the contract card

The "Så här har Eneo förstått uppgiften" card is the product's handshake: a
blue-wash header stating who understood what, a plain summary sentence, the
user's own request quoted behind a neutral 2px rule, a definition list of
decisions with an "Ändra" outline button per row, and a linen footer with
the one primary action. Everything Eneo assumed is folded behind
"Antaganden (n)" with the first assumption shown as a teaser.

## Do's and Don'ts

### Do:

- **Do** put one primary action per screen, right-aligned, and make every
  other action outline, ghost or link.
- **Do** say the state in words beside its icon and colour (Sparat, Bekräftad,
  Publicerad).
- **Do** cap measure at 64 to 72ch and keep captions at 0.8125rem secondary.
- **Do** use the motion tokens in app.css and one authored moment per state
  change, with `prefers-reduced-motion` honoured.
- **Do** write Swedish first in the institution's own register: full
  sentences, no exclamation marks, "du" form, no developer words on
  Användare screens.

### Don't:

- **Don't** use civic blue for decoration, headings or non-actionable icons.
- **Don't** render text under 12px or rely on the raw `--text-muted` shade
  for readable text.
- **Don't** add coloured left borders, gradients, glass or dark surfaces.
- **Don't** add an entrance animation to every section or a transition to a
  frequent action.
- **Don't** nest a card inside a card; use hairline rows and folds instead.
