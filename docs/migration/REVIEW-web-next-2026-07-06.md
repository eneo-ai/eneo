# Web-next migration review — 2026-07-06

Fresh verified audit of `apps/web-next` (Next.js/React/shadcn) against `apps/web`
(SvelteKit) on `refactor/web-next`, superseding the 2026-06-29 review. Method:
7-area parallel audit (auth/shell, chat, builders, knowledge/jobs, admin A,
admin B, cross-cutting), each comparing actual code on both sides and treating
PARITY.md rows as claims to verify. All blocker-severity findings were
independently re-verified against source before inclusion.

Companion doc: `IMPROVEMENTS-web-next-2026-07-06.md` (nice-to-have logic/UX
improvement potential found during the same review).

## 1. Verdict

The migration is broad and most PARITY.md PASS rows held up (auth architecture,
proxy/session security, spaces/members, MCP admin, templates admin,
help-assistants, prompt library, i18n key parity 3829/3829 en↔sv, jobs/upload
pipeline fidelity, knowledge CRUD). But this round found **3 verified blockers**
(group-chat send broken, a 401 redirect loop that swallows the unprovisioned-user
flow, dead inline citations), a **systemic autosave race** in the builders
editors, and a cluster of admin-models gaps that make some model lifecycle
operations impossible. Cutover is **not** advisable until §2 is fixed.

## 2. Blockers (verified)

### 2.1 Group chats cannot send messages
`features/chat/chat-view.tsx:274` unconditionally sends
`require_tool_approval: true`. The backend rejects that for group chats with 400
(`backend/src/eneo/conversations/conversations_router.py:319-326`, same guard for
continued sessions in `conversation_service.py`). Every group-chat send fails.
Introduced with the per-tool approval commit (`08f51ca70`).
Side effect for regular assistants: the old default was auto-run tools
(`autoAcceptTools` defaulted true, localStorage-persisted); now every MCP call
halts on an approval prompt — a behavior regression on top of the bug.
**Fix:** send `require_tool_approval` only when the partner is an assistant and
the user has not opted into auto-accept; restore an auto-accept toggle.

### 2.2 401 redirect loop; activate/self-provision unreachable
`lib/api/server.ts:26-37`: on backend 401, `clearSessionCookie()` throws inside
RSC render (cookies read-only; swallowed) and then `redirect("/login")`.
`(public)/login/page.tsx:19` sees a locally-valid session cookie
(`getSession()` checks decryption/expiry only, never the backend) and redirects
straight back to `DEFAULT_LANDING` → infinite `/login ↔ /spaces` loop.
`lib/api/browser.ts` (`window.location.reload()` on 401) loops the same way
client-side.

This is exactly the path an unprovisioned OIDC user hits: with tenant
`provisioning` disabled the backend answers 401 `USER_NOT_CREATED` (9006), and
web-next has **no** call to `POST /api/v1/users/provision/` and **no** routing
to `/activate` (the landing page exists but is orphaned; old app routed error
9006 → `/activate` and POSTed provision from there). Backend JIT-provisioning
(`authentication/federated_user_service.py`) only covers tenants that enable it.
**Fix:** on 401 distinguish backend error codes (9006 → `/activate` + provision
flow; token-rejected → clear cookie via a route handler/server action, not RSC),
and make `/login` validate the session against the backend (or carry a
`?loggedOut=1` bypass) before bouncing forward.

### 2.3 Inline `<inref>` citations are dead code against the real backend
The backend instructs models to emit `<inref id="<8-hex>"/>`
(`backend/.../completion_models/infrastructure/static_prompts.py:19-24`) and the
old app buffered partial tags mid-stream (`ChatService.svelte.ts:542-594`) and
rendered them as inline blob-preview chips (`MessageAnswer.svelte:359` →
`MessageEneoInfoBlob`). The new `components/ai-elements/citation.tsx:27` rewrites
`[N]` numeric markers that the backend never emits; there are zero `inref`
matches in web-next. Consequences in real RAG chats: no inline citations, raw
`<inref>` tags leak into/are stripped by Streamdown, and copy-answer
(`chat-message.tsx:117`) copies raw tags (old `copyAssistantAnswer.ts` stripped
them). PARITY.md tracks "inline citations" as open, but the shipped hover-preview
feature satisfies it only cosmetically.
**Fix:** add an inref→citation transform (buffer split tags during streaming),
map ids to `providerMetadata.eneo` blob references, and strip tags in copy.

