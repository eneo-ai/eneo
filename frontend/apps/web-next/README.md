# @eneo/web-next

Next.js (App Router) rewrite of the Eneo web frontend. Runs side-by-side with
`apps/web` (SvelteKit) until cutover; see `docs/migration/` for the phase plan.

## Development

Dev server runs on port **3100** (the SvelteKit app owns 3000):

```bash
bun run dev      # next dev -p 3100
bun run build    # production build
bun run check    # tsc --noEmit
bun run lint     # prettier --check + eslint
bun run test     # vitest run
```

## Environment

Create a local `.env` (or `.env.local`) from this template:

```bash
# Server-side backend base URL (the browser never calls the backend directly)
ENEO_BACKEND_URL=http://localhost:8123

# Required from Phase 2: encrypts the session cookie (min 32 chars)
# SESSION_SECRET=

# Feature flags
SHOW_WEB_SEARCH=false
SHOW_HELP_CENTER=false
# HELP_CENTER_URL=
# REQUEST_INTEGRATION_FORM_URL=
```

Validation lives in `src/lib/env.ts` (zod, parsed at import time). There is no
`NEXT_PUBLIC_*` backend URL by design: all backend calls go through the server.

## UI components

shadcn/ui (new-york style, zinc base, CSS variables) installed into
`src/components/ui` via the CLI:

```bash
bunx shadcn@latest add <component>
```

The theme carries over ONLY the Eneo accent color from the legacy design
system; every other token is stock shadcn. Deviations are documented at the
top of `src/app/globals.css`.

## i18n

next-intl without URL-based routing; the locale comes from the `NEXT_LOCALE`
cookie (default `sv`, also `en`). Catalogs in `src/lib/i18n/messages/` are
generated from the SvelteKit app's Paraglide catalogs:

```bash
node scripts/convert-paraglide-messages.mjs
```

The script flags messages that need manual ICU review; do not edit the
generated catalogs by hand.
