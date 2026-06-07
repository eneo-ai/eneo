# External Knowledge Provider Contract

This document specifies the contract an **external knowledge provider** must
implement to integrate with Eneo as a knowledge source. It is provider-agnostic:
nothing here is specific to any one vendor, and any implementation that satisfies
this contract can be plugged in by setting two environment variables. It exists so
that anyone building a provider (or an alternative to an existing one) has a single
authoritative reference.

A "knowledge source" in Eneo is a collection that lives in your provider. Eneo asks
you to create the collection, then registers the collection's MCP endpoint as a
space-scoped MCP server. From that point on, retrieval happens over the Model
Context Protocol (MCP) like any other tool-backed knowledge.

## Roles and direction of calls

There are three legs. Note that the direction flips between them: do not assume
Eneo is always the server.

| Leg | Caller | Callee | Protocol | Purpose |
| --- | --- | --- | --- | --- |
| 1. Provisioning | Eneo | **Provider** | HTTPS/JSON | Create a collection, obtain its MCP endpoint |
| 2. Retrieval | Eneo | **Provider** | MCP (Streamable HTTP) | Search/answer over the collection at chat time |
| 3. File access | **Provider** | Eneo | HTTPS | Fetch original uploaded file bytes (e.g. for the ingest tool) |

In Legs 1 and 2 the provider is the server and Eneo is the client. In Leg 3 the
provider is the client and Eneo is the server.

## Configuration (Eneo side)

The feature is inert unless both of these are set:

```bash
EXTERNAL_KNOWLEDGE_PROVIDER_URL=https://your-provider.example.com
EXTERNAL_KNOWLEDGE_PROVIDER_API_KEY=<provisioning-api-key>
```

`EXTERNAL_KNOWLEDGE_PROVIDER_URL` is the base URL of your provisioning API (Leg 1).
The URL must be reachable from the Eneo backend's network. When either value is
unset, knowledge-source creation returns a clear "no provider configured" error and
nothing is called.

## Credentials

Two distinct credentials are in play. Do not conflate them.

1. **Provisioning key** (`EXTERNAL_KNOWLEDGE_PROVIDER_API_KEY`): a single global key
   Eneo sends on every Leg 1 request as `Authorization: Bearer <key>`. It
   authenticates Eneo to your provisioning API.
2. **Per-collection MCP token**: a token your provider returns when a collection is
   created (see Leg 1). Eneo stores it encrypted and presents it as the bearer token
   on every Leg 2 (MCP) request to that collection's endpoint. Scope it to the single
   collection.

## Leg 1: Provisioning API (the provider implements this)

Base URL: `EXTERNAL_KNOWLEDGE_PROVIDER_URL`. Auth: `Authorization: Bearer <provisioning-key>`
on every request. All bodies and responses are JSON.

### `POST /api/collections`

Create a new collection.

Request body:

```json
{ "name": "Handbook" }
```

Response: a JSON object describing the collection and its MCP surface. Eneo reads
the fields below and accepts several key spellings for each, so camelCase or
snake_case both work. Return at least one spelling per field.

| Concept | Accepted keys | Required |
| --- | --- | --- |
| Collection id | `id`, `collectionId`, `collection_id` | recommended |
| Collection slug | `slug`, `collectionSlug`, `collection_slug` | recommended (needed for the fallback below) |
| MCP block | `mcp`, `mcpServer`, `mcp_server` (object) | yes (here or via the fallback) |
| MCP endpoint (inside the MCP block) | `endpoint`, `httpUrl`, `http_url`, `url` | yes |
| MCP token (inside the MCP block) | `token`, `accessToken`, `access_token` | recommended (omit only if the endpoint needs no auth) |
| Tools (inside the MCP block) | `tools` (array) | optional, informational only |

Example response:

```json
{
  "id": "col_abc123",
  "slug": "handbook",
  "mcp": {
    "endpoint": "https://your-provider.example.com/mcp/handbook",
    "token": "mcp_sk_live_xxxxxxxx"
  }
}
```

### `GET /api/collections/{slug}/mcp`

Return the MCP block for an existing collection (same shape as the `mcp` object
above). Eneo calls this **only as a fallback**: when the create response returned a
slug but no inline MCP endpoint. If your create response always inlines the MCP
block, this endpoint is still recommended for robustness but will rarely be hit.

### Requirements

- The create flow must yield an MCP endpoint, either inline in the create response
  or via the fallback `GET`. If neither produces one, Eneo aborts with an error and
  no knowledge source is created.
- **The MCP endpoint must be live at provision time.** Immediately after obtaining
  the endpoint, Eneo performs a real MCP handshake against it (initialize +
  tools/list) to validate the connection and discover tools. If that handshake
  fails, provisioning fails and nothing is persisted. Do not return an endpoint that
  is not yet ready to serve MCP requests.
- The `tools` array in the HTTP response is informational. Eneo's source of truth
  for tools is the live MCP `tools/list`, so you do not need to keep the HTTP
  response's tool list in sync.

There is deliberately **no file-ingest HTTP endpoint** here. File ingest is an MCP
tool on the collection's server (see Leg 2), not an Eneo-to-provider byte push.

## Leg 2: MCP server (the provider implements this)

The endpoint returned in Leg 1 must be a Model Context Protocol server, scoped to the
one collection, speaking the **Streamable HTTP** transport (MCP 2025-03-26 or later).

- Auth: Eneo sends `Authorization: Bearer <per-collection-mcp-token>` on every
  request. If you returned no token, the endpoint must accept unauthenticated calls
  (not recommended for anything beyond local development).
