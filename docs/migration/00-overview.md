# Eneo Frontend Migration: SvelteKit → Next.js — Overview

Status: PLAN (discovery complete, no code written)
Date: 2026-06-11
Decisions confirmed with the maintainer: app location, auth model, chat protocol (see "Locked decisions").

---

## 1. Locked decisions

| Decision | Choice |
|---|---|
| App location | `frontend/apps/web-next` in the existing Bun monorepo, running side-by-side with `frontend/apps/web` until cutover. Package name `@eneo/web-next`: new code uses the eneo name, never the legacy `@intric/*` prefix |
| Target stack | Next.js 16.2.x (App Router) + TypeScript + React 19, shadcn/ui (Tailwind v4), Vercel AI SDK v6 (`ai` ^6, `@ai-sdk/react` ^3), AI Elements for chat UI, TanStack Query v5 for REST data |
| Design system | UI is composed exclusively from shadcn/ui + AI Elements primitives. Primitives are CLI-installed into the app at `src/components/ui` (the web app is the only consumer, so there is NO shared workspace package); generic composites live in `src/components/composites`. Feature code composes; it never defines bespoke primitives. Theme: shadcn's semantic token contract (new-york, CSS variables) with an intentional Eneo palette in `src/app/globals.css`; feature code must use semantic tokens, not hard-coded colors or copied Svelte token mappings. |
| Auth at launch | Generic OIDC (any standards-compliant IdP via discovery URL) + username/password. Zitadel and MobilityGuard-specific frontend flows are NOT ported; Zitadel is reachable through the generic flow since it is standard OIDC. |
| Session model | The Next.js app is a confidential OIDC client and rides the IdP session end-to-end: it holds IdP access + refresh tokens in an encrypted httpOnly cookie and refreshes them itself. The backend becomes an OIDC resource server (REQUIRED BACKEND CHANGE RB-1). Password login keeps the backend-issued Eneo JWT. |
| Chat streaming | Backend natively emits the AI SDK "UI Message Stream" SSE protocol (REQUIRED BACKEND CHANGE RB-2); the Next.js route handler is a thin auth-injecting proxy. |

Versions were verified against npm and live docs on 2026-06-11 (see `01-boilerplate.md` §Versions). Notable: `ai` v7 exists only as beta, do not target it; next-auth v5 never shipped stable; Better Auth was evaluated and rejected because riding the IdP session needs no app database and password login goes against the FastAPI backend anyway, so a hand-rolled `openid-client` v6 + `jose` session is lighter and fits better.

---

## 2. Discovery inventory

### 2.1 Route/feature map (parity checklist)

The SvelteKit app (`frontend/apps/web/src/routes`) groups into these feature areas. Every user capability below must exist in the new app unless marked DROP or DEFER.

**Public / auth** (`(public)` group)
- `/login` — password form + OIDC entry (today: Zitadel, MobilityGuard, generic federation). New app: generic OIDC button + password form.
- `/login/callback`, `/auth/callback` — OIDC code exchange. New app: one `/auth/callback` route handler.
- `/login/failed`, `/deactivated`, `/activate`, `/invite/[organisationId]`, `/logout`, `/login/switch-organisation`, `/healthz`.
- `/integrations/callback/token` — SharePoint service-account OAuth callback (BFF action).

**Dashboard**
- `/dashboard` — accordion of spaces → assistants/apps with sessions; scroll-state preservation.
- `/dashboard/[assistantId]/[[sessionId]]` — chat from a dashboard tile.
- `/dashboard/app/[appId]` (+ `/results/[resultId]`) — run app, view results.

**Spaces**
- `/spaces/list` — table of shared spaces, create (permission `shared_spaces`).
- `/spaces/[spaceId]/overview` — tile overview; `/members` — member + group-member role management; `/settings` — name, models (completion/embedding/transcription), MCP servers, security classification, storage/retention.

**Chat** (the core capability; rebuilt on ai-sdk + AI Elements)
- `/spaces/[spaceId]/chat` — chat hub for default assistant / assistant / group chat. History list with cursor pagination, session switching, insights tab, model switcher, new-conversation, mentions (`@assistant` in group chats), file attachments, web-search toggle, tool calls with MCP approval flow, context-usage bar fed by preflight + streamed token usage, reasoning indicator, abort, feedback (+1/-1 + text), rename, delete, auto-title.