## 3. Systemic flaw: builders autosave

All five assistant-editor sections plus group-chat and app editors share these
(files under `features/assistants/editor/`, `features/group-chats/`,
`features/apps/editor/`):

1. **Out-of-order response race** — every save's `onSuccess` does
   `setQueryData(fullResponse)` with no serialization (`use-assistant.ts:36`,
   `use-group-chat.ts:35`, `use-app.ts`). Two rapid toggles can land reversed,
   leaving the cache at the older state; the adopt-server-state effect
   (`mcp-section.tsx:33-38`) then visibly reverts the user's switch. Needs a
   per-resource mutation queue or field-scoped merge.
2. **Shared status keys lie** — name+description both use key `"general"`
   (`use-autosave.ts:19-40`); first resolve clears the key, so the header shows
   "All saved" and the `beforeunload` guard drops while the sibling save is
   in flight; a later success erases an earlier failure chip.
3. **Unsaved prompt lost on close** — `instructions-section.tsx:196` commits on
   blur only; the unload guard only covers in-flight saves, so typed-but-
   unblurred prompt text dies with the tab. Old app confirm-guarded all dirty
   state.
4. **Failed autosave leaves diverged UI** — on error the optimistic state stays
   (switch ON, server OFF) with no revert or per-field error marker
   (`mcp-section.tsx:49-55`, `knowledge-section.tsx:50-59`,
   `attachments-section.tsx:434-439`).

## 4. Missing per area (present in apps/web, absent in web-next)

### Auth / shell / account / spaces
- **Suspended-tenant routing** (major): old routed error 9025 → `/deactivated`
  (self-healing); new only handles password-login 403 — OIDC users of suspended
  tenants get the generic error boundary.
- **Multi-tenant federation login** (major): tenant list + remembered slug +
  per-tenant `/api/v1/auth/initiate?tenant=` (old `(public)/login`). New OIDC is
  one env-configured IdP. Only the Zitadel drop is documented in PARITY, not this.
- **Space settings: MCP server selection** (major): `space-settings.tsx:283`
  still says "stubbed until Phase 6 owns the MCP UI" — Phase 6 shipped.
- **Security-classification impact analysis** (major): old ran impactAnalysis
  and confirm-listed models/servers that would break; new autosaves the change
  silently (destructive, no warning).
- **Space-scoped API keys section** (major): old settings embedded
  `ApiKeysSettingsSection scopeType="space"`.
- **Account API keys** (major, PARITY over-claims PASS): missing
  suspend/reactivate (+reason), legacy-key banner/revoke, notification
  preferences + expiring-keys banner, search, and the rich create dialog
  (description, ownership, space/assistant/app scopes, resource permissions).
- **Expiring API-key notifications in the header bell** (moderate): old
  `JobManagerDropdownButton` showed urgency dots + panel section; no equivalent
  in `features/jobs/job-indicator.tsx`.
- **Mobile redirect + PWA dashboard manifest** (major for mobile users), **space
  icon upload** (minor), **login diagnostics** (correlation-id copy, distinct
  OIDC errors, `login/failed` params — minor), **logout/expired banners on
  login** (minor).

### Chat
- **Per-conversation insights tab** (major, confirmed still open): old
  `spaces/[spaceId]/chat/insights` (stats, AI-analysis Q&A, explore dialog).
  Note: web-next editors still expose `insight_enabled` toggles that currently
  enable nothing user-visible.
- **MCP tool references** (major): inline MCP citations, resource snippet modal,
  image attachment strip — absent live *and* for history (`map-session.ts`
  ignores the persisted field).
- **Per-conversation MCP server toggling** (`disabled_mcp_server_ids`, backend
  supports) **+ auto-accept toggle** (major, ties into §2.1).
- **Tool-call result content** (major): old lazily fetched real tool output on
  expand; `activity-timeline.tsx:189-193` shows only `{"status":"succeeded"}` —
  the per-step I/O promise of the progressive-disclosure design is hollow.
- Minor: `SHOW_WEB_SEARCH` flag gating, assistant switcher in chat header,
  attachment `max_files` client rule.

