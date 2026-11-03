# Building UI in web-next

Rules for humans and AI agents working in `frontend/apps/web-next`. The repo
root [AGENTS.md](../../../AGENTS.md) still applies (documentation and release
changes).

This app is the optional React/Vite beta with Astryx. SvelteKit remains the
primary frontend and the default for frontend development; work here must be
explicitly intended for the beta. See
[the frontend development policy](../../../AGENTS.md#frontend-development).
The UI rules below apply to web-next.

## Vite migration

On `feat/web-next-vite` and its slice branches, the target is a Vite SPA with
TanStack Router and Query; FastAPI is the only server. Build framework-neutral
React in `src/features`, `src/components` and `src/lib`, with routes in
`src/routes`. Do not reintroduce `src/app` or a frontend auth server. SvelteKit in `apps/web` is the production behaviour reference and
must not be changed by migration slices.

Follow the migration epic `eneo-web-next-vite-ded5` in Beads from the
`flows-core` workspace. Land reviewed slices by fast-forward on
`feat/web-next-vite`; never modify `develop` or merge, approve, close or enable
auto-merge on a pull request.

## In short

- **New UI uses [Astryx](https://github.com/facebook/astryx)** (`@astryxdesign/core`)
  with the Eneo theme. Look components up with the CLI before writing code.
- **shadcn/ui in `src/components/ui` is legacy.** Do not add shadcn components
  (`shadcn add`) or build new features on them; replace them with Astryx when
  you rework a screen. Mixing both during the migration is fine.
- **Layout** with Astryx `VStack`/`HStack`/`Layout` or Tailwind utilities.
- **Tokens only**: no raw colours, no `dark:` variants (both are lint errors in
  TS/TSX). Every colour, radius and shadow flips with the colour mode by itself.
- **Every UI string goes through use-intl** (Swedish is the default locale).
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
- Accessible names, `alt`, `title` and `placeholder` come from use-intl, never
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
  (`useFocusTrap`, `useListFocus`), shortcuts (`useHotkeys`), breakpoints
  (`useMediaQuery`), announcements (`useAnnounce`: never a hand-rolled
  `aria-live`/`role="status"` region), copying (through our `useCopy` in
  `src/lib/hooks/use-copy.ts`, which wraps `useClipboard` and adds the refusal
  toast; raw `useClipboard` only for the secret reveal and chat's rich-text
  copy), clickable
  cards with nested actions (`useClickableContainer`), overflow (`useOverflow`),
  truncation (`useTruncation`, exported from `@astryxdesign/core/Text`, paired
  with `Tooltip`), free-text tags (`Tokenizer` with `hasCreate`), table
  sorting, filtering, pagination, selection and row expansion (the `Table`
  plugins; `TableSelectionToolbar` for the selected rows' bulk actions, as
  the websites tab does), and the chat hooks from `@astryxdesign/core/Chat`
  (`useChatStreamScroll`, `useChatNewMessages`, `useChatComposerTokens`,
  `useChatPasteAsToken`) plus `useStreamingText` from `/hooks`.
  `useFocusReturnVisibility`, `useTriggerMenu` and `useScrollSpy` exist in
  Astryx's dist but are not exported; do not import them. Astryx has no
  debounce, before-unload, cursor-pagination or copy-feedback hook: ours live
  in `src/lib/hooks` (`useCopy` among them).
- **One implementation per behaviour.** When an Astryx hook or component
  replaces ours, delete our version and its tests in the same change instead
  of keeping both.
- **Keep ours only for a reason** — a CSP, accessibility or product constraint
  Astryx doesn't meet — and say why in a comment next to it.
- **Fix an Astryx gap in one place**, never at each call site: a wrapper in
  `src/components/astryx/` (lint sends imports there), or the bun patch for
  what a wrapper can't reach (How it is wired → Packages). Known gaps in
  Astryx 0.7.5:
  - A `Banner` has no live region unless it is given one. A banner for
    something that just happened (a refusal, a list that failed to load) gets
    `role="alert"`; a page-level notice that may change gets `role="status"`;
    a notice about a state that lasts, shown on every visit to its page or
    tab, gets no role, and what is new is announced politely with
    `useAnnounce`.
  - `Typeahead` and `Tokenizer` set no `aria-invalid` for an error status and
    leave the `KEYBOARD` attributes out of their types: use the wrappers in
    `@/components/astryx/`.
  - A `Collapsible` jumps open and shut unless it is given a
    `useAnimatedLayout` handle: the wrapper in `@/components/astryx/collapsible`
    takes the one the page panel provides (`AnimatedLayoutScope`). The chat
    transcript opts out (`StillLayoutScope`): only its follow logic moves it.
  - The Swedish catalog lacks some strings: `astryx-sv-supplement.ts` (next to
    the provider) adds them, and its test fails when a component we use has an
    untranslated string.
  - CommandPalette marks only a picked value as selected: patched (the
    highlighted option is exposed as selected, as the APG combobox pattern
    says). DateInput's `nativePicker` is deprecated since 0.6.4: use
    `presentation` (`"adaptive-bottom-sheet"` keeps the CSP-blocked browser
    picker away, see `key-expiry-field.tsx`).
  - BottomSheet skips `data-autofocus` when opening the dialog already focused
    its panel: focus the target yourself once the sheet is open (as
    `activity-sources.tsx` does).
  - MoreMenu and DropdownMenu put `className` on the menu, not on its button
    (lint refuses it; the theme already makes the button 44 px on touch), and
    end a menu row's label in an ellipsis: `globals.css` (section 12d) wraps
    it. A start-aligned menu gets only the room right of its button: align a
    button near the right edge `end`, and one whose place varies `center`.
  - A searchable Selector names its trigger by its label alone: give it an
    `aria-label` that includes the value (as `model-selector.tsx` does).
  - Table names every scroll region "Tabell", and absolutely positioned
    (screen-reader-only) cell content escaped its scroll box and widened the
    page: `@/components/astryx/table` names the region, and `globals.css`
    (section 9) makes the scroll box `relative`.
  - ScrollableArea's `axis="inline"` adds an `inline` class that collides with
    Tailwind's display utility. `globals.css` restores block layout for its
    viewport so overflowing content stays contained and keyboard-scrollable.
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

## Long settings editors

Use `src/components/composites/sectioned-settings.tsx` for editors with several
settings sections inside a space. Its header is `EditorHeader`
(`src/features/spaces/editor-header.tsx`): the breadcrumb back to the space
and the tab, the name as the h1, the save state and the actions. The editor
owns the surface: `spaceRoute` classifies the assistant, app and group-chat
editors as `editor`, and the space frame renders no space header or tabs
above them. Provide one ordered section list for both the section links and
the single-column content. Below 1024 px the links are an Astryx TabList in
the header, in its navigation pattern (it scrolls with edge fades, keeps the
current link in view and moves with the arrow keys, so no label is ever
truncated); from 1024 px they are a sticky list beside the form, under the
sections' groups, still inside the editor page (no other sidebar in the space
navigation). Keep conditional sections in that list so a link never points to
hidden or unavailable settings. Use `SettingsGroup` for each card's heading
and rows. Anchors and focused controls stay clear of the sticky header
through its measured height (`--editor-header-h`); check keyboard navigation
and narrow widths when changing the shared layout. A page under a frame's
header (space settings) passes `isFramed` to start on its line instead of
centring. An editor opened right after "Skapa …" gets the resource through
`useJustCreated` (`src/features/spaces/just-created.ts`): it focuses the
default name and announces the creation; `createWithUniqueName` numbers the
default name on a backend name collision (9017).

On a phone an editor opens on an index of its sections (decision 21): pass
`phone` (`useEditorPhoneIndex`) and give each section a `group` and, where its
data is loaded, a `summary` (`src/features/spaces/editor-summaries.ts`). The
index and the sections are views of one mounted tree chosen by `?section=`,
so a draft and its pending save outlive a trip to the index or a turn to the
tablet layout; never render a section only in one view. A section's
`SettingsGroup` drops its card frame and repeated title there by itself. A
resource just created opens on General, so its name field is in view. Space
settings uses it too, but with only a `title`: the space's own page bar sits above
the index (a globals.css rule hides it, and its connection banner, while a section is
open), so the index has no bar of its own and names itself with a heading.

## How it is wired

- **Packages** (beta, pinned exactly; upgrade together, then run
  `bunx astryx upgrade` and `bun run theme:build`): `@astryxdesign/core`,
  `@astryxdesign/theme-neutral`, `@stylexjs/stylex` (runtime only), dev
  `@astryxdesign/cli`. `frontend/patches/@astryxdesign%2Fcore@0.7.5.patch`
  makes CommandPalette mark the highlighted option as selected, and gives
  the layers' slide-rule `<style>` the page's CSP nonce. After an upgrade bun silently skips
  the stale patch and the guard tests in `src/components/astryx/` fail:
  recreate it with `bun patch @astryxdesign/core` (keep the diff free of bun's
  `.bun-tag-*` file), or drop a part Astryx has fixed.
  - Mermaid 11.16.1 inserts SVG styles without a CSP nonce. The
    `mermaid@11.16.1` patch uses `NonceProvider`'s request nonce while measuring,
    parsing and displaying the SVG. Serialization hides a live node's nonce,
    so it is restored on inert markup before sanitization and display. The production
    `tests/answer-presentation.spec.ts` covers this; retain the patch on upgrades
    until upstream supports nonces, then remove it once that test passes.
- **Theme**: `src/theme/eneo-theme.ts` extends Astryx Neutral with the Eneo
  palette, radii, shadows and fonts; it is the single source of truth.
  `bun run theme:build` compiles it to `src/theme/eneo.{css,js,d.ts}`
  (generated and committed; never edit them; `bun run lint` fails when stale).
- **CSS** (`src/styles/globals.css`): one cascade-layer order,
  `properties, reset, theme, base, astryx-base, astryx-theme, components, utilities`.
  Tailwind utilities are the top layer, so a utility in an Astryx component's
  `className` wins. The shadcn variables (`--background`, `--primary`, …) point
  at Astryx tokens, so unmigrated screens already use the Eneo look.
- **Providers**: `src/components/providers/astryx-provider.tsx` mounts the root
  `Theme`, Astryx's own strings in the active locale and the app's link
  (`@/lib/link`) for Astryx links. Don't add another app-wide `Theme`; a nested `<Theme>` for one region
  is fine.
- **Colour mode**: next-themes owns the preference (the profile menu's
  `ThemeSubMenu` calls `setTheme`). The nonce-bearing script in `index.html`
  sets `.light`/`.dark` and `data-theme` on `<html>` before React starts.
  `globals.css` pins `color-scheme` to that class, and Astryx stays on
  `mode="system"` so its tokens follow the same setting. Browser values are
  available on the first render; do not add hydration gates.
- **Background jobs** (`src/features/jobs/`): the backend publishes every job
  status change after commit (`eneo/jobs/job_events.py`) and streams them per
  user as server-sent events; `job-events.ts` receives them through the
  `/api/v1/jobs/events/` endpoint (one EventSource per tab, browser reconnect, a
  30 s retry after a refusal) and writes each update into the `["jobs"]`
  cache. `JobsProvider` still polls `GET /jobs` as the safety net (30 s while
  the feed is open; 2 s while it is down and something runs or was just
  started; paused in hidden tabs) and compares snapshots with
  `job-transitions.ts`. Every job
  the client starts goes through `trackJob(job)` (`trackJob(jobs)` for calls
  made together) so its completion counts even when the first poll already
  says "complete". A finished job toasts and
  announces (`job-feedback.ts`), refreshes the query keys in
  `job-invalidation.ts` (add a prefix there when a new kind of job lands
  somewhere new) and records its info-blob in `recent-results.ts`, which the
  file table uses to mark the row "Nyss tillagd". Nothing in the app needs a
  reload to see a job's result; if something does, the missing invalidation
  key is the bug.
- **Fonts**: Figtree for UI and assistant answers (`font-sans`; answers use
  `ANSWER_TEXT_CLASS` in `ai-elements/message.tsx`), JetBrains Mono (`font-mono`).
  Source Serif 4 stays loaded as `font-voice` so the answer voice can be flipped
  back with one class. Type scale 14px / 1.2.
- **App shell** (`src/components/shell/`): Astryx `SideNav` from 768px (`wide:`), an
  icon rail by default below 1280px (an iPad either way, a small laptop) and
  the full nav above; a stored choice (the `eneo_sidenav_collapsed` cookie,
  "1" or "0", read on first mount) wins at every width. An admin mode under
  `/admin`, Astryx `MobileNav` and the top bar on a phone, held either way
  (`PHONE_SCREEN_QUERY`; markup that follows the shell uses `phone:`/`wide:`)
  and the ⌘K `CommandPalette`. A page
  header that replaces the phone top bar (the chat header, a pushed screen's
  `PageBar` with its back link) spreads `OWN_MOBILE_HEADER` and the top bar
  hides in CSS while it is on the page, from its first render. A space and an
  admin area are pushed on phones only (tablets show them with breadcrumbs
  beside the side navigation): their bar is `PageBar until="phone"`, which
  spreads `OWN_PHONE_HEADER` instead; Konto's pages keep theirs below 1024px. The chat
  header opens the drawer with
  `window.dispatchEvent(new CustomEvent(OPEN_NAV_EVENT))`
  (`src/components/shell/routes.ts`).
- **Phones and tablets**: `index.html` runs the page edge to
  edge (`viewport-fit=cover`), lets the Android keyboard resize the layout
  (`interactive-widget=resizes-content`) and colours the status bar with the
  surface token (`ThemeColor` follows an explicit Tema). Each safe-area inset
  has one owner: the shell frame pads the top and sides, `main#main-content`
  the bottom, the drawer's panel pads itself (`globals.css` section 14), and
  Astryx Dialog, Popover and BottomSheet pad themselves. Don't add
  `env(safe-area-inset-*)` inside the page. The page never pulls to refresh
  (`overscroll-behavior`), and the drawer and dialogs have no backdrop blur.
- **Panels by the room they have**: the chat's side panel and history decide
  beside or sheet from the width of the row they share (`useElementWidth`,
  decision 14: the conversation keeps 480 px), not from a media query; the
  chat page owns that row and the history gives way to a panel that opens
  where both do not fit. Widths in that rule are px, set inline.
- **Collections of resources** (spaces, assistants, apps and the
  catalog) render through `ResourceCollection` (`resource-tile.tsx`): list
  rows on a phone (`usePhoneScreen`), cards otherwise in a grid that fits as
  many columns as the page has room for. A list row with a link is one
  target (globals.css 12b); put controls in its end slot. A turn between the
  two remounts every item, so the dialogs of an item's menu (move, publish,
  delete) are not in the item: `createResourceActions`
  (`resource-action-scope.tsx`) puts them in one scope above the collection,
  the menus only ask to open one, and an open dialog survives the turn. Follow
  `apps/actions.tsx` for a new resource.
