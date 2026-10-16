# Chat stream contract (conversation API version 3)

The React app (web-next) receives chat answers as a Vercel AI SDK
**UI Message Stream**. This document is the shared contract between the
backend encoder and the client, derived from the code as it is; where the
code was ambiguous it was changed and the change is called out.

| Side     | Code                                                                                                                                  |
| -------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| Backend  | `backend/src/eneo/conversations/ui_message_stream.py` (used by `conversations_router.chat` when `version=3` and `stream=true`)        |
| Proxy    | `src/app/api/chat/route.ts` (adds the bearer token, relays the SSE body untouched)                                                    |
| Client   | `src/lib/chat/transport.ts`, `types.ts`, `map-session.ts`; consumed by `useChat` in `src/features/chat/chat-view.tsx`                 |
| Fixtures | `backend/tests/fixtures/ui_message_stream/*.json` (shared by both test suites, see [Fixtures](#fixtures))                             |
| Tests    | `backend/tests/unittests/conversations/test_ui_message_stream*.py`, `src/lib/chat/contract.test.ts`, `src/lib/chat/transport.test.ts` |

## Pinned SDK versions

`frontend/apps/web-next/package.json` pins exact versions (no caret):

- `ai` **6.0.291**
- `@ai-sdk/react` **3.0.294**

Every statement below about client behaviour ("the SDK throws…", "status
becomes…") was verified against these versions. See
[Bumping the SDK](#bumping-the-sdk) before changing them.

## Transport

- Client → `POST /api/chat` (same origin, Next route handler) →
  `POST {ENEO_BACKEND_URL}/api/v1/conversations/?version=3` with
  `Authorization: Bearer <token>`, `Accept: text/event-stream`. The proxy
  passes the upstream status and the `content-type`,
  `x-vercel-ai-ui-message-stream` and `x-trace-id` headers through, and
  propagates the client's abort to the upstream fetch.
- Response: `200`, `content-type: text/event-stream`, marker header
  `x-vercel-ai-ui-message-stream: v1`. **Data-only SSE**: every event is one
  `data: <json>` line; the last event is `data: [DONE]`. The server sends a
  comment line (`: ping - …`) every 15 s while idle (for example while an
  approval is pending); the SDK parser ignores comments.
- A non-2xx response carries a JSON body (`{"message": …, "eneo_error_code": …}`
  from the backend, `{"message": "Not authenticated"}` from the proxy). The
  SDK turns it into a failed request (`status: "error"`, `error.message` =
  response text) without opening a stream.

### Request body (`ConversationBody`, `types.ts`)

The backend owns the history: only the **latest question** is sent, never
the message array. `transport.ts` builds the body from the last user
message's text parts (joined with `\n`) and the per-send options
`sendMessage(…, { body })` provides.

| Field                     | Type                                       | Notes                                                                                       |
| ------------------------- | ------------------------------------------ | ------------------------------------------------------------------------------------------- |
| `question`                | `string`                                   | The user's text.                                                                            |
| `stream`                  | `true`                                     | Always `true` on this path.                                                                 |
| `files`                   | `{ id: string }[]`                         | Uploaded attachment ids (defaults to `[]`).                                                 |
| `session_id`              | `string \| null`                           | Continue a conversation.                                                                    |
| `assistant_id`            | `string \| null`                           | Start one with an assistant (also the personal/default assistant).                          |
| `group_chat_id`           | `string \| null`                           | Start one with a group chat.                                                                |
| `tools`                   | `{ assistants: { id, handle }[] } \| null` | @mention of a group-chat member.                                                            |
| `disabled_capabilities`   | `CapabilityPurpose[]`                      | Capabilities the user turned off for this message.                                          |
| `disabled_mcp_server_ids` | `string[]`                                 | MCP servers the user turned off; can never enable one.                                      |
| `require_tool_approval`   | `boolean`                                  | Ask before running MCP tools. Requires `stream: true`; rejected with `400` for group chats. |

Exactly one of `session_id`, `assistant_id`, `group_chat_id` identifies the
target (backend `ConversationRequest`).

## Stream parts

All parts are JSON objects with a `type` discriminator. Fields marked
_eneo_ are Eneo-specific payloads carried inside the SDK's extension points
(`providerMetadata.eneo` or custom `data-*` parts). Every part the backend
emits is listed; the SDK rejects anything else (see
[Failures](#what-the-client-treats-as-failure)).

### Lifecycle

| Part     | Fields      | Notes                                                                                                                                                                                                                                         |
| -------- | ----------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `start`  | `messageId` | First part. `messageId` is the **question id** (the persisted `Message.id`), so the live assistant message gets the id history will use. Falls back to a random uuid only if the backend has no question id (it always has one on this path). |
| `finish` | —           | Last part before `[DONE]`. No `finishReason` is sent.                                                                                                                                                                                         |
| `error`  | `errorText` | Provider/stream failure. Always preceded by `data-error`; see [Terminal states](#terminal-states). `errorText` may be empty; the UI then shows its generic message.                                                                           |

### `data-session` (eneo)

Emitted once, right after `start`; replaces the v2 `first_chunk`. Not
transient, so it lands in `message.parts` (first part of every live answer).

```json
{
  "type": "data-session",
  "data": {
    "session_id": "<uuid>",
    "completion_model": {/* CompletionModelPublic (OpenAPI), or null */},
    "files": [/* FilePublic[] — the question's uploaded attachments */],
    "web_search_references": [],
    "mcp_tool_references": [/* McpToolReferencePublic[] known at start (usually []) */],
    "answering_assistant": { "id": "<uuid>", "handle": "…" } /* group chats; else null */
  }
}
```

The client reads `session_id` (to continue the conversation and to enable
title generation), `answering_assistant`, and `completion_model.{id,name,nickname,token_limit}`.

### Text and reasoning

| Part              | Fields        | Notes                                                      |
| ----------------- | ------------- | ---------------------------------------------------------- |
| `reasoning-start` | `id`          | `id` = `reasoning-N`, N counting from 0 per answer.        |
| `reasoning-delta` | `id`, `delta` |                                                            |
| `reasoning-end`   | `id`          |                                                            |
| `text-start`      | `id`          | `id` = `text-N`.                                           |
| `text-delta`      | `id`, `delta` | One delta per provider token (the UI throttles rendering). |
| `text-end`        | `id`          |                                                            |

A **part** is one contiguous block. Reasoning precedes the answer within a
model round; opening text closes an open reasoning part and vice versa. A
later round (after a tool call) that starts with text or reasoning opens a
new part (`text-1`, `reasoning-1`, …); the paragraph break the adapter puts
in front of a later round is dropped when it would start a new part and kept
when it continues the current one. The SDK projects each part to
`{ type: "text", text, state }` / `{ type: "reasoning", id, text, state }`
with `state: "streaming"` until the matching `-end` sets `"done"`.

### `source-document` (citations)

```json
{
  "type": "source-document",
  "sourceId": "<info blob id>",
  "mediaType": "text/plain",
  "title": "…",
  "providerMetadata": { "eneo": {/* InfoBlobAskAssistantPublic */} }
}
```

Emitted for references retrieved **before** generation (right after
`data-session`) and for references found while answering (right after the
`text-delta` that carried them). Each `sourceId` is emitted **once** per
stream. The SDK keeps it as a `source-document` part in stream order
(`filename` is absent).

### `file` (generated files)

```json
{
  "type": "file",
  "url": "<base>/api/v1/files/<id>/download/?token=<signed>",
  "mediaType": "image/png",
  "filename": "generated.png",
  "providerMetadata": { "eneo": {/* FilePublic */} }
}
```

`url` is a signed inline-download link valid for 24 h. The pinned SDK keeps
only `mediaType`, `url` and `providerMetadata` on the part — **`filename` is
dropped**, so read the name from `providerMetadata.eneo.name`. The file part
may arrive while a text part is still open.

### Tool calls (`dynamic-tool` parts)

The backend streams **status snapshots** of MCP tool calls, never tool
results. All tool parts carry `dynamic: true`, `toolCallId` and
`providerMetadata.eneo`:

```json
"providerMetadata": { "eneo": {
  "server_name": "files", "title": "Read a file", "purpose": null,
  "is_internal": true
} }
```

`purpose` names the capability a provider serves (`"web_search"`,
`"image_generation"`) or is null. `is_internal` (`true`/`false`/`null`)
says whether the call ran on one of Eneo's own servers, stamped by the
server the call was **routed** to — never inferred from `server_name`,
which an admin may set to "files" or "knowledge" on an external server.
`null` means the backend did not know (older rows).

| Part                    | Extra fields                        | Emitted when `result_status` is                           |
| ----------------------- | ----------------------------------- | --------------------------------------------------------- |
| `tool-input-available`  | `toolName`, `input` (arguments)     | Always first for a call, whatever its status (see below). |
| `tool-output-available` | `output: { "status": "succeeded" }` | `succeeded`                                               |
| `tool-output-error`     | `errorText: <result_status>`        | `failed`, `denied`, `timeout_denied`                      |

Rules:

- `toolCallId` is the provider's tool call id. A snapshot entry without one
  gets a generated uuid that stays stable for its position in the list.
- Each `(toolCallId, part type)` pair is emitted **once**; repeated
  snapshots add nothing.
- `tool-input-available` **always precedes** an output part for the same
  id. The SDK throws (`No tool invocation found…`) for an output it has not
  seen the input of; before this contract a denied approval produced exactly
  that, because a denied call's first snapshot is already terminal. The
  encoder now announces the input first (**backend change**).
- `result_status: "approved"` (the call was approved and is about to run) is
  an input-phase status: only `tool-input-available` is emitted for it.
- The SDK projects the call to one `dynamic-tool` part updated in place:
  `state` is `input-available` → `output-available` | `output-error`;
  `callProviderMetadata` holds the metadata from the input part,
  `resultProviderMetadata` the one from the output part.

The client never executes tools: `useChat` has no `onToolCall`, and the
transport never adds tool outputs (`addToolOutput`,
`addToolApprovalResponse`) or resubmits (`sendAutomaticallyWhen` is unset).
The SDK's own `tool-approval-request` part is **not used**.

### `data-mcp-tool-references` (eneo)

```json
{
  "type": "data-mcp-tool-references",
  "data": {
    "mcp_tool_references": [
      {
        "id": "<uuid>",
        "uri": "mcp://…",
        "mime_type": "text/markdown",
        "content": "…",
        "meta": {},
        "tool_call_id": "call-1",
        "mcp_tool_name": "files__read_file"
      }
    ]
  }
}
```

MCP resource citations produced by a tool call; emitted with the snapshot
that carries them, before that snapshot's tool parts. Not transient (one
part per batch, no id).

### `data-tool-approval` (eneo) — see [Tool approval](#tool-approval)

```json
{ "type": "data-tool-approval", "id": "<approval_id>", "data": {
  "approval_id": "<approval_id>",
  "status": "pending" | "approved" | "denied" | "timeout_denied",
  "tools": [ { "server_name", "tool_name", "arguments", "tool_call_id",
               "approved": true | false | null, "result_status": …, "is_internal": … } ] } }
```

`id` = `approval_id`, so every update **replaces the same part in place**.

### `data-token-usage` (eneo, transient)

```json
{
  "type": "data-token-usage",
  "transient": true,
  "data": { "prompt_tokens": 12, "completion_tokens": 3, "turn_tokens": 15 }
}
```

Delivered to `onData` only; never stored in `message.parts`. Arrives after
the answer text (the text part may still be open).

### `data-error` (eneo, transient)

```json
{ "type": "data-error", "transient": true, "data": { "code": 503 } }
```

Numeric Eneo error code for the UI's message lookup. Always immediately
followed by `error`.

## Ids

| Id                     | Live stream                                                 | Persisted turn (`map-session.ts`)                                                          |
| ---------------------- | ----------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| Assistant message      | `start.messageId` = question id                             | `Message.id` (same value)                                                                  |
| User message           | Generated by the SDK (`generateId`)                         | `${Message.id}-q`                                                                          |
| Text / reasoning parts | `text-N` / `reasoning-N` (reasoning keeps `id` on its part) | No ids (one `reasoning` part, one `text` part)                                             |
| Tool call              | `toolCallId` = provider id or generated uuid                | `tool_call_id`, else `${Message.id}-tool-<part index>`                                     |
| Source                 | `sourceId` = info blob id                                   | `reference.id`                                                                             |
| Approval               | `data-tool-approval.id` = `approval_id`                     | Not reconstructed (`providerMetadata.eneo.approved` on the tool part records the decision) |

Consequences: after a reload the assistant message keeps its id; the user
message id changes (random → `-q`); `data-session`, `data-mcp-tool-references`
and `data-tool-approval` parts do not exist in history (the equivalent data
is on `message.metadata`: `mcpToolReferences`, `generatedFiles`,
`answeringAssistant`, `tokens`, `completionModel`); generated files are
`file` parts live but `metadata.generatedFiles` in history.

Persisted tool parts map `result_status` to `state: "output-available"`
(`succeeded` or missing) or `"output-error"` with `errorText = result_status`,
`output: { status }`, and carry `server_name`, `title`, `purpose`,
`is_internal` and `approved` in `providerMetadata.eneo`.

## Ordering guarantees

1. `start`, then `data-session`.
2. Pre-retrieved `source-document` parts (deduplicated).
3. The body, in completion order:
   - text and reasoning as described above; a `source-document` follows the
     delta that cited it;
   - for a tool-call snapshot: approval decisions (`data-tool-approval`
     updates), then `data-mcp-tool-references`, then the tool parts (input
     before output per call);
   - `data-tool-approval` (`pending`, `timeout_denied`) at the moment the
     backend pauses / gives up;
   - `file` parts where the adapter produced them;
   - `data-token-usage` after the final text of the turn.
4. Open reasoning/text parts are closed (`reasoning-end`, `text-end`).
5. `finish`, then `[DONE]`.

On an `ERROR` completion the encoder emits `data-error`, `error`, then still
closes open parts and sends `finish` + `[DONE]` so the SSE stream is
well-formed for any consumer; the SDK **stops at `error`** and never applies
what follows.

## Terminal states

What `useChat` ends in, verified against the pinned versions:

| Stream ends with                                                | `status` | `error`                     | `onFinish`                                            | Message                                                                                                                                                                             |
| --------------------------------------------------------------- | -------- | --------------------------- | ----------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `finish` (+ `[DONE]`)                                           | `ready`  | `undefined`                 | `isError: false, isAbort: false`                      | Complete; parts `done`.                                                                                                                                                             |
| `error` part                                                    | `error`  | `Error(errorText)`          | `isError: true` (after `onError`)                     | Kept as far as it got; open text parts stay `state: "streaming"`. `data-error.code` reached `onData` just before.                                                                   |
| User `stop()` (fetch aborted)                                   | `ready`  | `undefined`                 | `isAbort: true, isError: false`; `onError` not called | Partial answer stays on screen. The backend sees the disconnect, stops generating and persists the partial answer/reasoning in the background.                                      |
| Connection closed without a terminal part                       | `error`  | `StreamContractError`       | `isError: true`                                       | Partial, never shown as finished. **Client change**: the SDK alone would report `ready`; `transport.ts` wraps the stream and fails it when it closes without `finish`/`error`.      |
| `[DONE]` without `finish`                                       | `error`  | `StreamContractError`       | `isError: true`                                       | `[DONE]` is framing, not a terminal part.                                                                                                                                           |
| Invalid JSON event, unknown part type, part for an unstarted id | `error`  | SDK parse/validation error  | `isError: true`                                       | Partial.                                                                                                                                                                            |
| Unknown `data-*` part                                           | `error`  | `StreamContractError`       | `isError: true`                                       | **Client change**: the SDK would append it silently; the transport allows only the five `data-*` types above (`DATA_PART_TYPES`). Add a part type on both sides, fixtures included. |
| Non-2xx response                                                | `error`  | `Error(response body text)` | `isError: true`                                       | No assistant message.                                                                                                                                                               |

Cancel semantics decided here: **a cancel is only ever initiated by the
client** (`stop()`); the backend has no "abort" part and a server-side
interruption is a failure. The SDK never retries or resubmits on any of
these outcomes (`sendAutomaticallyWhen` unset; `onFinish` is informational).
"Försök igen" is an explicit new `sendMessage` by the user.

`onData` receives the live chunk object. For a part reconciled by id the
first chunk becomes the part and its `data` is overwritten on each update,
so read what you need synchronously (as `chat-view.tsx` does).

## Tool approval

Approval is an Eneo flow over the open stream; the SDK's tool-approval
machinery is not involved. `useChat` sees only `data-tool-approval` parts
and ordinary tool parts.

1. The request carries `require_tool_approval: true` (and `stream: true`;
   group chats are rejected with `400`).
2. When the model calls MCP tools that need approval the backend registers
   an `approval_id` (uuid, Redis, TTL `mcp_tool_approval_ttl_seconds`, 305 s
   by default) and emits `data-tool-approval` with `status: "pending"`,
   `approved: null` per tool. The stream **stays open**, kept alive by the
   15 s ping comments, while the backend waits up to
   `mcp_tool_approval_timeout_seconds` (300 s by default).
3. The UI decides through the existing endpoint — never through the SDK:
   `POST /api/v1/conversations/approve-tools/?approval_id=<id>` with body
   `[{ "tool_call_id": "…", "approved": true|false }, …]`. Partial lists are
   accepted (`decisions_remaining` in the response); the wait ends once
   every call has a decision; omitted calls count as rejected when the
   request is finalized. Responses: `200` `ToolApprovalResponse`, `404`
   unknown/expired, `403` not the owner, `409` already decided differently,
   `429` more than 20 submissions per minute.
4. The backend resumes on the same stream with the decision snapshot, which
   the encoder turns into (**backend change**: the decision used to be
   visible only through the tool parts):

   | Outcome                           | `data-tool-approval.status` | Per tool                                                     | Then                                                                                                                                                             |
   | --------------------------------- | --------------------------- | ------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
   | Pending                           | `pending`                   | `approved: null`, `result_status: null`                      | Stream idle (pings).                                                                                                                                             |
   | At least one call approved        | `approved`                  | `approved: true/false`, `result_status: "approved"/"denied"` | `tool-input-available` for every call; approved ones run (`tool-output-available` / `tool-output-error "failed"`), denied ones get `tool-output-error "denied"`. |
   | Every call denied                 | `denied`                    | `approved: false`, `result_status: "denied"`                 | `tool-input-available` + `tool-output-error "denied"` per call; the model continues without the tools.                                                           |
   | Nobody decided within the timeout | `timeout_denied`            | `approved: false`, `result_status: "timeout_denied"`         | `tool-input-available` + `tool-output-error "timeout_denied"` per call; the approval is deleted server-side (`404` on a late decision).                          |

   The approval-level status summarizes; the per-tool `approved` flags are
   authoritative for mixed decisions.

5. The turn then finishes normally (`finish`). An approval never fails the
   request by itself.

Several approvals can occur in one turn (one part each, distinct ids).

## What the client treats as failure

Never shown as a finished answer (`status: "error"`, `onFinish.isError`):

- the stream closes (EOF) before a `finish` or `error` part — including a
  `[DONE]` line without `finish`;
- an event whose `data:` is not valid JSON;
- a part whose `type` the SDK schema does not know, or a known type with
  missing required fields;
- a `data-*` part not in `DATA_PART_TYPES`;
- a delta/end for a text or reasoning id that was never started, or an
  output for a tool call that was never announced;
- an `error` part, even when `finish` follows it;
- a non-2xx response.

Only the user's own `stop()` ends a stream early without failure.

## Fixtures

`backend/tests/fixtures/ui_message_stream/<name>.json`, one representative
turn each:

| Fixture                  | Ends with | Shows                                                                |
| ------------------------ | --------- | -------------------------------------------------------------------- |
| `plain-text`             | `finish`  | Text + token usage (transient part).                                 |
| `reasoning-and-text`     | `finish`  | Reasoning part before the text part.                                 |
| `tool-call-with-output`  | `finish`  | Tool input → MCP references → output.                                |
| `tool-failure`           | `finish`  | `tool-output-error "failed"`; the turn still finishes.               |
| `tool-approval-approved` | `finish`  | `pending` → `approved` (same part id) → call runs.                   |
| `tool-approval-denied`   | `finish`  | `pending` → `denied` → input + `tool-output-error "denied"`.         |
| `tool-approval-timeout`  | `finish`  | `pending` → `timeout_denied` → `tool-output-error "timeout_denied"`. |
| `file-part`              | `finish`  | Generated image with a signed url (token pinned to `fixture-token`). |
| `sources`                | `finish`  | Pre-retrieved and in-stream citations, deduplicated.                 |
| `cancelled-mid-stream`   | truncated | The prefix a cancelled client saw: no `finish`, no `[DONE]`.         |
| `backend-error`          | `error`   | Partial text, `data-error` + `error`, then the trailing close.       |

File format:

```json
{
  "name": "plain-text",
  "description": "…",
  "terminal": "finish" | "error" | "truncated",
  "events": [ /* the exact JSON payloads, in order; [DONE] is implied unless truncated */ ],
  "ui": {
    "status": "ready" | "error",
    "error": { "message": "…", "code": 503 },      // error fixtures only
    "message": { "id": "<question id>", "role": "assistant", "parts": [ /* SDK projection */ ] }
  }
}
```

`events` is asserted by the backend
(`test_ui_message_stream_fixtures.py`: the scripted `Completion` stream for
each scenario must encode to exactly these events; a truncated fixture must
be a strict prefix). `ui` is asserted by web-next (`contract.test.ts`: the
events, framed as SSE and fetched through `createChatTransport()` into the
SDK's `Chat`, must settle with that status and exactly those parts;
`cancelled-mid-stream` is additionally driven as a user abort).
`transport.test.ts` covers the malformed/interrupted cases.

The `data-session.completion_model` in the fixtures is the complete
`CompletionModelPublic` dump: adding a field to that model changes every
fixture (regenerate, below).

## Bumping the SDK

1. Change both pins in `frontend/apps/web-next/package.json` to the new
   exact versions (keep `ai` and `@ai-sdk/react` compatible: `@ai-sdk/react`
   depends on an exact `ai` version — check `bun.lock` after install).
2. `cd frontend && bun install`, then `bun install --frozen-lockfile` must pass.
3. Run the client suite: `cd frontend/apps/web-next && bun run check && bun run test src/lib/chat`.
   A changed projection (new or renamed part fields, different
   `state`/metadata handling, new terminal behaviour) shows up as a
   `contract.test.ts` diff against a fixture's `ui.message.parts` or
   `ui.status`. Read the SDK change, then update this document and the
   fixture's `ui` section by hand — never by copying the new output blindly.
   `transport.test.ts` failures mean the failure semantics changed; fix
   `transport.ts` so every case in [Failures](#what-the-client-treats-as-failure) still fails.
4. Run the backend suite (unchanged by an SDK bump, but it proves the
   fixtures still match the encoder):
   `cd backend && <export the env: block of .github/workflows/ci.yml> && .venv/bin/python -m pytest -q tests/unittests/conversations -p no:cacheprovider`.
5. If a part the backend emits is no longer accepted by the SDK, change the
   encoder, regenerate the fixtures' `events` with
   `UPDATE_STREAM_FIXTURES=1` in front of the pytest command (it rewrites
   `events` in place and keeps the truncated fixture's cut point), update
   the `ui` sections, rerun both suites and update this document.

Changing the contract from the backend side follows the same path from
step 4: encoder → `UPDATE_STREAM_FIXTURES=1` → `ui` sections and
`types.ts`/`transport.ts` (`DATA_PART_TYPES` for a new `data-*` part) →
both suites → this document.
