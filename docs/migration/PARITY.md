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
| Markdown / references / token usage / status | PASS | Streamdown; document/web/MCP references render from live stream + history. |
| Model selector + details (chat + editors) | PASS | rich `ai-elements/model-selector`: vendor groups, logos, prices/context/capabilities, policy filtering. |
| Mentions (group chat) | REDESIGNED | picker targeting one assistant. |
| Group-chat answer labels | PASS | `answering_assistant` is carried through the v3 stream and persisted message metadata. |
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
| Assistant editor: MCP server picker + attachments | PASS | mcp_servers picker (knowledge⇄MCP exclusivity) + file attachments. |
| Assistant editor: prompt version history / template apply on create | PASS | prompt-version endpoint + `from_template` create flow are wired. |

## Admin (phase 7)

| Capability | Status | Note |
|---|---|---|
| Admin gate + grouped nav | PASS | server-side `hasPermission("admin")`. |
| Feature toggles (templates / audit / provisioning) | PASS | optimistic + revert. |
| Users: list, search, state tabs, create/edit, activate/deactivate, delete | PASS | offset pagination (RB-5a). |
| Audit logs: justification gate, filters, table, retention, async export | PASS | includes URL-restored filters, JSON/JSONL, cancel/expired states, per-user GDPR export. |
| Audit category config | PASS | Categories tab. |
| Audit per-action config; actor-by-user filter | PASS | per-action drill-down + search; per-user GDPR log view. |
| Security classifications: CRUD, enable, reorder | PASS | |
| Models: list, enable/disable, set-default, classification | PASS | |
| Model full edit (custom) + per-provider API credentials | PASS | edit dialog (PUT tenant-models) + credentials tab (set/update keys). |
| Model add-wizard (provider + credentials + model) | PASS | capability-driven stepped dialog; POST model-providers + tenant-models. |
| Model migration + usage impact | PASS | validate → migrate dialog with impact counts + compatibility warnings. |
| Provider edit/delete, per-model usage-details list | PASS | model detail usage tab + provider management. |
| MCP servers: list, enable/disable, CRUD, tools panel | PASS | tools dialog (list + remote sync). |
| Org API keys: list, create, rotate/suspend/reactivate/revoke, notification policy | PASS | expiry-alert thresholds + auto-follow policy. |
| Tenant integrations: provider link/unlink | PASS | includes SharePoint Azure-AD app config + webhook subscription health/renew. |
| Usage: tokens + users + storage | PASS | per-user detail page, model breakdown, estimated cost. |
| Insights: counts + usage time-series + activity | PASS | recharts time-series (7/30/90d), custom range/compare, activity cards, per-assistant deep-dive. |
| Prompt library: CRUD | PASS | |
| Help assistants: roles + templates, install, toggles | PASS | |
| Templates: list, create/edit, featured, soft-delete, restore/permanent-delete | PASS | full CRUD (assistant + app). |
| Personal-assistant governance policy: toggle restrictions + enforced prompt | PASS | allow-list editing deferred. |
| Legacy roles / user-groups pages | DROPPED | OQ-2. |

## Cross-cutting

| Capability | Status | Note |
|---|---|---|
| i18n sv/en | PASS | 3880 keys, full parity (en↔sv), Swedish default. |
| Error / not-found / loading states | PASS | `(app)/error.tsx`, `not-found.tsx`, `loading.tsx`. |
| WebSocket live updates (app-run, crawl) | REDESIGNED | replaced by adaptive polling. |
| CSP (nonce-based strict `script-src`) | PASS | request nonce in `src/proxy.ts`; production `strict-dynamic`, `script-src-attr 'none'`. |
| E2E suite on the isolated stack | PASS | Playwright smoke coverage for auth setup, chat round-trip, and space/knowledge flow. |

## Parity buildout — 2026-06-29 (branch `feat/web-next-parity-buildout`)

A verified parity audit (`REVIEW-web-next-parity-2026-06-29.md`) re-opened the
deferrals and the listed gaps were built to parity. Now **PASS** (was DEFERRED /
over-claimed / a gap):

- MCP: bearer-token bug fixed; per-tool enable/disable + remote tool-change review.
- Audit: per-row forensic detail (IP/UA/metadata + copy) + JSON/JSONL export.
- Org API keys: constraint policy + super-key status + scope/key-type filters + per-key usage.
- Help-assistants: per-kind editor (reuses the assistant editor).
- SharePoint: Azure-AD app config + webhook subscription health/renew (admin API, not env-only).
- Models: custom-provider edit/delete, migration-history panel, per-model usage list + detail dialog.
- Knowledge: Confluence import (vendor-agnostic dialog); **assistant prompt-version history**
  (backend endpoint un-gated + typed).
- Templates: editor wizard config + model kwargs; **create assistant from template** (`from_template`).
- Auth/account: activate/self-provision landing; switch-organisation; **self-service change-password**
  (new backend endpoint `POST /users/me/change-password/`).
- Usage/Insights: per-user breakdown + estimated cost; insights custom date-range + compare mode.
- Chat: **group-chat answer labels** (new `answering_assistant` in the v3 stream); per-tool MCP
  approval; web-search source rendering.

### Remaining accepted deferrals

- **Personal-assistant governance allow-list editing** — policy enforcement and prompt locking are
  present; allow-list editing remains a narrow admin-governance enhancement.

None of the accepted deferrals block a member or everyday-admin from operating the platform.
