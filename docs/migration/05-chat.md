# Phase 5 — Chat on AI SDK v6 + AI Elements

## Goal
The chat experience rebuilt on `ai` v6 / `@ai-sdk/react` `useChat` + AI Elements, fed by the backend's new native AI SDK UI Message Stream (REQUIRED BACKEND CHANGE RB-2). Capability parity with today's chat: streaming answers with references, history with cursor pagination, session switching/rename/delete, attachments, web-search toggle, MCP tool calls with the approval flow, context-usage bar (preflight + live token usage), reasoning indicator, abort with partial persistence, feedback, auto-title, group-chat mentions, default-assistant model switcher.

## Prerequisites
- Phase 4 gate green.
- Backend PR for RB-2 raised early; the frontend transport work can proceed against a fixture stream, but the gate needs RB-2 on the dev backend.
- Re-verify at execution time against ai-sdk.dev: `useChat` transport API, UI Message Stream chunk names, and AI SDK v6's native tool-approval mechanism (v6 added human-in-the-loop primitives; the exact wire chunks for approval must be checked, see RB-2 §approval).

## REQUIRED BACKEND CHANGE — RB-2 (spec to hand to the backend task)
Add `version=3` to `POST /api/v1/conversations/` (same request body as v2; `version=2` untouched). When v3 + `stream=true`, emit the AI SDK UI Message Stream over SSE: each event `data: {json}\n\n`, terminated by `data: [DONE]`, with headers `x-vercel-ai-ui-message-stream: v1`, `Content-Type: text/event-stream`, `Cache-Control: no-cache`. Mapping from the current internal events (source: `assistant_protocol.py`, `session.py`):

| Today (v2) | v3 chunk(s) |
|---|---|
| `first_chunk` (session/message ids, files, model) | `start {messageId}` then `data-session` part `{session_id, completion_model {id,name,token_limit,reasoning}, files}` |
| `text` delta | `text-start {id}` once, then `text-delta {id, delta}` per chunk, `text-end {id}` at completion |
| references snapshot (today piggybacked on every `text`) | `source-document` part per NEW reference as it becomes known `{sourceId: blob id, title, mediaType, …score/metadata in providerMetadata}`; stop resending full snapshots |
| `image` / generated files | `file` part `{url: signed URL, mediaType}` (generate a signed URL server-side; today the client fetches files separately) |
| `intric_event: generating_image` | `data-status` part, `transient: true` |
| `token_usage` | `data-token-usage` part `{prompt_tokens, completion_tokens, turn_tokens}`, `transient: true` |
| `tool_call` (incl. updates by `tool_call_id`) | `tool-input-available {toolCallId, toolName, input}` then `tool-output-available {toolCallId, output}` (map `result_status` errors to `tool-output-error`) |
| `tool_approval_required` | AI SDK v6 native approval chunks if the verified protocol defines them; otherwise `data-tool-approval` part `{approval_id, tools[]}` and the stream stays open exactly as today (the existing Redis-backed approval manager and `POST /conversations/approve-tools/` are reused unchanged) |
| `tool_approval_timeout` | `data-tool-approval` update part (same part `id`, status `timeout_denied`) |
| `error` | `error {errorText}` (keep codes in a `data-error` part if the UI needs them) |
| stream end | `finish` then `data: [DONE]` |

Reasoning: today reasoning text arrives wrapped in `<intric_thinking>` tags inside the text stream; in v3 emit proper `reasoning-start/-delta/-end` chunks instead. Persistence, abort-partial-save, preflight, feedback, title, rename, delete endpoints are unchanged. Backend tests: golden-transcript test asserting a full v3 stream for a scripted completion (mock LLM), incl. tool-approval pause/resume; update the E2E mock LLM stack if it asserts v2 framing (overview OQ-6).

## Scope
**In**: `/api/chat` route handler (auth-injecting passthrough proxy of the v3 stream), `useChat` transport + typed `UIMessage` (custom data parts: `session`, `token-usage`, `status`, `tool-approval`; source + file + reasoning + tool parts), chat page at `/spaces/[spaceId]/chat` for all three partner types (default assistant, assistant, group chat), AI Elements composition (Conversation, Message, Response, Reasoning, Sources, Tool, Confirmation, Prompt Input, Attachments, Context, Suggestion as applicable), history panel (reuse `usePaginatedQuery`), session lifecycle (new/switch/rename/delete/feedback/auto-title), attachments (upload via `/api/v1/files/` through the proxy, progress, validation rules), preflight debounce + context bar, mentions for group chats, dashboard chat route (`/dashboard/[assistantId]/[[sessionId]]`) reusing the same components.
**Out**: insights tab (Phase 7 owns analytics), assistant/group-chat editing (Phase 6), services/apps (Phase 6).

