# @eneo/ui

Design tokens, themes and icons for the Eneo frontend.

The components themselves live in `apps/web` on shadcn-svelte
(`apps/web/src/lib/components/ui`). This package holds what those components are
styled with:

| Export                                  | Contents                                                                                           |
| --------------------------------------- | -------------------------------------------------------------------------------------------------- |
| `@eneo/ui/styles`                       | Tailwind 4 entry: colour tokens, themes (`src/styles/themes`), font stacks, utilities and `.prose` |
| `@eneo/ui/styles/prose`                 | Typography for rendered Markdown (`.prose`)                                                        |
| `@eneo/ui/icons/vite-plugin-eneo-icons` | Vite plugin that serves `src/icons/svg/*.svg` as `@eneo/icons/<name>` Svelte components            |
| `@eneo/ui/icons/types`                  | Type declarations for the `@eneo/icons/*` modules                                                  |

See `frontend/COLORS.md` for how the tokens are meant to be used.

## Developing

Dependencies are installed from the monorepo root (`bun install`). To rebuild the
package while working on it:

```bash
bun run dev
```
