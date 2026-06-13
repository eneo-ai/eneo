# web-next cutover checklist

How to flip production from `apps/web` (SvelteKit) to `apps/web-next` (Next)
behind the reverse proxy, with a rollback path. Owned by whoever operates
production; this is the migration team's handoff.

## Pre-flip

- [ ] **IdP client** (OQ-7): register the new redirect URI
      `${APP_ORIGIN}/auth/callback` on the OIDC client; keep the old SvelteKit
      redirect URI registered until rollback is no longer needed.
- [ ] **Backend flags**: `OIDC_RESOURCE_SERVER_ENABLED=true` and the RB-2
      conversation `version=3` framing deployed (already live on the backend
      used during the migration).
- [ ] **Env provisioning** (see `ENV.md`): `ENEO_BACKEND_URL`, `SESSION_SECRET`
      (≥32 chars), `OIDC_ISSUER`/`OIDC_CLIENT_ID`/`OIDC_CLIENT_SECRET`,
      `APP_ORIGIN`. Confirm `JWT_SECRET` / `ZITADEL_*` are NOT required.
- [ ] **Build the image**: `docker build -f frontend/apps/web-next/Dockerfile
      -t eneo-web-next ./frontend`; boot it with only the documented env vars.
- [ ] **In-container smoke**: `curl :3000/healthz` OK; a full login + chat
      round-trip against the target backend works from the container.
- [ ] **Reverse proxy**: disable response buffering on `/api/chat` (SSE). No
      WebSocket section needed (not ported). Route everything else normally.

## Hardening still open (verify in a browser before/just after flip)

- [ ] **CSP**: the app ships safe baseline headers (`X-Frame-Options`,
      `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`) but
      NOT a strict `script-src`. To add nonce-based CSP, wire a nonce through
      `src/proxy.ts`/middleware and set the header per request, then confirm
      zero CSP violations across a full walkthrough.
- [ ] **No-token-leak check**: confirm no `Authorization` header on any
      browser-initiated request (all go through `/api/eneo`) and no
      token-looking strings in `document.cookie` / `localStorage`.
- [ ] **E2E**: stand up web-next against `docker-compose.e2e.yml` + the mock
      LLM (v3) and run the critical journeys (login, space→assistant→upload→
      chat-with-citation, tool approval, admin user create, audit export).

## Flip

- [ ] Point the proxy upstream for the app origin at the web-next container.
- [ ] Watch `/healthz`, error rates, and trace-ids (surfaced on the
      `(app)/error.tsx` boundary) for the first traffic.
- [ ] Users re-login once (sessions are cookie-local; no data migration — same
      backend).

## Rollback

- [ ] `apps/web` stays built and deployable; revert the proxy upstream to it.
      No backend/data changes are required to roll back (cookie sessions only).

## Post-cutover (ops tasks, out of migration scope)

- [ ] Finish the DEFERRED rows in `PARITY.md` that the maintainer reclassifies
      as needed (model wizards/migration, template editors, insights charts,
      SharePoint Azure-AD config, api-key policy, governance allow-list editor).
- [ ] Retire `apps/web` once web-next is stable.
- [ ] PWA manifest (OQ-4) if the maintainer wants it.