## Design notes
- **Transport**: `DefaultChatTransport({ api: "/api/chat", prepareSendMessagesRequest })` building the backend's `ConversationRequest` from app state: `{session_id, assistant_id | group_chat_id, question: <last user message text>, files: [{id}], tools: {assistants: [...mention]}, stream: true, use_web_search, require_tool_approval}`. History is server-owned: on session switch, fetch `GET /conversations/{id}/` and map persisted `Message[]` → `UIMessage[]` (write the mapper + tests; question/answer pairs become user/assistant messages with text, source, file, tool parts).
- **`/api/chat` route handler**: validate session → forward body to `POST {ENEO_BACKEND_URL}/api/v1/conversations/?version=3` with bearer → return the response body stream unchanged, preserving the `x-vercel-ai-ui-message-stream` header. Abort: propagate request signal to the upstream fetch (backend already persists partials).
- **Approval flow**: a `data-tool-approval` part (or the native v6 mechanism) renders AI Elements `Confirmation`; approve/deny posts to `/api/eneo/conversations/approve-tools/?approval_id=` and the open stream continues. Timeout updates the part in place (same part id).
- **Context bar**: debounce 400ms → `POST /conversations/preflight` via proxy; combine with the latest `data-token-usage` part; disable send when `willExceedContext` (port the derivation from `ChatService.svelte.ts`).
- **Rendering**: AI Elements `Response` (streamdown) replaces the bespoke RAF buffering; do not port the RAF code. Keep the CSP in mind (`script-src 'self'` parity is set in Phase 8).
- **State**: `useChat` owns messages; everything else (partner, history list, preflight) is Query state or local component state. No global chat store.

## Step-by-step
1. Install `ai@^6`, `@ai-sdk/react@^3`, run `bunx ai-elements@latest` so components land in `src/components/ai-elements/` (it installs through the shadcn registry, so the Phase 1 `components.json` wiring applies; verify placement on the first component before adding the rest). AI Elements components are editable source and count as primitives: customize them in place and build chat features by composing them rather than writing parallel chat UI.
2. Define `EneoUIMessage` types (data-part schemas via zod) + persisted-message → UIMessage mapper with unit tests on captured fixtures.
3. `/api/chat` route handler + test (mock upstream: header preserved, stream passthrough, abort propagation, 401).
4. Chat page skeleton: partner resolution from query params (`type`, `id`, `session_id`, `tab` — keep URL contract so links/bookmarks from the old app port), `useChat` wiring, message rendering for text + sources + reasoning + files + tools.
5. History panel + session lifecycle (new, switch with mapper, rename, delete, feedback, title generation trigger).
6. Attachments (validation rules port: max count/size/formats, 5-concurrent queue is unnecessary if uploads go sequentially through the proxy; keep progress UX), web-search toggle, mentions (group chat), model switcher (default assistant).
7. Tool approval UI + context bar.
8. Dashboard chat route reusing the same feature components.

## Files/structure created (representative)
```
src/app/api/chat/route.ts
src/lib/chat/{types.ts, map-session.ts, transport.ts, use-preflight.ts}
src/components/ai-elements/*   (CLI-vendored, editable)
src/features/chat/{chat-view.tsx, history-panel.tsx, prompt-area.tsx, tool-approval.tsx, context-bar.tsx, attachments.tsx}
src/app/(app)/spaces/[spaceId]/chat/page.tsx
src/app/(app)/dashboard/[assistantId]/[[...sessionId]]/page.tsx
+ fixtures: captured v3 stream transcripts for tests
```

## VALIDATION GATE
1. `bun run check && bun run lint && bun run test` — green (mapper, route handler, preflight hook tests).
2. Backend: RB-2 golden-transcript test green in backend CI; `curl -N` against `/api/v1/conversations/?version=3` shows `x-vercel-ai-ui-message-stream: v1` and `[DONE]` framing.
3. Manual against dev backend, per partner type (default assistant, regular assistant, group chat):
   - Send a message → token-by-token streaming; references render as Sources; answer persists after reload (history mapper round-trip).
   - Attach an image + a PDF → both accepted, appear on the message, model receives them (vision answer references the image).
   - Group chat: `@mention` targets the named assistant; response label shows which assistant answered.
   - MCP tool with `require_tool_approval`: stream pauses, Confirmation renders, approve → tool runs and output part appears; repeat with deny; let one time out → part flips to timeout state.
   - Abort mid-stream → partial answer saved (visible after reload).
   - Context bar moves on typing (preflight) and after a turn (usage part); a deliberately huge paste disables send.
   - Rename, delete, feedback (+1 with text), auto-title on first exchange.
4. Side-by-side parity check with the Svelte app on the same assistant: same answer content/references for the same question (mock LLM makes this deterministic).
5. Old frontend regression: Svelte app chat (v2) still works against the same backend.

## Exit criteria
Chat is daily-drivable in web-next with the full capability list above; no bespoke SSE parsing code exists in the new app (the protocol lives behind `useChat`).

## Risks / unknowns
- The exact v6 tool-approval wire chunks must be verified against live docs before finalizing the RB-2 spec; the `data-tool-approval` fallback is fully specified so the phase cannot block on this.
- Long-lived SSE through the Next route handler (proxy buffering, devcontainer networking): validate early with a 60s+ generation; disable any proxy buffering in deployment configs (Phase 8 nginx notes).
- The mock-LLM E2E stack speaks v2 today; budget for teaching it v3 (overview OQ-6).
- Mapping historical messages with tool calls/references to parts may surface data oddities in old sessions; the mapper must be lenient (unknown fields → ignore, never throw).