### Builders
- **effective_config enforcement in the assistant editor** (major): zero hits
  for `prompt_locked|models_enforced|mcp_enforced` in `features/assistants` —
  prompt always editable, all space models and MCP servers offered. The personal
  default assistant is editable through this same route, so governance locks are
  invisible (old: `.../assistants/[assistantId]/edit/+page.svelte:66-92`).
- **Per-tool MCP (`mcp_tools`) in the editor + tool-calling model warning**
  (major, PARITY row 49 over-claims).
- **Assistant- and app-scoped API keys sections** (major) and **app editor
  attachments section** (major) — `app-editor.tsx:21-23` admits both deferrals;
  PARITY rows 45/47 say PASS.
- **Template wizard** (major): create-from-template always sends
  `additional_fields: null` (`create-menu.tsx:118`); templates requiring
  knowledge/attachments create incomplete. **Create app from template** (minor).
- Minor: client-side validation of assistant attachment uploads
  (accept/size from `allowed_attachments`), list search on
  assistants/apps/services grids, help-assistant logging notice, app prompt
  version history.

### Knowledge / jobs
- Expandable per-item blob list in the knowledge picker (deferred in code, not
  in PARITY); table filter/sort on websites/collections/crawl-runs; crawl-
  limitations banner; integrations beta notice + admin-configure affordance;
  "no create permission" info affordance (was deliberately WCAG-treated in old).

### Admin
- **Model deletion — all 3 kinds** (high): no DELETE to
  `/admin/tenant-models/*` anywhere; since provider DELETE 400s while models are
  attached, **a provider with models can never be deleted** (the delete action in
  `provider-overview.tsx:106` is a guaranteed dead end). Old also mapped
  `MODEL_IN_USE` (9039) → "migrate instead" CTA.
- **Add/edit embedding + transcription models** (high): wizard filters
  `modes.includes("completion")` (`model-providers.ts:181`); `canEdit/anMigrate`
  are completion-only (`model-row.tsx:258-260`). Embedding security
  classification is unreachable. Transcription migration impossible.
- **Migration `force_override`** (medium): backend rejects security blockers
  without it; old had blocker/warning classification + ack checkbox; new always
  sends only `confirm_migration: true` → blocked migrations dead-end.
- **Pre-create model validation** (`validate-model` endpoint unused, medium);
  **provider config-field editing** (Azure endpoint/api_version can never be
  corrected, medium); **template rollback** (low).
- **Per-assistant insights deep-dive** (moderate, confirmed still missing);
  **per-user usage detail page** (moderate); **audit filters in URL**
  (moderate — the shipped deep link `usage-dialog.tsx:146` →
  `/admin/audit-logs?search=…` is dead because the audit page ignores query
  params); **actor-filtered GDPR export** (minor — backend accepts `actor_id`,
  UI just disables the button).

### Cross-cutting
- **CSP**: no `Content-Security-Policy` header at all (baseline headers only,
  `next.config.ts:13-19`); nonce middleware still an open CUTOVER task.
- **Lint guardrails**: neither `no-hardcoded-text` nor `no-raw-color` exist in
  web-next's eslint config (old app enforced both). i18n is currently clean by
  discipline (3829/3829 keys, ~2 hardcoded strings) but nothing keeps it so;
  ~236 raw palette-color occurrences already accumulated.
- **E2E**: exists but minimal — auth setup + 6 admin/account smoke tests; no
  chat, spaces, or knowledge flow.
- Account preferred copy-format (still open, orphaned i18n keys only).

## 5. Flaws per area (migrated but broken/regressed)

### Chat
- **Live web-search sources never render** — `data-session.web_search_references`
  dropped in `chat-view.tsx:177-198`; chips only appear after reload. PARITY
  "web-search source rendering PASS" over-claims.
- **User attachments vanish from the live transcript** — `sendMessage({ text })`
  has no file parts; files reappear only after reload.
- **Bridge drops mid-turn reasoning** — `ui_message_stream.py:212-227`: a
  REASONING chunk after TEXT closes emits `reasoning-delta` for an ended part id
  (protocol-invalid). Affects agentic reason→tool→reason flows.
