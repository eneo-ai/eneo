<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Dialog, Button, Select } from "@intric/ui";
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
          errorMessage = m.invalid_json_custom_headers();
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
      errorMessage = error?.message || error?.body?.message || (isEditMode ? m.failed_update_mcp_server() : m.failed_create_mcp_server());
    } finally {
      submitting = false;
    }
  }

  const authPlaceholder = $derived(isEditMode ? m.leave_empty_keep_existing() : "");
</script>

<Dialog.Root {openController}>
  <Dialog.Content width="medium">
    <Dialog.Title>
      <span class="flex items-center gap-3">
        <span class="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-dimmer">
          <svg class="h-5 w-5 text-accent-default" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" aria-hidden="true">
            <path stroke-linecap="round" stroke-linejoin="round" d="M5.25 14.25h13.5m-13.5 0a3 3 0 01-3-3m3 3a3 3 0 100 6h13.5a3 3 0 100-6m-16.5-3a3 3 0 013-3h13.5a3 3 0 013 3m-19.5 0a4.5 4.5 0 01.9-2.7L5.737 5.1a3.375 3.375 0 012.7-1.35h7.126c1.062 0 2.062.5 2.7 1.35l2.587 3.45a4.5 4.5 0 01.9 2.7m0 0a3 3 0 01-3 3m0 3h.008v.008h-.008v-.008zm0-6h.008v.008h-.008v-.008zm-3 6h.008v.008h-.008v-.008zm0-6h.008v.008h-.008v-.008z" />
          </svg>
        </span>
        {isEditMode ? m.edit_mcp_server() : m.add_mcp_server()}
      </span>
    </Dialog.Title>

    <Dialog.Section scrollable={true}>
      <form onsubmit={(e) => { e.preventDefault(); handleSubmit(); }} class="space-y-5 px-4 pt-2 pb-6">
        {#if errorMessage}
          <div class="flex items-start gap-3 rounded-lg border border-negative-default/30 bg-negative-dimmer px-4 py-3" role="alert">
            <svg class="mt-0.5 h-5 w-5 shrink-0 text-negative-default" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" aria-hidden="true">
              <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
            </svg>
            <div class="text-sm text-negative-stronger">{errorMessage}</div>
          </div>
        {/if}

        <!-- Server Identity Section -->
        <fieldset class="space-y-4">
          <legend class="sr-only">Serverinformation</legend>

          <div>
            <label for="mcp-name" class="mb-1.5 flex items-center gap-1.5 text-sm font-medium text-default">
              {m.name()}
              <span class="text-negative-default" aria-hidden="true">*</span>
            </label>
            <input
              id="mcp-name"
              type="text"
              bind:value={name}
              required
              aria-required="true"
              placeholder="Min MCP-server"
              class="border-default bg-primary ring-accent-default w-full rounded-lg border px-3 py-2.5 text-sm shadow-sm transition-shadow focus:ring-2 focus:border-accent-default focus:outline-none hover:border-stronger"
            />
          </div>

          <div>
            <label for="mcp-description" class="mb-1.5 block text-sm font-medium text-default">
              {m.description()}
              <span class="ml-1 text-xs font-normal text-muted">(valfritt)</span>
            </label>
            <textarea
              id="mcp-description"
              bind:value={description}
              rows="2"
              placeholder="Beskriv vad denna MCP-server gör..."
              class="border-default bg-primary ring-accent-default w-full rounded-lg border px-3 py-2.5 text-sm shadow-sm transition-shadow focus:ring-2 focus:border-accent-default focus:outline-none hover:border-stronger resize-none"
            ></textarea>
          </div>
        </fieldset>

        <!-- Connection Section -->
        <fieldset class="space-y-4 rounded-xl border border-dimmer bg-secondary/20 p-4 pt-3">
          <legend class="-ml-1 flex items-center gap-2 rounded-md bg-secondary px-2 py-1 text-[11px] font-medium uppercase tracking-wider text-muted">
            <svg class="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" aria-hidden="true">
              <path stroke-linecap="round" stroke-linejoin="round" d="M13.19 8.688a4.5 4.5 0 011.242 7.244l-4.5 4.5a4.5 4.5 0 01-6.364-6.364l1.757-1.757m13.35-.622l1.757-1.757a4.5 4.5 0 00-6.364-6.364l-4.5 4.5a4.5 4.5 0 001.242 7.244" />
            </svg>
            Anslutning
          </legend>

          <div>
            <label for="mcp-http_url" class="mb-1.5 flex items-center gap-1.5 text-sm font-medium text-default">
              {m.server_url_required()}
              <span class="text-negative-default" aria-hidden="true">*</span>
            </label>
            <div class="relative">
              <input
                id="mcp-http_url"
                type="url"
                bind:value={http_url}
                required
                aria-required="true"
                aria-describedby="url-hint"
                placeholder="https://example.com/mcp"
                class="border-default bg-primary ring-accent-default w-full rounded-lg border pl-3 pr-10 py-2.5 font-mono text-sm shadow-sm transition-shadow focus:ring-2 focus:border-accent-default focus:outline-none hover:border-stronger"
              />
              {#if http_url}
                <div class="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2">
                  <span class="flex h-5 w-5 items-center justify-center rounded-full bg-positive-dimmer">
                    <svg class="h-3 w-3 text-positive-default" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="3" aria-hidden="true">
                      <path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5" />
                    </svg>
                  </span>
                </div>
              {/if}
            </div>
            <p id="url-hint" class="mt-1.5 text-xs text-muted">{m.server_url_hint()}</p>
          </div>
        </fieldset>

        <!-- Authentication Section -->
        <fieldset class="space-y-4 rounded-xl border border-dimmer bg-secondary/20 p-4 pt-3">
          <legend class="-ml-1 flex items-center gap-2 rounded-md bg-secondary px-2 py-1 text-[11px] font-medium uppercase tracking-wider text-muted">
            <svg class="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" aria-hidden="true">
              <path stroke-linecap="round" stroke-linejoin="round" d="M16.5 10.5V6.75a4.5 4.5 0 10-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 002.25-2.25v-6.75a2.25 2.25 0 00-2.25-2.25H6.75a2.25 2.25 0 00-2.25 2.25v6.75a2.25 2.25 0 002.25 2.25z" />
            </svg>
            Autentisering
          </legend>

          <!-- TODO: Add more auth options when OAuth support is implemented -->
          <Select.Simple
            options={[
              { value: "none", label: "Publik (ingen autentisering)" },
            ]}
            bind:value={http_auth_type}
          >
            {m.authentication_type()}
          </Select.Simple>

          {#if http_auth_type === "bearer"}
            <div>
              <label for="mcp-bearer_token" class="mb-1.5 block text-sm font-medium text-default">{m.bearer_token()}</label>
              <input
                id="mcp-bearer_token"
                type="password"
                bind:value={bearer_token}
                placeholder={authPlaceholder || "Ange din bearer token..."}
                autocomplete="off"
                class="border-default bg-primary ring-accent-default w-full rounded-lg border px-3 py-2.5 font-mono text-sm shadow-sm transition-shadow focus:ring-2 focus:border-accent-default focus:outline-none hover:border-stronger"
              />
              <p class="mt-1.5 text-xs text-muted">
                {#if isEditMode}<span class="text-warning-default">{m.leave_empty_keep_existing()}.</span>{/if}
                {m.will_be_sent_as_bearer()}
              </p>
            </div>
          {/if}

          {#if http_auth_type === "api_key"}
            <div class="space-y-4">
              <div>
                <label for="mcp-api_key" class="mb-1.5 block text-sm font-medium text-default">{m.api_key()}</label>
                <input
                  id="mcp-api_key"
                  type="password"
                  bind:value={api_key}
                  placeholder={authPlaceholder || "Ange din API-nyckel..."}
                  autocomplete="off"
                  class="border-default bg-primary ring-accent-default w-full rounded-lg border px-3 py-2.5 font-mono text-sm shadow-sm transition-shadow focus:ring-2 focus:border-accent-default focus:outline-none hover:border-stronger"
                />
                {#if isEditMode}
                  <p class="mt-1.5 text-xs text-warning-default">{m.leave_empty_keep_existing()}</p>
                {/if}
              </div>
              <div>
                <label for="mcp-api_key_header" class="mb-1.5 block text-sm font-medium text-default">{m.header_name()}</label>
                <input
                  id="mcp-api_key_header"
                  type="text"
                  bind:value={api_key_header}
                  placeholder="X-API-Key"
                  class="border-default bg-primary ring-accent-default w-full rounded-lg border px-3 py-2.5 font-mono text-sm shadow-sm transition-shadow focus:ring-2 focus:border-accent-default focus:outline-none hover:border-stronger"
                />
                <p class="mt-1.5 text-xs text-muted">{m.default_header_x_api_key()}</p>
              </div>
            </div>
          {/if}

          {#if http_auth_type === "custom_headers"}
            <div>
              <label for="mcp-custom_headers" class="mb-1.5 block text-sm font-medium text-default">{m.custom_headers_json()}</label>
              <textarea
                id="mcp-custom_headers"
                bind:value={custom_headers}
                rows="4"
                placeholder={isEditMode ? m.leave_empty_keep_existing() : '{\n  "X-Custom-Header": "värde",\n  "Authorization": "Basic abc123"\n}'}
                class="border-default bg-primary ring-accent-default w-full rounded-lg border px-3 py-2.5 font-mono text-sm shadow-sm transition-shadow focus:ring-2 focus:border-accent-default focus:outline-none hover:border-stronger resize-none"
              ></textarea>
              <p class="mt-1.5 text-xs text-muted">
                {#if isEditMode}<span class="text-warning-default">{m.leave_empty_keep_existing()}.</span>{/if}
                {m.provide_headers_json()}
              </p>
            </div>
          {/if}
        </fieldset>

        <!-- Optional Section -->
        <fieldset>
          <legend class="sr-only">Tillvalsuppgifter</legend>
          <div>
            <label for="mcp-documentation_url" class="mb-1.5 block text-sm font-medium text-default">
              {m.documentation_url()}
              <span class="ml-1 text-xs font-normal text-muted">(valfritt)</span>
            </label>
            <input
              id="mcp-documentation_url"
              type="url"
              bind:value={documentation_url}
              placeholder="https://docs.example.com"
              class="border-default bg-primary ring-accent-default w-full rounded-lg border px-3 py-2.5 text-sm shadow-sm transition-shadow focus:ring-2 focus:border-accent-default focus:outline-none hover:border-stronger"
            />
          </div>
        </fieldset>
      </form>
    </Dialog.Section>

    <Dialog.Controls let:close>
      <Button is={close} variant="secondary">
        {m.cancel()}
      </Button>
      <Button
        variant="primary"
        onclick={handleSubmit}
        disabled={submitting || !name || !http_url}
        class="min-w-[140px]"
      >
        {#if submitting}
          <svg class="mr-2 h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24" aria-hidden="true">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
          </svg>
          {m.loading()}
        {:else}
          {isEditMode ? m.save() : m.add_mcp_server()}
        {/if}
      </Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