- **Navigation and links**: app code imports `@/lib/navigation` and
  `@/lib/link`, which own the TanStack adapters.
- **Toasts**: only through `src/lib/toast.ts` (`no-restricted-imports` blocks
  `sonner` elsewhere). Errors and warnings don't time out; every toast has a
  close button; success and info close after 6 s. Sonner's stylesheet is
  static (see CSP). The stack rises clear of the focused element
  (`src/components/ui/toast-lift.ts`, WCAG 2.4.11); put `data-clear-of-toasts`
  on a docked group (like the chat composer) that should stay clear as a whole.

## Routing (Vite)

The Vite build (`bun run build`) routes with TanStack Router:
`src/router.tsx` owns every router option, `src/routes/` holds the route
files and `src/routes/__root.tsx` mounts the shared providers.

- **Loading has no side effects.** `beforeLoad` and loaders also run when a
  link is hovered, so they never mutate: logout, a module ticket or an
  integration callback runs once in an effect or a click handler, without
  retries or the query cache.
- **Loaders and guards read through `src/lib/api/query.ts`**, never a bare
  `queryClient.query`:
  - `readCached`: session and display data, as cached, even when stale or
    after a failed background refresh (mounted observers refresh it);
  - `readFresh`: a guard's evidence (a permission, a resource that may be
    gone), read again when stale or invalidated; the guard keeps its 403/404
    handling;
  - `warmQuery`: starts what the page will need without waiting, with the
    query's own retry policy.

  None of them changes `retry`: every reader of a query shares the options
  of the request that started it. `makeQueryClient` owns the default (never
  on a 4xx, three more tries on a server or network failure); a resource that
  must not retry, such as a guard's that must fail at once, sets
  `retry: false` in its own options, after any spread.

