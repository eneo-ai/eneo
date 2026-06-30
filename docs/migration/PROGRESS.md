# Migration progress — session handoff

Status ledger for the web-next migration (branch `refactor/web-next`). Read this
first in a new session; the phase docs (01–08) are the plans, this is what
actually happened. Update this file when a phase lands.

> **STOP POINT 2026-06-13 (Phase 7 functionally complete)** — every admin
> section from 07-admin.md ships a working web-next page behind the admin gate
> (`/admin/layout.tsx`): feature toggles, users, audit-logs (incl. the RB-5(d)
> access-session cookie spike in the proxy), security classifications, models,
> MCP servers, org API keys, tenant integrations, usage, insights, prompt
> library, help assistants, templates. Heavy/low-traffic sub-flows are deferred
> with notes (see "Phase 7 status" below): model add/edit wizards + migration,
> audit config tab, api-key policy/super-key, SharePoint Azure-AD config +
> webhooks, template editors, insights charts. The audit category-config tab
> and the personal-assistant governance policy page were since added. **Phase
> 8 in progress**: i18n parity verified, app error/not-found/loading states,
> standalone build + Dockerfile, ENV/PARITY/CUTOVER docs landed. Remaining
> Phase 8 is **ops-owned** (E2E stack, strict nonce-CSP, Docker-boot smoke,
> Lighthouse, maintainer PARITY sign-off) — tracked in CUTOVER.md. The `/admin`
> nav link is in main-nav, gated by can("admin").
> Frontend QA runs on the HOST (`bun run check/lint/test/build` in
> apps/web-next), never `bun install` in the container; backend dev server +
> `bun run dev` (port 3100) you start yourself in devcontainer terminals.

## Phase status

| Phase | Status | Commits (key) |
|---|---|---|
| 1 Boilerplate | ✅ done | `a62a08916` |
| 2 Auth (OIDC + password, RB-1) | ✅ done | `b30c634a6`, `34b3cd12a` |
| 3 API layer (typed client, proxy, Query) | ✅ done | `4763c9c69` |
| 4 Shell, spaces, dashboard, account | ✅ done | `bd1cf68cb` |
| 5 Chat (RB-2 + AI SDK v6) | ✅ done | `16a3f2e66` (backend), `f1bc473bd`, `34af2c932`, `03d01aa39` |
| 6 Builders + knowledge | ✅ done | jobs/knowledge `d3b3fc4c4`/`ab577d5c4`, integrations/assistants/group-chats `4b8cd627e`, apps `6432056c0`, services |
| 7 Admin | ✅ done (with documented deferrals) | all sections shipped; heavy sub-flows deferred |
| 8 i18n / polish / parity | 🟡 in progress | i18n parity, states, standalone+Docker, ENV/PARITY/CUTOVER docs; E2E/CSP/Lighthouse are ops |

## Architecture conventions (established, follow these)

- **Data access**: server components use `eneoApi()` (`src/lib/api/server.ts`);
  client components use `browserApi` (`src/lib/api/browser.ts`) which goes
  through the `/api/eneo/[...path]` proxy (full `/api/v1/...` path appended).
  Always wrap calls in `unwrap()` (`src/lib/api/errors.ts`) → throws
  `EneoApiError` (status, code, traceId). Toasts via `toastApiError(error, t)`.
- **Types**: `Schema<"ModelName">` from `src/lib/api/models.ts` (generated
  `schema.d.ts`). Regenerate with `bun run gen:api` (backend must run);
  CI drift-checks it (schema-drift job regenerates both web-next and
  intric-js schemas from `app.openapi()`).
- **Query**: SSR pages `fetchQuery` (NOT `prefetchQuery` — it swallows the
  401-redirect) + `HydrationBoundary`; query keys mirror backend paths
  (`["spaces", routeId]`, `["dashboard"]`, `["api-keys", state]`,
  `["conversations", kind, partnerId]`). Mutations invalidate by key.
  Cursor pagination: `usePaginatedQuery` (`src/lib/hooks/`).
- **Permissions**: tenant-level `useAppContext().can(requirement)`
  (anyOf/allOf port); space-level `useSpace().can(action, resource)`.
  Space data comes from the `[spaceId]` layout prefetch
  (`spaceQueryOptions`, aliases `personal`/`organization`).
