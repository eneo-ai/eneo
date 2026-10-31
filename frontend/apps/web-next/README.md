# @eneo/web-next

The optional React/Vite SPA with TanStack Router, TanStack Query and Astryx for Eneo. SvelteKit in
`frontend/apps/web` is the primary frontend and the default for frontend
development. Implement ordinary frontend fixes and new features in Svelte;
work here must be explicitly intended for the beta. See
[the frontend development policy](../../../AGENTS.md#frontend-development).
Both apps share the backend, accounts and data.

For deployment, callback registration, the opt-in banner and rollback, use
[the deployment guide](../docs-site/src/content/guides/deployment.mdx#run-the-react-beta-alongside-the-existing-app).

## Development

Copy [`.env.example`](.env.example) to `.env.local` and set `ENEO_BACKEND_URL`
to your FastAPI backend. The Vite dev server runs on port **3101** (SvelteKit
owns 3000):

```bash
bun run dev      # Vite dev server
bun run dev:clean # clear generated caches, then start Vite
bun run build    # generate routes and build the static SPA in dist/
bun run check    # generate routes and run tsc --noEmit
bun run lint     # i18n + theme staleness + prettier --check + eslint
bun run test     # vitest run
bun run theme:build # compile src/theme/eneo-theme.ts after editing it
```

## Production build

FastAPI serves `dist/` from the backend image, together with the API and
authentication callbacks. There is no separate Node server or `start` command.
`dev:vite` and `build:vite` remain aliases for existing development scripts.

`src/routeTree.gen.ts` is generated and committed: commit it together with the
route change that produced it. `vite build` does not type-check; `bun run check`
does.

Each Vite build writes `node_modules/.cache/vite-bundle-report.json` with
module membership, chunk imports and uncompressed JavaScript sizes. The
`startup` scope includes the entry and required `render-app` module with their
static dependencies; `chat` covers the chat feature's static dependencies, or
is `null` while that feature is absent from the build. Other dynamic imports,
including locale catalogs, remain visible in the chunk graph. These sizes
exclude CSS and other assets.

CI checks route-tree drift before type checking, builds the SPA, and
publishes the bundle report and peak Vite build memory in the
`web-next-vite-build-resources` artifact. Memory also appears in the job
summary. Sizes and memory are measured without a budget gate.

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

## Runtime configuration

Configure deployment links and browser sessions on the backend. The SPA reads
validated public settings from `GET /api/v1/runtime-config`; it contains no
deployment credentials. `ENEO_BACKEND_URL` configures the development proxy
only. Production API requests use the document's origin.

## Auth

Password login and generic OIDC federation use FastAPI's browser-session
endpoints and HTTP-only cookies (`__Host-eneo_web` in production, `eneo_web`
on development localhost). Register the beta's callback with the federation
and identity provider as described in the deployment guide. The frontend does
not hold tokens or OIDC client secrets.

The browser transport binds each document to its checked session generation;
an account change in another tab requires a new document. FastAPI checks
request origin, session, tenant, role and resource access. Router guards control
navigation but do not replace backend authorization.

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
`src/styles/globals.css`, so keep all feature styling on tokens instead of
hard-coded colours.

## i18n

The app uses use-intl.
The locale comes from the `NEXT_LOCALE` cookie (default `sv`, also `en`), and
changing it reloads the document. Catalogs in `src/lib/i18n/messages/` are
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