**Builders**
- `/spaces/[spaceId]/assistants` (+ `[assistantId]/edit`) — assistant CRUD, prompt, knowledge, MCP servers, publish, templates.
- `/spaces/[spaceId]/group-chats/[groupChatId]/edit` — assistants selection, mention mode, icon upload, publish.
- `/spaces/[spaceId]/apps` (+ `[appId]`, `/edit`, `/results/[resultId]`) — app CRUD, run with form inputs, results.
- `/spaces/[spaceId]/services` (+ `[serviceId]`) — service CRUD + run.

**Knowledge**
- `/spaces/[spaceId]/knowledge` — tabs: Collections, Websites, Integrations; bulk recrawl; sync history dialog.
- `.../collections/[collectionId]`, `.../websites/[id]`, `.../integrations/wrapper/[wrapperId]`.

**Account**
- `/account` — profile, language selector, version info. (Zitadel display-name editing: DROP, IdP-specific.)
- `/account/api-keys` — API-key CRUD, rotation, revocation, scopes, expiry notifications.
- `/account/integrations` — personal integration connections (OAuth popup flow).

**Admin** (permission `admin`)
- `/admin` — feature toggles (templates, audit logging, provisioning).
- `/admin/users` (+ editor) — user CRUD, invite, activate/deactivate, search, pagination.
- `/admin/audit-logs` — filtered table + retention policy + async CSV export (today via 4 SvelteKit BFF `+server.ts` proxies; ported as Next route handlers).
- `/admin/models` — model/provider CRUD, favorites, credentials, migration flow with validation.
- `/admin/security-classifications`, `/admin/mcp-servers`, `/admin/api-keys`, `/admin/integrations`, `/admin/templates` (+ new/edit per kind), `/admin/help-assistants` (+ `[kind]`), `/admin/insights` (+ per-assistant), `/admin/usage` (tokens/storage/per-user).
- `/admin/legacy/roles`, `/admin/legacy/user-groups` — OPEN QUESTION OQ-2 (port or drop).

### 2.2 Auth today (what we are replacing)

- Backend issues an HS256 "Eneo JWT" (`sub` = email, TTL = `jwt_expiry_time`, no refresh; sessions die silently). Frontend stores it in an httpOnly `auth` cookie, misnamed `id_token` internally; a second `acc` cookie holds the Zitadel access token.
- Four login paths: Zitadel PKCE (frontend exchanges code at IdP, uses Zitadel ID token directly against the backend), MobilityGuard PKCE (backend exchanges via `/users/login/openid-connect/mobilityguard/`), generic federation (backend-driven: `GET /api/v1/auth/initiate` → signed-state JWT → `POST /api/v1/auth/callback` → Eneo JWT, with JIT provisioning + allowed-domains), and password (`POST /api/v1/users/login/token/`).
- Frontend env couples to the backend via a shared `JWT_SECRET`. This coupling is removed in the new app.
- Authorization: roles (custom + predefined) with a flat `Permission` enum, fetched via `/api/v1/users/me/`; resource-level roles on spaces (admin/editor/viewer).

### 2.3 Chat today (what we are replacing)

- `POST /api/v1/conversations/?version=2` with `{session_id | assistant_id | group_chat_id, question, files, tools, stream, use_web_search, require_tool_approval}`; response is bespoke SSE: `first_chunk`, `text` (delta + full references snapshot per event), `image` (generated files), `intric_event`, `token_usage`, `tool_call`, `tool_approval_required`, `tool_approval_timeout`, `error`.
- Sibling endpoints: list (cursor-paginated), get, rename, delete, feedback, title generation, `POST /conversations/preflight` (token estimate, rate-limited 600/min), `POST /conversations/approve-tools/?approval_id=`.
- Frontend: `ChatService.svelte.ts` (runes), RAF-buffered rendering, AbortController; backend persists partial messages on abort. No WebSockets in chat (WS exists only for `app_run_updates`).

### 2.4 Backend API surface consumed (summary + contract quality)

Hand-written client `@intric/intric-js` wraps types generated by `openapi-typescript` from the backend's `/openapi.json` (regenerated via `npm run update`). All endpoints under `/api/v1/`.

