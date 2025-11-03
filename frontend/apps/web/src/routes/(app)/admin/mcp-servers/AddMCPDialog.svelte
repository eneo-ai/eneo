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
    onSubmit: (data: any) => Promise<void>;
  };

  const { openController, onSubmit }: Props = $props();

  let name = $state("");
  let description = $state("");
  let http_url = $state("");
  let transport_type = $state<"sse" | "streamable_http">("sse");
  let http_auth_type = $state<"none" | "bearer" | "api_key" | "custom_headers">("none");
  let documentation_url = $state("");

  // Authentication credentials
  let bearer_token = $state("");
  let api_key = $state("");
  let api_key_header = $state("X-API-Key");
  let custom_headers = $state("");

  let submitting = $state(false);

  async function handleSubmit() {
    submitting = true;
    try {
      const data: any = {
        name,
        http_url,
        transport_type,
        http_auth_type,
      };

      // Add optional fields with actual values
      if (description) data.description = description;
      if (documentation_url) data.documentation_url = documentation_url;

      // Add auth config if needed
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
          alert("Invalid JSON for custom headers");
          submitting = false;
          return;
        }
      }

      await onSubmit(data);

      // Reset form
      name = "";
      description = "";
      http_url = "";
      transport_type = "sse";
      http_auth_type = "none";
      documentation_url = "";
      bearer_token = "";
      api_key = "";
      api_key_header = "X-API-Key";
      custom_headers = "";

      $openController = false;
    } finally {
      submitting = false;
    }
  }
</script>

<Dialog.Root {openController}>
  <Dialog.Content width="medium">
    <Dialog.Title>{m.add_mcp_server()}</Dialog.Title>

    <Dialog.Section scrollable={true}>
      <form on:submit|preventDefault={handleSubmit} class="space-y-4 px-4 py-4">
        <div>
          <label for="name" class="text-default mb-1 block text-sm font-medium">{m.name()}</label>
          <input
            id="name"
            type="text"
            bind:value={name}
            required
            class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
          />
        </div>

        <div>
          <label for="description" class="text-default mb-1 block text-sm font-medium">{m.description()}</label>
          <textarea
            id="description"
            bind:value={description}
            rows="3"
            class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
          ></textarea>
        </div>

        <div>
          <label for="http_url" class="text-default mb-1 block text-sm font-medium">HTTP URL *</label>
          <input
            id="http_url"
            type="url"
            bind:value={http_url}
            required
            placeholder="https://example.com/sse or https://example.com/mcp"
            class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
          />
          <p class="text-muted mt-1 text-xs">Full URL to the MCP server endpoint</p>
        </div>

        <div>
          <label for="transport_type" class="text-default mb-1 block text-sm font-medium">Transport Type</label>
          <select
            id="transport_type"
            bind:value={transport_type}
            required
            class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
          >
            <option value="sse">SSE (Server-Sent Events)</option>
            <option value="streamable_http">Streamable HTTP</option>
          </select>
          <p class="text-muted mt-1 text-xs">SSE is recommended for most use cases</p>
        </div>

        <div>
          <label for="http_auth_type" class="text-default mb-1 block text-sm font-medium">Authentication Type</label>
          <select
            id="http_auth_type"
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
            <label for="bearer_token" class="text-default mb-1 block text-sm font-medium">Bearer Token</label>
            <input
              id="bearer_token"
              type="password"
              bind:value={bearer_token}
              placeholder="your-bearer-token"
              class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
            />
            <p class="text-muted mt-1 text-xs">Will be sent as: Authorization: Bearer &lt;token&gt;</p>
          </div>
        {/if}

        {#if http_auth_type === "api_key"}
          <div class="space-y-3">
            <div>
              <label for="api_key" class="text-default mb-1 block text-sm font-medium">API Key</label>
              <input
                id="api_key"
                type="password"
                bind:value={api_key}
                placeholder="your-api-key"
                class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
              />
            </div>
            <div>
              <label for="api_key_header" class="text-default mb-1 block text-sm font-medium">Header Name</label>
              <input
                id="api_key_header"
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
            <label for="custom_headers" class="text-default mb-1 block text-sm font-medium">Custom Headers (JSON)</label>
            <textarea
              id="custom_headers"
              bind:value={custom_headers}
              rows="4"
              placeholder="&#123;&quot;X-Custom-Header&quot;: &quot;value&quot;, &quot;Authorization&quot;: &quot;Bearer token&quot;&#125;"
              class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 font-mono text-sm shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
            ></textarea>
            <p class="text-muted mt-1 text-xs">Provide headers as a JSON object</p>
          </div>
        {/if}

        <div>
          <label for="documentation_url" class="text-default mb-1 block text-sm font-medium">{m.documentation_url()}</label>
          <input
            id="documentation_url"
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
        {submitting ? m.loading() : m.add_mcp_server()}
      </Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
