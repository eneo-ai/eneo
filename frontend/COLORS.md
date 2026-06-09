# Colors & theming

Eneo has a **three-layer color system**. Always use the top layer (Tailwind
utilities backed by semantic tokens). Never write raw colors into `class`.

```
1. Raw palette        packages/ui/src/styles/themes/palette.css
   (theme-independent) --color-ui-red-500, --color-ui-yellow-50, --color-soil-500 …
                       ⚠️ never reference directly

2. Semantic tokens    themes/light.css + dark.css, wired by themes/index.css to
   (per theme)         :root[data-theme="light"|"dark"] — auto-switch per theme.
                       Each comes in dimmer / default / stronger:
                         surfaces   --background-primary | -secondary | -tertiary
                         text       --text-primary | -secondary | -muted | -on-fill
                         border     --border-dimmer | -default | -stronger | -strongest
                         status     --negative-* (error) | --warning-* | --positive-*
                         brand      --accent-* | --brand-intric | --chart-*

3. Tailwind utilities apps/web/src/app.css (@theme inline) maps layer 2 to classes:
   (what you write)    bg-negative-dimmer, text-warning-stronger, bg-secondary,
                       text-muted, border-default, bg-accent-default, …
```

## The rule

> Pick a class by **intent + intensity**, never by raw color.

| Intent | Use |
| --- | --- |
| Error / failure / destructive | `negative-*` (e.g. `bg-negative-default/10`, `text-negative-stronger`) |
| Caution / warning | `warning-*` |
| Success / ok | `positive-*` |
| Brand / primary action | `accent-*` / `primary` |
| Page & dialog surfaces | `bg-primary` / `bg-secondary` / `bg-tertiary` |
| Body / dimmed / inverted text | `text-primary` / `text-secondary` / `text-muted` / `text-on-fill` |
| Hairlines & outlines | `border-dimmer` / `border-default` / `border-stronger` |

### Don't

- ❌ Tailwind palette utilities: `bg-orange-50`, `text-red-600`, `border-gray-300`.
  These don't adapt between light/dark.
- ❌ Arbitrary literals in classes: `bg-[#fff]`, `text-[rgb(...)]`.
- ❌ The `dark:` variant. **It is inert in this app** — the theme switches via
  `data-theme` on `<html>`, not via a `.dark` class (none is ever set, no
  `<ModeWatcher>` is mounted). A semantic token already carries its dark value,
  so `bg-negative-default/10` is correct in both themes; `dark:bg-…` does nothing.

### Enforcement

`intric/no-raw-color` (ESLint) flags raw palette utilities and arbitrary color
literals in `class`. It runs at **warn** today because of a pre-existing backlog
(~250 occurrences across ~20 files); flip it to `error` in
`apps/web/eslint.config.js` once the backlog is burned down. Escape hatch for a
genuinely themeless surface: `<!-- eslint-disable-next-line intric/no-raw-color -->`.
