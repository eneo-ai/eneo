# @eneo/web-next

Next.js (App Router) rewrite of the Eneo web frontend. Runs side-by-side with
`apps/web` (SvelteKit) until cutover; see `docs/migration/` for the phase plan.

## Development

Dev server runs on port **3100** (the SvelteKit app owns 3000):

```bash
bun run dev      # next dev -p 3100
bun run dev:clean # clear .next/node cache, then start next dev -p 3100
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

# Encrypts the session cookie (required, min 32 chars)
SESSION_SECRET=

# Origin the app is reached at; used for OIDC redirect URIs (default http://localhost:3100)
# APP_ORIGIN=

# OIDC login (enabled iff OIDC_ISSUER is set; any discovery-capable IdP).
# The IdP must issue JWT-format access tokens with an email claim, and the
# client may need offline tokens/consent enabled for the offline_access scope.
# OIDC_ISSUER=
# OIDC_CLIENT_ID=
# OIDC_CLIENT_SECRET=
# OIDC_SCOPES=openid profile email offline_access

# Feature flags
SHOW_WEB_SEARCH=false
SHOW_HELP_CENTER=false
# HELP_CENTER_URL=
# REQUEST_INTEGRATION_FORM_URL=
```

Validation lives in `src/lib/env.ts` (zod, parsed at import time). There is no
`NEXT_PUBLIC_*` backend URL by design: all backend calls go through the server.

## Auth

Two login modes (see `docs/migration/02-auth-oidc.md`):

- **OIDC**: the app is a confidential client riding the IdP session. Tokens
  live in the encrypted httpOnly `eneo_session` cookie (JWE); `src/proxy.ts`
  does optimistic gating and the sliding refresh. The backend accepts the IdP
  access token directly when `OIDC_RESOURCE_SERVER_ENABLED` is on (RB-1).
- **Password**: server action against the backend's OAuth2 password flow; the
  backend-issued Eneo JWT lives in the same session cookie. No refresh until
  RB-3 ships, so the session ends when the JWT expires.

## UI components

shadcn/ui (new-york style, zinc base, CSS variables) installed into
`src/components/ui` via the CLI:

```bash
bunx shadcn@latest add <component>
```

The theme uses shadcn's semantic token contract (`background`, `primary`,
`muted`, `sidebar`, chart tokens, etc.) but the token values are an intentional
Eneo palette, not stock shadcn. The implemented palette and its rationale are
documented at the top of `src/app/globals.css`; keep all feature styling on
semantic tokens instead of hard-coded colors.

## i18n

next-intl without URL-based routing; the locale comes from the `NEXT_LOCALE`
cookie (default `sv`, also `en`). Catalogs in `src/lib/i18n/messages/` are
generated from the SvelteKit app's Paraglide catalogs:

```bash
node scripts/convert-paraglide-messages.mjs
```

The script flags messages that need manual ICU review; do not edit the
generated catalogs by hand.

`bun run lint` runs `scripts/check-i18n.mjs`, which fails when `sv`/`en` drift
apart or when a literal `t("key")` call is missing from the generated catalogs.
Add web-next-only strings to `src/lib/i18n/extra/{sv,en}.json`, then regenerate.
