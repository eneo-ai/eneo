# @eneo/web-next

The optional Next.js (App Router) frontend for Eneo. The existing SvelteKit
app remains the default. Both apps share the backend, accounts and data.

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
- **Frontend-managed OIDC** is an optional separate confidential client,
  configured with `OIDC_*`. It supports refresh tokens; the backend accepts
  the IdP access token when `OIDC_RESOURCE_SERVER_ENABLED` is enabled and
  the matching issuer/audience are configured.

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