- **`loaderDeps` hold no UI state** (`tab`, `page`, `search`, `role_id`,
  `session_id`, `step`): a tab or filter change must not show pending UI or
  run the loader again.
- **Every page route has a title**: `head: routeTitle("key")`
  (`src/lib/route-head.ts`), shown as "<Page> · Eneo".
- **Pending UI belongs to page routes**, not `_app`, so the shell stays while
  a page loads. Chat routes show none for a change of parameters alone.
- **Errors**: `RouteError` is for a route that failed to load or render. A
  query that fails while its data is on screen stays with
  `QueryStateBoundary`.
- **Search** is flat `URLSearchParams` (`src/lib/router/search.ts`): every
  value is a string, a repeated key a list.
- **Navigation**: `@/lib/navigation` and `@/lib/link` own the shared TanStack
  implementations. The hooks report the page on screen until the next
  one has loaded; `replaceUrl` is a router navigation in place (no history
  entry, no scroll reset, the page stays mounted). Test them in a real router
  with `renderWithRouter` (`src/test/router.tsx`).

## Styling

1. Component props first (`variant`, `size`, `status`, …).
2. Then `className` with Tailwind utilities. Never `xstyle` or
   `stylex.create()`: this app has no StyleX compiler (Astryx ships compiled CSS).
