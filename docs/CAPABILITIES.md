# Capabilities (web search, image generation)

**Status:** provider-independent capability configuration
**Audience:** Tenant administrators configuring providers, operators tuning limits, developers extending the capability set

Capabilities are functions an assistant can use: **Webbsökning** and
**Bildgenerering**. Image generation can run through a configured image model
or an external MCP server; web search uses an external server.

## 1. Configuration and navigation

Open **Admin → Verktyg** (/admin/tools). **Funktioner** is the default tab.
Each function keeps its source identity, configuration status and activation
action visible. The source's ellipsis menu contains **Ändra** and **Ta bort**;
deletion still requires confirmation. Use the arrow beside the source to expand
its tools, including read-only tool details for built-in image models.
Saved inactive sources can be activated; active sources can be disabled; blocked
sources show why they cannot currently serve requests. Group-specific sources
appear beneath the tenant default.

The **MCP-servrar** tab appears first and lists ordinary external tool connections
by default. Select **Visa funktionsservrar** to also show external connections
providing a function. Authentication, tool discovery, approval and connection
controls remain available for these connections. The connection form's **Funktion**
selection distinguishes **Allmänna verktyg** from function sources. Internal image-model providers appear only under
Funktioner. The former /admin/mcp-servers URL redirects to this tab.

For image generation, choose **Bildmodell** or **Extern MCP-server**. The model
picker lists enabled, current models on active providers. A saved model that
becomes invalid stays visible with its blocking reason. **Lägg till bildmodell**
opens the existing model wizard and selects the created model on return.
Credentials, pricing, defaults and classification remain in **Modeller**.

**Spara och aktivera** saves and activates a model-backed source in one
transaction. External connections are saved inactive; review and approve any
pending tools, then activate. A failed activation leaves the saved connection
available for repair/retry. Prepare replacements as separate sources: the
activation action identifies the default that will be replaced.

## 2. Saved intent and provider lifecycle

Spaces and assistants store enabled_capabilities, a list of purposes
(web_search, image_generation). Governance policies store purposes with
is_default_enabled. These rows reference their owner, never a provider.
They remain intact when a provider is switched, disabled or deleted—even
when the last provider disappears. A replacement restores availability.

Omitting enabled_capabilities on updates preserves selections; [] clears
them. Turning a function off always works. Newly enabling a function requires
an eligible source and the applicable space/classification rules. Temporary
unavailability does not prevent unrelated edits.

Activation rechecks tenant ownership, enabled/current image model, active
model provider, usable approved tools and connection validation before
changing the default. A failed validation or transaction keeps the previous
default active. Stored readiness describes configuration; it is **not** a
claim of live health for an external server.

### Audience

| Audience | Behaviour |
|----------|-----------|
| **Everyone** (default) | The tenant's default provider. At most one active per capability. |
| **User groups** | Serves members of the selected groups. Any number may be active alongside the default. When a user matches several, the lowest **priority** number wins, then the name. |

An active default cannot be narrowed to user groups in place. Deactivate it first, or activate another default.

### Built-in image provider

Image generation does not need an external MCP server. First add the image model under **Admin → Models → Image models**: pick the model provider and enter the model name the provider serves, for example `gpt-image-1` on OpenAI or Azure OpenAI, `imagen-4.0-generate-001` on Gemini, or whatever name a vLLM or other OpenAI-compatible endpoint exposes on its `/v1/images/generations` route. Default size and quality, cost per image and the security classification live on the model, like on any other catalog model. Alternatively, add the model directly from the function configuration wizard. Select it under **Verktyg → Funktioner → Bildgenerering**.

Under the hood the row is an ordinary provider whose endpoint is Eneo's own loopback MCP server (`/internal-mcp/image_generation`), whose auth type is `internal`, and which references the image model through a foreign key. It carries no credentials and no classification of its own: on every request the ask path mints a short-lived token naming the provider row, and the loopback tool calls the model through LiteLLM with the credentials stored on the model's provider, using the model's defaults unless the assistant asks for a size or quality. The classification check at ask time uses the image model's classification. Every provider is reached through the same OpenAI Images API shaped call, so a self-hosted GPU endpoint and a hosted API take the identical path.

Activation, audiences and permissions work exactly as for external providers, and the provider's tool is approved automatically on sync because it is Eneo's own code. To change the active source type, prepare a separate replacement and activate it after validation. Disabling the image model makes the capability unavailable until it is re-enabled or the provider is pointed at another model; deleting the model is refused while a provider runs on it. Web search has no built-in provider.

The backend must be able to reach its own loopback URL (`INTERNAL_MCP_BASE_URL`, the same requirement as the knowledge and files servers).

## 3. Ask-time resolution

For each capability an assistant requests, the provider is attached only when all of these hold:

- the user's role grants the capability permission (`web_search` or `image_generation`; roles can be edited under **Admin → Roles**);
- a provider serves the user: a group-targeted provider covering one of their groups, else the tenant default;
- the provider has at least one enabled, approved tool;
- for a built-in provider, its image model is enabled, not deprecated or deleted, and its model provider is active;
- the provider's security classification (for a built-in provider, its image model's) meets the space's classification;
- the completion model supports tool calling.

Otherwise the capability is silently unavailable for that turn. Service API keys can use web search but not image generation: a generated image is stored as a file owned by a user, and a service key has no user.

Conversation requests carry purpose-based disabled_capabilities; ordinary server opt-outs remain in disabled_mcp_server_ids. The chat toolbar persists purpose keys, so an opt-out survives a provider switch.

## 4. Generated images

An MCP `image` content block returned by any tool becomes a generated file shown in the chat. Before persistence the proxy applies these guards:

| Setting | Default | Effect |
|---------|---------|--------|
| `MCP_TOOL_IMAGE_MAX_BYTES` | 10485760 | Decoded size cap per image; larger images are dropped with a notice to the model. |
| `MCP_TOOL_IMAGE_MAX_COUNT` | 4 | Images admitted per tool result; the rest are dropped with one notice. |
| `MCP_TOOL_OUTPUT_MAX_CHARS` | 32768 | Text budget per tool result. Images do not count against it. |

Only `image/png`, `image/jpeg`, `image/webp` and `image/gif` are accepted. The model sees a short placeholder instead of the bytes. Only the latest turn's generated images are replayed to the model on follow-ups; older ones are described by the placeholder in their tool result. Generated files are deleted with their conversation.

## 5. Extending the capability set

Adding a capability requires updating the backend `CapabilityPurpose` type and `CAPABILITY_PURPOSES` list, adding the matching permission and frontend `capabilities.ts` descriptor with its messages, and migrating the association-table purpose constraints and existing role permissions. All admin, space, assistant and chat surfaces render from those lists.


## 6. Deployment and client changes

Ship migration **202609041000**, backend, frontend and the bundled JavaScript
client together. The migration backfills active and inactive capability
attachments, collapses duplicate purposes, preserves a policy default as on
when any duplicate was on, and removes obsolete provider attachments and
capability tool overrides. Ordinary MCP associations and tool settings remain.

There is no compatibility adapter for provider IDs used as capability
selections. Clients must use the new purpose fields. Effective configuration
responses include enabled_capabilities, available_capabilities and
default_disabled_capabilities; admin providers include readiness_reason.

Take a database backup before rollout, stop old writers, apply the migration,
then start the matching application versions. Rollback requires restoring the
backup with the previous application version: provider-based storage cannot
represent saved intent after its last provider has been deleted.

For devcontainer UI validation, Node 22 is supplied by the devcontainer feature,
and post-create installs Chromium with its Linux dependencies. Bun remains the
frontend package manager and script runner.
