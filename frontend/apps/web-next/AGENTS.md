# Building UI in web-next

Rules for humans and AI agents working in `frontend/apps/web-next`. The repo
root [AGENTS.md](../../../AGENTS.md) still applies (documentation and release
changes).

## In short

- **New UI uses [Astryx](https://github.com/facebook/astryx)** (`@astryxdesign/core`)
  with the Eneo theme. Look components up with the CLI before writing code.
- **shadcn/ui in `src/components/ui` is legacy.** Do not add shadcn components
  (`shadcn add`) or build new features on them; replace them with Astryx when
  you rework a screen. Mixing both during the migration is fine.
- **Layout** with Astryx `VStack`/`HStack`/`Layout` or Tailwind utilities.
- **Tokens only**: no raw colours, no `dark:` variants (both are lint errors in
  TS/TSX). Every colour, radius and shadow flips with the colour mode by itself.
- **Every UI string goes through next-intl** (Swedish is the default locale).
- **Accessibility is a requirement: WCAG 2.2 AA.** Follow the section below
  and [ACCESSIBILITY.md](ACCESSIBILITY.md).
- **Reuse before you build.** If an Astryx component or hook already does it,
  use it and delete our version. See [Reuse before you build](#reuse-before-you-build).
- Before you finish: `bun run check && bun run lint && bun run test`.

## Accessibility (required)

web-next must meet WCAG 2.2 A and AA (DOS-lagen, EN 301 549).
[ACCESSIBILITY.md](ACCESSIBILITY.md) is the standard: the rules per topic, the
manual test protocol and the exceptions process. Read it before building UI.

- Use Astryx components and native elements; they carry roles, states and
  keyboard support. Never put `onClick` on a `div`/`span`; no `autoFocus`, no
  positive `tabIndex`.
- Everything works with the keyboard, in visual order, with a visible 3:1
  focus indicator that sticky headers and the docked chat composer never cover
  (`scroll-pt-*` / `scroll-pb-*` on the scroll container).
- Accessible names, `alt`, `title` and `placeholder` come from next-intl, never
  literals (`eneo/no-literal-accessible-name`). Icon-only controls get a
  translated `aria-label`; decorative images get `alt=""`.
- Every form control has a visible label; errors are text at the field with a
  fix suggestion; login allows paste and password managers; personal data
  fields have `autoComplete`.
- Colours only from tokens. Text tokens pass 4.5:1 on every surface; form
  controls use `border-ax-border-control` (3:1); never lighten text or icons
  with opacity. Colour is never the only signal.
- Targets are at least 24×24 px; 44×44 px on touch layouts.
- Every drag has a button alternative (file drop zones have "Välj filer").
- Status changes are announced politely without moving focus: Astryx
  `useAnnounce` (never a hand-rolled `aria-live`/`role="status"` region) and
  toasts from `@/lib/toast` (lint-enforced; errors and warnings stay until
  closed). In chat: "svar klart", errors and tool approvals go through
  `useAnnounce`; never `aria-live` on streaming text.
- Works at 320 px width and 400% zoom, with reduced motion and in forced
  colours; parts in another language get `lang`.
- Shared components get an axe test (`expectNoAxeViolations` from
  `@/test/axe`); new screens get a scan in `tests/a11y.spec.ts`.
- Fix, don't suppress. `eslint-suppressions.json` is the baseline of old
  violations and only shrinks: after fixing one, run
  `bunx eslint --prune-suppressions`. Exceptions need a reason and an issue
  link (ACCESSIBILITY.md → Exceptions).
- Do the manual protocol (keyboard only, VoiceOver/NVDA smoke test, 200%/400%
  zoom, reduced motion, forced colours) and fill in the PR's Accessibility
  section.

## Look it up, don't guess

Run from `frontend/apps/web-next` (docs ship offline with `@astryxdesign/cli`):

| Command                                | Use                                                                           |
| -------------------------------------- | ----------------------------------------------------------------------------- |
| `bunx astryx search "<thing>"`         | Find components, hooks, docs and templates                                    |
| `bunx astryx component <Name> --dense` | Props, examples, theming targets                                              |
| `bunx astryx build "<idea>"`           | Composition kit (page + blocks) for a screen                                  |
| `bunx astryx template --list`          | Page and block recipes (`--skeleton` to read)                                 |
| `bunx astryx docs <topic>`             | `layout`, `tokens`, `color`, `typography`, `migration`, `styling`, `theme`, … |
| `bunx astryx manifest --json`          | Everything, machine-readable                                                  |

Do not run `astryx init`: it rewrites the ASTRYX block at the end of this file
with generic advice (unprefixed Tailwind names) that conflicts with ours.

## Reuse before you build

We are a small team, so every line we own is a line we maintain. Code that
ships must be release-ready: correct, accessible, tested and without dead ends.

- **Search Astryx first** (`bunx astryx search "<behaviour>" --type hook`, then
  `--type component`) before writing behaviour yourself: focus handling
  (`useFocusTrap`, `useFocusReturnVisibility`, `useListFocus`), shortcuts
  (`useHotkeys`), breakpoints (`useMediaQuery`), announcements (`useAnnounce`),
  copying (`useClipboard`), clickable cards with nested actions
  (`useClickableContainer`), truncation and overflow (`useTruncation`,
  `useOverflow`), table sorting, filtering, pagination and selection (the
  `Table` plugins), and the chat hooks (`useChatStreamScroll`,
  `useChatNewMessages`, `useStreamingText`, `useChatComposerTokens`,
  `useTriggerMenu`).
- **One implementation per behaviour.** When an Astryx hook or component
  replaces ours, delete our version and its tests in the same change instead
  of keeping both.
- **Keep ours only for a reason** — a CSP, accessibility or product constraint
  Astryx doesn't meet — and say why in a comment next to it.
- **Fix an Astryx gap in one place**, never at each call site: a wrapper in
  `src/components/astryx/` (lint sends imports there), or the bun patch for
  what a wrapper can't reach (How it is wired → Packages). Known gaps in
  Astryx 0.6.3:
  - `Switch` announces a hard-coded English "Loading" in its busy state: use
    `Switch` from `@/components/astryx/switch`, which leaves
    `isLoading`/`changeAction` out.
  - CommandPalette marks only a picked value as selected, and DateInput passes
    `nativePicker` on to the DOM: both patched.
  - BottomSheet skips `data-autofocus` when opening the dialog already focused
    its panel: focus the target yourself once the sheet is open (as
    `activity-sources.tsx` does).
  - A searchable Selector names its trigger by its label alone: give it an
    `aria-label` that includes the value (as `model-selector.tsx` does).
  - Table names every scroll region "Tabell", and absolutely positioned
    (screen-reader-only) cell content escaped its scroll box and widened the
    page: `@/components/astryx/table` names the region, and `globals.css`
    (section 9) makes the scroll box `relative`.
  - DateInput's calendar toggle is its 16 px icon, below the 24 px target
    size: `globals.css` (section 11) grows it. DateRangeInput's toggle
    (`astryx-date-range-input-toggle-icon`) is as small; extend section 11
    before using it.
  - `CodeBlock`/`CodeEditor` inject runtime styles the CSP blocks (code fences
    in answers render through Streamdown's `@streamdown/code` in
    `MessageResponse`), `useClipboard` writes text/plain only (the chat's
    rich-text copy keeps `navigator.clipboard.write`, commented), and the
    dictation hooks (`useChatDictation`, `useSpeechRecognition`) send audio to
    the browser vendor, so we don't use them.
- **Quality bar for every change:** small focused modules, typed APIs, no dead
  or duplicated code, tests for behaviour (including keyboard and axe), and
  `bun run check && bun run lint && bun run test` green.

## How it is wired

- **Packages** (beta, pinned exactly; upgrade together, then run
  `bunx astryx upgrade` and `bun run theme:build`): `@astryxdesign/core`,
  `@astryxdesign/theme-neutral`, `@stylexjs/stylex` (runtime only), dev
  `@astryxdesign/cli`. `frontend/patches/@astryxdesign%2Fcore@0.6.3.patch`
  makes CommandPalette mark the highlighted option as selected and keeps
  DateInput's `nativePicker` off the DOM. After an upgrade bun silently skips
  the stale patch and the guard tests in `src/components/astryx/` fail:
  recreate it with `bun patch @astryxdesign/core` (keep the diff free of bun's
  `.bun-tag-*` file), or drop a part Astryx has fixed.
- **Theme**: `src/theme/eneo-theme.ts` extends Astryx Neutral with the Eneo
  palette, radii, shadows and fonts; it is the single source of truth.
  `bun run theme:build` compiles it to `src/theme/eneo.{css,js,d.ts}`
  (generated and committed; never edit them; `bun run lint` fails when stale).
- **CSS** (`src/app/globals.css`): one cascade-layer order,
  `properties, reset, theme, base, astryx-base, astryx-theme, components, utilities`.
  Tailwind utilities are the top layer, so a utility in an Astryx component's
  `className` wins. The shadcn variables (`--background`, `--primary`, …) point
  at Astryx tokens, so unmigrated screens already use the Eneo look.
- **Providers**: `src/components/providers/astryx-provider.tsx` mounts the root
  `Theme`, Astryx's own strings in the active locale and `next/link` for Astryx
  links. Don't add another app-wide `Theme`; a nested `<Theme>` for one region
  is fine.
- **Colour mode**: next-themes owns it (the profile menu's `ThemeSubMenu` calls
  `setTheme`). Its
  nonce'd blocking script sets `.light`/`.dark` and `data-theme` on `<html>`
  before first paint; Astryx mirrors `resolvedTheme` after hydration. For other
  client-only values use `useHydrated()` (`src/lib/hooks/use-hydrated.ts`)
  instead of effect + setState.
- **Fonts**: Figtree for UI (`font-sans`), JetBrains Mono (`font-mono`), Source
  Serif 4 for assistant answers (`font-voice`). Type scale 14px / 1.2.
- **App shell** (`src/components/shell/`): Astryx `SideNav` (collapsed state in
  the `eneo_sidenav_collapsed` cookie, read by the layout), an admin mode under
  `/admin`, Astryx `MobileNav` below 768px and the ⌘K `CommandPalette`. A page
  header that carries its own phone menu button (the chat header) calls
  `useOwnMobileHeader()` so the shell hides its top bar while it is mounted, and
  opens the drawer with `window.dispatchEvent(new CustomEvent(OPEN_NAV_EVENT))`
  (`src/components/shell/routes.ts`).
- **Toasts**: only through `src/lib/toast.ts` (`no-restricted-imports` blocks
  `sonner` elsewhere). Errors and warnings don't time out; every toast has a
  close button; success and info close after 6 s. Sonner's stylesheet is
  static (see CSP). The stack rises clear of the focused element
  (`src/components/ui/toast-lift.ts`, WCAG 2.4.11); put `data-clear-of-toasts`
  on a docked group (like the chat composer) that should stay clear as a whole.

## Styling

1. Component props first (`variant`, `size`, `status`, …).
2. Then `className` with Tailwind utilities. Never `xstyle` or
   `stylex.create()`: this app has no StyleX compiler (Astryx ships compiled CSS).
3. Import Astryx from subpaths: `import { Button } from "@astryxdesign/core/Button"`.
   Interactive Astryx components are client components; server components can
   render them with serialisable props.
4. Icons: `lucide-react`.

New code uses the prefixed **`ax-*` bridge** to Astryx tokens. The legacy
shadcn names (`bg-background`, `text-muted-foreground`, `border-input`,
`bg-primary`, …) keep working. Do not import
`@astryxdesign/core/tailwind-theme.css`; its unprefixed names (`text-primary`,
`bg-accent`) mean something else here.

| Role                                      | Tailwind                                                                   | Token                                       |
| ----------------------------------------- | -------------------------------------------------------------------------- | ------------------------------------------- |
| App background behind the page panel      | `bg-ax-body`                                                               | `--color-background-body`                   |
| Page panel / surface, card, popover       | `bg-ax-surface`, `bg-ax-card`, `bg-ax-popover`                             | `--color-background-*`                      |
| Muted fill, sunken well                   | `bg-ax-muted`, `bg-ax-sunken`                                              | `…-muted`, `--eneo-color-background-sunken` |
| Text                                      | `text-ax-text`, `-secondary`, `-tertiary`, `-disabled`                     | `--color-text-*`                            |
| Accent (Eneo blue)                        | `bg-ax-accent text-ax-on-accent`, `bg-ax-accent-muted text-ax-text-accent` | `--color-accent*`                           |
| Hover, pressed, selected row, modal scrim | `bg-ax-hover`, `bg-ax-pressed`, `bg-ax-selected`, `bg-ax-scrim`            | `--color-overlay-*`, `--color-neutral`      |
| Borders (decorative)                      | `border-ax-border`, `border-ax-border-strong`                              | `--color-border*`                           |
| Form-control boundary (3:1)               | `border-ax-border-control` (= shadcn `border-input`)                       | `--eneo-color-border-control`               |
| Status                                    | `text-ax-{success,warning,error}`, `bg-ax-…-muted`, `text-ax-on-…`         | `--color-{success,warning,error}*`          |
| Categorical (amber = orange, rose = pink) | `text-ax-{blue,teal,purple,orange,pink}` + `bg-ax-{hue}-muted`             | `--color-text-*`, `--color-background-*`    |
| Radius                                    | `rounded-ax-{inner,element,container,page,chat}` = 6/10/12/18/20px         | `--radius-*`                                |
| Elevation                                 | `shadow-ax-{low,med,high}` (= `shadow-sm/md/lg`)                           | `--shadow-*`                                |

- Legacy radius classes follow the same scale: `rounded-sm` 6, `-md` 10
  (buttons, inputs), `-lg` 12, `-xl` 14, `-2xl` 18 (page panel), `-3xl` 20.
- Contrast is tested (`src/theme/eneo-theme.contrast.test.ts`): text tokens
  pass 4.5:1 on every surface, secondary also on hover/selected/pressed rows.
  Use `-secondary` instead of `-tertiary` on pressed states and on hover or
  selected rows over `body` (the sidebar). Add a pair to the test when you add
  a token or use one on a new surface.
- `border-ax-border` and `-strong` are decorative (dividers, container edges)
  and below 3:1. Inputs, selects, checkboxes, radios and switch tracks use the
  control border; Astryx controls get it from the theme's `components`
  overrides.
- `--color-*` custom properties are Astryx tokens (`--color-accent` is the blue);
  `--accent` is the shadcn hover tint. Don't mix them up in `var()`.
- Filled controls darken on hover with `bg-ax-hover-overlay` (an overlay on the
  fill), never a faded fill: `hover:bg-primary/90` drops text below 4.5:1.
- Focus rings are full strength (`focus-visible:outline-2
focus-visible:outline-offset-2 focus-visible:outline-ring`);
  `eneo/no-weak-focus-indicator` rejects translucent rings (`ring-ring/50`) and
  `outline-none` without a replacement.
- Page layout: the app shell (`src/components/shell/app-shell.tsx`) puts
  pages in a `bg-ax-surface rounded-ax-page` panel on the `bg-ax-body`
  background, and `main#main-content` is the scroll container. Pages don't
  set their own page background.

## Tables

- Use `Table` from `@/components/astryx/table` (lint enforces it; the other
  parts still come from `@astryxdesign/core/Table`), preferably data-driven
  (`data` + `columns`) with a width on every column: `pixel(n)` for fixed
  columns, `proportional(n)` for text (it keeps a 120 px minimum). Its plugins
  do sorting, filtering, pagination and selection.
- Every table is named: `aria-labelledby` its visible heading, or a translated
  `aria-label` (the wrapper's type requires one). The wrapper gives the
  table's horizontal scroll region the same name; Astryx would call it just
  "Tabell". Tables in answer content (Markdown) are the exception.
- In children mode (`TableHeader` / `TableRow` / `TableHeaderCell`), header
  cells truncate with `max-width: 0`, which cancels a plain `w-*`: the column
  collapses to its padding. Give a fixed column its min width too
  (`w-36 min-w-36`, which is what `pixel()` does). Percentage widths (`w-2/5`)
  and one column without a width, which takes what is left, work as they are.
- A column with a button or menu is at least `w-14 min-w-14`: on touch,
  Astryx controls are 44 px, plus the cell's 12 px start padding.
- Give a table with many columns a min width (`min-w-*` on `Table`). Below it
  the table scrolls sideways in its own focusable region instead of squeezing
  the columns.
- The page scans in `tests/a11y.spec.ts` fail on a column that collapsed.
- Legacy shadcn tables (`@/components/ui/table`) get the same keyboard-scrollable,
  named container from Astryx's `useScrollableArea`; name them the same way.

## Shared building blocks (`src/components/composites`)

- `PageHeader` — `title`, `description?`, `breadcrumbs?: {label, href?, current?}[]`
  (only `current` marks a crumb as this page; a crumb without `href` is a plain
  label), `actions?` (legacy `children` still work), `headingLevel?`,
  `headingRef?`, `tour?`.
- `EmptyState` — `title`, `description?`, `icon?`, `actions?` (or `children`),
  `headingLevel?` (1–4, default 2), `isCompact?`, `framed?` (dashed frame,
  default on).
- `LoadingState` — skeleton status region: `label?`, `rows?`,
  `variant?: "rows" | "text"`. Never show an EmptyState that says "Loading".
- `EntityAvatar` — coloured tile for spaces/assistants: `name`, `id?`, `tone?`,
  `src?`, `icon?`, `size?: sm|md|lg|xl`, `label?`. Colours via
  `entityTone()` / `entityAccent()` in `src/lib/entity-accent.ts`.
- `StatusLabel` — Astryx `StatusDot` plus text: `status`, `label`, `isPulsing?`.
- `ClientTime` — the one way to show a date: `value`, `format: "date" |
"date_long" | "date_time" | "relative" | "auto"` (`auto`, for lists: relative
  for the last week, then date and time). It renders in the viewer's time zone
  after hydration, so server and client HTML never disagree. Where the text
  must go into a label (an accessible name), `useClientTimeText` returns the
  same string.
- `ResourceCard` (`resource-tile.tsx`) — the card for assistants, apps and
  services (Astryx `ClickableCard`; its action menu is a sibling, so actions
  never open the card).
- `ConfirmDialog` / `ConfirmDialogControlled` — confirmations; put the
  controlled one outside menus.
- `ConfirmedSecretInput` — a secret typed twice (API keys, passwords) on
  Astryx fields: paste and password managers work, `autoComplete` is a prop,
  and "required" / "mismatch" errors show as text at the field.
- `SettingsGroup` / `SettingsRow` — legacy (shadcn-based); keep using them until
  a screen is migrated.

Shared behaviour outside `composites`:

- Removing something from a list: `useRemovalMutation` + `RemovalFocusScope`
  (`src/features/spaces/removal.tsx`) wait for the refetch, close the dialog and
  move focus with `rescueFocus` (`src/lib/focus-rescue.ts`) to the list's
  heading or panel, so focus never falls to `<body>`.
- Settings switches that save on toggle: `useSettingSwitch`
  (`src/features/admin/use-setting-switch.ts`) — optimistic, reverts on error,
  queues a press made during a save.
- Public pages (login, activate, …) use `PublicPage`
  (`src/app/(public)/public-page.tsx`): one `main`, one `h1` and the
  accessibility statement link.

## CSP

Production allows `<style>` elements only with the request nonce
(`style-src 'self' 'nonce-…'`); inline `style=""` attributes are allowed. It
has no `'unsafe-eval'`. Development allows both (`src/proxy.ts`), so only the
production build shows these violations. Never loosen the policy.

- The Eneo theme is pre-built, so `Theme` injects nothing. Never pass a runtime
  `defineTheme()` object to `<Theme>`; runtime themes inject `<style>` tags.
- Astryx parts that still inject `<style>` at runtime and are blocked in
  production: `CodeBlock`/`CodeEditor` syntax colours (don't use them; code
  fences render through Streamdown's `@streamdown/code`) and `DateInput`'s
  engine probe (falls back to a pointer heuristic). Chat's stream-scroll rule
  is server-rendered with the nonce in `src/app/layout.tsx`; Astryx skips its
  own injection when that element is there.
- Zod probes for eval on its first object parse; `src/instrumentation-client.ts`
  sets `jitless` so it doesn't (Zod's switch for strict CSPs).
- Sonner injects its stylesheet at runtime unless patched:
  `frontend/patches/sonner@2.0.8.patch` makes the Toaster import the static
  `sonner/dist/styles.css`. After a sonner upgrade bun silently skips the stale
  patch; recreate it with `bun patch sonner` (`src/components/ui/sonner.test.tsx`
  fails if a `<style>` appears).
- e2e specs import `{ expect, test }` from `tests/csp.ts`, which fails a test
  on any `securitypolicyviolation`, so the production build is checked too.
- A server component that needs the nonce reads `(await headers()).get("x-nonce")`
  (see `src/app/layout.tsx`).

## Text and i18n

- next-intl, locales `sv` (default) and `en`, chosen by the `NEXT_LOCALE` cookie.
  No hardcoded UI text (`eneo/no-hardcoded-text`).
- `src/lib/i18n/messages/{sv,en}.json` are generated; never edit them.
  `bun run i18n:convert` builds them from the SvelteKit app's catalogs
  (`apps/web/messages`) with `src/lib/i18n/extra/{sv,en}.json` merged over
  them, so web-next reuses apps/web's translations and `extra/` holds every
  string web-next owns.
- New or changed web-next text goes in `extra/sv.json` and `extra/en.json`
  (same keys in both; natural Swedish; append a block with your feature's
  prefix), then run `bun run i18n:convert`. To reword an apps/web string for
  web-next, add its key to `extra/`. Reuse existing keys when they fit.
- `bun run lint` (`scripts/check-i18n.mjs`) fails when `messages/*` is not
  what the converter writes, when `sv` and `en` have different keys, or when a
  literal `t("key")` is missing.
- So a change to apps/web's catalogs (e.g. merging `develop`) fails lint until
  someone runs the converter. That's on purpose: the check can't tell an
  apps/web change from a hand edit. Review the converter's diff: apps/web's new
  wording replaces ours unless the key is in `extra/`, and keys apps/web
  deleted are dropped. Lint lists those first ("It would drop these"): move the
  ones web-next still uses to `extra/` before you run it.
- Astryx's own strings (aria labels, pagination, …) come from its Swedish
  catalog through the provider; don't translate them yourself.

## Verify

- `bun run check` — route typegen and `tsc`.
- `bun run lint` — i18n drift, theme staleness, Prettier, ESLint. ESLint lints
  `src` with type information and fails on deprecated APIs
  (`@typescript-eslint/no-deprecated`): move to the replacement the warning names.
- `bun run test` — Vitest. `src/app/globals-css.test.ts` compiles `globals.css`
  and guards the layer order, the theme import, the Streamdown `@source`
  paths and the touch-target rules; `src/theme/eneo-theme.contrast.test.ts`
  checks the colour pairs; axe tests check component markup. Component tests
  opt into jsdom (`// @vitest-environment jsdom`) and use one harness in
  `src/test/`:
  - `renderInApp(ui, { queryClient?, appContext?, shell?, route? })` renders
    with the app's providers (next-intl in Swedish, Astryx, React Query with the
    app's 30 s staleTime and no retries, app and shell context); also
    `renderHookInApp` and `renderToHtml` (server render). Build app context with
    `testAppContext({ permissions: ["admin"], settings: { … } })`; don't mock
    `@/components/providers/app-context`.
  - Navigation: `vi.mock("next/navigation", () => import("@/test/navigation"))`,
    then the `route` option or `setRoute("/x?tab=y")`.
  - `src/test/setup-dom.ts` fills in what jsdom lacks and behaves like Chromium:
    `setViewport("phone" | "desktop" | {…})` drives `matchMedia`,
    `reportResize(el, { height })` drives ResizeObserver, `<dialog>` focuses
    its first focusable element on `showModal()`, nothing in a closed dialog
    takes focus, and `close` fires in a later task (advance fake timers).
- `bun run test:e2e` — Playwright against a running backend: the axe page scans
  in `tests/a11y.spec.ts` (light and dark, desktop and 390 px touch, with
  dialogs, menus and the palette open) and the flows in the other specs, all
  under the CSP fixture from `tests/csp.ts` (CI: "Frontend E2E (web-next)").
- Check new UI in light and dark mode, with the keyboard, and at phone width
  (the full manual protocol is in ACCESSIBILITY.md).

<!-- ASTRYX:START -->

Astryx 0.6.3 quick reference for this app (edited for web-next; see above).

- Discover: `bunx astryx search "<q>"`, `bunx astryx component <Name> --dense`,
  `bunx astryx build "<idea>"`, `bunx astryx docs layout`.
- Style with component props, then Tailwind `ax-*` utilities in `className`.
  No `xstyle`, no raw hex or px values, no unprefixed Astryx Tailwind names.
- Theme changes belong in `src/theme/eneo-theme.ts` + `bun run theme:build`,
  never in `:root` overrides.

<!-- ASTRYX:END -->
