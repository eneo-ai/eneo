# `src/lib/components/ui` — shadcn-svelte primitives

This directory holds the [shadcn-svelte](https://shadcn-svelte.com) components the web
app is built on. They are copied into the project with the shadcn CLI and run on
[bits-ui](https://bits-ui.com) and Svelte 5 runes.

It is the only component library in `apps/web`. `@eneo/ui` (`frontend/packages/ui`)
no longer ships components: it holds the design tokens, themes and the icon plugin
(`@eneo/icons/*`) that these components are styled with.

## Where things live

| What                                            | Where                                                                                                                               |
| ----------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| Primitives (Button, Dialog, Select, Tooltip, …) | `$lib/components/ui/*`                                                                                                              |
| App compositions of those primitives            | `$lib/components/*` — for example `dialogLayout.ts`, `DateRangePicker.svelte`, `StatusBadge.svelte`, `resource-table/`, `markdown/` |
| Feature UI                                      | `$lib/features/*` and the route folders                                                                                             |
| Tokens, themes, icons                           | `frontend/packages/ui/src/styles`, `frontend/packages/ui/src/icons`                                                                 |

Reach for an existing primitive first. When several features need the same
composition, add it once under `$lib/components` instead of repeating the markup.

## Adding a new shadcn component

1. Run `bun x shadcn-svelte@latest add <component>` from `frontend/apps/web`.
   - If the CLI asks to overwrite an existing component, answer no: several vendored
     files carry eneo-specific patches (see the NOTE comments in them).
   - If it changes `package.json` or `bun.lock` (it sometimes bumps dependencies),
     revert those changes and keep only what the new component needs.
2. Check which Tailwind tokens the new component references
   (`text-muted-foreground`, `bg-muted`, `border-*`, `ring-*`, etc.).
3. Make sure each referenced token is mapped in `src/app.css` under the
   `@theme inline { … }` block, pointing shadcn's semantic tokens at eneo's tokens
   (`--background-*`, `--text-*`, `--border-*`).
4. Replace `bg-primary` / `text-primary-foreground` with `bg-accent-default` /
   `text-on-fill` and add the file to the list in `src/app.css` (see the
   `--color-primary` namespace conflict comment there).
5. Otherwise keep the generated files verbatim so future CLI updates merge
   cleanly. Customize via class overrides at the call site.

## Component file conventions

- Files are kept as the shadcn-svelte CLI generates them, apart from the patches
  marked with `NOTE:` comments.
- Each component folder has an `index.ts` that re-exports the parts as both
  named exports (`Card`, `CardHeader`) and a namespace (`Card.Root`,
  `Card.Header`).
- Prefer the namespace import in consumers: `import * as Card from "$lib/components/ui/card/index.js"`.
- Menu items take `onSelect`, not `onclick`: bits-ui skips its select-and-close
  step when an `onclick` handler disables the item.