| Group | Quality | Notes |
|---|---|---|
| Spaces (CRUD, members, group-members, applications, knowledge) | clean | |
| Assistants | wants-changing | POST used for updates (should be PATCH); sessions endpoints superseded by conversations |
| Conversations | good | `version=2` param; superseded by RB-2 (version=3) |
| Group chats, Apps, Services, Knowledge groups, Websites/crawls, Templates, Roles, Models (+migration flow), Prompts, Dashboard, Settings | clean/good | |
| Files | clean | multipart upload + signed-URL download (good fit for the new app; browser never needs the bearer token for downloads) |
| Users | wants-changing | two pagination styles (cursor on `/users/`, offset on `/admin/users/`), duplicate update endpoints (by username and by id) |
| Audit logs | wants-changing | separate cookie-based "access session" auth; offset pagination |
| Jobs | minimal | no filtering; polled at 2s/30s |
| Errors | wants-changing | `detail` is variously a string, an object, or a validation array; `intric_error_code` + `X-Trace-Id` headers exist |
| Integrations | good | complex but coherent; OAuth popup flow |
| WebSocket | n/a | `app_run_updates` channel only; token passed to browser JS today (incompatible with the new "browser never holds a token" model, see RB-4) |

### 2.5 Cross-cutting concerns

- **State**: Svelte 5 runes services (ChatService, AttachmentManager, JobManager, SpacesManager…) bound via context. Maps to React: TanStack Query for server state, small zustand-or-context stores only where needed (chat is owned by `useChat`).
- **i18n**: Paraglide v2, `sv` (base) + `en`, ~3,383 keys per locale in `frontend/apps/web/messages/{sv,en}.json`, CI parity checks. New app: next-intl, reusing the catalogs via a conversion script (keys are flat, mostly ICU-compatible; verify plurals).
- **Env vars today**: `PUBLIC_ENEO_BACKEND_URL` (browser), `ENEO_BACKEND_URL` / `ENEO_BACKEND_SERVER_URL` (server), `JWT_SECRET` (shared with backend; eliminated), `ZITADEL_*` (dropped), `PUBLIC_ORIGIN`, feature flags `SHOW_WEB_SEARCH` (legacy, dropped), `SHOW_HELP_CENTER`, `FORCE_LEGACY_AUTH`, `REQUEST_INTEGRATION_FORM_URL`, `HELP_CENTER_URL`.
- **Feature flags**: env-derived + backend `/api/v1/auth/federation-status` + tenant settings (`/api/v1/settings/`).
- **Uploads**: chat attachments (5 concurrent, progress via XHR) and knowledge blobs (job-tracked). Downloads via signed URLs.
- **Realtime**: SSE for chat; WS for app-run updates; adaptive polling (JobManager 2s→30s) as fallback.
- **Theming**: data-theme attribute, OKLCH token system in `@intric/ui`, partial shadcn-svelte adoption already mapping shadcn tokens onto Eneo tokens. New app: deliberately NOT ported; fresh shadcn theme with only the Eneo accent carried over (see Locked decisions §Design system).
- **Errors/toasts**: `IntricError` with `code`/`status`/`traceId`/`getReadableMessage()`; melt-ui toaster. New app: sonner (shadcn default) + the same error-code → message mapping.
- **Build/deploy**: adapter-node, Bun-built, Node 20 runtime Docker image on port 3000, strict CSP (`script-src 'self'`), PWA manifest (installable, no service worker). CI: i18n checks, typecheck, lint, vitest (browser-mode), build, Playwright E2E against an isolated docker-compose stack with a mock LLM, OpenAPI schema-drift check.

---

## 3. Target architecture

```
frontend/apps/web-next/                  Next.js 16 App Router, TS strict (@eneo/web-next)
├─ src/app/
│  ├─ globals.css                       Tailwind v4 @theme: fresh shadcn palette + Eneo accent
│  ├─ (public)/login, /auth/callback, /logout, /healthz, ...
│  ├─ (app)/dashboard, /spaces/[spaceId]/..., /admin/..., /account/...
│  └─ api/
│     ├─ eneo/[...path]/route.ts        REST proxy → FastAPI, injects Bearer from session
│     └─ chat/route.ts                  chat proxy → FastAPI v3 stream, passthrough
├─ src/components/
│  ├─ ui/                               shadcn/ui primitives (new-york, CLI-installed)
│  ├─ ai-elements/                      AI Elements (CLI-vendored, editable; from Phase 5)
│  └─ composites/                       generic composites (data-table, form fields, page
│                                       header, confirm dialog, empty state, …)
├─ src/lib/
│  ├─ auth/                             openid-client v6 + jose JWE session cookie, refresh
│  ├─ api/                              openapi-typescript types + openapi-fetch client
│  ├─ chat/                             useChat transport, UIMessage type defs, approval hook
│  └─ i18n/                             next-intl, sv + en
├─ src/features/                        feature compositions (built from src/components)
└─ proxy.ts                             optimistic auth gating (cookie presence) + locale
```

