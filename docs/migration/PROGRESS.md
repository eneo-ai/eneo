# Migration progress — session handoff

Status ledger for the web-next migration (branch `refactor/web-next`). Read this
first in a new session; the phase docs (01–08) are the plans, this is what
actually happened. Update this file when a phase lands.

## Phase status

| Phase | Status | Commits (key) |
|---|---|---|
| 1 Boilerplate | ✅ done | `a62a08916` |
| 2 Auth (OIDC + password, RB-1) | ✅ done | `b30c634a6`, `34b3cd12a` |
| 3 API layer (typed client, proxy, Query) | ✅ done | `4763c9c69` |
| 4 Shell, spaces, dashboard, account | ✅ done | `bd1cf68cb` |
| 5 Chat (RB-2 + AI SDK v6) | ✅ done | `16a3f2e66` (backend), `f1bc473bd`, `34af2c932`, `03d01aa39` |
| 6 Builders + knowledge | ⬜ next | — |
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
- Backend dev server (uvicorn, port 8123) and `bun run dev` (port 3100) are
  run by the developer in devcontainer terminals. VS Code auto-forwards the
  ports; processes started via plain `docker exec` are NOT forwarded.
- QA loop: `bun run format && bun run lint && bun run check && bun run test
  && bun run build` (web-next). Backend: `uv run pytest tests/unittests/...`,
  `uv run ruff check/format`.
- Login for manual testing: `alexander.andersson@sundsvall.se` / `Password1!`
  (password mode). Generated schemas are excluded from the pre-commit
  large-file hook.

## Phase 6 starting pointers

- Plan: `docs/migration/06-builders-and-knowledge.md`. Sources to port:
  `frontend/apps/web/src/routes/(app)/spaces/[spaceId]/{assistants,apps,services,group-chats,knowledge}`
  plus `lib/features/{knowledge,integrations,attachments,icons}`.
- The space sidebar already links to assistants/apps/knowledge/services
  (currently 404). Chat partner resolution (`space-chat.client.tsx`) already
  handles `type=assistant|group-chat` for builder-created entities.
- File uploads through the proxy are proven (chat attachments use
  `POST /api/v1/files/` with FormData + custom bodySerializer).
