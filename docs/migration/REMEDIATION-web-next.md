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

- [ ] **S1** Serialize saves per resource (mutation queue / field-scoped merge) —
      `use-assistant.ts`, `use-group-chat.ts`, `use-app.ts`.
- [ ] **S2** Unique autosave status keys per field (no shared `"general"`); failure chip must
      not be erased by a sibling success — `use-autosave.ts`, `general-section.tsx`.
- [ ] **S3** Prompt commit on debounce/`visibilitychange` + unload guard covers dirty (not
      just in-flight) state — `instructions-section.tsx`, `save-status.tsx`.
- [ ] **S4** Revert optimistic state (or show per-field error) on failed autosave —
      mcp/knowledge/attachments sections.

## P2 — Flaws

### Chat
- [ ] **C1** Render live web-search sources (consume `data-session.web_search_references`).
- [ ] **C2** Show user attachments in the live transcript (file parts on `sendMessage`).
- [ ] **C3** Bridge: reopen reasoning part when REASONING follows TEXT (`ui_message_stream.py:212`).
- [ ] **C4** Keep group-chat answer label after stream end (`chat-message.tsx:53`).
- [ ] **C5** Consume `data-error {code}` → translated message; restore composer input on
      pre-stream failure.
- [ ] **C6** Chat WCAG: name scroll-to-bottom button, focus-visible history row actions,
      label rename input.
- [ ] **C7** Render non-image generated files (download chip) in live messages.

### Builders
- [ ] **BU1** Enforce `max_files` on app-run multi-select; fix per-file vs combined `maxSize`.
- [ ] **BU2** Delete detached not-yet-saved attachment blobs (parity with app-run inputs).
- [ ] **BU3** Service editor → autosave (drop local Save button).
- [ ] **BU4** i18n: `getResultTitle`, input-type labels, service kwarg options.
- [ ] **BU5** Replace raw palette colors in builders files with semantic tokens.
- [ ] **BU6** WCAG: status-badge icon variant accessible name; persistent aria-live region in
      `SaveStatusIndicator`.

### Knowledge / jobs
- [ ] **K1** Import dialogs: error + reconnect state on preview failure; no infinite spinner
      when integration id is missing (sharepoint/confluence).
- [ ] **K2** Upload success cue (open job panel or success toast).
- [ ] **K3** aria-live announcements for upload/job completion+failure (`job-indicator.tsx`).
- [ ] **K4** Failure reasons accessible (not `title`-only) — websites/crawl-runs.
- [ ] **K5** Scope grouped select-all per group + indeterminate state (`websites.tsx:364`).
- [ ] **K6** Unique keys for duplicate file names in upload dialog.
- [ ] **K7** i18n bulk-recrawl toast (`websites.tsx:295`).
- [ ] **K8** Replace raw palette colors in knowledge files with semantic tokens.

### Admin A
- [ ] **A1** Fix insights preset i18n keys (`last_${preset}_days` missing).
- [ ] **A2** Audit export matches table filters (multi-action + search) or warns.
- [ ] **A3** Handle cancelled/expired export states (`export-dialog.tsx:112`).
- [ ] **A4** Move `auditConfigQueryOptions` out of `"use client"` file.
- [ ] **A5** i18n `IP` table header (`usage-dialog.tsx:111`).
- [ ] **A6** WCAG: `aria-expanded` on toggle button, preset pressed state, export aria-live.
- [ ] **A7** Replace raw palette colors in admin A files with semantic tokens.

### Admin B (models/MCP/templates/integrations)
- [ ] **M1** Model deletion (completion/embedding/transcription) + `MODEL_IN_USE` → migrate CTA.
- [ ] **M2** Add/edit embedding + transcription models (incl. security classification).
- [ ] **M3** Transcription model migration.
- [ ] **M4** `force_override` acknowledgment flow for security-blocked migrations.
- [ ] **M5** Pre-create model validation (`validate-model`) with create-anyway gate.
- [ ] **M6** Provider config-field editing (Azure endpoint / api_version).
- [ ] **M7** Template rollback (`original_snapshot`).
- [ ] **M8** Preserve existing `completion_model_kwargs` on template save.
- [ ] **M9** Edit dialog: expose `name` (litellm id), `hosting`, `open_source`.
- [ ] **M10** Wizard Back after provider creation must not create duplicates.
- [ ] **M11** Guard 0/0 token limits on catalog create (pre-create edit or block).
- [ ] **M12** Migration dialog: translate `warning_codes`; exclude disabled/deprecated targets;
      block on impact fetch error; invalidate history+usage after migrate.
- [ ] **M13** Model detail dialog: correct description label; pass real `ModelProvider` to edit dialog.
- [ ] **M14** Raw palette colors + placeholder-only search name in admin B files.