Principles:
- All UI is built from shadcn/ui and AI Elements primitives CLI-installed into `src/components/ui` / `src/components/ai-elements`; if a primitive is missing, install it via the shadcn CLI rather than hand-rolling it. There is no shared UI workspace package (the web app is the only consumer). Feature code composes; it does not define primitives.
- Server Components by default; Route Handlers only for the two proxies, auth endpoints, and the audit-export BFF. Mutations via Server Actions where a form fits, TanStack Query mutations elsewhere.
- The browser never holds a bearer token. All backend calls go server-side (RSC/route handler/server action). Signed URLs cover file downloads; job polling replaces the WebSocket initially (RB-4 optional).
- Explicit caching only (`"use cache"` where safe); everything else request-time, which matches the current app's no-cache behavior.
- UI flows may be redesigned (this is sanctioned); capabilities are the parity contract, the route map in §2.1 is the checklist.
- Testing policy (all phases): business logic gets unit tests — parsers, mappers, session/token handling, pagination and error normalization, stream protocol mapping, conversion scripts, route-handler logic. UI tests (component render, snapshot, per-phase E2E) are NOT required; do not build them for parity. The isolated E2E stack appears once, in Phase 8, as a thin smoke layer.
- The API layer is a rewrite, not a port: `@intric/intric-js` is replaced (Phase 3), and its patterns must not be carried over. Where the old client did something awkward (hand-written wrapper class, hand-patched type overrides, cookie misnomers, baked-in POST-as-update calls), design the better alternative instead of transcribing it.

---

## 4. Required backend changes

Each is specified in the phase that consumes it. None block Phase 1.

| ID | Change | Rationale | Consumed by |
|---|---|---|---|
| **RB-1** | Accept IdP-issued access tokens as a first-class auth method: validate RS256 via cached JWKS (configured issuer + audience), map the email claim to a user, reuse existing allowed-domains + JIT-provisioning logic from `federation_router.py`. New settings: `OIDC_RESOURCE_SERVER_ENABLED`, `OIDC_ACCEPTED_ISSUER`, `OIDC_ACCEPTED_AUDIENCE`. Keep HS256 Eneo-JWT validation for password sessions and API keys. | Lets the frontend ride the IdP session (refresh tokens give real session continuity; today sessions silently die because Eneo JWTs have no refresh). Removes the shared `JWT_SECRET` frontend coupling. The JWKS validation code already exists for the federation callback; this reuses it on the request path. Forward-looking: the backend then holds a genuine IdP-issued token per request, usable as the subject token for RFC 8693 token exchange toward MCP servers and other downstream services (on-behalf-of the real user), which the self-signed Eneo JWT can never be. Keep login scopes minimal; exchange for downstream audiences as needed. | Phase 2 |
| **RB-2** | Conversations stream `version=3`: emit the AI SDK UI Message Stream SSE protocol (`start`, `text-start/-delta/-end`, `tool-input-available`, `tool-output-available`, `source-document`, `file`, `data-*` custom parts, `error`, `finish`, `data: [DONE]`) with header `x-vercel-ai-ui-message-stream: v1`. Mapping from today's events is specified in `05-chat.md`. `version=2` stays untouched for the old frontend. | Makes the Python backend natively `useChat`-compatible; the Next.js chat route handler becomes a passthrough instead of a permanent protocol-translation layer. Tool approval, references, and token usage become typed parts instead of bespoke events. | Phase 5 |
| **RB-3** (recommended, not blocking) | Refresh for password sessions: short-lived access token + `POST /api/v1/users/login/refresh/` (rotating refresh token). | Without it, password users keep today's silent-session-death behavior. OIDC users are unaffected. | Phase 2 (graceful degradation if absent) |
| **RB-4** (optional) | Short-lived WS ticket endpoint (`POST /api/v1/ws/ticket` → one-time token) so the browser can open the `app_run_updates` socket without holding the bearer token. | Today the WS token is exposed to browser JS. Polling (already the fallback) covers parity, so this is deferred until polling proves insufficient. | Phase 6 |
| **RB-5** (cleanups, apply opportunistically when an endpoint is touched) | (a) Unify list pagination on cursor style (`/admin/users/`, audit logs are offset today); (b) PATCH instead of POST for partial updates (assistants, services, groups, user by username); (c) one error envelope `{"detail": {"message", "code"}}` everywhere (today: string / object / validation array); (d) audit-log auth via Bearer + a justification header instead of a separate cookie session; (e) document file-size limits in OpenAPI. | Consistency for the typed client; the new frontend codes against the good shape and lists per-endpoint workarounds it had to keep. | Phases 3–7 |

