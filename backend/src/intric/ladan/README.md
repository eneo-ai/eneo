# ladan — external service integration

This package wraps eneo's integration with **Ladan**, a separate Next.js
service that hosts collections, file ingestion, and paired MCP servers
for semantic search. Ladan is single-tenant; eneo proxies all calls on
behalf of its users with a single API key, and enforces tenant + space
isolation inside eneo via the `knowledge_sources` ownership table.

## Layout

| File | Role |
|---|---|
| `client.py` | `LadanClient` — httpx wrapper for the admin API + per-MCP runtime. Owns URL rewriting for devcontainer reachability. |
| `service.py` | `KnowledgeSourceService` — create / list / delete knowledge sources, plus file upload / list / delete on a source. Orchestrates the proxy + the matching space-scoped MCP server row. |
| `table.py` | `KnowledgeSources` SQLAlchemy ownership table. |
| `models.py` | Pydantic DTOs for the router. |
| `router.py` | FastAPI `APIRouter` with the 5 endpoints — registered conditionally by `server/routers.py` based on `is_enabled()`. |
| `feature_flag.py` | Single `is_enabled()` check based on the three env settings. |

## Disabling the integration

Unset either `LADAN_URL` or `LADAN_API_KEY` in your `.env`. Effects:

1. `is_enabled()` returns `False`.
2. `server/routers.py` skips `include_router(ladan.router, ...)`,
   so the `/spaces/{id}/knowledge-sources/...` endpoints are simply absent.
3. The DI container's `ladan_client` provider returns `None`;
   service methods that depend on it raise `BadRequestException` if
   reached through any other path.

The rest of eneo (tenant-curated MCP catalog, internal collections,
websites, integrations) is unaffected.

## What this integration is NOT

- It is **not** the place to put generic external file storage logic.
  `file_storage_uploader.py` (one level up) handles
  per-chat-session uploads to whatever URL `FILE_STORAGE_URL` points at —
  the same Ladan instance today, but the API is generic on purpose
  (POST bytes, get a URL back).
- It does **not** introduce a "knowledge backend kind" discriminator. The
  resulting MCP server in eneo's catalog is just a space-scoped MCP server
  like any other; downstream code paths (assistant editor, MCP proxy,
  chat) do not branch on its origin.

## Cross-repo coordination

The companion plan for Ladan lives at
`/Users/alexander/code/ladan/.claude/plans/integration-with-eneo.md`.
That side defines:

- `POST /api/collections {slug, name, embeddingModelId}` →
  `{collection, mcpServer: {mcpEndpoint, mcpBearerToken, ...}}`
- `DELETE /api/collections/{slug}` (cascades to paired MCP)
- `POST /api/collections/{slug}/files` (multipart) + `GET` / per-id `DELETE`
- The paired MCP server's runtime: `POST /mcp/{slug}` with the bearer
