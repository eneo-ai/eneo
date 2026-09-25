# Accessibility in web-next

The accessibility standard for `frontend/apps/web-next`: the level we must
meet, the rules for building UI on this stack, how they are checked and what a
pull request needs before it merges. It applies to people and AI agents alike.
[AGENTS.md](AGENTS.md) has the short version; this file wins on detail.

## Required level

**WCAG 2.2 level A and AA, for all web-next UI.**

- **Law.** Eneo is used by public-sector organisations, so their deployments
  fall under _Lag (2018:1937) om tillgänglighet till digital offentlig service_
  (DOS-lagen), supervised by Myndigheten för digital förvaltning (Digg). Digg's
  guidance covers intranets too, and Eneo is used by municipal staff. The
  requirements are those of the harmonised standard EN 301 549, which for web
  content means WCAG 2.1 A and AA, and every service needs a published
  accessibility statement (_tillgänglighetsredogörelse_).
- **Upcoming standard.** EN 301 549 V4.1.1 (published 2 September 2026)
  aligns with WCAG 2.2. Until the European Commission cites it in the Official
  Journal (planned for October–November 2026), the legal reference stays
  V3.2.1, which is WCAG 2.1 AA.
- **Our decision.** We build to WCAG 2.2 AA. It includes everything WCAG 2.1 AA
  requires and adds, at A/AA: 2.4.11 Focus Not Obscured (Minimum), 2.5.7
  Dragging Movements, 2.5.8 Target Size (Minimum), 3.2.6 Consistent Help, 3.3.7
  Redundant Entry and 3.3.8 Accessible Authentication (Minimum). (WCAG 2.2
  retires 4.1.1 Parsing.)
- **Scope.** Every screen: public pages (login, activation, error pages), the
  app shell, chat, spaces and admin. Vendored code in `src/components/ui` and
  `src/components/ai-elements` renders in the product, so it is in scope. Both
  colour modes, both locales, desktop and touch widths.