- **UI**: primitives from `src/components/ui` (shadcn CLI only, never
  hand-rolled — run via `bunx shadcn@latest add X --yes`); generic composites
  in `src/components/composites/` (page-header, settings-rows, confirm-dialog,
  empty-state, secret-reveal); AI Elements vendored editable in
  `src/components/ai-elements/`; feature compositions in `src/features/`.
  Theme values live only in `src/app/globals.css` as shadcn semantic tokens
  with an Eneo palette. Feature code uses tokens/utilities, not hard-coded
  colors or copied Svelte design-system variables.
- **i18n**: keys come from the converted Svelte catalogs; web-next-only keys
  go in `src/lib/i18n/extra/{en,sv}.json`, then run
  `node scripts/convert-paraglide-messages.mjs`. `t()` is untyped (plain
  string keys), but `bun run lint` runs `scripts/check-i18n.mjs` to enforce
  `sv`/`en` key parity and literal `t("key")` coverage. Swedish is default;
  locale is the `NEXT_LOCALE` cookie set via server action
  (`src/lib/i18n/actions.ts`).
- **Layout shell**: `(app)/layout.tsx` is viewport-locked (`h-svh`, scroll
  inside `main`) so chat can pin its input; don't reintroduce page-level
  growth. In chat, URL updates use `window.history.replaceState`
  (NOT `router.replace` — its RSC transition blocks streaming re-renders).

## Chat (Phase 5) specifics

- Backend `POST /api/v1/conversations/?version=3` emits the AI SDK UI Message
  Stream (`backend/src/intric/conversations/ui_message_stream.py`; golden
  tests in `backend/tests/unittests/conversations/test_ui_message_stream.py`).
  v3 = framing only; service still runs with version=2 semantics. Custom data
  parts: `data-session`, `data-token-usage` (transient), `data-status`
  (transient), `data-tool-approval` (reconciled in place by approval_id),
  `data-error`.
- The conversation request takes EXACTLY ONE of session_id / assistant_id /
  group_chat_id (continuing a session ⇒ only session_id). Applies to
  preflight too.
- Frontend: `/api/chat` passthrough proxy; `src/lib/chat/` (types, transport,
  map-session + tests, use-preflight); `src/features/chat/` (chat-page,
  chat-view, history-panel, message-parts, use-attachments). Tool approval
  posts to `approve-tools/` while the stream stays open.
- Streamdown markdown styling requires the `@source` lines in
  `src/app/globals.css`; new `@source` globs need a dev-server restart.

## Known deviations / deferred (with reasons)

- Reasoning chunks not emitted: backend strips `<think>` and never streamed
  reasoning (the `<intric_thinking>` claim in 05-chat.md is stale).
- AI SDK v6 native tool approval unused: it assumes client resubmission;
  eneo holds the stream open on Redis → spec'd `data-tool-approval` fallback.
- Group-chat answer labels not shown: v3 doesn't carry which assistant
  answered (RB candidate). Mentions are a picker targeting one assistant
  (matches backend `tools.assistants[0]` behavior), not contenteditable.
- Mock-LLM E2E stack still speaks v2 (overview OQ-6) — not yet taught v3.
- Space settings: MCP-server section stubbed (Phase 6 owns MCP UI); icon
  upload + space-scoped API keys section not ported.
- `/` redirects to `/dashboard` until Phase 5's chat becomes the landing
  (parity target `/spaces/personal/chat`); flip in Phase 8.
- RB-5 inventory: `docs/migration/rb-5-issue-draft.md` (kept local —
  **never create GitHub issues from this migration work**; stealth POC).

## Parity target moved by the develop merge (2026-06-12)

