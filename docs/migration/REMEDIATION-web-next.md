# Web-next remediation tracker

Working checklist for `REVIEW-web-next-2026-07-06.md` (+ `IMPROVEMENTS-web-next-2026-07-06.md`).
Check items off (`[x]`, add date) as they land on `refactor/web-next`. IDs are referenced
in commit messages.

## P0 — Blockers

- [x] **B1** (2026-07-06) Group-chat send 400: only send `require_tool_approval` for assistant partners
      (`features/chat/chat-view.tsx:274`; backend guard `conversations_router.py:319`).
- [x] **B2** (2026-07-06) 401 redirect loop + orphaned activate: route backend 401/9006 → `/activate`
      (wire `POST /users/provision/` there), 403/9025 → `/deactivated`, other 401 →
      cookie-clearing logout route instead of RSC `redirect("/login")`
      (`lib/api/server.ts`, `lib/api/browser.ts`, `(public)/activate`, `(public)/login`).
- [x] **B3** (2026-07-06) Inline `<inref>` citations: parse/buffer `<inref id="8hex"/>` in answers, map to
      sources, render as citation chips; strip tags from copy
      (`components/ai-elements/citation.tsx`, `features/chat/chat-message.tsx`).

## P1 — Systemic: builders autosave

- [x] **S1** (2026-07-06) Serialize saves per resource (mutation queue / field-scoped merge) —
      `use-assistant.ts`, `use-group-chat.ts`, `use-app.ts`.
- [x] **S2** (2026-07-06) Unique autosave status keys per field (no shared `"general"`); failure chip must
      not be erased by a sibling success — `use-autosave.ts`, `general-section.tsx`.
- [x] **S3** (2026-07-06) Prompt commit on debounce/`visibilitychange` + unload guard covers dirty (not
      just in-flight) state — `instructions-section.tsx`, `save-status.tsx`.
- [x] **S4** (2026-07-06) Revert optimistic state (or show per-field error) on failed autosave —
      mcp/knowledge/attachments sections.

## P2 — Flaws

### Chat
- [x] **C1** (2026-07-06) Render live web-search sources (consume `data-session.web_search_references`).
- [x] **C2** (2026-07-06) Show user attachments in the live transcript (file parts on `sendMessage`).
- [x] **C3** (2026-07-06) Bridge: reopen reasoning part when REASONING follows TEXT (`ui_message_stream.py:212`).
- [x] **C4** (2026-07-06) Keep group-chat answer label after stream end (`chat-message.tsx:53`).
- [x] **C5** (2026-07-06) Consume `data-error {code}` → translated message; restore composer input on
      pre-stream failure.
- [x] **C6** (2026-07-06) Chat WCAG: name scroll-to-bottom button, focus-visible history row actions,
      label rename input.
- [x] **C7** (2026-07-06) Render non-image generated files (download chip) in live messages.

### Builders
- [x] **BU1** (2026-07-06) Enforce `max_files` on app-run multi-select; fix per-file vs combined `maxSize`.
- [x] **BU2** (2026-07-06) Delete detached not-yet-saved attachment blobs (parity with app-run inputs).
- [x] **BU3** (2026-07-06) Service editor → autosave (drop local Save button).
- [x] **BU4** (2026-07-06) i18n: `getResultTitle`, input-type labels, service kwarg options.
- [x] **BU5** (2026-07-06) Replace raw palette colors in builders files with semantic tokens.
- [x] **BU6** (2026-07-06) WCAG: status-badge icon variant accessible name; persistent aria-live region in
      `SaveStatusIndicator`.

### Knowledge / jobs
- [x] **K1** (2026-07-06) Import dialogs: error + reconnect state on preview failure; no infinite spinner
      when integration id is missing (sharepoint/confluence).
