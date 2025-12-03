<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Dialog, Button } from "@intric/ui";
  import { m } from "$lib/paraglide/messages";
  import type { Writable } from "svelte/store";

  type Props = {
    openController: Writable<boolean>;
    mcpServer?: any;
    onSubmit: (data: any, id?: string) => Promise<void>;
  };

  const { openController, mcpServer, onSubmit }: Props = $props();

  const isEditMode = $derived(!!mcpServer);

  let name = $state("");
  let description = $state("");
  let http_url = $state("");
  let http_auth_type = $state<"none" | "bearer" | "api_key" | "custom_headers">("none");
  let documentation_url = $state("");

  // Authentication credentials
  let bearer_token = $state("");
  let api_key = $state("");
  let api_key_header = $state("X-API-Key");
  let custom_headers = $state("");

  let submitting = $state(false);
  let errorMessage = $state("");

  // Reset/populate form when dialog opens or mcpServer changes
  $effect(() => {
    if (mcpServer) {
      name = mcpServer.name || "";
      description = mcpServer.description || "";
      http_url = mcpServer.http_url || "";
      http_auth_type = mcpServer.http_auth_type || "none";
      documentation_url = mcpServer.documentation_url || "";
    } else {
      name = "";
      description = "";
      http_url = "";
      http_auth_type = "none";
      documentation_url = "";
    }
    // Always clear auth credentials (they're stored securely, not shown)
    bearer_token = "";
    api_key = "";
    api_key_header = "X-API-Key";
    custom_headers = "";
    errorMessage = "";
  });

  async function handleSubmit() {
    submitting = true;
    errorMessage = "";

    try {
      const data: any = {
        name,
        http_url,
        http_auth_type,
      };

      // Add optional fields with actual values
      if (description) data.description = description;
      if (documentation_url) data.documentation_url = documentation_url;

      // Add auth config if provided
      if (http_auth_type === "bearer" && bearer_token) {
        data.http_auth_config_schema = { token: bearer_token };
      } else if (http_auth_type === "api_key" && api_key) {
        data.http_auth_config_schema = {
          api_key: api_key,
          header_name: api_key_header
        };
      } else if (http_auth_type === "custom_headers" && custom_headers) {
        try {
          data.http_auth_config_schema = JSON.parse(custom_headers);
        } catch (e) {
          errorMessage = "Invalid JSON for custom headers";
          submitting = false;
          return;
        }
      }

      await onSubmit(data, mcpServer?.mcp_server_id);

      // Reset form on success (for add mode)
      if (!isEditMode) {
        name = "";
        description = "";
        http_url = "";
        http_auth_type = "none";
        documentation_url = "";
        bearer_token = "";
        api_key = "";
        api_key_header = "X-API-Key";
        custom_headers = "";
      }

      $openController = false;
    } catch (error: any) {
      errorMessage = error?.message || error?.body?.message || `Failed to ${isEditMode ? 'update' : 'create'} MCP server. Please try again.`;
    } finally {
      submitting = false;
    }
  }

  const authPlaceholder = $derived(isEditMode ? "Leave empty to keep existing" : "");
</script>