- Tools: expose whatever retrieval tools make sense (for example a search or
  question-answering tool over the collection). Eneo discovers them via `tools/list`
  and enables them in the space.
- Behave like a normal MCP server: support `initialize`, `tools/list`, and
  `tools/call`. Standard MCP error semantics apply.

At chat time, when the knowledge source is granted to an assistant, Eneo connects to
this endpoint as an MCP client and calls its tools.

### Ingest tool (how operator file ingest works)

File ingest is **a tool on this MCP server**, not a byte push from Eneo. Eneo never
uploads file bytes to the provider; it does not invent a parallel ingest API. Expose
a tool that takes signed download URLs, for example:

```
ingest_documents(urls: string[], ...)   # tool name and extra args are yours
```

The flow:

1. The operator attaches files in a chat with the assistant that has this knowledge
   source granted.
2. Eneo uploads each file to its own object store and surfaces a signed download URL
   per file to the model (the same file-reference mechanism every MCP tool gets, see
   Leg 3). The model receives one `{filename, mimetype, size_bytes, url}` entry per
   file. No special wiring per provider.
3. The model calls your `ingest_documents` tool with the collected URLs.
4. Your tool **fetches the bytes from each signed URL itself** (Leg 3, behind your
   SSRF guard) and ingests them durably into the collection.

So ingest reuses Legs 2 and 3 you already implement: a tool call plus a file fetch.
The collection is implicit (this MCP server is already scoped to one collection), so
the tool does not need a collection argument.

Eneo's create call (Leg 1) sends only `{ "name": ... }` and passes no ingest flag, so
enable the ingest tool on Eneo-provisioned collections by default rather than gating
it behind a per-collection parameter.

**Storage dependency + text fallback.** A signed URL only exists for files whose
original bytes live in Eneo object storage. Without object storage Eneo retains only
extracted text (no original to fetch), so there is no URL to pass. If you want to
support that configuration, also expose a text-ingest tool (for example
`capture_document(text, ...)`) that the model can call with the file's extracted text
that Eneo inlines into the prompt. The URL path is the primary, durable one; the text
path is a best-effort fallback.

## Leg 3: File access (provider calls Eneo)

Required if you support file ingest (the ingest tool fetches here); otherwise optional.


When Eneo invokes your MCP tools it can surface references to original uploaded
files so your tool can fetch the bytes itself. This is the mechanism the ingest tool
(Leg 2) uses. Two parts, both inherited from Eneo's general MCP integration (not
specific to knowledge sources):

### Identity headers

If the operator enables `forward_identity` on the knowledge source's MCP server,
Eneo sends the acting user's and tenant's identity on every Leg 2 request. Use these
for authorization or per-user scoping; never trust them as authentication on their
own.

| Header | Value |
| --- | --- |
| `X-Eneo-User-Id` | acting user UUID |
| `X-Eneo-User-Email` | acting user email |
| `X-Eneo-User-Name` | acting user display name |
| `X-Eneo-Tenant-Id` | tenant UUID |
| `X-Eneo-Tenant-Name` | tenant name |
| `X-Eneo-Role` | comma-separated role names |

Headers whose value is unavailable are omitted. Forwarding is off by default:
identity is PII egress to a third party, so it is opted into per server.

### Signed file-reference URLs

Eneo can hand your tool a pre-signed, time-limited download URL for an uploaded file:

```
GET {base}/api/v1/files/{file_id}/download/?token=<signed-token>
```

- `base` is Eneo's tool-facing origin (`FILE_REFERENCE_BASE_URL`, falling back to the
  public origin). It must be reachable from your provider's network, which may differ
  from the browser-facing origin.
- No `Authorization` header is needed: the token in the query string authorizes the
  download.
- Supports HTTP `Range` requests (returns `206 Partial Content`).
- The token expires (`401` afterward) and is bound to the tenant (`403` on
  cross-tenant replay). Treat the URL as a short-lived secret.

## Conformance checklist

A minimal conforming provider:

- [ ] Accepts `Authorization: Bearer` with the provisioning key on Leg 1.
- [ ] `POST /api/collections` creates a collection and returns an MCP endpoint
      (inline or resolvable via `GET /api/collections/{slug}/mcp`).
- [ ] Returns a per-collection MCP token (or documents that the endpoint is
      unauthenticated).
- [ ] The MCP endpoint is live and passes an MCP handshake the moment it is returned.
- [ ] The MCP server speaks Streamable HTTP and exposes at least one retrieval tool.
- [ ] (For file ingest) Exposes an ingest tool that takes signed file URLs
      (e.g. `ingest_documents(urls)`) and fetches the bytes itself, SSRF-guarded.
- [ ] (Optional) Reads `X-Eneo-*` identity headers when present.

## Reference: end-to-end happy path

Configuration happens in edit mode; content (ingest) and retrieval happen in normal
chat once the source is granted.

1. Operator, in assistant edit mode, says "create a knowledge source called Handbook
   and give it to this assistant."
2. Eneo: `POST {provider}/api/collections {"name":"Handbook"}` with the provisioning key.
3. Provider returns `{slug, mcp:{endpoint, token}}`.
4. Eneo runs an MCP handshake against `endpoint`, discovers tools, registers it as a
   space-scoped MCP server (bearer = `token`), enables it in the space, and grants it
   to the assistant.
5. Operator turns off edit mode, attaches files in normal chat, and says "add these to
   Handbook."
6. Eneo surfaces a signed download URL per file to the model; the model calls the
   provider's `ingest_documents` tool with the URLs; the provider fetches and ingests.
7. Retrieval: the model calls the provider's search/answer tools over the collection,
   optionally with `X-Eneo-*` identity headers.