### Auth / shell / account / spaces
- [x] **AU1** (2026-07-06) Deactivated page: correct title, complete copy (admin contact — the old
      mailto's salesEmail was never wired in env), logout/retry actions + self-heal check.
- [x] **AU2** (2026-07-06) Activate page: functional retry (re-provision), plain `<a>` for logout.
- [ ] **AU3** API-keys table: fix state-column header; translate permission enum.
- [ ] **AU4** Skip-to-content link in the app shell.
- [ ] **AU5** Gate switch-organisation on `has_multi_tenant_federation`.
- [ ] **AU6** Localized default-assistant tile name on dashboard.
- [ ] **AU7** i18n members-dialog placeholder (`space-members.tsx:198`).
- [ ] **AU8** Respect `tenant_app_configured === false` on account integration cards.
- [x] **AU9** (2026-07-06) Show logout/expired messages on login page.

### Cross-cutting
- [x] **X1** (2026-07-06) `Cache-Control: no-store` on authenticated proxy + chat routes.
- [ ] **X2** `(public)/error.tsx`, `(app)/not-found.tsx`, redact raw `error.message`.
- [ ] **X3** Dynamic-import recharts in admin insights.
- [ ] **X4** Gate `/(app)/chat-mock` to dev.
- [ ] **X5** Default accessible names for vendored ai-elements icon buttons; keyboard support
      for clickable table rows.
- [ ] **X6** Port `no-hardcoded-text` / `no-raw-color` lint rules to web-next.
- [ ] **X7** CSP: nonce middleware + strict `script-src` (CUTOVER task).
- [ ] **X8** E2E: add chat round-trip + space/knowledge flow.

## P3 — Missing features

### Auth / shell / spaces
- [x] **MF1** (2026-07-06) Suspended-tenant routing for OIDC users (folded into B2).
- [ ] **MF2** Multi-tenant federation login (tenant selector, remembered slug, per-tenant initiate).
- [ ] **MF3** Space settings: MCP server selection (replace stub).
- [ ] **MF4** Security-classification change impact analysis + confirm dialog.
- [ ] **MF5** Space-scoped API keys section in space settings.
- [ ] **MF6** Account API keys parity: suspend/reactivate, legacy-key banner, notification
      prefs, search, rich create dialog (scopes/permissions).
- [ ] **MF7** Expiring API-key notifications in header bell.
- [ ] **MF8** Mobile redirect + PWA dashboard manifest.
- [ ] **MF9** Space icon upload.
- [ ] **MF10** Login diagnostics (correlation IDs, OIDC error detail, `login/failed` params).

### Chat
- [ ] **MC1** Per-conversation insights tab (`/chat/insights` equivalent).
- [ ] **MC2** MCP tool references (inline citations, snippet modal, image strip) live + history.
- [ ] **MC3** Per-conversation MCP server toggling (`disabled_mcp_server_ids`) + auto-accept toggle.
- [ ] **MC4** Fetch real tool-call result content in activity timeline.
- [ ] **MC5** `SHOW_WEB_SEARCH` feature-flag gating.
- [ ] **MC6** Assistant switcher in chat header.
- [ ] **MC7** Client-side attachment `max_files` rule.

### Builders
- [ ] **MB1** Honor `effective_config` in assistant editor (prompt_locked / models_enforced /
      mcp_enforced).
- [ ] **MB2** Per-tool MCP (`mcp_tools`) in editor + tool-calling model warning.
- [ ] **MB3** Assistant- and app-scoped API keys sections.
- [ ] **MB4** App editor attachments section.
- [ ] **MB5** Template wizard (`additional_fields`) in create-from-template.
- [ ] **MB6** Create app from template.
- [ ] **MB7** Client-side attachment validation from `allowed_attachments`.
- [ ] **MB8** Search/filter on assistants/apps/services grids.
- [ ] **MB9** Help-assistant logging notice; app prompt version history.

### Knowledge
- [ ] **MK1** Expandable per-item blob list in knowledge picker.
- [ ] **MK2** Filter/sort on websites/collections/crawl-runs tables.
- [ ] **MK3** Crawl-limitations banner, integrations beta notice, admin-configure affordance,
      "no create permission" info.

### Admin
- [ ] **MA1** Per-assistant insights deep-dive (question history + AI analysis).
- [ ] **MA2** Per-user usage detail page.
- [ ] **MA3** Audit filters in URL (restore `?search=` deep link).
- [ ] **MA4** Actor-filtered (GDPR) audit export.

### Cross-cutting
- [ ] **MX1** Account preferred copy-format.

## P4 — Documentation

- [ ] **PR1** Reconcile PARITY.md (over-claims, stale rows, unrecorded deferrals — review §6).

## P5 — Improvements (nice-to-have)

Tracked in `IMPROVEMENTS-web-next-2026-07-06.md`; promote items here when scheduled.