- [x] **K2** (2026-07-06) Upload success cue (open job panel or success toast).
- [x] **K3** (2026-07-06) aria-live announcements for upload/job completion+failure (`job-indicator.tsx`).
- [x] **K4** (2026-07-06) Failure reasons accessible (not `title`-only) — websites/crawl-runs.
- [x] **K5** (2026-07-06) Scope grouped select-all per group + indeterminate state (`websites.tsx:364`).
- [x] **K6** (2026-07-06) Unique keys for duplicate file names in upload dialog.
- [x] **K7** (2026-07-06) i18n bulk-recrawl toast (`websites.tsx:295`).
- [x] **K8** (2026-07-06) Replace raw palette colors in knowledge files with semantic tokens.

### Admin A
- [x] **A1** (2026-07-06) Fix insights preset i18n keys (`last_${preset}_days` missing).
- [x] **A2** (2026-07-06) Audit export matches table filters (multi-action + search) or warns.
- [x] **A3** (2026-07-06) Handle cancelled/expired export states (`export-dialog.tsx:112`).
- [x] **A4** (2026-07-06) Move `auditConfigQueryOptions` out of `"use client"` file.
- [x] **A5** (2026-07-06) i18n `IP` table header (`usage-dialog.tsx:111`).
- [x] **A6** (2026-07-06) WCAG: `aria-expanded` on toggle button, preset pressed state, export aria-live.
- [x] **A7** (2026-07-06) Replace raw palette colors in admin A files with semantic tokens.

### Admin B (models/MCP/templates/integrations)
- [x] **M1** (2026-07-06) Model deletion (completion/embedding/transcription) +
      `MODEL_IN_USE` → migrate CTA.
- [x] **M2** (2026-07-06) Add/edit embedding + transcription models (incl. security classification).
- [x] **M3** (2026-07-06) Transcription model migration.
- [x] **M4** (2026-07-06) `force_override` acknowledgment flow for security-blocked migrations.
- [x] **M5** (2026-07-06) Pre-create model validation (`validate-model`) with create-anyway gate.
- [x] **M6** (2026-07-06) Provider config-field editing (Azure endpoint / api_version).
- [x] **M7** (2026-07-06) Template rollback (`original_snapshot`).
- [x] **M8** (2026-07-06) Preserve existing `completion_model_kwargs` on template save.
- [x] **M9** (2026-07-06) Edit dialog: expose `name` (litellm id), `hosting`, `open_source`.
- [x] **M10** (2026-07-06) Wizard Back after provider creation must not create duplicates.
- [x] **M11** (2026-07-06) Guard 0/0 token limits on catalog create (pre-create edit or block).
- [x] **M12** (2026-07-06) Migration dialog: translate `warning_codes`; exclude disabled/deprecated targets;
      block on impact fetch error; invalidate history+usage after migrate.
- [x] **M13** (2026-07-06) Model detail dialog: correct description label; pass real
      `ModelProvider` to edit dialog.
- [x] **M14** (2026-07-06) Raw palette colors + placeholder-only search name in admin B files.