- **Group-chat answer label disappears at stream end** (`chat-message.tsx:53`
  falls back to live data only while streaming).
- **Error codes dropped** — bridge emits `data-error {code}` but nothing consumes
  it; UI shows raw `errorText`/generic message; composer input not restored on
  pre-stream failure (old did both).
- WCAG: scroll-to-bottom button unnamed (`ai-elements/conversation.tsx:82`);
  history row actions hover-only with no focus-visible state
  (`history-panel.tsx:138`); rename input unlabeled (`history-panel.tsx:187`).
- Non-image generated files render nothing live (`chat-message.tsx:90-99`).

### Builders
- §3 autosave cluster (race, lying status keys, lost prompt, no revert).
- **App run `max_files` not enforced** on multi-select
  (`use-app-run.ts:45-78`); `maxSize` documented "combined" but applied per file.
- **Orphaned upload blobs** — assistant attachment removal only detaches; the
  blob is never deleted (old deleted unsaved uploads); app-run inputs *do*
  delete — inconsistent.
- **Service editor uses a local Save button** (`service-editor.tsx:285-289`) —
  violates the web-next autosave convention.
- i18n: `apps/apps.ts:59-64` `getResultTitle` emits hardcoded English (used as
  page title + delete-confirm body); `input-section.tsx:61` raw `text/audio/image`
  labels; `service-editor.tsx:224` untranslated kwarg options (ai-section
  translates the same values).
- Raw palette colors: `attachments-section.tsx:83-184` (12 icon chips),
  `apps/status-badge.tsx:9-15`, `knowledge-section.tsx:70`, `mcp-section.tsx:62`,
  `audio-recorder-input.tsx:239`.
- WCAG: queued-run status icon variant renders an empty pill with no accessible
  name (`status-badge.tsx:47-56`); `SaveStatusIndicator` swaps whole live-region
  nodes instead of updating one persistent region (`save-status.tsx:80-113`).

### Knowledge / jobs
- **SharePoint/Confluence preview errors render as empty state** — only
  `isPending` handled; expired OAuth (401) shows "no matching sites found" with
  no reconnect hint; null integration id → infinite spinner
  (`import/sharepoint-import.tsx:236-243`, same in confluence).
- **Upload success gives no cue** — old force-opened the job panel; new closes
  the dialog silently (`upload-dialog.tsx:101-103`).
- **No aria-live anywhere in the jobs/upload pipeline** (`job-indicator.tsx`) —
  completion/failure never announced (WCAG hard requirement).
- Failure reasons only in `title` tooltips (keyboard/touch/SR-unreachable) —
  `websites.tsx:69-77`, `crawl-runs.tsx:61-71`.
- Grouped websites "select all" checkbox is global across groups and never
  indeterminate (`websites.tsx:364-370`); React key collision on duplicate file
  names (`upload-dialog.tsx:132`); hardcoded English in bulk-recrawl toast
  (`websites.tsx:295`); raw palette colors across websites/integrations/import
  files; jobs poller never restarts for externally started work
  (`use-jobs.tsx:128-133` — parity with old, but PARITY's WS-replacement claim
  only holds for in-tab actions).

### Admin A
- **Broken i18n keys** — `insights-page.tsx:263` `t(\`last_${preset}_days\`)`:
  keys don't exist (only `audit_last_*`); buttons render raw key strings.
- **Export silently mismatches the table** — `export-dialog.tsx:59` sends only
  `filters.actions[0]` and drops `search` with no warning; **cancelled export
  shows "exporting…"** forever (no cancelled/expired handling,
  `export-dialog.tsx:112-121`).
- `auditConfigQueryOptions` defined in a `"use client"` file
  (`audit-config.tsx:27`) — violates the QueryOptions boundary rule.
- Hardcoded `IP` table header (`usage-dialog.tsx:111`); raw palette colors
  (user-table, audit-table, usage-dialog, insights delta).
- WCAG: `aria-expanded` on the `<tr>` instead of the toggle button
  (`audit-table.tsx:50-71`); insights presets have no pressed/selected state;
  export progress changes unannounced.

### Admin B
- **Template editor wipes kwargs** — `template-editor-dialog.tsx:123-124`
  rebuilds `completion_model_kwargs` as `{}`/`{temperature}`; saving destroys
  existing `top_p`/`reasoning_effort`.
