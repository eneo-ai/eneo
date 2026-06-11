# Phase 8 — i18n completeness, polish, production readiness, parity audit

## Goal
Ship-readiness: full sv/en translation coverage with CI checks, hardened production build (Docker, CSP, healthz, env docs), E2E suite on the isolated stack, a systematic parity audit against the Phase 0 inventory, and a cutover checklist. This phase turns "feature-complete" into "deployable replacement".

## Prerequisites
- Phases 1–7 gates green.
- Decisions on overview OQ-3 (cutover mechanics) and OQ-4 (PWA) from the maintainer/ops.

## Scope
**In**: translation sweep + i18n CI (parity + unused-key checks, porting the spirit of `scripts/check-i18n-*.py`), loading/empty/error states pass over every route (Suspense boundaries, `error.tsx`, `not-found.tsx` per area), accessibility pass on forms/dialogs (labels, focus traps, keyboard nav), CSP (`script-src 'self'` parity; Next inline-runtime needs nonces or hashes — verify the Next 16 CSP guide), Dockerfile (standalone output, Node 20 slim runner, port 3000), `next.config.ts` production review (`output: "standalone"`, image config, explicit `"use cache"` audit), CI completion (E2E job), Playwright E2E porting the critical journeys to web-next on the existing `docker-compose.e2e.yml` stack (mock LLM speaking v3 per Phase 5), PWA manifest port (if OQ-4 says yes), parity audit, cutover checklist.
**Out**: actually flipping production traffic (ops-owned, guided by the checklist), deleting `frontend/apps/web` (post-cutover task).

## Step-by-step
1. **Translation sweep**: re-run the conversion script against the full catalogs; walk every route in `sv` then `en` hunting raw keys/English-in-Swedish; wire the i18n CI checks (duplicate keys, sv/en parity, unused keys via a scan).
2. **State polish**: per area add `loading.tsx`/Suspense skeletons, `error.tsx` with trace-id display, empty states with CTAs (the Svelte app's template hints, "no assistants yet" etc.).
3. **A11y pass**: keyboard-only walkthrough of login, chat, one builder, one admin table; fix focus/label gaps (AI Elements and shadcn are solid baselines; the custom composites are the risk).
4. **Security/CSP**: add CSP headers (nonce-based `script-src`), verify no token leaks (automated check: Playwright asserts no `Authorization` header in any browser-initiated request and no token-looking strings in `document.cookie`/localStorage).
5. **Production build**: Dockerfile (Bun build stage → Node 20 runner, standalone output), `/healthz` verified in-container, env documented in `.env.example` + a `docs/migration/ENV.md` mapping old SvelteKit vars → new vars (explicitly: `JWT_SECRET` gone, `ZITADEL_*` gone, `OIDC_*`/`SESSION_SECRET` new). Reverse-proxy notes: disable response buffering on `/api/chat` (SSE), websocket section N/A (not ported).
6. **E2E**: extend `docker-compose.e2e.yml` (or a sibling compose file) to build/run web-next against the isolated backend + mock LLM; port the highest-value Playwright journeys: login (password mode; OIDC mocked or against a containerized IdP if the stack gains one), space create → assistant create → upload knowledge → chat with citation, tool-approval flow, admin user create, audit export. Reuse the storage-state auth pattern.
7. **Parity audit**: walk `00-overview.md` §2.1 line by line; produce `docs/migration/PARITY.md` with one row per capability: PASS / REDESIGNED (note) / DROPPED (justified: Zitadel/MobilityGuard flows, legacy admin per OQ-2, WS app-run updates → polling) / MISSING (blocks cutover). Every MISSING gets fixed or explicitly accepted by the maintainer before exit.
8. **Cutover checklist** (`docs/migration/CUTOVER.md`): IdP client registration for the new redirect URI (OQ-7), backend flags (`OIDC_RESOURCE_SERVER_ENABLED=true`, RB-2 deployed), env provisioning, reverse-proxy flip plan + rollback (old app stays deployable), data considerations (none expected: same backend, sessions are cookie-local; users re-login once), monitoring (healthz, error rates, trace-ids), comms.

## VALIDATION GATE
1. Full local CI parity: `bun run check && bun run lint && bun run test && bun run build` green; i18n checks green; E2E suite green on the isolated stack (run twice to shake flakes).
2. `docker build` of web-next succeeds; container boots with only documented env vars; `curl /healthz` OK; a full login + chat round-trip works against the dev backend from the containerized app.
3. CSP: browser console shows no CSP violations across a full walkthrough; the no-token-leak Playwright assertion passes.
4. Lighthouse (or equivalent) sanity on `/dashboard` and chat: no regression class issues (TTI not worse than the Svelte app by an order of magnitude; record numbers, no hard budget).
5. `PARITY.md` complete with zero unaccepted MISSING rows; maintainer sign-off recorded in the file.
6. `CUTOVER.md` reviewed by whoever operates production.

## Exit criteria
web-next is deployable as a drop-in replacement behind a proxy flip, with an auditable parity record and a rollback path. The migration project closes; cutover execution and `apps/web` retirement proceed as ops tasks.

## Risks / unknowns
- E2E OIDC: containerizing an IdP (e.g. Keycloak) in the e2e stack is the robust option but is new infrastructure; password-mode E2E + a manually verified OIDC flow is the acceptable fallback for the gate.
- CSP with Next inline scripts requires the nonce pattern; budget iteration time.
- The parity audit will find forgotten small capabilities (it exists to do exactly that); reserve slack in this phase rather than treating it as a checkbox.
