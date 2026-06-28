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
                         brand      --accent-* | --brand-eneo | --chart-*

3. Tailwind utilities apps/web/src/app.css (@theme inline) maps layer 2 to classes:
   (what you write)    bg-negative-dimmer, text-warning-stronger, bg-secondary,
                       text-muted, border-default, bg-accent-default, …
```

## The rule

> Pick a class by **intent + intensity**, never by raw color.

| Intent                        | Use                                                                    |
| ----------------------------- | ---------------------------------------------------------------------- |
| Error / failure / destructive | `negative-*` (e.g. `bg-negative-default/10`, `text-negative-stronger`) |
| Caution / warning             | `warning-*`                                                            |
| Success / ok                  | `positive-*`                                                           |
| Brand / primary action        | `accent-*` / `primary`                                                 |
| Page & dialog surfaces        | `bg-primary` / `bg-secondary` / `bg-tertiary`                          |
| Body / dimmed / inverted text | `text-primary` / `text-secondary` / `text-muted` / `text-on-fill`      |
| Hairlines & outlines          | `border-dimmer` / `border-default` / `border-stronger`                 |

### Don't

- ❌ Tailwind palette utilities: `bg-orange-50`, `text-red-600`, `border-gray-300`.
  These don't adapt between light/dark.
- ❌ Arbitrary literals in classes: `bg-[#fff]`, `text-[rgb(...)]`.
- ❌ The `dark:` variant in application code. Theme differences belong in the
  semantic token definitions, so `bg-negative-default/10` is correct in both
  themes. The variant remains wired to `data-theme` only for vendored components
  that have not yet been migrated.

### Enforcement

`eneo/no-raw-color` (ESLint) runs as an error in the web app and shared UI
package. It inspects Svelte, JavaScript, and TypeScript strings, including
generated markup and component `<style>` blocks. The existing backlog is tracked
in each package's `eslint-suppressions.json`; adding another violation exceeds
the baseline and fails CI.

Escape hatch for a genuinely themeless surface:
`<!-- eslint-disable-next-line eneo/no-raw-color -->`.
