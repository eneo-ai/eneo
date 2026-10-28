# @eneo/web-next

The optional React/Next.js (App Router) beta with Astryx for Eneo. SvelteKit in
`frontend/apps/web` is the primary frontend and the default for frontend
development. Implement ordinary frontend fixes and new features in Svelte;
work here must be explicitly intended for the beta. See
[the frontend development policy](../../../AGENTS.md#frontend-development).
Both apps share the backend, accounts and data.

For deployment, callback registration, the opt-in banner and rollback, use
[the deployment guide](../docs-site/src/content/guides/deployment.mdx#run-the-next-beta-alongside-the-existing-app).

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

## Vite build (migration)

The app is moving from Next.js to a Vite SPA with TanStack Router. Until the
move is done, this package builds both, and Next stays the default:

```bash
bun run dev:vite        # Vite dev server on port 3101, beside Next on 3100
bun run build:vite      # static SPA in dist/ (vite.config.mts)
bun run routes:generate # rewrite src/routeTree.gen.ts from src/routes/
```

`src/routeTree.gen.ts` is generated and committed: commit it together with the
route change that produced it. `vite build` does not type-check; `bun run check`
does.

### Vite dev server

The browser talks only to `http://localhost:3101`. The dev server forwards
`/api` (WebSockets too), `/version`, `/login/callback` and `/auth/callback` to
the backend at `ENEO_BACKEND_URL` without changing the Host header, so the
session cookie and the backend's same-origin checks work as in production. It
refuses to start without `ENEO_BACKEND_URL` (set it in `.env.local`). It sends no
CSP; the CSP is checked against the build FastAPI serves.

Run the backend in development mode with these in its `.env`:

```bash
ENVIRONMENT=development          # session cookie eneo_web, without Secure, works on http
BROWSER_SESSION_ENABLED=true
PUBLIC_ORIGIN=http://localhost:3101
```

The backend refuses to start with the browser session in development mode
unless `PUBLIC_ORIGIN` is a localhost origin. The SSO `redirect_uri` follows the
request's host, so register `http://localhost:3101/login/callback` with the
identity provider or the tenant's federation redirect URIs; with global OIDC,
`PUBLIC_ORIGIN` already makes it the redirect URI.

## Environment

Copy [`.env.example`](.env.example) to `.env.local`. Set the backend URL,
the app's public origin and a separate `SESSION_SECRET` (at least 32
characters). Generate the secret with `openssl rand -base64 48`; rotating
it invalidates existing Next sessions. Do not reuse the backend JWT secret.

Validation lives in `src/lib/env.ts` (zod, parsed at import time). There is no
`NEXT_PUBLIC_*` backend URL by design: all backend calls go through the server.

## Auth

- **Password and tenant federation** use the existing backend authentication
  flow and store the backend-issued token in the encrypted, HTTP-only
  `eneo_session` cookie. Register the beta callback with the tenant's
  federation configuration and identity provider as described in the
  deployment guide. These sessions end when the backend token expires.
- **Frontend-managed OIDC** is an experimental separate confidential client,
  configured with `OIDC_*`. The backend accepts its IdP access token when
  `OIDC_RESOURCE_SERVER_ENABLED` and the matching issuer/audience are configured.
  Concurrent requests can reuse a one-time rotating refresh token and invalidate
  the session; refresh ownership is not coordinated across requests or replicas.
  Use backend-managed authentication for the beta rollout. See the deployment
  guide before evaluating this alternative.

`src/proxy.ts` gates navigation and request origins. Backend authorization
remains responsible for tenant, role and resource access on every API call.

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
