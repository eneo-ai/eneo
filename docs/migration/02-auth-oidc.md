# Phase 2 — Auth: generic OIDC riding the IdP session + password login

## Goal
Working end-to-end auth in `web-next`: OIDC login against any standards-compliant IdP (discovery-configured) where the Next.js app is a confidential client holding IdP access + refresh tokens in an encrypted httpOnly cookie and refreshing them itself; username/password login against the backend as the second mode; protected routes; logout (incl. RP-initiated IdP logout). The backend accepts IdP access tokens directly (REQUIRED BACKEND CHANGE RB-1).

This intentionally replaces today's model (frontend obtains a long-lived backend-issued Eneo JWT with no refresh, shared `JWT_SECRET` between frontend and backend, Zitadel/MobilityGuard-specific code paths). Zitadel deployments reconfigure as a generic OIDC client (overview OQ-7).

## Prerequisites
- Phase 1 gate green.
- An IdP reachable from the devcontainer for testing (any OIDC provider with discovery; a local Keycloak/Authentik or the dev Zitadel works since all are standard OIDC).
- Backend PR for RB-1 raised (spec below). Password mode works without RB-1, so frontend work can start in parallel; the OIDC exit criteria need RB-1 deployed to the dev backend.

## REQUIRED BACKEND CHANGE — RB-1 (spec to hand to the backend task)
Accept IdP-issued access tokens as bearer auth, alongside the existing HS256 Eneo JWT:
- New settings in `backend/src/intric/main/config.py`: `oidc_resource_server_enabled: bool = False`, `oidc_accepted_issuer: str | None`, `oidc_accepted_audience: str | None`, `oidc_jwks_cache_ttl_seconds: int = 3600`.
- In the bearer-token dependency (`backend/src/intric/server/dependencies/auth_definitions.py` path): if HS256/`iss=eneo` decode fails AND resource-server mode is on, validate RS256 against the issuer's JWKS (discovery → `jwks_uri`, cached), enforce `iss`, `aud`, `exp` (reuse the leeway setting), then resolve the user by the email claim with the SAME logic the federation callback uses today (allowed-domains check, JIT provisioning if `tenant.provisioning`, active-state checks) in `federation_router.py`. Factor that logic into a shared service rather than duplicating it.
- Behavior preserved: API keys and Eneo JWTs (password sessions, service integrations) keep working unchanged.
- Implementation anchors: the request-path choke point is `UserService.authenticate` → `_get_user_from_token` (`users/user_service.py`), reached from `get_current_active_user` and variants in `authentication/auth_dependencies.py`; the RS256/JWKS validation to reuse is `auth_service.get_payload_from_openid_jwt` (today callback-only); the email→tenant/user resolution to extract into a shared service lives inline in `federation_router.py`.
- Launch constraint: the IdP MUST be configured to issue JWT-format access tokens containing the email claim (Keycloak/Authentik default; Zitadel requires enabling "JWT as access token" on the client — add to the OQ-7 reconfiguration checklist). RFC 7662 introspection for opaque tokens is a documented possible extension, not in scope.
- JIT provisioning moves to the request hot path: parallel first requests from a new user will race. User creation must be idempotent (unique email constraint, catch-and-refetch) and emit exactly one USER_CREATED audit row.
- Tests: valid IdP token → 200 and correct user; wrong `aud` → 401; opaque/non-JWT token → 401 (not 500); unknown email with provisioning off → 403; provisioning on → user created (audit-logged as today); two concurrent first requests → one user, one audit row; JWKS key rotation (unknown kid → refetch → success).
- RECOMMENDED (RB-3, separate PR, non-blocking): short-lived Eneo access token (e.g. 15 min) + `POST /api/v1/users/login/refresh/` with rotating refresh token for password sessions. The frontend below degrades gracefully without it (password sessions then live exactly as long as today's JWT).

## Scope
**In**: session module (JWE cookie via `jose`), `openid-client` v6 flows (authorize redirect with PKCE + state + nonce, code exchange, refresh-token grant, RP-initiated logout), password login form + server action, `proxy.ts` optimistic gating, `getSession()`/`requireSession()` server helpers, login/logged-out/deactivated pages, session-mode abstraction so later phases just call `getAccessToken()`.
**Out**: calling business endpoints (Phase 3), multi-tenant per-tenant federation (overview OQ-1), `/invite` + `/activate` (verify need here, implement in Phase 4 if still required; overview OQ-8).

## Design
- **Session cookie**: name `eneo_session`, JWE (A256GCM, key = `SESSION_SECRET`, 32 bytes), httpOnly, secure (prod), sameSite=lax, path=/. Payload: `{mode: "oidc"|"password", accessToken, accessTokenExpiresAt, refreshToken?, idToken? (for logout hint), user: {email, name?}}`. Cookie maxAge: OIDC → refresh-token-bounded sliding window (e.g. 30 days); password → token exp.
- **OIDC mode**: `GET /auth/login` (route handler) → discovery (cached) → authorize URL (scopes `openid profile email offline_access`, PKCE S256, state, nonce; verifier+state+nonce in a short-lived httpOnly cookie) → IdP → `GET /auth/callback` → code exchange with client secret → store tokens in session cookie → redirect to `next` param or `/dashboard`. Refresh: `getSession()` checks `accessTokenExpiresAt`; if within 60s, runs the refresh grant and re-sets the cookie (serialize concurrent refreshes per request; accept the rare double-refresh across parallel requests, IdPs tolerate it unless rotation is strict; note in code).
- **Password mode**: login page form → server action → `POST {ENEO_BACKEND_URL}/api/v1/users/login/token/` (urlencoded) → store returned `access_token` as `accessToken`, `expiresAt` from its JWT `exp`. If RB-3 ships, store the refresh token and refresh like OIDC mode.
- **Gating**: `proxy.ts` (Next 16; not `middleware.ts`) checks cookie presence for `(app)` paths and redirects to `/login?next=…`; real validation happens in `requireSession()` at the data layer (standard Next guidance). 401 from the backend later (Phase 3) clears the session and redirects.
- **Logout**: `GET /logout` clears the cookie; OIDC mode also redirects to `end_session_endpoint` with `id_token_hint` + `post_logout_redirect_uri=/login` when available.
- **Env (server-only)**: `SESSION_SECRET`, `OIDC_ISSUER` (discovery base), `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, `OIDC_SCOPES` (default above), `APP_ORIGIN` (for redirect URI `${APP_ORIGIN}/auth/callback`). OIDC mode is enabled iff `OIDC_ISSUER` is set; the login page renders the OIDC button and/or the password form accordingly (mirrors today's conditional login methods).

## Step-by-step
1. Install `openid-client@^6` and use `jose` for the JWE session (add both).
2. Build `src/lib/auth/session.ts` (encrypt/decrypt/set/clear, `getSession`, `requireSession`, `getAccessToken` with refresh) with unit tests (round-trip, expiry, refresh-trigger boundary, tampered cookie rejected).
3. Build `src/lib/auth/oidc.ts` (cached discovery, authorize URL builder, callback exchange, refresh, logout URL) with unit tests against mocked discovery metadata.
4. Route handlers: `/auth/login`, `/auth/callback`, `/logout`. Pages: `(public)/login` (password form via server action + OIDC button, error states incl. `access_denied`), `(public)/login/failed`, `(public)/deactivated`.
5. `proxy.ts` with the optimistic check + `next` redirect param.
6. Wire the `(app)` layout to `requireSession()` and render the user's email in the header profile placeholder.
7. Smoke endpoint: temporary server component or route that calls `GET {ENEO_BACKEND_URL}/api/v1/users/me/` with `Authorization: Bearer ${await getAccessToken()}` and renders the email. With RB-1 on, this proves the IdP-token path; in password mode it proves the legacy path. (Removed in Phase 3 when the real client lands.)

## Files/structure created
```
src/lib/auth/{session.ts, oidc.ts, password.ts, index.ts}
src/app/auth/{login/route.ts, callback/route.ts}
src/app/logout/route.ts
src/app/(public)/login/{page.tsx, actions.ts}
src/app/(public)/{login/failed/page.tsx, deactivated/page.tsx}
proxy.ts
+ tests: src/lib/auth/*.test.ts
```

## VALIDATION GATE
1. `bun run check && bun run lint && bun run test` — green (session + oidc unit tests included).
2. Manual OIDC flow (RB-1 deployed on dev backend, real IdP): visit `/dashboard` logged out → redirected to `/login` → OIDC button → IdP login → land on `/dashboard` → smoke component shows the correct email from `/users/me/`.
3. Refresh: set IdP access-token lifetime short (e.g. 1 min) in the test IdP; stay on the app past expiry; next server-rendered request still succeeds and the cookie is re-set (observe via response Set-Cookie / debug log). No re-login prompt.
4. Manual password flow: login with a seeded dev user → `/users/me/` smoke shows the email.
5. Logout: `/logout` clears the cookie AND the IdP session (re-visiting `/auth/login` prompts for credentials again).
6. Negative: tampered `eneo_session` cookie → treated as logged out, no 500. Deactivated user → backend 403 → `/deactivated`.
7. Backend RB-1 tests pass in the backend repo CI (wrong-aud 401, provisioning on/off).

## Exit criteria
Both login modes work against the dev backend; browser devtools show NO bearer token anywhere client-visible (cookie is httpOnly + encrypted); `JWT_SECRET` is absent from the new app's env.

## Risks / unknowns
- IdP refresh-token behavior varies (Keycloak offline_access quirks are a known prior issue in this project's MCP OAuth work). Budget a spike against the actual deployment IdP; the session module isolates this.
- `offline_access` scope may need IdP-side client config (consent, offline tokens enabled). Document in `.env.example` comments.
- Sliding-cookie refresh inside RSC rendering: Next restricts cookie writes during render; perform refresh + Set-Cookie in `proxy.ts` or route handlers/server actions, and have `getAccessToken()` in RSC use the refreshed value without writing. Decide the exact split during implementation; both patterns are documented in Next 16 docs.
- If RB-1 slips: fall back temporarily to exchanging the OIDC login for an Eneo JWT via the backend-driven `/api/v1/auth/initiate` + `/api/v1/auth/callback` flow (today's federation path) behind the same session abstraction; the rest of the phase is unchanged. Flag loudly in the PR if this fallback ships.
