# Migration progress — session handoff

Status ledger for the web-next migration (branch `refactor/web-next`). Read this
first in a new session; the phase docs (01–08) are the plans, this is what
actually happened. Update this file when a phase lands.

> **STOP POINT 2026-06-13 (`4b8cd627e`)** — Phase 6 in progress. Landed this
> session: develop merged in (conflict-free) + schema regen, integrations
> (list/wrapper pages, SharePoint import, sync history, OAuth connect),
> assistants (list + editor incl. knowledge picker), group chat editor.
> **Pick up next: Apps** (06-builders-and-knowledge.md; editor, run page with
> dynamic input forms, results, dashboard routes), then Services. The
> assistant-editor follow-ups list below is the polish backlog. Frontend QA
> runs on the HOST (`bun run check/lint/test/build` in apps/web-next), never
> `bun install` in the container; backend dev server + `bun run dev` (port
> 3100) you start yourself in devcontainer terminals.

## Phase status

| Phase | Status | Commits (key) |
|---|---|---|
| 1 Boilerplate | ✅ done | `a62a08916` |
| 2 Auth (OIDC + password, RB-1) | ✅ done | `b30c634a6`, `34b3cd12a` |
| 3 API layer (typed client, proxy, Query) | ✅ done | `4763c9c69` |
| 4 Shell, spaces, dashboard, account | ✅ done | `bd1cf68cb` |
| 5 Chat (RB-2 + AI SDK v6) | ✅ done | `16a3f2e66` (backend), `f1bc473bd`, `34af2c932`, `03d01aa39` |
| 6 Builders + knowledge | 🟡 in progress | `d3b3fc4c4` (jobs), `ab577d5c4` (knowledge: collections + websites) |
| 7 Admin | ⬜ | — |
| 8 i18n / polish / parity | ⬜ | — |

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
- **i18n**: keys come from the converted Svelte catalogs; web-next-only keys
  go in `src/lib/i18n/extra/{en,sv}.json`, then run
  `node scripts/convert-paraglide-messages.mjs`. `t()` is untyped (plain
  string keys). Swedish is default; locale is the `NEXT_LOCALE` cookie set via
  server action (`src/lib/i18n/actions.ts`).
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

Remaining for Phase 6 (in plan order):
1. **Apps** (editor, run page with dynamic input forms, results, dashboard
   routes).
2. **Services** (CRUD + run).

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
