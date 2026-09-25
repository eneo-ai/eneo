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
- Before you finish: `bun run check && bun run lint && bun run test`.

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

## How it is wired

- **Packages** (beta, pinned exactly; upgrade together, then run
  `bunx astryx upgrade` and `bun run theme:build`): `@astryxdesign/core`,
  `@astryxdesign/theme-neutral`, `@stylexjs/stylex` (runtime only), dev
  `@astryxdesign/cli`.
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
- **Colour mode**: next-themes owns it (`ThemeSwitcher` calls `setTheme`). Its
  nonce'd blocking script sets `.light`/`.dark` and `data-theme` on `<html>`
  before first paint; Astryx mirrors `resolvedTheme` after hydration. For other
  client-only values use `useHydrated()` (`src/lib/hooks/use-hydrated.ts`)
  instead of effect + setState.
- **Fonts**: Figtree for UI (`font-sans`), JetBrains Mono (`font-mono`), Source
  Serif 4 for assistant answers (`font-voice`). Type scale 14px / 1.2.

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
| Borders                                   | `border-ax-border`, `border-ax-border-strong`                              | `--color-border*`                           |
| Status                                    | `text-ax-{success,warning,error}`, `bg-ax-…-muted`, `text-ax-on-…`         | `--color-{success,warning,error}*`          |
| Categorical (amber = orange, rose = pink) | `text-ax-{blue,teal,purple,orange,pink}` + `bg-ax-{hue}-muted`             | `--color-text-*`, `--color-background-*`    |
| Radius                                    | `rounded-ax-{inner,element,container,page,chat}` = 6/10/12/18/20px         | `--radius-*`                                |
| Elevation                                 | `shadow-ax-{low,med,high}` (= `shadow-sm/md/lg`)                           | `--shadow-*`                                |

- Legacy radius classes follow the same scale: `rounded-sm` 6, `-md` 10
  (buttons, inputs), `-lg` 12, `-xl` 14, `-2xl` 18 (page panel), `-3xl` 20.
- `text-ax-text-tertiary` meets AA only on surface, card and sunken; use
  `-secondary` on `body` and `muted` backgrounds.
- `--color-*` custom properties are Astryx tokens (`--color-accent` is the blue);
  `--accent` is the shadcn hover tint. Don't mix them up in `var()`.
- The body is still `bg-background` (surface) until the shell adopts the page
  panel layout (`bg-ax-body` around a `bg-ax-surface rounded-ax-page` panel).

## Shared building blocks (`src/components/composites`)

- `PageHeader` — `title`, `description?`, `breadcrumbs?: {label, href?}[]`,
  `actions?` (legacy `children` still work), `tour?`.
- `EmptyState` — `title`, `description?`, `icon?`, `actions?` (or `children`),
  `headingLevel?` (2), `isCompact?`, `framed?` (dashed frame, default on).
- `LoadingState` — skeleton status region: `label?`, `rows?`,
  `variant?: "rows" | "text"`. Never show an EmptyState that says "Loading".
- `EntityAvatar` — coloured tile for spaces/assistants: `name`, `id?`, `tone?`,
  `src?`, `icon?`, `size?: sm|md|lg|xl`, `label?`. Colours via
  `entityTone()` / `entityAccent()` in `src/lib/entity-accent.ts`.
- `StatusLabel` — Astryx `StatusDot` plus text: `status`, `label`, `isPulsing?`.
- `SettingsGroup` / `SettingsRow`, `ResourceTileCard` — legacy (shadcn-based);
  keep using them until a screen is migrated.

## CSP

Production allows `<style>` elements only with the request nonce
(`style-src 'self' 'nonce-…'`); inline `style=""` attributes are allowed. Never
loosen the policy.

- The Eneo theme is pre-built, so `Theme` injects nothing. Never pass a runtime
  `defineTheme()` object to `<Theme>`; runtime themes inject `<style>` tags.
- Astryx parts that still inject `<style>` at runtime and are blocked in
  production: `CodeBlock`/`CodeEditor` syntax colours (use
  `src/components/ai-elements/code-block.tsx` instead), `DateInput`'s engine
  probe (falls back to a pointer heuristic; harmless) and Chat's stream-scroll
  rule (shipped statically in `globals.css`).
- A server component that needs the nonce reads `(await headers()).get("x-nonce")`
  (see `src/app/layout.tsx`).

## Text and i18n

- next-intl, locales `sv` (default) and `en`, chosen by the `NEXT_LOCALE` cookie.
  No hardcoded UI text (`eneo/no-hardcoded-text`).
- New web-next strings go in **both** `src/lib/i18n/extra/sv.json` and `en.json`
  (same keys, natural Swedish), then `node scripts/convert-paraglide-messages.mjs`.
  Never edit `src/lib/i18n/messages/*` by hand. Reuse existing keys when they fit.
- Astryx's own strings (aria labels, pagination, …) come from its Swedish
  catalog through the provider; don't translate them yourself.

## Verify

- `bun run check` — route typegen and `tsc`.
- `bun run lint` — i18n drift, theme staleness, Prettier, ESLint.
- `bun run test` — Vitest. `src/app/globals-css.test.ts` compiles `globals.css`
  and guards the layer order, the theme import and the Streamdown `@source`
  paths.
- Check new UI in light and dark mode, with the keyboard, and at phone width.

<!-- ASTRYX:START -->

Astryx 0.6.3 quick reference for this app (edited for web-next; see above).

- Discover: `bunx astryx search "<q>"`, `bunx astryx component <Name> --dense`,
  `bunx astryx build "<idea>"`, `bunx astryx docs layout`.
- Style with component props, then Tailwind `ax-*` utilities in `className`.
  No `xstyle`, no raw hex or px values, no unprefixed Astryx Tailwind names.
- Theme changes belong in `src/theme/eneo-theme.ts` + `bun run theme:build`,
  never in `:root` overrides.

<!-- ASTRYX:END -->
