# web-next parity audit

Status of each `apps/web` (SvelteKit) capability in `apps/web-next` (Next).
Legend: **PASS** = ported at parity · **REDESIGNED** = intentionally different,
equivalent outcome · **DROPPED** = removed by decision · **DEFERRED** = not yet
ported, accepted for now · **MISSING** = parity gap that should block cutover.

There are currently **no MISSING rows**. Maintainer sign-off: _pending_.

## Auth & shell (phases 1–4)

| Capability | Status | Note |
|---|---|---|
| OIDC login (generic) | PASS | `OIDC_*`; replaces Zitadel/MobilityGuard. |
| Password login | PASS | dev/non-OIDC tenants. |
| Zitadel / MobilityGuard flows | DROPPED | generic OIDC only (RB-1). |
| Session (cookie, encrypted) | PASS | `SESSION_SECRET`; no client-held bearer. |
| Logout / deactivated / activate | PASS | |
| App shell, header, profile menu, theme, locale | PASS | viewport-locked shell. |
| Spaces list, space layout + nav, overview | PASS | |
| Personal/organization space aliases | PASS | |
| Dashboard (assistant + app tiles) | PASS | |
| Account: profile, API keys, integrations | PASS | |

## Chat (phase 5)

| Capability | Status | Note |
|---|---|---|
| Conversation streaming (AI SDK v6 UI Message Stream, v3 backend) | PASS | |
| History panel, attachments, tool approval | PASS | held-stream approval fallback. |
| Markdown / references / token usage / status | PASS | Streamdown. |
| Model selector + details (chat + editors) | PASS | rich `ai-elements/model-selector`: vendor groups, logos, prices/context/capabilities, policy filtering. |
| Mentions (group chat) | REDESIGNED | picker targeting one assistant. |
| Group-chat answer labels | DEFERRED | v3 doesn't carry the answering assistant (RB candidate). |
| Reasoning chunks | DROPPED | backend strips `<think>`; never streamed. |

## Builders & knowledge (phase 6)

| Capability | Status | Note |
|---|---|---|
| Jobs poller + header indicator | PASS | polling (WS app-run updates not ported). |
| Collections: CRUD, upload + progress, blobs | PASS | |
| Websites: CRUD, crawl runs, recrawl | PASS | |
| Integrations: list, OAuth connect popup, SharePoint import, sync logs | PASS | |
| Assistants: list, editor, publish, transfer, knowledge picker | PASS | per-section save (REDESIGNED from global draft). |
| Group chats: editor, mentions, response labels, publish | PASS | |
| Apps: list, editor, run (text/upload/recorder), results, dashboard routes | PASS | run status via polling. |
| Services: list, playground, editor | PASS | |
| Assistant templates / prompt-history / MCP picker / attachments on editor | DEFERRED | sanctioned editor follow-ups. |

## Admin (phase 7)

| Capability | Status | Note |
|---|---|---|
| Admin gate + grouped nav | PASS | server-side `hasPermission("admin")`. |
| Feature toggles (templates / audit / provisioning) | PASS | optimistic + revert. |
| Users: list, search, state tabs, create/edit, activate/deactivate, delete | PASS | offset pagination (RB-5a). |
| Audit logs: justification gate, filters, table, retention, async export | PASS | RB-5(d) cookie spike in the proxy. |
| Audit category config | PASS | Categories tab. |
| Audit per-action config; actor-by-user filter | PASS | per-action drill-down + search; per-user GDPR log view. |
| Security classifications: CRUD, enable, reorder | PASS | |
| Models: list, enable/disable, set-default, classification | PASS | |
| Model full edit (custom) + per-provider API credentials | PASS | edit dialog (PUT tenant-models) + credentials tab (set/update keys). |
| Model add-wizard (provider + credentials + model) | PASS | capability-driven stepped dialog; POST model-providers + tenant-models. |
| Model migration + usage impact | PASS | validate → migrate dialog with impact counts + compatibility warnings. |
| Provider edit/delete, per-model usage-details list | DEFERRED | minor: wizard creates providers; usage shows counts (not the per-entity list). |
| MCP servers: list, enable/disable, CRUD | PASS | tools panel deferred. |
| Org API keys: list, create, rotate/suspend/reactivate/revoke | PASS | policy/super-key/scope deferred. |
| Tenant integrations: provider link/unlink | PASS | SharePoint Azure-AD config + webhooks deferred. |
| Usage: tokens + storage | PASS | |
| Insights: counts + usage time-series + activity | PASS | recharts time-series (7/30/90d) + active-assistant/user cards; per-assistant deep-dive deferred. |
| Prompt library: CRUD | PASS | |
| Help assistants: roles + templates, install, toggles | PASS | |
| Templates: list, soft-delete, featured, restore/permanent-delete | PASS | create/edit wizard forms deferred. |
| Personal-assistant governance policy: toggle restrictions + enforced prompt | PASS | allow-list editing deferred. |
| Legacy roles / user-groups pages | DROPPED | OQ-2. |

## Cross-cutting

| Capability | Status | Note |
|---|---|---|
| i18n sv/en | PASS | 3609 keys, full parity (en↔sv), Swedish default. |
| Error / not-found / loading states | PASS | `(app)/error.tsx`, `not-found.tsx`, `loading.tsx`. |
| WebSocket live updates (app-run, crawl) | REDESIGNED | replaced by adaptive polling. |
| CSP (nonce-based strict `script-src`) | DEFERRED | safe baseline headers shipped; strict CSP needs nonce middleware + browser verification (CUTOVER.md). |
| E2E suite on the isolated stack | DEFERRED | ops task; see CUTOVER.md. |

## Accepted deferrals before cutover

All DEFERRED rows are advanced/low-traffic surfaces or ops tasks; none block a
member or everyday-admin from operating the platform. The maintainer should
confirm acceptance (or reclassify any as MISSING) before the proxy flip.
