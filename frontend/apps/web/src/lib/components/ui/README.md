# `src/lib/components/ui` — shadcn-svelte primitives

This directory holds [shadcn-svelte](https://shadcn-svelte.com) components copied
into the project via the shadcn CLI. They are an entry point for adopting
shadcn-svelte in eneo and live alongside the existing `@eneo/ui` package.

## Why two UI systems?

`@eneo/ui` (in `frontend/packages/ui`) is the existing in-house design system
(Svelte 4 syntax, melt-ui, brand tokens). It is **not** going away — it covers
many components shadcn-svelte does not, and rewriting it has no business value.

shadcn-svelte is being introduced because:

- It uses Svelte 5 runes, matching the direction the codebase is moving.
- "Copy the source into your project" lets us evolve components without
  fighting upstream APIs.
- Its bits-ui foundation gives us modern, well-maintained primitives where
  `@eneo/ui` would otherwise need new investment.

## When to use which

| Use shadcn-svelte (`$lib/components/ui/*`) when… | Use `@eneo/ui` when… |
| --- | --- |
| Building a new primitive that does not yet exist in `@eneo/ui` | The component already exists in `@eneo/ui` and works |
| You explicitly want Svelte 5 runes / bits-ui semantics | Touching code that already uses `@eneo/ui` — don't mix in the same file |
| The component is web-app-only and unlikely to be shared across apps | The component should be available to other apps in the monorepo |

**Avoid** importing both `@eneo/ui` and shadcn primitives in the same file.
Pick one per surface and convert wholesale if needed.

## Adding a new shadcn component

1. Run `npx shadcn-svelte@latest add <component>` from `frontend/apps/web`.
2. Check which Tailwind tokens the new component references
   (`text-muted-foreground`, `bg-muted`, `border-*`, `ring-*`, etc.).
3. Make sure each referenced token is mapped in `src/app.css` under the
   `@theme inline { … }` block. Map shadcn semantic tokens to existing
   eneo tokens (`--background-*`, `--text-*`, `--border-*`).
4. **Do not** add token mappings to `frontend/packages/ui/src/styles/main.css`
   — that file is shared across apps and must stay shadcn-agnostic.
5. Try to keep the generated component files verbatim so future CLI
   updates merge cleanly. Customize via class overrides at the call site.

## Component file conventions

- Files are kept as the shadcn-svelte CLI generates them.
- Each component folder has an `index.ts` that re-exports the parts as both
  named exports (`Card`, `CardHeader`) and a namespace (`Card.Root`,
  `Card.Header`).
- Prefer the namespace import in consumers: `import * as Card from "$lib/components/ui/card/index.js"`.