### Auth / shell / account / spaces
- [x] **AU1** (2026-07-06) Deactivated page: correct title, complete copy (admin contact — the old
      mailto's salesEmail was never wired in env), logout/retry actions + self-heal check.
- [x] **AU2** (2026-07-06) Activate page: functional retry (re-provision), plain `<a>` for logout.
- [x] **AU3** (2026-07-06) API-keys table: fix state-column header; translate permission enum.
- [x] **AU4** (2026-07-06) Skip-to-content link in the app shell.
- [x] **AU5** (2026-07-06) Gate switch-organisation on `has_multi_tenant_federation`.
- [x] **AU6** (2026-07-06) Localized default-assistant tile name on dashboard.
- [x] **AU7** (2026-07-06) i18n members-dialog placeholder (`space-members.tsx:198`).
- [x] **AU8** (2026-07-06) Respect `tenant_app_configured === false` on account integration cards.
- [x] **AU9** (2026-07-06) Show logout/expired messages on login page.

### Cross-cutting
- [x] **X1** (2026-07-06) `Cache-Control: no-store` on authenticated proxy + chat routes.
- [x] **X2** (2026-07-06) `(public)/error.tsx`, `(app)/not-found.tsx`, redact raw `error.message`.
- [x] **X3** (2026-07-06) Dynamic-import recharts in admin insights.
- [x] **X4** (2026-07-06) Gate `/(app)/chat-mock` to dev.
- [x] **X5** (2026-07-06) Default accessible names for vendored ai-elements icon buttons; keyboard support
      for clickable table rows.
- [x] **X6** (2026-07-06) Port `no-hardcoded-text` / `no-raw-color` lint rules to web-next.
- [x] **X7** (2026-07-06) CSP: nonce middleware + strict `script-src` (CUTOVER task).
- [x] **X8** (2026-07-06) E2E: add chat round-trip + space/knowledge flow.

## P3 — Missing features

### Auth / shell / spaces
- [x] **MF1** (2026-07-06) Suspended-tenant routing for OIDC users (folded into B2).
- [x] **MF2** Multi-tenant federation login (tenant selector, remembered slug, per-tenant initiate).
- [x] **MF3** Space settings: MCP server selection (replace stub).
- [x] **MF4** Security-classification change impact analysis + confirm dialog.
- [x] **MF5** Space-scoped API keys section in space settings.
- [x] **MF6** Account API keys parity: suspend/reactivate, legacy-key banner, notification
      prefs, search, rich create dialog (scopes/permissions).
- [x] **MF7** Expiring API-key notifications in header bell.
- [x] **MF8** Mobile redirect + PWA dashboard manifest.
- [x] **MF9** Space icon upload.
- [x] **MF10** Login diagnostics (correlation IDs, OIDC error detail, `login/failed` params).

### Chat
- [x] **MC1** Per-conversation insights tab (`/chat/insights` equivalent).
- [x] **MC2** MCP tool references (inline citations, snippet modal, image strip) live + history.
- [x] **MC3** Per-conversation MCP server toggling (`disabled_mcp_server_ids`) + auto-accept toggle.
- [x] **MC4** Fetch real tool-call result content in activity timeline.
- [x] **MC5** `SHOW_WEB_SEARCH` feature-flag gating.
- [x] **MC6** Assistant switcher in chat header.
- [x] **MC7** Client-side attachment `max_files` rule.

### Builders
- [x] **MB1** Honor `effective_config` in assistant editor (prompt_locked / models_enforced /
      mcp_enforced).
- [x] **MB2** Per-tool MCP (`mcp_tools`) in editor + tool-calling model warning.
- [x] **MB3** Assistant- and app-scoped API keys sections.
- [x] **MB4** App editor attachments section.
- [x] **MB5** Template wizard (`additional_fields`) in create-from-template.
- [x] **MB6** Create app from template.
- [x] **MB7** Client-side attachment validation from `allowed_attachments`.
- [x] **MB8** Search/filter on assistants/apps/services grids.
- [x] **MB9** Help-assistant logging notice; app prompt version history.

### Knowledge
- [x] **MK1** Expandable per-item blob list in knowledge picker.
- [x] **MK2** Filter/sort on websites/collections/crawl-runs tables.
- [x] **MK3** Crawl-limitations banner, integrations beta notice, admin-configure affordance,
      "no create permission" info.

### Admin
- [x] **MA1** Per-assistant insights deep-dive (question history + AI analysis).
- [x] **MA2** Per-user usage detail page.
- [x] **MA3** Audit filters in URL (restore `?search=` deep link).
- [x] **MA4** Actor-filtered (GDPR) audit export.

### Cross-cutting
- [x] **MX1** Account preferred copy-format.

## P4 — Documentation

- [x] **PR1** Reconcile PARITY.md (over-claims, stale rows, unrecorded deferrals — review §6).

## P5 — Improvements (nice-to-have)

Tracked in `IMPROVEMENTS-web-next-2026-07-06.md`; promote items here when scheduled.