- **Edit dialog drops writable fields** — `edit-model-dialog.tsx` omits `name`
  (the litellm model id — a typo can never be fixed), `hosting`, `open_source`.
- **Wizard Back duplicates providers** — `add-model-wizard.tsx:431` returns to a
  cleared credentials step after the provider was already created; re-submit
  creates a duplicate.
- **Catalog creates models with `max_input_tokens: 0 / max_output_tokens: 0`**
  when LiteLLM defaults are missing (`model-catalog-step.tsx:144-145`) — old
  explicitly guarded ("backend… divide by zero").
- Migration dialog: renders backend **English** `warnings` instead of
  translating `warning_codes` (`migrate-model-dialog.tsx:84-88`); target list
  includes disabled/deprecated/provider-less models (`:110-112`); impact fetch
  error → confirm with zero impact data shown (`:37-40`); after migration the
  history panel + usage details aren't invalidated (`:117-118`).
- Model detail dialog renders the description under the label `t("name")`
  (`model-detail-dialog.tsx:65`); `ProviderEditDialog` is fed a fabricated
  provider object (`provider-overview.tsx:145-156`); raw palette colors in
  migration-history/help-assistant-editor/sharepoint dialogs; migration-history
  search input has placeholder-only accessible name.

### Auth / shell
- **Deactivated page broken** — title renders `t("account")` instead of the
  deactivated heading; body copy ends mid-sentence ("…Please contact") because
  the mailto tail was dropped; no logout/retry actions → dead end.
- **Activate page actions** — "Retry" links to `/login`, which bounces straight
  back (see §2.2); uses `<Link href="/logout">` (prefetch risk on a mutating
  route handler; profile-menu deliberately uses `<a>`).
- API-keys table: header says "Key Type" over the **state** column; permission
  cell shows raw enum with CSS capitalize though translated keys exist.
- **No skip-to-content link** (WCAG 2.4.1; old shell had one).
- Switch-organisation menu item shown unconditionally (old gated on
  `has_multi_tenant_federation`) — in password-only deployments it's a disguised
  logout; dashboard default-assistant tile shows raw name instead of the
  localized "Personal assistant"; hardcoded `user@example.com` placeholder
  (`space-members.tsx:198`); account integration card ignores
  `tenant_app_configured === false` (Connect fails opaquely).

### Cross-cutting
- **No `Cache-Control: no-store` on authenticated proxy responses**
  (`api/eneo/[...path]/route.ts`; the chat route's `no-cache` should also be
  `no-store`). Path traversal, session encryption, redirect safety verified OK.
- `(public)` route group has no error boundary; `(app)/error.tsx:27` prints raw
  `error.message` to end users; in-app `notFound()` renders without the shell.
- `recharts` imported at top level of a client component (admin insights).
- `/(app)/chat-mock` design-mock route ships to every logged-in user.
- Vendored ai-elements icon buttons without default accessible names
  (`conversation.tsx:82,143`, `code-block.tsx:478`); clickable table rows
  without keyboard handling (`migration-history-panel.tsx:134`,
  `audit-table.tsx:50`).

## 6. PARITY.md corrections needed

- **Over-claimed PASS:** Assistants row 45 / Apps row 47 (scoped API keys +
  app attachments missing), MCP picker row 49 (no `mcp_tools`), model add-wizard
  / full-edit / migration rows 63-66 (completion-only; no delete; no
  force_override; no provider config edit), "create assistant from template"
  (no wizard `additional_fields`), "per-tool MCP approval" + "web-search source
  rendering" (group-chat send broken; live sources never render),
  "activate / self-provision landing" (unreachable, no provision call),
  account API keys row 23 (reduced create dialog + missing lifecycle actions).
- **Stale contradictions:** rows 34-35 ("group-chat answer labels DEFERRED",
  "reasoning DROPPED") contradict the buildout section that marks both done.
- **Confirmed still open:** per-assistant insights deep-dive, `/chat/insights`,
  account copy-format, CSP nonce, full E2E. "Inline citations" should move back
  to open-in-effect (§2.3).
- **Unrecorded deferrals found in code comments:** knowledge-picker blob list,
  app editor attachments/API keys, space-settings MCP stub, create-app-from-
  template.