Sources: [Digg: DOS-lagen och Diggs föreskrifter](https://www.digg.se/webbriktlinjer/lagar-och-krav/dos-lagen-och-diggs-foreskrifter),
[Digg: EN 301 549 och WCAG](https://www.digg.se/webbriktlinjer/lagar-och-krav/det-har-ar-en-301-549-och-wcag),
[AccessibleEU: EN 301 549 updated](https://accessible-eu-centre.ec.europa.eu/content-corner/news/european-accessibility-standard-en-301-549-has-been-updated-2026-09-07_en),
[European Commission: latest changes to the standard](https://digital-strategy.ec.europa.eu/en/policies/latest-changes-accessibility-standard),
[WCAG 2.2](https://www.w3.org/TR/WCAG22/).

## Definition of done

A pull request that changes UI in web-next is done when:

- [ ] `bun run check && bun run lint && bun run test` pass. They include the
      accessibility lint rules, the axe component tests and the colour contrast
      test.
- [ ] New or changed shared components (`src/components/composites`, shell,
      shared feature components) have an axe test: `expectNoAxeViolations`.
- [ ] A new route or screen is scanned in `tests/a11y.spec.ts`.
- [ ] The [manual test protocol](#manual-test-protocol) is done for the changed
      screens, and the PR's **Accessibility** section says so.
- [ ] No new suppressions or exclusions; if you fixed a baselined violation,
      the baseline was pruned ([Exceptions](#exceptions)).
- [ ] Every new string, including accessible names, exists in `sv` and `en`.

## Rules

Each rule names the WCAG success criteria it serves. Prefer Astryx components:
they implement the roles, states and keyboard patterns below. Where this file
says "Radix" it means the legacy shadcn primitives in `src/components/ui`.

### 1. Page structure and titles (1.3.1, 2.4.1, 2.4.2, 2.4.6)

- The shell renders the skip link as the first focusable element, then the
  header and navigation, then `<main id="main-content" tabIndex={-1}>`.
  `tests/a11y.spec.ts` checks the skip link. Screens render inside that main;
  never add a second `<main>`.
- One `h1` per page, from `PageHeader`. Section headings follow in order (`h2`,
  then `h3`); pick the level for the outline and style with props or classes.
  `EmptyState` takes `headingLevel`.
- Every route has a unique, translated title: `generateMetadata` from
  `pageTitle("key")` (`src/lib/page-metadata.ts`) gives "Titel · Eneo".
- More than one `<nav>` on a page: give each a translated `aria-label`.
- Lists are `<ul>`/`<ol>`, tables are `<table>` with `<th scope>`, never a grid
  of divs that looks like a table.

### 2. Keyboard and focus order (2.1.1, 2.1.2, 2.4.3, 3.2.1)

- Everything that works with a pointer works with the keyboard. Use `<button>`,
  `<a href>` and Astryx controls; never `onClick` on a `div` or `span`, never a
  positive `tabIndex` (lint).
- Focus order follows the visual order. Don't reorder interactive content with
  CSS (`order`, `flex-row-reverse`).
- Composite widgets (menus, tabs, listboxes, trees, grids) follow the
  [WAI-ARIA APG](https://www.w3.org/WAI/ARIA/apg/patterns/) keyboard patterns.
  Use Astryx or Radix; don't hand-roll roving focus.
- A scrollable area without focusable content inside (code block, wide table,
  log) gets `role="region"`, a translated `aria-label` and `tabIndex={0}` so it
  can be scrolled from the keyboard.
- When the focused element disappears (row deleted, dialog closed), move focus
  somewhere logical: the next row, the list heading or the trigger.
- Focus never moves by itself on page load or on input (no `autoFocus`; lint).
  Receiving focus or changing a value never navigates or submits.

### 3. Visible focus that is never hidden (2.4.7, 2.4.11, 1.4.11)

- Every focusable element shows a focus indicator with 3:1 contrast. Astryx
  draws a 2px `--color-accent` outline with a 3px offset: keep it.
- Custom focus styles use the full-strength ring: `focus-visible:outline-2`,
  `focus-visible:outline-offset-2`, `focus-visible:outline-ring`. Never an
  alpha ring (`ring-ring/50`, the legacy shadcn halo, is about 2:1 on white)
  and never `outline-none` without a replacement.
- The focused element is never covered by sticky or docked UI: the header, the
  docked chat composer, toolbars, toasts, cookie-style banners. Give the scroll
  container padding for them (`scroll-pt-*`, `scroll-pb-*` equal to the sticky
  element's height) so Tab and `focus()` scroll the element into the visible
  part. Check by tabbing through a long list with the sticky UI present.

### 4. Target size (2.5.8)

- Every pointer target is at least 24×24 CSS px, or has 24 px of free space
  around it (the spacing exception). Inline links in running text are exempt.
  Astryx element sizes (28/32/36 px) and shadcn `size="icon"` (36 px) pass;
  never go below `size-6` for an icon button.
- **Design standard: 44×44 px on touch layouts** (`pointer: coarse`).
  Astryx controls get it centrally; don't add sizes for them:
  - `eneo-theme.ts` → `adaptations` sets the element sizes
    (`--size-element-sm/md/lg`) to 44 px: buttons (icon-only ones are
    square), menu triggers, tabs, nav items, inputs and selectors. Segmented
    control items and checkbox, radio and switch rows get `min-height: 44px`.
  - `globals.css` (section 7) grows the transparent native input of checkboxes,
    radios and switches to 44 × 44; the theme cannot reach it.
  - A class that fixes a size (`size-10`, `h-8`) overrides the theme; give it
    `pointer-coarse:size-11` or drop it. Custom targets (links styled as
    buttons, legacy shadcn controls) use Tailwind's `pointer-coarse:` variant
    (`pointer-coarse:min-h-11`).
- Measured on real pages by axe (`target-size`) in `tests/a11y.spec.ts`.

### 5. Colour and contrast (1.4.1, 1.4.3, 1.4.11)

- Colours come only from theme tokens (`eneo/no-raw-color`). The theme's
  foreground/background pairs are verified in light and dark mode by
  `src/theme/eneo-theme.contrast.test.ts`: text 4.5:1, non-text 3:1.
- Text: `text-ax-text`, `-secondary` and `-tertiary` pass on every surface
  (`bg-ax-body`, `-surface`, `-card`, `-popover`, `-muted`, `-sunken`) and
  secondary also on hover, selected and pressed rows. Tertiary is not for
  pressed states or hover/selected rows on the body background (the sidebar);
  use secondary there. `text-ax-text-disabled` is only for disabled controls.
- Don't lighten text or icons with opacity (`opacity-60`, `text-ax-text/70`);
  the test can't see alpha modifiers. Use the next token instead.
- Form-control boundaries (inputs, selects, checkboxes, radios, switch tracks)
  use `border-ax-border-control` (3:1). Astryx controls and shadcn
  `border-input` get it from the theme. `border-ax-border` and
  `border-ax-border-strong` are decorative: dividers and container edges,
  never the only boundary of a control.
- Icons that carry meaning use `--color-icon-*` / `text-ax-*` status tokens;
  status dots come from `StatusLabel` / Astryx `StatusDot`.
- Colour is never the only signal: statuses have text (`StatusLabel`), links
  in running text are underlined, errors have text and an icon, selection has
  a check mark or shape, charts have labels or a table.
- Adding a colour token, or using one on a new surface? Add the pair to the
  contrast test. Never lower a threshold; change the token.

### 6. Zoom, reflow and text spacing (1.3.4, 1.4.4, 1.4.10, 1.4.12)

- Usable at 200% zoom and at 320 CSS px width (1280 px at 400%) without
  scrolling in two directions. Only content that needs two dimensions (data
  tables, code, diagrams) may scroll, inside its own region.
- No fixed heights on containers with text (`min-h-*`, not `h-*`); sizes in
  `rem`. Never disable pinch zoom or lock orientation.
- Text survives line height 1.5, paragraph spacing 2em, letter spacing 0.12em
  and word spacing 0.16em without clipping. `truncate` / `line-clamp-*` only
  when the full text is reachable another way (detail view, expandable text).

### 7. Motion (2.2.2, 2.3.1, 2.3.3)

- `prefers-reduced-motion` is honoured app-wide (`globals.css`); don't defeat it
  with `!important` animations. Motion is decoration, never the message.
- Anything that moves, blinks or auto-updates for more than 5 seconds can be
  paused. Nothing flashes more than three times per second.

### 8. Forms (1.3.1, 1.3.5, 2.5.3, 3.3.1–3.3.4, 3.3.7, 3.3.8, 4.1.2)

- Every control has a visible label that is its accessible name (Astryx
  `label` prop, or `<Label htmlFor>`). The accessible name starts with the
  visible text (2.5.3). A placeholder is a hint, never the label; controls
  without a visible label (search, the chat composer) get a translated
  `aria-label`.
- Related controls are grouped: `<fieldset>` + `<legend>` or `role="group"`
  with `aria-labelledby` (radio groups, checkbox lists).
- Instructions and formats come before the field (`description`,
  `aria-describedby`). Required fields say so in text, not only with `*` or
  colour.
- Personal data fields have `autoComplete` tokens (`email`, `name`,
  `username`, `current-password`, `new-password`, `one-time-code`; 1.3.5).
- Errors (3.3.1, 3.3.3): on submit, show the error as text at the field (Astryx
  `status="error"` with its message, or `aria-invalid` + `aria-describedby`),
  move focus to the first invalid field or to an error summary, and say how to
  fix it ("Ange en e-postadress, till exempel namn@kommun.se"). Keep what the
  user typed.
- Destructive or irreversible actions are confirmed (`ConfirmDialog`) or can
  be undone (3.3.4).
- Redundant entry (3.3.7): never ask for the same information twice in one
  process. Carry it over, prefill it or offer it for selection; going back
  keeps what was entered.
- Accessible authentication (3.3.8): login allows paste and password managers
  (`autoComplete="username"` / `"current-password"`, no paste blocking, no
  split code boxes without paste support) and never requires a cognitive test
  (no puzzle CAPTCHAs, no transcribing characters). SSO is fine.
- Changing a setting never navigates or submits unexpectedly (3.2.2). Autosave
  is fine when its status is announced (`SaveStatus`).

### 9. Dragging and pointer gestures (2.5.1, 2.5.2, 2.5.7)

- Every drag has a single-pointer alternative without dragging: file drop
  zones have a "Välj filer" button (`FileInput`, or a visible button that opens
  the file picker), reorderable lists have move up/down actions, resizable
  panels have buttons or keyboard resizing.
- No path-based or multi-finger gestures without a single-tap alternative.
  Actions fire on release (native buttons do this).

### 10. Status messages (4.1.3)

- Results of an action that don't move focus are announced politely: saved,
  copied, "3 filer uppladdade", search result counts. Use a toast (the sonner
  `Toaster` is a polite live region) or a `role="status"` region that is
  already in the DOM before the message is written into it.
- Urgent errors that block the task use `role="alert"`, sparingly. Loading
  uses `LoadingState` (a `role="status"` region); don't announce every spinner.
- Error toasts stay until dismissed; don't auto-hide information the user
  must act on (2.2.1).

#### AI chat

- The chat view announces short messages politely through Astryx `useAnnounce`
  (one shared live region, no hand-rolled `aria-live` elements): "Svaret är
  klart" when an answer finishes, the error when generation fails, "Verktyget …
  väntar på godkännande" when a tool needs approval. Use `useAnnounce` for other
  status messages in the app too. Never put `aria-live` on the message list or a
  streaming message: screen readers would read every token.
- The finished answer is readable in browse mode and identified as the
  assistant's message.
- While generating, the send button becomes a stop button in the same place,
  reachable by keyboard and named "Stoppa generering" (Esc may also stop, but
  not only Esc).
- Citations, sources, activity/tool steps and reasoning are real buttons or
  links in reading order, with names that say what they open ("Källa 2:
  <titel>"); expandable parts expose `aria-expanded`.
- Markdown output: tables have header cells, code blocks are named, focusable
  scroll regions with a named copy button, headings fit under the page outline
  (start at `h3`).
- Follow new tokens with scrolling only while the user is at the bottom; never
  move focus into new content. "Scroll to latest" is a named button.
- The composer has a persistent translated accessible name, and the keyboard
  hint (Enter sends, Shift+Enter adds a line) is visible or in its
  description.

### 11. Images and icons (1.1.1, 4.1.2)

- lucide-react icons are `aria-hidden` by default: keep icons next to text
  decorative.
- Icon-only buttons and links get a translated name that says what happens
  ("Ta bort samling"), via `aria-label` or `sr-only` text.
- Informative images: `alt={t("…")}`. Decorative images: `alt=""`.
  User-uploaded images: the entity or file name.
- Charts have a text alternative: a summary plus the data as a table.
- `EntityAvatar` is decorative next to a visible name; pass `label` when it
  stands alone.

### 12. Language (3.1.1, 3.1.2)

- `<html lang>` follows the next-intl locale (root layout). All UI text,
  including accessible names, alt text, titles and placeholders, comes from
  next-intl (`eneo/no-hardcoded-text`, `eneo/no-literal-accessible-name`).
  Swedish is the default; add every key to `sv` and `en`.
- Text in another language than the page gets `lang`: language names in the
  language picker, quoted foreign text, and model output when its language is
  known.
- Astryx's own strings come from its Swedish catalog through the provider.

### 13. Consistent navigation and help (3.2.3, 3.2.4, 3.2.6)

- Navigation, the profile menu and help (help center, support contact, the
  accessibility statement) sit in the same place and order on every page. The
  shell owns them; screens don't add their own variants.
- The same function has the same name and icon everywhere.

### 14. Dialogs, menus and popovers (1.4.13, 2.1.2, 2.4.3, 4.1.2)

- Every dialog is an Astryx `Dialog`, a native modal `<dialog>`: the browser
  makes the rest of the page inert, Esc closes (except `purpose="required"`),
  focus returns to the trigger, and the visible title is the dialog's name.
  The legacy shadcn `Dialog` and `AlertDialog` in `src/components/ui` keep
  their API but render Astryx Dialog, and return focus to the menu button
  when a menu item opened them; the legacy Radix popups inside them (Select,
  DropdownMenu, Popover, Tooltip) portal into the dialog. Toasts shown while
  any modal is open appear inside it, so they stay visible and announced.
- Let the dialog place initial focus: the title (alert dialogs: Cancel). No
  `autoFocus`; it runs before `showModal()` and does nothing.
- Menus are non-modal, the legacy shadcn `DropdownMenu` included (a modal
  Radix menu hides the page with `aria-hidden`, which strips Astryx buttons of
  their names). Menus that select something use radio or checkbox items so
  the state is announced (see `ThemeSwitcher`).
- Tooltips only repeat or supplement; essential information is never only in
  a tooltip. Hover and focus content can be dismissed with Esc and hovered.

### 15. Time limits and session expiry (2.2.1)

- A password session ends when its token expires. Before any timeout that can
  hit a user who is working, warn at least 20 seconds ahead and offer to
  continue; where continuing is impossible, keep unsaved input (drafts) and
  return the user to the same place after signing in (`next`).
- No other time limits on reading or acting.

### 16. Name, role, value (4.1.2)

- Custom controls expose their state: toggles `aria-pressed`, disclosures
  `aria-expanded` + `aria-controls`, the current page `aria-current="page"`,
  selected tabs `aria-selected` (Astryx and Radix set these).
- Ids are unique (`useId`), and `aria-*` references point at existing elements.
- Don't add ARIA that native HTML already provides.

## How it is enforced

Run from `frontend/apps/web-next`.

| Check                                                | Catches                                                                       | Runs in                                          |
| ---------------------------------------------------- | ----------------------------------------------------------------------------- | ------------------------------------------------ |
| ESLint `jsx-a11y` (strict set)                       | Static markup errors: click handlers on divs, autofocus, invalid ARIA, labels | `bun run lint`, CI "Frontend (web-next)"         |
| ESLint `eneo/no-literal-accessible-name`             | Literal `aria-label`, `alt`, `title`, `placeholder`, … (not from i18n)        | `bun run lint`, CI "Frontend (web-next)"         |
| ESLint `eneo/no-raw-color`, `eneo/no-hardcoded-text` | Raw colours, untranslated text                                                | `bun run lint`, CI "Frontend (web-next)"         |
| `src/theme/eneo-theme.contrast.test.ts`              | Token pairs below 4.5:1 (text) or 3:1 (non-text), light and dark              | `bun run test`, CI "Frontend (web-next)"         |
| Vitest + axe (`src/test/axe.ts`)                     | Component markup: names, roles, ARIA, labels, lists, landmarks                | `bun run test`, CI "Frontend (web-next)"         |
| Playwright + axe (`tests/a11y.spec.ts`)              | Real pages in light and dark mode, incl. contrast and target size; skip link  | `bun run test:e2e`, CI "Frontend E2E (web-next)" |
| [Manual protocol](#manual-test-protocol)             | Everything else: focus order, announcements, zoom, reading experience         | Every PR that changes UI                         |

Both axe checks use the WCAG 2.2 A/AA tags from `src/test/wcag.ts`. Automated
tools find only part of the problems; the manual protocol is not optional.

### ESLint

`eslint.config.mjs` enables `eslint-plugin-jsx-a11y`'s strict set for all
shipped TSX in `src/` (vendored primitives included; tests and the dev-only
chat mock excluded), plus:

- **Added:** `no-aria-hidden-on-focusable`, `lang`.
- **Configured:** `label-has-associated-control` looks three levels deep for
  label text (label + description spans) and treats the shadcn form
  primitives as controls.
- **Relaxed:** `no-noninteractive-tabindex` allows `tabIndex={0}` on
  `role="region"` (named scroll areas, rule 2) and `role="tabpanel"` (the
  WAI-ARIA tabs pattern). Everything else is as strict as upstream.
- Not enabled: `control-has-associated-label` (off in strict; it misreports
  controls inside labels). Button and link names are checked by axe instead.

**Baseline.** Violations that existed when the rules were introduced are
listed in `eslint-suppressions.json` (ESLint bulk suppressions, like
`apps/web`). ESLint ignores exactly that many violations per file and rule; any
new violation fails `bun run lint`. The baseline only shrinks:

- Fix, don't suppress. Never run `eslint --suppress-all` or `--suppress-rule`
  to make a new violation pass.
- After fixing a baselined violation, `bun run lint` fails with "There are
  suppressions left that do not occur anymore". Run
  `bunx eslint --prune-suppressions` and commit the smaller file.

### Component tests (Vitest + axe)

```tsx
// @vitest-environment jsdom
import { expectNoAxeViolations } from "@/test/axe";

const { container } = render(<PageHeader title="Ytor" />);
await expectNoAxeViolations(container); // document.body for open menus and dialogs
```

jsdom has no layout, so the helper skips `color-contrast`, `link-in-text-block`
and `target-size`; the contrast test and the page scans cover those.

### Page scans (Playwright + axe)

`tests/a11y.spec.ts` opens each key route, waits for real content (no
`aria-busy` skeletons left) and fails on any violation, in light and dark
mode. Add a route when you add a screen. Locally, run it against a dev server
with a seeded backend (see `playwright.config.ts`); in CI it runs on the
isolated e2e stack.

## Manual test protocol

For every PR that changes UI, on the screens it touches, in light and dark
mode:

1. **Keyboard only.** Unplug the mouse. Tab through everything: every control
   is reachable in a sensible order, shows a visible focus indicator that is
   never hidden behind sticky UI, and works with Enter/Space/arrows/Esc. Open
   and close every dialog and menu: focus is trapped inside and returns to the
   trigger. No keyboard traps.
2. **Screen reader smoke test.** VoiceOver on macOS (Cmd+F5, Safari) and
   iOS/iPadOS for touch layouts; NVDA on Windows (Firefox or Chrome) when you
   can. Check the page title, headings and landmarks (VoiceOver rotor, NVDA
   H/D), every control's name, role and state, and that status messages and
   errors are announced once.
3. **Zoom and reflow.** 200% and 400% browser zoom at 1280 px, and a 320 px
   wide viewport: nothing overlaps or is cut off, no horizontal scrolling
   except inside tables and code.
4. **Text spacing.** Apply the WCAG 1.4.12 spacing (a text-spacing bookmarklet
   or user stylesheet): no clipped or overlapping text.
5. **Reduced motion.** Turn on "Reduce motion" (macOS: System Settings →
   Accessibility → Display): nothing essential is lost, nothing keeps moving.
6. **Forced colours.** Windows contrast themes, or Chrome DevTools → Rendering
   → "Emulate CSS forced-colors: active": focus, control borders, icons and
   selected states stay visible. A state shown only as a background tint needs
   a `forced-colors:` fallback (border or outline).

Write what you checked in the PR's **Accessibility** section.

## Exceptions

Fix rather than suppress. If a violation can't be fixed in the PR (an Astryx or
Radix bug, or a fix the product owner has deferred), open an issue labelled
`a11y` and add a narrow, explained exception:

- ESLint: `// eslint-disable-next-line <rule> -- <reason> <issue link>` (in
  JSX: `{/* eslint-disable-next-line <rule> -- <reason> <issue link> */}`).
- Vitest: `expectNoAxeViolations(container, { disableRules: { "<rule>": "<reason> <issue link>" } })`.
- Playwright: `.exclude("<selector>")` or `.disableRules(["<rule>"])` on the
  `AxeBuilder`, with a comment giving the reason and the issue link.

Never lower a contrast threshold, add entries to `eslint-suppressions.json`, or
switch a rule off in `eslint.config.mjs` without changing this file in the
same PR and explaining why. Open `a11y` issues and the lint baseline are the
list of known deviations for the accessibility statement.

## Accessibility statement (tillgänglighetsredogörelse)

DOS-lagen and Digg's regulations require every organisation that offers a
digital service to publish an accessibility statement: its compliance status,
known deviations, how to report problems and how to contact Digg. The
organisation that deploys Eneo owns and publishes it, since each deployment is
that organisation's service.

web-next links to it when `ACCESSIBILITY_STATEMENT_URL` is set (see
[README](README.md#environment)): "Tillgänglighetsredogörelse" on the login
page and in the profile menu. When the navigation changes, the link moves with
it and stays in the same place on every page.