- **Phase 7 scope grew**: governance (#417) added new Svelte admin areas —
  `/admin/prompt-library` and `/admin/personal-assistant` (configuration +
  policy). `07-admin.md` predates them; fold them into the Phase 7 plan.
- **Phase 5 parity, small**: the Svelte model selector now shows model
  details (#493); mirror in web-next's ModelSelector before the Phase 8
  parity audit. Also check attachment same-file reselect (#491) in
  use-attachments.
- **Schema**: prompt-library + governance-policy endpoints exist now; run
  `bun run gen:api` before the next build session.

## Manual gate items still open

- Two-user walkthrough (admin vs plain member affordances) — needs a second
  account.
- Vision attachments answer check, live MCP approval flow, abort-mid-stream,
  huge-paste send lockout, Svelte side-by-side parity checks.

## Environment / workflow notes

- Commands run via
  `docker exec -u vscode eneo_devcontainer-eneo-1 bash -i -c "cd /workspace/... && ..."`;
  bun needs `export PATH=/home/vscode/.bun/bin:$PATH` for spawned children
  (shadcn/ai-elements CLIs).
- Frontend QA (check/lint/test/build) must run on the HOST: the container has
  no node, so vitest falls back to bun's runtime and dies in tinypool.
  Never `bun install` inside the container — it swaps platform binaries to
  linux and breaks host tooling (reinstall on host + `git checkout bun.lock`
  to recover). `bun run build` needs a `.env` (env.ts zod-validates at import
  during page-data collection).
- Backend dev server (uvicorn, port 8123) and `bun run dev` (port 3100) are
  run by the developer in devcontainer terminals. VS Code auto-forwards the
  ports; processes started via plain `docker exec` are NOT forwarded.
- QA loop: `bun run format && bun run lint && bun run check && bun run test
  && bun run build` (web-next). Backend: `uv run pytest tests/unittests/...`,
  `uv run ruff check/format`.
- Login for manual testing: `alexander.andersson@sundsvall.se` / `Password1!`
  (password mode). Generated schemas are excluded from the pre-commit
  large-file hook.

## Phase 6 progress (6a partially done; stop point of 2026-06-12 session)

Done:
- **Jobs** (`d3b3fc4c4`): `src/features/jobs/use-jobs.tsx` — `["jobs"]` query,
  adaptive refetchInterval (2s for 15s after `trackJob()`, else 30s, stops when
  idle); upload queue (max 5 concurrent, XHR to
  `/api/eneo/api/v1/groups/{id}/info-blobs/upload/` for byte progress).
  Completion (active→complete or job aged out) invalidates
  `JOB_INVALIDATION_KEYS`: spaces/collections/websites/integration-knowledge/
  info-blobs/apps. Header bell popover: `job-indicator.tsx`.
- **Knowledge: collections + websites** (`ab577d5c4`):
  `src/features/knowledge/` (knowledge.ts query layer, collections, blobs,
  upload-dialog, websites, website-dialog, crawl-runs, move-dialog,
  embedding-model-select, knowledge-page) + routes `knowledge/`,
  `knowledge/collections/[collectionId]/`, `knowledge/websites/[websiteId]/`.
  Tab state via `?tab=` + history.replaceState. Lists come from the space
  object (filtered `space_id === space.id`), grouped per embedding model when
  >1 in use. Detail pages prefetch via fetchQuery + HydrationBoundary; crawl
  runs poll at 30s. `src/lib/format.ts` (bytes/datetime/relative/duration —
  no dayjs dep). `ConfirmDialogControlled` added to composites for
  dropdown-launched deletes.

Done (2026-06-13 session):
- **Knowledge: integrations tab, list slice**: `src/features/knowledge/
  integrations.tsx` (groupIntegrationRows + countSharePointItemTypes pure +
  unit-tested; wrapper rows ≥2 items, vendor logos copied as PNGs, status cell
  with last-sync + SharePoint webhook state via `hoursUntil` in lib/format,
  item/wrapper rename-sync-delete actions) + wrapper detail route
  `knowledge/integrations/wrapper/[wrapperId]` (client-only, derives from the
  space object; delete navigates back). Tab gated by
  `can("read","integrationKnowledge")`. New i18n key `open_in_confluence` in
  extra catalogs (Svelte used a hardcoded English fallback). Sync-history
  trigger intentionally NOT wired (status is plain text until the dialog
  lands).

Done (2026-06-13 session, continued):
- **Integrations restructured into modules** (`src/features/knowledge/
  integrations/`): grouping.ts (pure, tested), vendor.tsx, queries.ts,
  status.tsx, actions.tsx, table.tsx, tab.tsx, sync-history.tsx,
  import/{selection.ts (pure, tested), folder-tree, sharepoint-import,
  import-dialog}. Old single-file integrations.tsx removed.
- **SyncHistoryDialog**: paginated 10/page (`GET /api/v1/integrations/
  sync-logs/{id}/?skip&limit`), status cell now opens it.
- **SharePoint import flow**: ImportKnowledgeDialog (select connected
  integration; SharePoint-only, matching the Svelte knowledge layout filter —
  Confluence import is effectively disabled there too) → site picker grouped
  by category (my_teams/public_teams/other/onedrive) → one-level folder tree
  with breadcrumbs → nested-selection dedupe (selection.ts) → wrapper name
  required when >1 effective item → batch import + trackJob. New i18n keys
  `sharepoint_import_hint`/`confluence_import_hint` (hardcoded English in
  Svelte). Toolbar gated by `can("create","integrationKnowledge")`; personal
  spaces get a connect CTA to /account/integrations, org spaces a hint
  (tenant-app admin UI is Phase 7).

- **OAuth connect popup flow**: `src/features/integrations/`
  (use-integration-auth.ts hook — popup FIRST then auth URL with
  state=tenant_integration_id, same-origin message listener, code
  registration; callback-message.ts contract) + popup-only callback page
  `(public)/integrations/callback/token` (`/integrations/callback` was
  already in proxy PUBLIC_PREFIXES). Account integrations connect button
  wired. Service-account branch deferred to Phase 7 admin. Lint gotchas:
  react-hooks/set-state-in-effect (defer via queueMicrotask) and
  react-hooks/refs (latest-ref updates must happen inside useEffect).

Done (2026-06-13 session, assistants):
- **Assistants list** (`src/features/assistants/`): tile grid at
  `/spaces/[spaceId]/assistants` (assistants + group chats merged and
  name-sorted like SpacesManager), published/drafts sections for users with
  publish permission, create split-button (blank assistant → editor; group
  chat stays on list), actions (edit/publish/move/delete; group chats have
  no move). PublishDialog is shared and reusable for apps later.
  MoveResourceDialog gained a children slot (assistant "include knowledge"
  switch) + optional hint.
- **Assistant editor** (`src/features/assistants/editor/`): per-section save
  like space-settings (the Svelte global draft/diff editor was intentionally
  NOT ported — sanctioned redesign). Sections: general (name/description/
  icon via POST /api/v1/icons/ multipart through the proxy), instructions
  (prompt), AI settings (model select + behaviour presets creative 1.25/
  default null/deterministic 0.25/custom + model-specific kwargs driven by
  supported_model_kwargs capabilities — pure module model-kwargs.ts,
  unit-tested), security (retention, inherits space), publishing (status +
  insights toggle gated by insight_toggle permission).
- Governance effective_config branches intentionally skipped: the schema
  documents it as only populated for personal default assistants, never for
  space assistants.

Done (2026-06-13 session, continued — knowledge picker + group chats):
- **Knowledge picker** (`src/features/knowledge/select/`): logic.ts is the
  pure port of knowledgeOrigin + knowledgeIntegration + getAvailableKnowledge
  (origin bucketing personal/org via the organization space id from the
  spaces list, wrapper collapse rules, per-embedding-model sections with
  dominant-model compatibility) — unit-tested. knowledge-picker.tsx renders
  one origin (selected rows + Popover/Command combobox). Wired into the
  assistant editor as KnowledgeSection (personal + organization rows, single
  save; MCP mutual-exclusion warning/disable). The Svelte expandable
  per-item blob list (lazy file/page listing) is deferred polish.
- **Group chat editor** (`src/features/group-chats/` +
  `group-chats/[groupChatId]/edit` route): name, icon, assistants picker
  with per-assistant user_description override dialog, mentions +
  response-label toggles (save-on-toggle), publishing + insights. Creating
  a group chat now navigates straight to the editor (Svelte's default).
- **IconField generalized** into `components/composites/icon-field.tsx`
  (owns upload/delete against /api/v1/icons/; onSave persists the id on the
  owning resource) — used by both editors and the tile via its iconUrl.

Assistants follow-ups (deferred, in rough priority order):
- MCP servers picker, attachments section, prompt version history dialog,
  prompt-guide modal (help-assistants), API keys section, selected-knowledge
  expandable blob list.
- Templates: creation is blank-only; TemplateCreateAssistant flow +
  TemplateCreateAssistantHint not ported.

Done (2026-06-13 session, apps):
- **Apps** (`src/features/apps/`): apps.ts (types, query options
  app/appRuns/appRun, getResultTitle + inputFieldRules + isRunActive pure +
  unit-tested, fileSignedUrl helper), apps-page (tile grid, published/drafts
  for publishers), create-app (blank create → editor; templates deferred),
  tile, actions (edit/publish/delete; reuses assistants PublishDialog),
  status-badge (icon/full run status pill, web-next Tailwind palette not the
  eneo *-dimmer tokens which web-next lacks).
- **Editor** (`editor/`): per-section save like assistants (use-app.ts =
  appQueryOptions + useUpdateApp **PATCH** /apps/{id}/ — apps update via PATCH,
  not the assistant POST-as-update). Sections: general (name/desc/icon via
  IconField), input (description + grouped type select text/audio/image →
  input_fields PATCH), instructions (prompt.text; PromptCreate body), AI
  (completion model + behaviour presets + model-specific kwargs reusing
  `@/features/assistants/editor/model-kwargs`; transcription model row shown
  only when an audio input is configured), security (retention), publishing
  (publish/unpublish — apps have **no** insights toggle, unlike assistants).
- **Run** (`run/`): use-app-run (text + file upload queue → POST
  /api/v1/files/ `upload_file`, run create POST /apps/{id}/runs/ with
  `{files:[{id}], text}` + trackJob + navigate). app-inputs renderer →
  text-input / upload-input (drag-drop + accept from input field rules) /
  audio-recorder-input (condensed MediaRecorder port: timesliced capture,
  size-limit auto-stop, volume meter, preview → "use this recording"). Shared
  files array across input fields (matches Svelte's single AttachmentManager;
  apps are normally single-input). run-view = identity + form + submit.
- **Results** (`results/`): results-table (polls 5s while a run is active,
  delete via DELETE /app-runs/{id}/), result-detail (polls 3s while active —
  **app_run_updates websocket intentionally replaced by polling**, per plan;
  output Streamdown + copy/download, transcription tab with signed-URL audio
  playback, failed-with-files signed-URL downloads, status sidebar).
- **Detail + dashboard**: app-detail (run/results tabs, `?tab=`), space routes
  (apps, [appId], [appId]/edit, [appId]/results/[resultId]) + dashboard routes
  (`dashboard/app/[appId]` + results/[resultId], reusing RunView/ResultsTable/
  ResultDetail — none depend on useSpace; the dashboard list already linked
  there). Org-space exclusion handled by the nav gate (no server 404 guard,
  matching the sibling assistants page); all app i18n keys already existed.

Apps follow-ups (deferred):
- Prompt version history dialog, app prompt-attachments section, API-keys
  section, template create flow (TemplateCreateApp), print-to-PDF on the
  result page (copy + download text shipped). The AppSwitcher dropdown in the
  detail header was not ported (plain back-link instead).

Done (2026-06-13 session, services):
- **Services** (`src/features/services/`): services.ts (types — Service =
  ServicePublicWithUser, ServiceUpdate = PartialServiceUpdatePublic; query
  options + spaceServices), services-page (tile grid + create), create-service
  (name + "open editor after creation" switch → navigates to ?tab=settings),
  tile, actions (edit/move/delete; reuses MoveResourceDialog **without** the
  knowledge switch — services transfer with move_resources:false; no publish).
- **Detail** (`service-detail.tsx`): playground / settings tabs, `?tab=`.
  Playground (input → POST /services/{id}/run/ `{input}` → ServiceOutput
  `{output}`, string-or-JSON rendered + copy). Editor (`editor/`: use-service
  = serviceQueryOptions + useUpdateService **POST** /services/{id}/ —
  POST-as-update RB-5(b)) is a single-save form (name, prompt, completion
  model + behaviour presets + model-specific kwargs reusing
  `@/features/assistants/editor/model-kwargs`, output_format json/list/boolean/
  none, json_schema textarea parsed on save). Settings tab gated by edit perm.
- New i18n key `there_are_currently_no_services_configured` added to the extra
  catalogs (en+sv) + regenerated. Services live in org spaces too (no 404
  guard, matching the Svelte page); the nav already gates on read:service.

**Phase 6 complete.**

## Phase 7 progress (Admin — widest phase, multi-session)

Plan: `07-admin.md` step order — (1) layout+gating+nav, (2) feature toggles,
(3) users, (4) audit-logs (+export BFF), (5) models + security-classifications,
(6) mcp-servers + org api-keys + integrations, (7) templates + help-assistants,
(8) insights + usage. Develop-merge additions to fold in: `/admin/prompt-library`
and `/admin/personal-assistant` (governance). Legacy roles/user-groups DROPPED
(OQ-2). Charts approximate via recharts/shadcn (OQ-5).

Done (2026-06-13 session, foundation + toggles — steps 1–2):
- **Admin layout** (`src/app/(app)/admin/layout.tsx`): server component fetches
  `/users/me/` and `hasPermission(user)("admin")` → `redirect("/")` if not
  (backend is the real authority; this is the client-visible guard). Sidebar
  shell mirrors the space `[spaceId]/layout` (aside nav + scrollable content).
- **Admin nav** (`admin-nav.client.tsx`): grouped sections like the Svelte
  AdminMenu, but only lists implemented pages — extend the `groups` array as
  pages land. `/admin` link already in main-nav gated by `can("admin")`.
- **Feature toggles** (`features/admin/feature-toggles.tsx`): overview page
  (`admin/page.tsx`). templates / audit-logging / provisioning via
  PATCH `/api/v1/settings/{templates|audit-logging|provisioning}` body
  `{enabled}` → SettingsPublic. Optimistic flip + revert-on-error +
  `router.refresh()` (re-runs the (app) layout so the new settings propagate,
  e.g. template pickers) — the web-next analogue of the Svelte invalidateAll.
  openapi-fetch needs literal paths, so a `patchSetting` switch dispatches the
  three (identical body/response shape).

Done (2026-06-13 session, users — step 3):
- **Users** (`src/features/admin/users/`): users.ts (types + offset-pagination
  query options `adminUsersQueryOptions({page,stateFilter,search})` against
  `GET /api/v1/admin/users/` — RB-5(a); `rolesQueryOptions` flattens
  predefined+custom from `GET /api/v1/roles/`; search committed only at 0 or
  ≥3 chars per the backend rule). users-page (active/inactive tabs with counts
  from metadata, debounced search box, offset prev/next pagination with
  keepPreviousData, URL sync via window.history.replaceState for shareable
  links, create button). user-table (email / role badges / state badge —
  active=green, invited=blue, inactive=gray). user-actions (edit, deactivate/
  reactivate via `POST /admin/users/{username}/{deactivate,reactivate}`, delete
  via `DELETE /users/admin/{id}/`; deactivate+delete disabled for self).
  user-editor (create `POST /admin/users/` UserAddAdmin; update
  `POST /admin/users/{username}/` UserUpdatePublic — username read-only; role
  checkboxes grouped predefined/custom; form mounted fresh per open so initial
  state seeds without a reset effect). Route prefetches the first page + roles.
  Added "Access → Users" to the admin nav.
- Deviations: **invite is NOT ported** — the Svelte admin UI never wires
  `users.invite` (create uses a password), so it's deferred (the endpoint
  exists). **User-groups dropped** from the table + editor (OQ-2). Role
  assignment kept. All user i18n keys already existed.

Done (2026-06-13 session, audit-logs — step 4):
- **RB-5(d) cookie spike SOLVED** in the proxy (`src/app/api/eneo/[...path]/
  route.ts`): the backend gates audit access with a 1-hour HTTP-only
  `audit_session_id` cookie scoped to `Path=/api/v1`. The proxy now (a)
  forwards ONLY that cookie to the backend (never the web-next session
  cookie), and (b) re-scopes the backend's Set-Cookie — rewrites
  `Path=/api/v1` → `/api/eneo/api/v1` and strips `Domain` — so the browser
  stores it and replays it on subsequent proxied audit calls. Other cookies
  stay behind. **Needs manual verification against a live backend** (cookie
  Secure/SameSite over the dev origin).
- **Audit feature** (`src/features/admin/audit/`): audit.ts (types + query
  options for logs/retention/action-config; `actionLabel`/`categoryLabel` =
  `t(\`audit_action_${a}\`)` — no 500-line label map needed since web-next t()
  is untyped; logs query `retry:false` so a 401 surfaces as the gate).
  justification-form (category + 10–500 char description → POST
  /audit/access-session → invalidate logs). audit-filters (action
  multi-select from /audit/config/actions grouped by category via Popover+
  Command, from/to date, debounced search). audit-table (timestamp, action,
  actor, description, success/failure outcome). retention-panel (GET/PUT
  /audit/retention-policy). export-dialog (async: POST /export/async → poll
  /status 2s → download via the proxied /download URL → /cancel). audit-page
  ties it together with the 401 gate + offset pagination. Added "Analytics &
  logs → Audit logs" to the admin nav.
- **Export BFF NOT needed**: the 4 SvelteKit BFF endpoints only attached the
  bearer, which the generic /api/eneo proxy already does — so export goes
  straight through the proxy (download is a plain proxied link). Deviation
  from the plan's "4 route handlers", simpler.
- Deferred: the audit **config tab** (per-category / per-action enable-disable,
  AuditConfigTab) and the **actor (by-user) filter**. New i18n keys (from,
  action, audit_actor_*, audit_outcome_*, audit_last_purge, audit_export_hint)
  added to the extra catalogs (en+sv) + regenerated; the rest reused existing.

Done (2026-06-13 session, security-classifications — part of step 5):
- **Security classifications** (`src/features/admin/security-classifications/`):
  query options (`SecurityClassificationResponse` = `{security_enabled,
  security_classifications}`; backend orders least→highest by security_level,
  `highestFirst` reverses for display). Page: enable toggle (POST /enable/
  `{enabled}`) gated by enable/disable confirm dialogs; ordered list (highest
  at top, lowest at bottom) with create/edit dialogs (POST / + PATCH /{id}/),
  delete (DELETE /{id}/), and move up/down via the rank endpoint (PATCH / with
  `security_classifications: ModelId[]` in least→highest order — reverse of the
  display order). Added "Governance → Security classifications" to the nav.
  All i18n keys already existed.

Done (2026-06-13 session, models — rest of step 5):
- **Models** (`src/features/admin/models/`): models.ts (query options →
  `GET /api/v1/ai-models/` = `ModelsPresentation` with the *SecurityStatus
  variants; `groupByProvider` by `org`, `modelLabel`). models-page (completion/
  embedding/transcription tabs). model-table (grouped by provider; per row an
  enable switch + capability badges (vision/reasoning/hosting) + classification
  cell when security enabled + an actions dropdown). Everyday flags go through
  the **simple** `POST /api/v1/{completion|embedding|transcription}-models/{id}/`
  endpoints — `CompletionModelUpdateFlags` / `TranscriptionModelUpdate` accept
  `is_org_enabled` + `is_org_default` + `security_classification`;
  `EmbeddingModelUpdateFlags` only `is_org_enabled`. So: enable/disable (all),
  set-as-default (completion/transcription), set/clear classification
  (completion/transcription, when security enabled). Locked models (missing
  credentials) show a disabled switch with a tooltip. Added "Configuration →
  Models" to the nav. Reused existing i18n (capability_vision, default_model,
  set_as_default_model, toggle_to_*_model, api_credentials_required_for_provider).
- **Deferred** (the heavy tenant-model-management surface): the add-model
  **AddWizard** (provider → credentials → model drafts w/ cost/token editing),
  full model-definition edit (name/costs/capabilities via `tenantModels.update*`),
  provider + tenant-credential management, the **migration wizard**
  (validate → migrate → history), and usage breakdowns. The `migration_history`
  tab from Svelte is not ported.

Done (2026-06-13 session, step 6 — mcp / api-keys / integrations):
- **MCP servers** (`src/features/admin/mcp/`): list (GET /mcp-servers/settings/
  → MCPServerSettingsPublic), enable/disable (POST/DELETE /settings/{id}/),
  create/edit (POST /mcp-servers/ + /{id}/; name/url/description/auth
  none|bearer with bearer_token → http_auth_config_schema), delete. Tools
  panel (sync/approve) deferred.
- **Org API keys** (`src/features/admin/api-keys/org-api-keys.tsx`): cursor-
  paginated admin list (GET /admin/api-keys with state filter), create org
  key (POST /api-keys ownership:"service", scope_type:"tenant"),
  rotate/suspend/reactivate/revoke (POST /admin/api-keys/{id}/{action}, no
  body), secret reveal. Deferred: policy panel, super-key status, scope
  resource selectors, notification policy, expiring-soon.
- **Tenant integrations** (`src/features/admin/integrations/`): provider grid
  with link/unlink (POST /integrations/tenant/add/{id}/, DELETE
  /integrations/tenant/remove/{id}/). The SharePoint Azure-AD app credential
  setup + webhook-subscription management (untyped /admin/sharepoint/* admin
  endpoints) are **deferred** with an on-screen note.
- Nav: Configuration += mcp-servers, integrations; Access += api-keys. New
  i18n in extra catalogs (mcp_auth_*, confirm_delete_mcp_server,
  admin_integrations_*); reused existing api-keys_* keys.

Done (2026-06-13 session, steps 7–8 + governance — usage/insights/templates/
help-assistants):
- **Usage** (`features/admin/usage/`): tokens (total + per-model) + storage
  (totals + per-space) tabs.
- **Insights** (`features/admin/insights/`): headline counts (assistants/
  sessions/questions) from /analysis/counts/. Charts + per-assistant
  drill-down **deferred** (no chart infra; OQ-5 approximate).
- **Prompt library** (`features/admin/prompt-library/`): CRUD (governance).
- **Help assistants** (`features/admin/help-assistants/`): installed roles +
  available templates, install/uninstall, enable + visible-to-users toggles
  (POST/DELETE /admin/help-assistants/roles/{kind}/, PATCH .../{enabled,
  visible} with ToggleRequest {value}).
- **Templates** (`features/admin/templates/`): assistant/app tabs, list +
  soft-delete (DELETE /admin/templates/{kind}/{id}). Nav item gated on
  settings.using_templates. Create/edit wizards, featured/default toggle,
  restore + permanent-delete **deferred**.

## Phase 7 status: functionally complete

Every admin section from 07-admin.md has a working web-next page, gated by the
admin permission (`/admin/layout.tsx`). Sections shipped: overview/feature
toggles, users, audit-logs (+ the RB-5(d) cookie spike), security
classifications, models, MCP servers, org API keys, tenant integrations,
usage, insights, prompt library, help assistants, templates.

**Documented deferrals** (heavy/low-traffic sub-flows; pick up if needed):
- Models: add-model AddWizard, full model-definition edit (tenantModels.*),
  provider + tenant-credential management, the migration wizard, usage
  breakdowns, the migration_history tab.
- Audit: per-action (not per-category) enable-disable; actor-by-user filter.
  (The per-category config tab is now SHIPPED — `audit-config.tsx`, a Categories
  tab on the audit page.)
- API keys: policy panel, super-key status, scope-resource selectors,
  notification policy, expiring-soon.
- Integrations: SharePoint Azure-AD app credential setup + webhook
  subscription management (untyped /admin/sharepoint/* endpoints).
- Templates: create/edit wizards, featured/default toggle, restore +
  permanent-delete + rollback + the deleted-templates list.
- Insights: time-series charts + per-assistant analytics + the analysis
  assistant stream.
- Governance: the personal-assistant policy page (`/admin/personal-assistant`)
  is now SHIPPED — it toggles each restriction (models / MCP / prompt
  enforcement, preserving the allow-lists) and picks the enforced prompt.
  Editing the model / MCP-server / tool **allow-lists** themselves (the Svelte
  multi-section PolicyDraft with per-model default + provider/tool selection)
  remains deferred.
- Manual gate: the audit access-session cookie re-scoping needs verification
  against a live backend (see step 4).

## Phase 8 progress (i18n / polish / parity — production readiness)

Done (2026-06-13 session):
- **i18n parity**: en/sv catalogs verified equal (3609 keys each, 0 missing
  either way; 13 identical strings are proper nouns/technical terms). Swedish
  default. All web-next-only keys live in `src/lib/i18n/extra/{en,sv}.json` and
  flow through `convert-paraglide-messages.mjs`.
- **State polish**: `(app)/error.tsx` (message + trace-id + retry),
  `(app)/loading.tsx` (spinner), top-level `not-found.tsx`.
- **Production build**: `next.config.ts` → `output: "standalone"` + safe
  security headers (X-Frame-Options, X-Content-Type-Options, Referrer-Policy,
  Permissions-Policy). `Dockerfile` (Bun build → Node 20 slim runner; verified
  the standalone entrypoint is `apps/web-next/server.js`). `.env.example`
  deduped + OIDC vars documented.
- **Docs**: `ENV.md` (old SvelteKit → new var mapping; JWT_SECRET/ZITADEL_*
  gone, OIDC_*/SESSION_SECRET new), `PARITY.md` (capability-by-capability audit,
  zero MISSING rows, sign-off pending), `CUTOVER.md` (proxy-flip checklist +
  rollback + open hardening).

Remaining for Phase 8 — **ops-owned** (need infra/browser/sign-off I can't run
here; all listed in CUTOVER.md):
- Strict nonce-based CSP (`script-src 'self' 'nonce-…'`) via middleware +
  browser verification. Safe baseline headers already shipped.
- Playwright E2E suite on `docker-compose.e2e.yml` + mock LLM (v3).
- `docker build` + container-boot smoke (`curl /healthz`, login+chat round-trip).
- Lighthouse sanity; no-token-leak Playwright assertion.
- Maintainer PARITY.md sign-off; OQ-3 (cutover mechanics) / OQ-4 (PWA) decisions.

**Migration feature work is complete.** Phases 1–7 shipped; Phase 8's
codebase-side deliverables are in. What remains is ops execution (cutover) per
CUTOVER.md.

Notes / gotchas hit:
- eslint react-hooks/purity forbids `Date.now()` in render — keep time math in
  `src/lib/format.ts` helpers (`daysSince`).
- react-hooks/immutability forbids self-referencing useCallback — recursive
  queue pumps need an inner named function.
- i18n: all knowledge/jobs keys already existed in the converted catalogs
  (ICU `{param}` style, `t(key, {param: string})`).
- Blob text create: `POST /api/v1/groups/{id}/info-blobs/` body
  `{info_blobs:[{text, metadata:{title}}]}`. Website update is POST (RB-5).
  Duplicate-URL precheck: `GET /api/v1/websites/check-url/?url=` (skip on org
  space; create anyway on check failure).
