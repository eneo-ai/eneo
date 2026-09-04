# Capabilities (web search, image generation)

**Status:** ✅ v1
**Audience:** Tenant administrators configuring providers, operators tuning limits, developers extending the capability set

Eneo has no built-in search engine or image generator. Each *capability* is served by an MCP server the tenant administrator registers and activates. Assistants and spaces turn a capability on or off; which provider actually serves a user is decided at ask time.

---

## 1. Concepts

| Term | Meaning |
|------|---------|
| **Capability purpose** | The `purpose` of an MCP server: `general` (ordinary tools) or a capability, currently `web_search` and `image_generation`. |
| **Provider** | An MCP server with a capability purpose. Registered under **Admin → MCP servers** like any other server, but activated rather than enabled. |
| **Marker** | A capability server attached to a space or assistant. It requests the capability; it does not pin the provider. |
| **Resolution** | At ask time every marker is replaced by the provider that serves the current user (see §3). Switching providers never requires editing spaces or assistants. |

Only one marker per capability can be attached to a space or assistant.

## 2. Administering providers

1. Create the server under **Admin → MCP servers**: use **Set up …** on the capability's card at the top of the page (it opens the dialog with **Used for** preset, and image generation on the built-in source), or add a server from the header and set **Used for** yourself. Capability servers are saved inactive.
2. Sync and approve its tools.
3. Activate it. Activation is atomic: activating a default provider deactivates the previous default for the same capability.

Changing a server's purpose re-homes it. Moving a general server into a capability keeps its space and assistant attachments as markers. Moving a provider back to general detaches it everywhere, because markers were admitted without the space classification check that general servers get.

### Audience

| Audience | Behaviour |
|----------|-----------|
| **Everyone** (default) | The tenant's default provider. At most one active per capability. |
| **User groups** | Serves members of the selected groups. Any number may be active alongside the default. When a user matches several, the lowest **priority** number wins, then the name. |

An active default cannot be narrowed to user groups in place. Deactivate it first, or activate another default.

### Built-in image provider

Image generation does not need an external MCP server. In the server dialog, set **Used for** to image generation and **Source** to *Built-in, via a model provider*. Pick one of the tenant's active model providers (**Admin → Models**) and enter the image model or deployment name, for example `gpt-image-1` on OpenAI or Azure OpenAI, or `imagen-4.0-generate-001` on Gemini. Default size and quality are optional; the assistant may override them per request.

Under the hood the row is an ordinary provider whose endpoint is Eneo's own loopback MCP server (`/internal-mcp/image_generation`) and whose auth type is `internal`. It carries no credentials: on every request the ask path mints a short-lived token naming the provider row, and the loopback tool calls the model through LiteLLM with the credentials stored on the selected model provider. Activation, audiences, permissions and classification work exactly as for external providers, and its tool is approved automatically on sync because it is Eneo's own code. Switching an existing external server to the built-in source replaces its tool catalog with the loopback's tools in the same save, so no manual sync is needed. Web search has no built-in provider.

The backend must be able to reach its own loopback URL (`INTERNAL_MCP_BASE_URL`, the same requirement as the knowledge and files servers).

## 3. Ask-time resolution

For each capability an assistant requests, the provider is attached only when all of these hold:

- the user's role grants the capability permission (`web_search` or `image_generation`; roles can be edited under **Admin → Roles**);
- a provider serves the user: a group-targeted provider covering one of their groups, else the tenant default;
- the provider has at least one enabled, approved tool;
- the provider's security classification meets the space's classification;
- the completion model supports tool calling.

Otherwise the capability is silently unavailable for that turn. Service API keys can use web search but not image generation: a generated image is stored as a file owned by a user, and a service key has no user.

Users can switch a capability off for a single conversation from the toolbar popover.

## 4. Generated images

An MCP `image` content block returned by any tool becomes a generated file shown in the chat. Before persistence the proxy applies these guards:

| Setting | Default | Effect |
|---------|---------|--------|
| `MCP_TOOL_IMAGE_MAX_BYTES` | 10485760 | Decoded size cap per image; larger images are dropped with a notice to the model. |
| `MCP_TOOL_IMAGE_MAX_COUNT` | 4 | Images admitted per tool result; the rest are dropped with one notice. |
| `MCP_TOOL_OUTPUT_MAX_CHARS` | 32768 | Text budget per tool result. Images do not count against it. |

Only `image/png`, `image/jpeg`, `image/webp` and `image/gif` are accepted. The model sees a short placeholder instead of the bytes. Only the latest turn's generated images are replayed to the model on follow-ups; older ones are described by the placeholder in their tool result. Generated files are deleted with their conversation.

## 5. Extending the capability set

Adding a capability is one entry in `CAPABILITY_PURPOSES` (backend entity module), one permission value equal to the purpose, one descriptor in the frontend `capabilities.ts` module with its messages, and a migration granting the permission to existing roles. All admin, space, assistant and chat surfaces render from those lists.