<Dialog.Root {openController}>
  <Dialog.Content width="medium">
    <Dialog.Title>{isEditMode ? m.edit_mcp_server() : m.add_mcp_server()}</Dialog.Title>

    <Dialog.Section scrollable={true}>
      <form onsubmit={(e) => { e.preventDefault(); handleSubmit(); }} class="space-y-4 px-4 py-4">
        {#if errorMessage}
          <div class="rounded-lg bg-negative-default/10 px-3 py-2 text-sm text-negative-default">
            {errorMessage}
          </div>
        {/if}

        <div>
          <label for="mcp-name" class="text-default mb-1 block text-sm font-medium">{m.name()}</label>
          <input
            id="mcp-name"
            type="text"
            bind:value={name}
            required
            class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
          />
        </div>

        <div>
          <label for="mcp-description" class="text-default mb-1 block text-sm font-medium">{m.description()}</label>
          <textarea
            id="mcp-description"
            bind:value={description}
            rows="3"
            class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
          ></textarea>
        </div>

        <div>
          <label for="mcp-http_url" class="text-default mb-1 block text-sm font-medium">Server URL *</label>
          <input
            id="mcp-http_url"
            type="url"
            bind:value={http_url}
            required
            placeholder="https://example.com/mcp"
            class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
          />
          <p class="text-muted mt-1 text-xs">Full URL to the MCP server endpoint (Streamable HTTP)</p>
        </div>

        <div>
          <label for="mcp-http_auth_type" class="text-default mb-1 block text-sm font-medium">Authentication Type</label>
          <select
            id="mcp-http_auth_type"
            bind:value={http_auth_type}
            required
            class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
          >
            <option value="none">None</option>
            <option value="bearer">Bearer Token</option>
            <option value="api_key">API Key</option>
            <option value="custom_headers">Custom Headers</option>
          </select>
        </div>

        {#if http_auth_type === "bearer"}
          <div>
            <label for="mcp-bearer_token" class="text-default mb-1 block text-sm font-medium">Bearer Token</label>
            <input
              id="mcp-bearer_token"
              type="password"
              bind:value={bearer_token}
              placeholder={authPlaceholder || "your-bearer-token"}
              class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
            />
            <p class="text-muted mt-1 text-xs">
              {#if isEditMode}Leave empty to keep existing credentials.{/if}
              Will be sent as: Authorization: Bearer &lt;token&gt;
            </p>
          </div>
        {/if}

        {#if http_auth_type === "api_key"}
          <div class="space-y-3">
            <div>
              <label for="mcp-api_key" class="text-default mb-1 block text-sm font-medium">API Key</label>
              <input
                id="mcp-api_key"
                type="password"
                bind:value={api_key}
                placeholder={authPlaceholder || "your-api-key"}
                class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
              />
              {#if isEditMode}
                <p class="text-muted mt-1 text-xs">Leave empty to keep existing credentials</p>
              {/if}
            </div>
            <div>
              <label for="mcp-api_key_header" class="text-default mb-1 block text-sm font-medium">Header Name</label>
              <input
                id="mcp-api_key_header"
                type="text"
                bind:value={api_key_header}
                placeholder="X-API-Key"
                class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
              />
              <p class="text-muted mt-1 text-xs">Default: X-API-Key</p>
            </div>
          </div>
        {/if}

        {#if http_auth_type === "custom_headers"}
          <div>
            <label for="mcp-custom_headers" class="text-default mb-1 block text-sm font-medium">Custom Headers (JSON)</label>
            <textarea
              id="mcp-custom_headers"
              bind:value={custom_headers}
              rows="4"
              placeholder={isEditMode ? "Leave empty to keep existing headers" : '{"X-Custom-Header": "value"}'}
              class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 font-mono text-sm shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
            ></textarea>
            <p class="text-muted mt-1 text-xs">
              {#if isEditMode}Leave empty to keep existing credentials.{/if}
              Provide headers as a JSON object
            </p>
          </div>
        {/if}

        <div>
          <label for="mcp-documentation_url" class="text-default mb-1 block text-sm font-medium">{m.documentation_url()}</label>
          <input
            id="mcp-documentation_url"
            type="url"
            bind:value={documentation_url}
            placeholder="https://docs.example.com"
            class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
          />
        </div>
      </form>
    </Dialog.Section>

    <Dialog.Controls let:close>
      <Button is={close} variant="secondary">
        {m.cancel()}
      </Button>
      <Button variant="primary" onclick={handleSubmit} disabled={submitting || !name || !http_url}>
        {submitting ? m.loading() : (isEditMode ? m.save() : m.add_mcp_server())}
      </Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
