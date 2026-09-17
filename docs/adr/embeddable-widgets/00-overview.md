# Embeddable widgets

- **Status:** Proposed — awaiting review; decisions 1–4 below confirmed by the
  product owner on 2026-09-17
- **Date:** 2026-09-17
- **Decision owners:** Product, security, architecture, and frontend
- **Scope:** Publishing an assistant as an embeddable chat widget on a
  municipality's own website (loader, embed page, public API, admin, policy)
- **Prerequisite:** [#842](https://github.com/eneo-ai/eneo/pull/842) removes
  the 2024 `widgets` table and its dead code
- **Parts:** this overview · [01-backend.md](01-backend.md) ·
  [02-frontend.md](02-frontend.md) ·
  [03-security-privacy-compliance.md](03-security-privacy-compliance.md) ·
  [04-review.md](04-review.md) (self-review log)

## TL;DR

A municipality embeds one script tag; a visitor to its website gets a streamed,
cited answer from a published Eneo assistant without an account. The chat UI
runs in an iframe served from Eneo's own origin (same-origin API, no key in
page source), the browser enforces where it may render (`frame-ancestors`
from the widget's origin allowlist), visitors hold 15-minute tokens minted
after a self-hosted proof of work, and cost is bounded by per-visitor, per-IP
and per-day limits with a one-click pause. Built in core, not as a module.

## What a widget is

A **widget** is a published assistant that a municipality embeds on its own public website. A visitor to `www.kommun.se` opens a chat panel, asks a question and gets a streamed answer with citations, without having an Eneo account. The same widget can be opened as a stand-alone page (`chatt.kommun.se`-style link) for sites that cannot add scripts.

Widgets are a **core feature**, built in the backend and the production Svelte app. They are deliberately *not* a module: modules are stateless BFFs for signed-in employees (SSO handoff, no database, `module_net` with no egress), while a widget serves anonymous visitors and needs per-visitor state, limits, budgets and retention. Running it as a module would duplicate the chat UI and the origin/rate-limit/governance machinery that already exists in core. The one benefit of the module model — isolating a public surface — is achieved with a per-route CSP, dedicated rate limits and, where wanted, a separate Traefik router for `/embed/*`.

## Decisions (confirmed 2026-09-17)

| # | Decision | Consequence |
|---|---|---|
| 1 | **Own `widgets` entity + short-lived visitor tokens.** No API key in page source. | New table, new public endpoints under `/api/v1/widgets/{public_id}/`, visitor JWT (`token_use=widget_visitor`). Reuses origin matching, the Redis rate-limit primitive and tenant policy from API keys v2. |
| 2 | **Frontend in the Svelte app**, `(public)/embed/[publicId]`. | Reuses `ChatService` + `ConversationView`. Loader is framework-free TypeScript in its own workspace package. |
| 3 | **Abuse protection in v1 = rate limits + daily token budget + pause + ALTCHA** (self-hosted proof-of-work, no third party). | Backend issues and verifies ALTCHA challenges; solved in the iframe before a visitor token is minted. |
| 4 | **Tenant admin activates, with review.** Space editors create, configure and preview; `status=active` requires `Permission.ADMIN`. | Activation and pausing are explicit, audited actions. Autosave applies to configuration only. |

## Architecture

```
kommun.se page                          Eneo origin (eneo.kommun.se)
┌──────────────────────────────┐        ┌──────────────────────────────────────────┐
│ <script src=/widget/v1/eneo.js│        │ GET /widget/v1/eneo.js   (loader, 4 kB)  │
│   data-widget-id="wgt_…">    │        │                                          │
│                              │        │ GET /embed/wgt_…  (Svelte (public) route)│
│ <eneo-widget> custom element │ iframe │   CSP frame-ancestors = widget origins   │
│   shadow DOM launcher button │──────▶ │   renders ConversationView               │
│   panel = <iframe title=…>   │        │        │ same-origin fetch / SSE          │
│        ▲ postMessage ▼       │        │        ▼                                 │
└──────────────────────────────┘        │ /api/v1/widgets/{public_id}/…            │
                                        │   config · challenge · visitor-sessions  │
                                        │   ask (SSE) · sessions/{id} · feedback   │
                                        │        │                                 │
                                        │   widgets · sessions(widget_id,visitor_id)│
                                        │   Redis: limits, budget, ALTCHA replay   │
                                        └──────────────────────────────────────────┘
```

Key properties:

- **The iframe is served from Eneo's own origin.** API calls from inside it are same-origin: no CORS, no key in the host page, and the host site's CSP only needs `script-src` + `frame-src` for the Eneo domain.
- **The browser enforces where the widget may render.** The embed page answers with `Content-Security-Policy: frame-ancestors <widget.allowed_origins>`; the rest of the app stays `frame-ancestors 'none'`.
- **Nothing long-lived is public.** The page source holds only `public_id`. A visitor token lives 15 minutes, is bound to one widget and one pseudonymous `visitor_id`, and is invalidated the moment the widget is paused.
- **Visitor state is partition-friendly.** The `visitor_id` lives in the iframe's `localStorage`, which modern browsers partition per top-level site: continuity across pages of the same municipal site, no cross-site tracking.

## What already exists in `develop` (verified 2026-09-17)

| Capability | Where | Reuse |
|---|---|---|
| Origin pattern matching incl. `*.host` | `backend/src/eneo/allowed_origins/origin_matching.py` | Widget `allowed_origins` validation and CSP generation |
| Atomic Redis rate limiting (Lua INCR+EXPIRE) | `backend/src/eneo/audit/infrastructure/rate_limiting.py` | Per-visitor, per-IP and per-widget limits |
| Sessions without a user (`user_id XOR api_key_id`) | `backend/src/eneo/database/tables/sessions_table.py` | Extend to `widget_id` + `visitor_id` |
| Typed JWT signing/verification with audience | `backend/src/eneo/authentication/auth_service.py` (`create_scoped_mcp_token`, module tokens) | Visitor token |
| `ask_assistant` streaming path with SSE event types | `backend/src/eneo/assistants/api/assistant_router.py`, `sessions/session.py` | Widget ask reuses the service layer, not the router |
| Governance `effective_config` | `governance_policy/application/effective_config_service.py` | Widgets inherit the assistant's governed config and additionally disable tools/uploads |
| Audit service, feature flags, tenant policy | `audit/`, `feature_flag/`, API-key policy | Activation audit, staged rollout, per-tenant quotas |
| Streaming chat UI, citations, feedback, i18n, semantic color tokens | `frontend/apps/web/src/lib/features/chat/` | Embed page |
| E2E harness (Playwright) and component tests (Vitest browser mode) | `frontend/apps/web/e2e`, `frontend/TESTING.md` | Cross-origin widget E2E |

Not present and built new: the `widgets` table and admin API, public widget endpoints, visitor tokens, ALTCHA, daily token budget accounting, retention job, the loader package, the embed route, the admin "Web widget" page and the docs page.

## Phasing and PR stack

| Phase | Deliverable | Depends on |
|---|---|---|
| **0. Groundwork** | #842 (legacy removal) · app-wide `frame-ancestors 'none'` with a per-route override hook · this plan | — |
| **1. Backend core** | `widgets` table + sessions columns · admin CRUD + activate/pause · public config · ALTCHA · visitor tokens · ask/session/feedback · limits + budget · retention job · audit · tests | Phase 0 |
| **2. Embed page** | `(public)/embed/[publicId]` · `ChatService` with visitor auth · anonymous app context · theming/i18n · WCAG pass | Phase 1 (contract can be stubbed with fixtures) |
| **3. Loader + admin** | `packages/widget-loader` · `/widget/v1/eneo.js` route · custom element launcher · admin "Web widget" page with preview and snippet · i18n | Phase 2 |
| **4. Hardening + docs** | Cross-origin Playwright E2E with axe · load test of limits/budget · docs-site page "Bädda in en assistent" · accessibility-statement template · release note | Phases 1–3 |
| **5. Later** | Group chats and apps as widget targets · page-context passing · usage dashboard · per-widget model override · proactive greeting rules · Traefik rate-limit middleware in the deployment template | Product need |

Suggested PRs, each reviewable on its own: (1) schema + admin CRUD + policy, (2) ALTCHA + visitor tokens + limits/budget, (3) public ask/session/feedback + retention + audit, (4) embed page, (5) loader package + route, (6) admin UI, (7) E2E + docs. PRs 1–3 target `develop` in order; 4 can start against fixtures once 1 has merged.

## Open questions

- Default `retention_days` (proposal: 30) and whether tenants may set `0` = do not store conversations at all (proposal: yes, answers still stream, nothing persisted, no follow-ups).
- Whether widget sessions feed the assistant's Insights (proposal: yes, tagged as widget traffic, so editors can improve the assistant; excluded from any per-user views).
- Tenant-level quota on active widgets and default daily token budget (proposal: 5 widgets, 500k tokens/day, both overridable by sysadmin policy).
- Whether the loader should also be published to npm as `@eneo/widget-loader` for SPA hosts (the custom element already covers it; npm is packaging only).
