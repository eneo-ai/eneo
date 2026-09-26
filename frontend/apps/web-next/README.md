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
bun run lint     # i18n + theme staleness + prettier --check + eslint
bun run test     # vitest run
bun run theme:build # compile src/theme/eneo-theme.ts after editing it
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

# Your organisation's accessibility statement (tillgänglighetsredogörelse,
# required by DOS-lagen). Linked from the login page and the profile menu when
# set; see ACCESSIBILITY.md.
# ACCESSIBILITY_STATEMENT_URL=
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

New UI is built with [Astryx](https://github.com/facebook/astryx)
(`@astryxdesign/core`) and the Eneo theme (`src/theme/eneo-theme.ts`, compiled
to static CSS with `bun run theme:build`). **Read [AGENTS.md](AGENTS.md) before
building UI**: it covers the offline component docs (`bunx astryx component
<Name>`), tokens and the `ax-*` Tailwind bridge, the shared composites, and the
CSP and i18n rules.

web-next must meet **WCAG 2.2 AA**. [ACCESSIBILITY.md](ACCESSIBILITY.md) is the
standard: rules per topic, the automated checks (jsx-a11y and `eneo/*` lint
rules, axe component tests, the token contrast test, Playwright page scans) and
the manual test protocol for every PR that changes UI.

The shadcn/ui components in `src/components/ui` are legacy: don't add new ones,
and replace them as screens migrate. Their semantic variables (`--background`,
`--primary`, `--muted`, …) are mapped onto the Eneo tokens in
`src/app/globals.css`, so keep all feature styling on tokens instead of
hard-coded colours.

## i18n

next-intl without URL-based routing; the locale comes from the `NEXT_LOCALE`
cookie (default `sv`, also `en`). Catalogs in `src/lib/i18n/messages/` are
generated from the SvelteKit app's Paraglide catalogs:

```bash
bun run i18n:convert
```

The script flags messages that need manual ICU review; do not edit the
generated catalogs by hand. Add web-next-only strings (and web-next wording of
an apps/web string) to `src/lib/i18n/extra/{sv,en}.json`, then regenerate.

`bun run lint` runs `scripts/check-i18n.mjs`, which fails when `sv`/`en` drift
apart, when a literal `t("key")` call is missing from the generated catalogs,
or when the catalogs differ from what the converter writes (a hand edit, or
apps/web's catalogs changed since the last run): regenerate to fix it.
