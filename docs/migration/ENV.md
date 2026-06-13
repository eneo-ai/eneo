# web-next environment variables

The Next app validates its environment at import (`src/lib/env.ts`, zod). Unset
or invalid required vars fail the build/boot fast. This maps the old SvelteKit
(`apps/web`) variables to the new ones.

## Required

| Var | Purpose | Notes |
|---|---|---|
| `ENEO_BACKEND_URL` | Base URL of the FastAPI backend | e.g. `http://localhost:8123`. The browser never calls it directly — everything goes through the `/api/eneo` proxy and the chat passthrough. |
| `SESSION_SECRET` | Encrypts the session cookie | Min 32 chars. Rotating it logs everyone out. |

## OIDC (enabled iff `OIDC_ISSUER` is set)

| Var | Purpose |
|---|---|
| `OIDC_ISSUER` | Discovery base URL of the IdP. Unset ⇒ password-login mode. |
| `OIDC_CLIENT_ID` | Required when `OIDC_ISSUER` is set. |
| `OIDC_CLIENT_SECRET` | Required when `OIDC_ISSUER` is set. |
| `OIDC_SCOPES` | Default `openid profile email offline_access`. |
| `APP_ORIGIN` | Public origin used to build OIDC redirect URIs. Default `http://localhost:3100`. In prod set to the deployed origin (drives the redirect URI registered with the IdP — see CUTOVER.md). |

## Optional feature flags

| Var | Default | Purpose |
|---|---|---|
| `SHOW_HELP_CENTER` | `false` | Shows the help-center link in the admin shell. |
| `HELP_CENTER_URL` | — | URL for the above. |
| `REQUEST_INTEGRATION_FORM_URL` | — | "Request an integration" link target. |

## Migration mapping (SvelteKit `apps/web` → web-next)

| Old (SvelteKit) | New (web-next) | Change |
|---|---|---|
| `INTRIC_BACKEND_URL` / `baseUrl` | `ENEO_BACKEND_URL` | renamed |
| `JWT_SECRET` | — | **gone** (sessions are cookie-encrypted via `SESSION_SECRET`; the backend issues/validates its own bearer) |
| `ZITADEL_*` / MobilityGuard vars | — | **gone** (Zitadel/MobilityGuard flows dropped; generic OIDC via `OIDC_*`) |
| — | `SESSION_SECRET` | **new** (cookie encryption) |
| — | `OIDC_ISSUER` / `OIDC_CLIENT_ID` / `OIDC_CLIENT_SECRET` / `OIDC_SCOPES` | **new** (generic OIDC) |
| — | `APP_ORIGIN` | **new** (redirect-URI origin) |

## Reverse proxy

- Disable response buffering on `/api/chat` (Server-Sent Events streaming).
- No WebSocket section needed — the WS app-run/crawl updates were not ported
  (polling covers parity).
- The audit access-session cookie is re-scoped to `Path=/api/eneo/api/v1` by
  the proxy route; no proxy cookie config needed beyond passing cookies through
  on the same origin.