---

## 5. Open questions

Answered ones are folded into the plan; these remain and are flagged where they bite:

- **OQ-1 Multi-tenant federation**: the new auth model configures ONE IdP via env (single-tenant). Per-tenant IdP federation (tenant picker, per-tenant discovery) is not in the launch plan. If a deployment needs it, the backend-driven `/auth/initiate` + `/auth/callback` flow must be kept as an additional login mode. Assumed out of scope for launch.
- **OQ-2 Legacy admin routes**: `/admin/legacy/roles` and `/admin/legacy/user-groups` are marked legacy in the current app. Plan assumes DROP; confirm before Phase 7.
- **OQ-3 Cutover strategy**: side-by-side at a different port/host is planned through Phase 8, but the final switch (reverse-proxy flip vs. gradual path-based routing) and the retirement of `apps/web` need an ops decision. Phase 8 contains a cutover checklist, not a mandate.
- **OQ-4 PWA**: current app ships an installable manifest (no offline). Plan ports the manifest in Phase 8; confirm it is actually used by anyone.
- **OQ-5 Insights charts**: current charts live in `@intric/ui` (Chart component). Plan assumes shadcn charts (recharts) are acceptable replacements; confirm no pixel-parity requirement.
- **OQ-6 E2E reuse**: plan assumes the existing `docker-compose.e2e.yml` stack (isolated Postgres/Redis, mock LLM) is reused with the new app pointed at it. If the mock LLM cannot speak the v3 stream (RB-2), it needs a small update; flagged in Phase 5.
- **OQ-7 Zitadel deployments**: dropping the Zitadel-specific flow means existing Zitadel deployments must be reconfigured as a generic OIDC client (new redirect URI, possibly new client, and "JWT as access token" enabled on the client since RB-1 requires JWT-format access tokens with an email claim; Zitadel issues opaque access tokens by default). Confirm this is acceptable operationally.
- **OQ-8 `/activate` + `/invite` flows**: tied to Zitadel provisioning today. With generic OIDC + JIT provisioning (RB-1 reuses it), plan assumes these flows reduce to backend-driven provisioning and the invite page; verify during Phase 2.

---

## 6. Phase list (each file is self-contained for a fresh session)

| Phase | File | Yields (runnable + verifiable) |
|---|---|---|
| 1 | `01-boilerplate.md` | `web-next` boots in the monorepo: layout shell, theming, i18n scaffold, lint/typecheck/test/build green, CI job |
| 2 | `02-auth-oidc.md` | Login (OIDC + password) → session → protected route → refresh → logout, against the real backend (RB-1, RB-3) |
| 3 | `03-api-layer.md` | Typed client + REST proxy + TanStack Query SSR pattern; `/dashboard` lists real data end-to-end |
| 4 | `04-app-shell-and-spaces.md` | App shell/nav, dashboard, spaces list/overview/members/settings, account pages |
| 5 | `05-chat.md` | Chat on ai-sdk v6 + AI Elements with the v3 stream (RB-2): streaming, history, attachments, tool approval, context bar, feedback |
| 6 | `06-builders-and-knowledge.md` | Assistant/group-chat/app/service builders, knowledge (collections/websites/integrations), jobs/uploads |
| 7 | `07-admin.md` | Full admin area incl. audit-log export BFF, models, templates, insights, usage |
| 8 | `08-i18n-polish-parity.md` | Translation completeness, error/empty/loading polish, Docker/CI/E2E, parity audit against §2.1, cutover checklist |

Dependency rule: each phase's Validation Gate must pass before the next starts. Backend changes RB-1 and RB-2 should be raised as backend PRs at the START of Phases 2 and 5 respectively (or earlier, in parallel) since they gate those phases' exit criteria.