3. Import Astryx from subpaths: `import { Button } from "@astryxdesign/core/Button"`.
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
- Contrast is tested (`src/theme/eneo-theme.contrast.test.ts`): every text,
  icon, status and control-border token on every surface under every state
  (hover, selected, pressed, both stacked, the muted fills), and every fill with
  its on-colour at rest, hovered and pressed. A new token is picked up by name.
  Use `-secondary` instead of `-tertiary` on pressed and stacked states, muted
  fills, and hover or selected rows over `body` (the sidebar), `muted` or
  `sunken`; keep form fields off tinted rows. What may fail is listed, with the
  reason, in `src/theme/contrast-exemptions.ts`, which can only shrink.
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
- Page width: every page sits in one centred 1152 px column with one left
  edge, so the heading stays put from page to page. Top-level routes and the
  admin layout render `PageFrame` (`src/components/composites/page-frame.tsx`,
  the inset and the column); the space frame and its header band use its
  `PAGE_COLUMN`. A page sets no `mx-auto` of its own (a unit test fails on
  it, outside Konto, the full-screen editors, the chat's column and a
  document's prose); a form or reading page may cap itself narrower
  (`max-w-4xl`) and so starts on the same edge. Konto keeps its own frame.

## Tables

- Use `Table` from `@/components/astryx/table` (lint enforces it; the other
  parts still come from `@astryxdesign/core/Table`), preferably data-driven
  (`data` + `columns`) with a width on every column: `pixel(n)` for fixed
  columns, `proportional(n)` for text (it keeps a 120 px minimum). Its plugins
  do sorting, filtering, pagination and selection.
- Size short columns (counts, dates, states, sizes) with `pixel(n)` to fit
  their content and header, and leave the name `proportional(1, { minWidth })`.
  The table's min width is the sum of the pixel columns plus, for each
  proportional one, its min width times the total share over its own share:
  three `proportional(1)` beside a `proportional(3)` make 840 px of a table
  whose content needs half. Beside the icon rail an iPad held upright leaves
  a page's table 682 px and one held sideways 1042 px. The users, audit and
  most knowledge tables fit upright; the websites table, a source's folder
  documents and the models table scroll there with their name pinned, and
  fit sideways.
- Decision 9: a table keeps every column on a phone and scrolls sideways with
  what names a row held in view: `pinnedColumn="name"` (the wrapper pins it
  and any selection or row-status column before it, and keeps focus clear of
  it). A space's Kunskap tab is the exception: on a phone its sources list
  rows (`RowsOrTable` in `features/knowledge/knowledge-list.tsx`, rows from
  `knowledge-rows.ts`, which the overview shares) under a segmented control;
  selecting websites for bulk actions stays on tablets and desktop. A
  collection's files stay a table. On touch, sortable headers are 44 px targets with their arrows shown,
  and long header labels wrap (`globals.css` section 9b). A pinned column takes
  its container's colour from `--table-sticky-background`: `TableFrame`
  sets it (and runs edge to edge on a phone); a table on the page sets
  `[--table-sticky-background:var(--color-ax-surface)]`.
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
- Give a children-mode table with many columns a min width (`min-w-*` on
  `Table`; data-driven tables get it from their columns). Below it the table
  scrolls sideways in its own focusable region instead of squeezing the
  columns.
- The page scans in `tests/a11y.spec.ts` fail on a column that collapsed.
- Legacy shadcn tables (`@/components/ui/table`) get the same keyboard-scrollable,
  named container from Astryx's `useScrollableArea`; name them the same way.

## Shared building blocks (`src/components/composites`)

- `PageHeader` — `title`, `description?`, `breadcrumbs?: {label, href?, current?}[]`
  (only `current` marks a crumb as this page; a crumb without `href` is a plain
  label), `actions?` (legacy `children` still work), `headingLevel?`,
  `headingRef?`, `tour?`.
- `SuccessMark` (`success-mark.tsx`) — the one green check-in-a-circle for a
  save that landed, a job that finished, a file that became searchable; give
  it a growing `replayKey` to pop it in once per success. Decorative; the text
  beside it carries the meaning.
- `QueryStateBoundary` / `ListError` (`query-state.tsx`) — the one loading and
  error state for a list or section: skeleton rows while pending, an error banner
  with the catalog message, "Försök igen" (refetch) and status/code/trace behind
  details. Never a hand-rolled "Laddar…" or a skeleton that cannot end.
- `EmptyState` — `title`, `description?`, `icon?`, `hue?` (the area's hue for
  the icon tile, `AREA_HUES` from `icon-tile.tsx`; neutral for zero results),
  `actions?` (or `children`), `headingLevel?` (1–4, default 2), `isCompact?`,
  `framed?` (dashed frame, default on), `isAnnounced?` (default on: Astryx
  reads an empty state that appears after load; off where a result count
  already says it, such as under `ResourceFilterInput`).
- `IconTile` — the coloured icon tile of the start page's starter cards and
  the empty states: `icon`, `hue?` (`neutral` | categorical, `AREA_HUES` maps
  each area to one), `size?: sm|md|lg`. Decorative; the text beside it
  carries the meaning.
- `LoadingState` — skeleton status region: `label?`, `rows?`,
  `variant?: "rows" | "text"`. Never show an EmptyState that says "Loading".
- `EntityAvatar` — coloured tile for spaces/assistants: `name`, `id?`, `tone?`,
  `src?`, `icon?`, `size?: sm|md|lg|xl`, `label?`. Colours via
  `entityTone()` / `entityAccent()` in `src/lib/entity-accent.ts`.
- `StatusLabel` — Astryx `StatusDot` plus text: `status`, `label`, `isPulsing?`.
- `ClientTime` — the one way to show a date: `value`, `format: "date" |
"date_long" | "date_time" | "relative" | "auto"` (`auto`, for lists: relative
  for the last week, then date and time). It renders in the viewer's time zone
  on the first render. Where the text
  must go into a label (an accessible name), `useClientTimeText` returns the
  same string.
- `ResourceCard` (`resource-tile.tsx`) — the card for assistants and apps
  (Astryx `ClickableCard`; its action menu is a sibling, so actions
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
  move focus to the list's heading or panel, so focus never falls to `<body>`.
  The scope owns that rescue (`useFocusRescue`, `src/lib/focus-rescue.ts`);
  other actions that may remove the focused element call the hook in the
  list or page that survives the change, never in the row.
- Settings switches that save on toggle: `useSettingSwitch`
  (`src/features/admin/use-setting-switch.ts`) — optimistic, reverts on error,
  queues a press made during a save.
- Public pages (login, password change, …) use `PublicPage`
  (`src/features/auth/public-page.tsx`): one `main`, one `h1` and the
  accessibility statement link.

## CSP

Production allows `<style>` elements only with the request nonce
(`style-src 'self' 'nonce-…'`); inline `style=""` attributes are allowed. It
has no `'unsafe-eval'`. FastAPI owns this policy (`backend/src/eneo/server/web_app.py`). The Vite dev server sends no CSP; verify against the production
build served by FastAPI. Never loosen the policy.

- The Eneo theme is pre-built, so `Theme` injects nothing. Never pass a runtime
  `defineTheme()` object to `<Theme>`; runtime themes inject `<style>` tags.
- `frame-src` allows `blob:` (file previews) and the one origin interactive
  tool views (MCP Apps) are served from, derived from the backend's
  `MCP_APP_CONTENT_BASE_URL`; the backend in turn frames a view
  only for its `PUBLIC_ORIGIN` and the origins in `MCP_APP_HOST_ORIGINS`, so
  list this app's origin there when testing views here. The Word preview
  builds a same-origin `srcdoc` frame and stamps the nonce on every `<style>`
  it adds (`src/features/workspace/preview/docx-preview.tsx`).
- Astryx parts that still inject `<style>` at runtime and are blocked in
  production: `CodeBlock`/`CodeEditor` syntax colours (don't use them; code
  fences render through Streamdown's `@streamdown/code`) and `DateInput`'s
  engine probe (falls back to a pointer heuristic). Chat's stream-scroll rule
  is in `index.html` with the response nonce; Astryx skips its
  own injection when that element is there.
- Zod probes for eval on its first object parse; `src/main.tsx`
  sets `jitless` so it doesn't (Zod's switch for strict CSPs).
- Sonner injects its stylesheet at runtime unless patched:
  `frontend/patches/sonner@2.0.8.patch` makes the Toaster import the static
  `sonner/dist/styles.css`. After a sonner upgrade bun silently skips the stale
  patch; recreate it with `bun patch sonner` (`src/components/ui/sonner.test.tsx`
  fails if a `<style>` appears).
- e2e specs import `{ expect, test }` from `tests/csp.ts`, which fails a test
  on any `securitypolicyviolation`, so the production build is checked too.
- `src/main.tsx` reads the document nonce and sets `__webpack_nonce__` before
  importing UI modules. `useNonce()` reads the same value from `NonceProvider`
  (`src/components/providers/nonce.tsx`). This covers react-remove-scroll's
  scroll lock, and the legacy Select passes it to Radix's viewport;
  `tests/csp.spec.ts` opens one.

## Text and i18n

- use-intl, locales `sv` (default) and `en`. `switchLocale` writes the `eneo_locale` preference cookie and reloads the document so React, router titles and boot data change language together. `AppIntlProvider` owns the Vite app's viewer time zone. Calendar dates and backend day aggregates keep their own semantics.
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

## Phones and tablets (the responsive contract)

Every screen works from a 320 px phone to a 1366 px iPad held sideways, with a
finger and with a mouse, and a test keeps it that way. Build a new screen from
what is here before writing layout of your own.

**Tiers.** Phone: below 768 px, or a touch screen under 500 px tall and under
1024 px wide (a phone turned sideways). JS reads it with `usePhoneScreen` or
`PHONE_SCREEN_QUERY`, CSS with the `phone:` and `wide:` variants (globals.css,
kept in step by a test); don't use `md:`/`max-md:` for the shell, a space's
chrome, an editor or a collection. Tablet: `wide:`, side navigation there too
(an icon rail below `xl`, 1280 px, unless the user chose). Admin and Konto
keep their own `md:`/`lg:` tiers. `short:` is a viewport under 30rem tall (a phone turned
sideways: a browser's own bars leave about 280 px, a keyboard leaves 50 to
150). A touch pointer (`pointer-coarse:`) gets 44 px targets; a mouse does not.

**Use these, do not rebuild them.**

| Need                                           | Use                                                                                                                                               |
| ---------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| A pushed screen's header and back link         | `PageBar` (`until="phone"`; Konto's below `lg`); its parent label names where it returns                                                          |
| The one primary action of a screen             | `DockedActions` (docked on a phone, in the header otherwise)                                                                                      |
| A list of resources                            | `ResourceCollection` / `ResourceCard` (rows on a phone, cards otherwise)                                                                          |
| Settings                                       | `SettingsGroup` / `SettingsRow`, `PageHeader`                                                                                                     |
| A page outside the shell (sign-in, a callback) | `p-safe` (clears the notch and the home indicator)                                                                                                |
| A search, e-mail or user-name field            | `{...KEYBOARD.search}` / `.email` / `.identifier` from `@/components/astryx/keyboard-hints`                                                       |
| A dialog                                       | `Dialog` from `@/components/ui/dialog`: it is capped at `100dvh - 2rem`, and one with a text field hangs from the top on touch. No `max-h-[90vh]` |
| Typed-name confirmation                        | `ConfirmDialog` / `confirmationMatches`                                                                                                           |
| A wide table                                   | `ScrollableArea` with a name, or rows on a phone; never a bare `overflow-x-auto`                                                                  |

**Do not.**

- Use `vh`, `h-screen`, a `min-h-[3xx px]` or reveal anything only on hover
  (lint rejects them). `hover:` already shows while a finger is down.
- Dim text with `opacity-*` or build a colour pair of your own: use the
  tokens (the contrast test cannot see alpha).
- Add `env(safe-area-inset-*)` inside a page. The shell frame, `DockedActions`,
  the side panel, the toaster and the space members sheet own it.
- Let Return send on a touch screen: Return adds a line there, Ctrl or
  Cmd+Enter sends (`prompt-guide` everywhere). The chat's composer is the one
  exception with a mouse or trackpad: Return sends, Shift+Return adds a line.
  The search key closes the keyboard.
- Confirm a copy with a toast over a docked composer: confirm at the button.
- Make a visible target smaller than 44 px on touch, or two targets overlap.

**The checks, so nobody walks screens by hand.** Every one is generated from
the route list `tests/responsive-routes.ts`; a route missing from it fails a
unit test (`src/test/responsive-routes.test.ts`), so a new screen cannot ship
unchecked: add its route, with a way to open it.

The contract counts a control as outside the screen only when no sideways scroller
(a tab strip, a wide table) can bring it into view; `tests/responsive-measure.spec.ts`
holds that rule on small hand-made pages.

`tests/turn-and-resize.spec.ts` opens the form dialogs that each screen's create buttons
open, on a phone, types into one and crosses 768 px and back (a phone turned, an iPad
split): the same field must be there, with its text and its focus, and the dialog open.
A component that swaps at a breakpoint rebuilds what is open and fails it.

`tests/tooltips.spec.ts` holds a tooltip to WCAG 1.4.13 with a mouse and the keyboard: the pointer can
move onto it, it stays, and Escape closes it. `src/test/a11y-source-guards.test.ts` guards what one line of
source could break (no orientation lock, no autoplay, no password paste block, no text dimmed with
`opacity-*` or a `text-*/NN` alpha outside its allowlist).

| What it finds                                                                                                                                                                               | Run                                                                                              |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| Sideways scroll, a target under 44 px, one outside the screen, two on top of each other, text cut off, a text field under 16 px on a phone (iPhone Safari zooms into it), at six sizes      | `tests/responsive-contract.spec.ts` (`CONTRACT_VIEWPORTS`, `CONTRACT_ROUTES`)                    |
| WCAG 2.2 A/AA by axe (contrast, names, target size, structure) on every route, phone and iPad, light and dark                                                                               | `tests/a11y-routes.spec.ts` (`A11Y_ROUTES`, `A11Y_VARIANTS`, `A11Y_SHOTS=<dir>` saves a picture) |
| The same with a dialog, menu or panel open, and what axe cannot see (collapsed table columns, reflow at 320)                                                                                | `tests/a11y.spec.ts`                                                                             |
| Text whose contrast axe could not judge (over a gradient, an image or another element; hover and pressed are gradients), more per scan than `tests/contrast-incomplete.baseline.json` holds | `tests/a11y-routes.spec.ts`, `tests/a11y.spec.ts` (`CONTRAST_UPDATE=1` rewrites the baseline)    |
| Contrast axe cannot judge: text under 4.5:1 (large 3:1), a field, checkbox or icon-only control under 3:1, with hover (mouse only), pressed and keyboard focus forced                       | `tests/contrast-probe.ts` in `tests/a11y-routes.spec.ts` (`PROBES_UPDATE=1`)                     |
| A switcher's selected option shown by a colour under 3:1 alone, or a selected plate darker than its track in dark mode                                                                      | `tests/selected-probe.ts` in `tests/a11y-routes.spec.ts`                                         |
| A list or overview page whose h1, first list row or second column is off the shared column's left edge by more than 1 px                                                                    | `tests/left-edge-probe.ts` in `tests/a11y-routes.spec.ts`                                        |
| A filled control with no boundary, or a legacy switch with no visible state, in Windows high contrast (forced colours), on every route                                                      | `tests/forced-colors.spec.ts` (`FORCED_ROUTES`)                                                  |
| A screen that shifts by more than 0.1 while it loads on a slow phone (CPU x4, Fast 4G, cold cache): a card shown before the editor that pushes it, a spinner that widens a button           | `tests/layout-shift.spec.ts` (`LAYOUT_ROUTES`)                                                   |
| A whole screen scrolling sideways with the text at 200% (a bar whose rem-sized controls no longer fit in a row)                                                                             | `tests/responsive-text-size.spec.ts`                                                             |
| Menus open in 165 ms (and close at once), drawers, sheets and dialogs open in 225; with reduced motion nothing moves or resizes, only an opacity fade of at most 200 ms runs (2.3.3)        | `tests/motion.spec.ts` (measured with `document.getAnimations()`)                                |
| A disclosure (`Collapsible`) glides what follows it as it opens and closes; with reduced motion only an opacity fade of at most 200 ms on touch, and nothing with a mouse (2.3.3)           | `tests/motion.spec.ts`                                                                           |
| The skip link first, and a visible focus on each of the first 30 Tab stops, on every route (2.4.1, 2.4.7)                                                                                   | `tests/keyboard-focus.spec.ts`                                                                   |
| Keyboard, safe areas, short screens, header and focus across a breakpoint                                                                                                                   | `tests/touch-platform.spec.ts`, `tests/header-continuity.spec.ts`                                |
| A raw `<select>` without 16 px text and a 44 px touch height, in the dialogs the contract never opens                                                                                       | `src/test/raw-select.test.ts`                                                                    |
| Patterns in the source: `vh`, a fixed bar without safe area, missing labels, label association                                                                                              | `eslint` (the `no-restricted-syntax` selectors and `jsx-a11y`)                                   |

`tests/responsive-contract.baseline.json` is where a known violation would be
listed. It is empty and `BASELINE_BUDGET` in `src/test/responsive-baseline.test.ts`
is 0: a violation fails the run, so fix the screen. `tests/contrast-incomplete.baseline.json`
is the same kind of ratchet for unjudged contrast (`src/test/contrast-incomplete-baseline.test.ts`
keeps it well-formed); it starts empty and is generated with `CONTRAST_UPDATE=1` on a fresh stack. Example of a narrow run:
`CONTRACT_VIEWPORTS=390x844 CONTRACT_ROUTES='^/spaces' bun run test:e2e tests/responsive-contract.spec.ts`.

The UI probes (`tests/ui-probes.ts`) each keep `tests/<probe>-probe.baseline.json`, budget 0 in
`src/test/ui-probes-baseline.test.ts`, generated with `PROBES_UPDATE=1` on a fresh stack. What a
probe cannot judge (text over an image) is attached to the run for review, never failed.
`tests/ui-probes.spec.ts` proves each probe on hand-made pages.

Automation finds the mechanical faults; it does not feel a tap, hear a screen
reader or judge whether a flow makes sense. Those stay with a person on a
device, once per feature (below).

**By hand, once a feature is done.** Open it on a phone (a real one, or the
iOS Simulator over https: Safari does not load a plain `http://localhost` app
under the production CSP) with the keyboard open, turned sideways, offline,
and with the text size at 130 %.

## Verify

- `bun run check` — route typegen and `tsc`.
- `bun run lint` — i18n drift, theme staleness, Prettier, ESLint. ESLint lints
  `src` with type information and fails on deprecated APIs
  (`@typescript-eslint/no-deprecated`): move to the replacement the warning names.
- `bun run test` — Vitest. `src/styles/globals-css.test.ts` compiles `globals.css`
  and guards the layer order, the theme import, the Streamdown `@source`
  paths and the touch-target rules; `src/theme/eneo-theme.contrast.test.ts`
  checks the colour pairs; axe tests check component markup. Component tests
  opt into jsdom (`// @vitest-environment jsdom`) and use one harness in
  `src/test/`:
  - `renderInApp(ui, { queryClient?, appContext?, shell?, route? })` renders
    with the app's providers (use-intl in Swedish, Astryx, React Query with the
    app's 30 s staleTime and no retries, app and shell context); also
    `renderHookInApp`. Build app context with
    `testAppContext({ permissions: ["admin"], settings: { … } })`; don't mock
    `@/components/providers/app-context`.
  - Navigation: `vi.mock("@/lib/navigation", () => import("@/test/navigation"))`,
    then the `route` option or `setRoute("/x?tab=y")`. Component tests use plain
    anchors by default. Real-router tests call `vi.unmock("@/lib/link")` and
    use `renderWithRouter` from `src/test/router.tsx`.
  - `src/test/setup-dom.ts` fills in what jsdom lacks and behaves like Chromium:
    `setViewport("phone" | "phone-landscape" | "desktop" | {…})` drives `matchMedia`,
    `reportResize(el, { height })` drives ResizeObserver, `<dialog>` focuses
    its first focusable element on `showModal()`, nothing in a closed dialog
    takes focus, and `close` fires in a later task (advance fake timers).
- `bun run test:e2e` — Playwright against a running backend: the axe page scans
  in `tests/a11y.spec.ts` (light and dark, desktop and 390 px touch, with
  dialogs, menus and the palette open) and the flows in the other specs, all
  under the fixture from `tests/csp.ts` (CI: "Frontend E2E (web-next)"): it
  fails a test on a CSP violation, and its `goto` and `reload` wait until the
  app has mounted.
  Successful authenticated API fixtures use `sessionResponseHeaders(route)`
  from `tests/helpers.ts` to preserve the requesting document's session.
  Local runs and CI use the complete suite against FastAPI. `E2E_BASE_URL` is
  required; copy the asset map from the running backend image before testing.
  Follow `frontend/TESTING.md` for the isolated stack. Vite development does not
  satisfy the suite's production CSP and built-asset contracts.
- Check new UI in light and dark mode, with the keyboard, and at phone width
  (the full manual protocol is in ACCESSIBILITY.md).

<!-- ASTRYX:START -->

Astryx 0.7.5 quick reference for this app (edited for web-next; see above).

- Discover: `bunx astryx search "<q>"`, `bunx astryx component <Name> --dense`,
  `bunx astryx build "<idea>"`, `bunx astryx docs layout`.
- Style with component props, then Tailwind `ax-*` utilities in `className`.
  No `xstyle`, no raw hex or px values, no unprefixed Astryx Tailwind names.
- Theme changes belong in `src/theme/eneo-theme.ts` + `bun run theme:build`,
  never in `:root` overrides.

<!-- ASTRYX:END -->
