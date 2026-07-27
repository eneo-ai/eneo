<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Dialog, Button, Select } from "@eneo/ui";
  import { m } from "$lib/paraglide/messages";
  import type { SecurityClassification, components } from "@eneo/eneo-js";
  import SelectSecurityClassification from "$lib/features/security-classifications/components/SelectSecurityClassification.svelte";
  import { getSecurityContext } from "$lib/features/security-classifications/SecurityContext.js";
  import type { Writable } from "svelte/store";

  type MCPServerSettings = components["schemas"]["MCPServerSettingsPublic"];
  const DEFAULT_TOOL_CATALOG_MAX_COUNT = 256;
  const DEFAULT_TOOL_CATALOG_MAX_MIB = 16;
  const DEFAULT_TOOL_DEFINITION_MAX_KIB = 64;

  type Props = {
    openController: Writable<boolean>;
    mcpServer?: MCPServerSettings | null;
    /** Purpose used when creating a new server. Defaults to "general". */
    purpose?: "general" | "web_search";
    onSubmit: (data: Record<string, unknown>, id?: string) => Promise<void>;
  };

  const { openController, mcpServer, purpose = "general", onSubmit }: Props = $props();

  const isEditMode = $derived(!!mcpServer);
  const isWebSearch = $derived(purpose === "web_search");

  // Web-search providers get provider wording; the general MCP variant is
  // unchanged.
  const dialogTitle = $derived(
    isWebSearch
      ? isEditMode
        ? m.edit_search_provider()
        : m.add_search_provider()
      : isEditMode
        ? m.edit_mcp_server()
        : m.add_mcp_server()
  );
  const submitLabel = $derived(
    isEditMode ? m.save() : isWebSearch ? m.add_search_provider() : m.add_mcp_server()
  );

  const classifications = getSecurityContext().security_classifications;

  let name = $state("");
  let description = $state("");
  let http_url = $state("");
  let http_auth_type = $state<"none" | "bearer" | "api_key_header">("none");
  let documentation_url = $state("");
  let security_classification = $state<SecurityClassification | null>(null);
  let forward_identity = $state(false);
  let tool_catalog_max_count = $state(DEFAULT_TOOL_CATALOG_MAX_COUNT);
  let tool_catalog_max_mib = $state(DEFAULT_TOOL_CATALOG_MAX_MIB);
  let tool_definition_max_kib = $state(DEFAULT_TOOL_DEFINITION_MAX_KIB);

  // Authentication credentials
  let bearer_token = $state("");
  let api_key_header_name = $state("");
  let api_key_token = $state("");

  let submitting = $state(false);
  let errorMessage = $state("");

  // Reset/populate form when dialog opens or mcpServer changes
  $effect(() => {
    if (mcpServer) {
      name = mcpServer.name || "";
      description = mcpServer.description || "";
      http_url = mcpServer.http_url || "";
      http_auth_type = (mcpServer.http_auth_type as "none" | "bearer" | "api_key_header") || "none";
      documentation_url = mcpServer.documentation_url || "";
      security_classification = mcpServer.security_classification ?? null;
      forward_identity = mcpServer.forward_identity ?? false;
      tool_catalog_max_count = mcpServer.tool_catalog_max_count ?? DEFAULT_TOOL_CATALOG_MAX_COUNT;
      tool_catalog_max_mib = Math.round(
        (mcpServer.tool_catalog_max_bytes ?? DEFAULT_TOOL_CATALOG_MAX_MIB * 1024 * 1024) /
          (1024 * 1024)
      );
      tool_definition_max_kib = Math.round(
        (mcpServer.tool_definition_max_bytes ?? DEFAULT_TOOL_DEFINITION_MAX_KIB * 1024) / 1024
      );
    } else {
      name = "";
      description = "";
      http_url = "";
      http_auth_type = "none";
      documentation_url = "";
      security_classification = null;
      forward_identity = false;
      tool_catalog_max_count = DEFAULT_TOOL_CATALOG_MAX_COUNT;
      tool_catalog_max_mib = DEFAULT_TOOL_CATALOG_MAX_MIB;
      tool_definition_max_kib = DEFAULT_TOOL_DEFINITION_MAX_KIB;
    }
    // Always clear auth credentials (they're stored securely, not shown).
    // The stored header name is not exposed by the API either; in edit mode
    // an empty header-name field means "keep the stored one".
    bearer_token = "";
    api_key_header_name = "";
    api_key_token = "";
    errorMessage = "";
  });

  async function handleSubmit() {
    submitting = true;
    errorMessage = "";

    try {
      const data: Record<string, unknown> = { name };

      // Purpose is set at creation time only (e.g. web-search providers).
      if (!isEditMode && purpose !== "general") {
        data.purpose = purpose;
      }

      // Only send connection-affecting fields when actually changed to avoid
      // unnecessary connection validation on the backend for simple edits
      if (!isEditMode || http_url !== mcpServer?.http_url) {
        data.http_url = http_url;
      }
      if (!isEditMode || http_auth_type !== mcpServer?.http_auth_type) {
        data.http_auth_type = http_auth_type;
      }

      // Add optional fields with actual values
      if (description) data.description = description;
      if (documentation_url) data.documentation_url = documentation_url;
      data.forward_identity = forward_identity;
      data.tool_catalog_max_count = tool_catalog_max_count;
      data.tool_catalog_max_bytes = tool_catalog_max_mib * 1024 * 1024;
      data.tool_definition_max_bytes = tool_definition_max_kib * 1024;

      // Security classification — send id or null
      data.security_classification = security_classification
        ? { id: security_classification.id }
        : null;

      // Add auth config if provided
      if (http_auth_type === "bearer" && bearer_token) {
        data.http_auth_config_schema = { token: bearer_token };
      }
      if (http_auth_type === "api_key_header" && api_key_token) {
        // A token-only replacement omits header_name; the backend keeps the
        // stored header name in that case.
        data.http_auth_config_schema = api_key_header_name
          ? { header_name: api_key_header_name, token: api_key_token }
          : { token: api_key_token };
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
        api_key_header_name = "";
        api_key_token = "";
        security_classification = null;
        forward_identity = false;
        tool_catalog_max_count = DEFAULT_TOOL_CATALOG_MAX_COUNT;
        tool_catalog_max_mib = DEFAULT_TOOL_CATALOG_MAX_MIB;
        tool_definition_max_kib = DEFAULT_TOOL_DEFINITION_MAX_KIB;
      }

      $openController = false;
    } catch (error: unknown) {
      const err = error as { message?: string; body?: { message?: string } };
      errorMessage =
        err?.message ||
        err?.body?.message ||
        (isEditMode ? m.failed_update_mcp_server() : m.failed_create_mcp_server());
    } finally {
      submitting = false;
    }
  }

  const credentialPreview = $derived(mcpServer?.credential_preview ?? "");
  const authPlaceholder = $derived(
    isEditMode && credentialPreview
      ? credentialPreview
      : isEditMode
        ? m.leave_empty_keep_existing()
        : ""
  );
</script>

<Dialog.Root {openController}>
  <Dialog.Content width="medium">
    <Dialog.Title>
      <span class="flex items-center gap-3">
        <span class="bg-accent-dimmer flex h-10 w-10 items-center justify-center rounded-xl">
          <svg
            class="text-accent-default h-5 w-5"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            stroke-width="2"
            aria-hidden="true"
          >
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              d="M5.25 14.25h13.5m-13.5 0a3 3 0 01-3-3m3 3a3 3 0 100 6h13.5a3 3 0 100-6m-16.5-3a3 3 0 013-3h13.5a3 3 0 013 3m-19.5 0a4.5 4.5 0 01.9-2.7L5.737 5.1a3.375 3.375 0 012.7-1.35h7.126c1.062 0 2.062.5 2.7 1.35l2.587 3.45a4.5 4.5 0 01.9 2.7m0 0a3 3 0 01-3 3m0 3h.008v.008h-.008v-.008zm0-6h.008v.008h-.008v-.008zm-3 6h.008v.008h-.008v-.008zm0-6h.008v.008h-.008v-.008z"
            />
          </svg>
        </span>
        {dialogTitle}
      </span>
    </Dialog.Title>

    <Dialog.Section scrollable={true}>
      <form
        onsubmit={(e) => {
          e.preventDefault();
          handleSubmit();
        }}
        class="space-y-5 px-4 pt-2 pb-6"
      >
        {#if errorMessage}
          <div
            class="border-negative-default/30 bg-negative-dimmer flex items-start gap-3 rounded-lg border px-4 py-3"
            role="alert"
          >
            <svg
              class="text-negative-default mt-0.5 h-5 w-5 shrink-0"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              stroke-width="2"
              aria-hidden="true"
            >
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z"
              />
            </svg>
            <div class="text-negative-stronger text-sm">{errorMessage}</div>
          </div>
        {/if}

        {#if isWebSearch && !isEditMode}
          <p
            class="border-dimmer bg-secondary/50 text-secondary rounded-lg border px-4 py-3 text-sm"
          >
            {m.web_search_provider_managed_note()}
          </p>
        {/if}

        <!-- Server Identity Section -->
        <fieldset class="space-y-4">
          <legend class="sr-only">{m.mcp_server_info_legend()}</legend>

          <div>
            <label
              for="mcp-name"
              class="text-default mb-1.5 flex items-center gap-1.5 text-sm font-medium"
            >
              {m.name()}
              <span class="text-negative-default" aria-hidden="true">*</span>
            </label>
            <input
              id="mcp-name"
              type="text"
              bind:value={name}
              required
              aria-required="true"
              placeholder={isWebSearch
                ? m.web_search_provider_name_placeholder()
                : m.mcp_name_placeholder()}
              class="border-default bg-primary ring-accent-default focus:border-accent-default hover:border-stronger w-full rounded-lg border px-3 py-2.5 text-sm shadow-sm transition-shadow focus:ring-2 focus:outline-none"
            />
          </div>

          {#if !isWebSearch}
            <div>
              <label for="mcp-description" class="text-default mb-1.5 block text-sm font-medium">
                {m.description()}
                <span class="text-muted ml-1 text-xs font-normal">{m.mcp_optional_label()}</span>
              </label>
              <textarea
                id="mcp-description"
                bind:value={description}
                rows="2"
                placeholder={m.mcp_description_placeholder()}
                class="border-default bg-primary ring-accent-default focus:border-accent-default hover:border-stronger w-full resize-none rounded-lg border px-3 py-2.5 text-sm shadow-sm transition-shadow focus:ring-2 focus:outline-none"
              ></textarea>
            </div>
          {/if}
        </fieldset>

        <!-- Connection Section -->
        <fieldset class="border-dimmer bg-secondary/20 space-y-4 rounded-xl border p-4 pt-3">
          <legend
            class="bg-secondary text-muted -ml-1 flex items-center gap-2 rounded-md px-2 py-1 text-[11px] font-medium tracking-wider uppercase"
          >
            <svg
              class="h-3 w-3"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              stroke-width="2"
              aria-hidden="true"
            >
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                d="M13.19 8.688a4.5 4.5 0 011.242 7.244l-4.5 4.5a4.5 4.5 0 01-6.364-6.364l1.757-1.757m13.35-.622l1.757-1.757a4.5 4.5 0 00-6.364-6.364l-4.5 4.5a4.5 4.5 0 001.242 7.244"
              />
            </svg>
            {m.mcp_connection_legend()}
          </legend>

          <div>
            <label
              for="mcp-http_url"
              class="text-default mb-1.5 flex items-center gap-1.5 text-sm font-medium"
            >
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
                placeholder={m.mcp_url_placeholder()}
                class="border-default bg-primary ring-accent-default focus:border-accent-default hover:border-stronger w-full rounded-lg border py-2.5 pr-10 pl-3 font-mono text-sm shadow-sm transition-shadow focus:ring-2 focus:outline-none"
              />
              {#if http_url}
                <div class="pointer-events-none absolute top-1/2 right-3 -translate-y-1/2">
                  <span
                    class="bg-positive-dimmer flex h-5 w-5 items-center justify-center rounded-full"
                  >
                    <svg
                      class="text-positive-default h-3 w-3"
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                      stroke-width="3"
                      aria-hidden="true"
                    >
                      <path
                        stroke-linecap="round"
                        stroke-linejoin="round"
                        d="M4.5 12.75l6 6 9-13.5"
                      />
                    </svg>
                  </span>
                </div>
              {/if}
            </div>
            <p id="url-hint" class="text-muted mt-1.5 text-xs">{m.server_url_hint()}</p>
          </div>
        </fieldset>

        <!-- Authentication Section -->
        <fieldset class="border-dimmer bg-secondary/20 space-y-4 rounded-xl border p-4 pt-3">
          <legend
            class="bg-secondary text-muted -ml-1 flex items-center gap-2 rounded-md px-2 py-1 text-[11px] font-medium tracking-wider uppercase"
          >
            <svg
              class="h-3 w-3"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              stroke-width="2"
              aria-hidden="true"
            >
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                d="M16.5 10.5V6.75a4.5 4.5 0 10-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 002.25-2.25v-6.75a2.25 2.25 0 00-2.25-2.25H6.75a2.25 2.25 0 00-2.25 2.25v6.75a2.25 2.25 0 002.25 2.25z"
              />
            </svg>
            {m.mcp_authentication_legend()}
          </legend>

          <Select.Simple
            options={[
              { value: "none", label: "Publik (ingen autentisering)" },
              { value: "bearer", label: "Bearer Token" },
              { value: "api_key_header", label: m.api_key_header_auth() }
            ]}
            bind:value={http_auth_type}
          >
            {m.authentication_type()}
          </Select.Simple>

          {#if http_auth_type === "api_key_header"}
            <div>
              <label
                for="mcp-api_key_header_name"
                class="text-default mb-1.5 block text-sm font-medium"
                >{m.api_key_header_name()}</label
              >
              <input
                id="mcp-api_key_header_name"
                type="text"
                bind:value={api_key_header_name}
                placeholder={m.api_key_header_name_placeholder()}
                autocomplete="off"
                class="border-default bg-primary ring-accent-default focus:border-accent-default hover:border-stronger w-full rounded-lg border px-3 py-2.5 font-mono text-sm shadow-sm transition-shadow focus:ring-2 focus:outline-none"
              />
              {#if isEditMode}
                <p class="text-muted mt-1.5 text-xs">{m.api_key_header_name_keep_hint()}</p>
              {/if}
            </div>
            <div>
              <label for="mcp-api_key_token" class="text-default mb-1.5 block text-sm font-medium"
                >{m.api_key()}</label
              >
              <input
                id="mcp-api_key_token"
                type="password"
                bind:value={api_key_token}
                placeholder={authPlaceholder}
                autocomplete="off"
                class="border-default bg-primary ring-accent-default focus:border-accent-default hover:border-stronger w-full rounded-lg border px-3 py-2.5 font-mono text-sm shadow-sm transition-shadow focus:ring-2 focus:outline-none"
              />
              <p class="text-muted mt-1.5 text-xs">
                {#if isEditMode}<span class="text-warning-default"
                    >{m.leave_empty_keep_existing()}.
                  </span>{/if}
                {m.api_key_header_sent_as()}
              </p>
            </div>
          {/if}

          {#if http_auth_type === "bearer"}
            <div>
              <label for="mcp-bearer_token" class="text-default mb-1.5 block text-sm font-medium"
                >{m.bearer_token()}</label
              >
              <input
                id="mcp-bearer_token"
                type="password"
                bind:value={bearer_token}
                placeholder={authPlaceholder || "Ange din bearer token..."}
                autocomplete="off"
                class="border-default bg-primary ring-accent-default focus:border-accent-default hover:border-stronger w-full rounded-lg border px-3 py-2.5 font-mono text-sm shadow-sm transition-shadow focus:ring-2 focus:outline-none"
              />
              <p class="text-muted mt-1.5 text-xs">
                {#if isEditMode}<span class="text-warning-default"
                    >{m.leave_empty_keep_existing()}.
                  </span>{/if}
                {m.will_be_sent_as_bearer()}
              </p>
            </div>
          {/if}
        </fieldset>

        <!-- Optional Section -->
        <fieldset>
          <legend class="sr-only">{m.mcp_optional_details_legend()}</legend>
          <div>
            <label
              for="mcp-documentation_url"
              class="text-default mb-1.5 block text-sm font-medium"
            >
              {m.documentation_url()}
              <span class="text-muted ml-1 text-xs font-normal">{m.mcp_optional_label()}</span>
            </label>
            <input
              id="mcp-documentation_url"
              type="url"
              bind:value={documentation_url}
              placeholder={m.mcp_docs_url_placeholder()}
              class="border-default bg-primary ring-accent-default focus:border-accent-default hover:border-stronger w-full rounded-lg border px-3 py-2.5 text-sm shadow-sm transition-shadow focus:ring-2 focus:outline-none"
            />
          </div>

          <div class="mt-4">
            <label for="mcp-forward_identity" class="flex items-start gap-2.5">
              <input
                id="mcp-forward_identity"
                type="checkbox"
                bind:checked={forward_identity}
                aria-describedby="forward-identity-hint"
                class="border-default text-accent-default ring-accent-default focus:ring-accent-default mt-0.5 h-4 w-4 rounded border shadow-sm focus:ring-2"
              />
              <span class="text-default text-sm font-medium">{m.mcp_forward_identity()}</span>
            </label>
            <p id="forward-identity-hint" class="text-muted mt-1.5 pl-6.5 text-xs">
              {isWebSearch ? m.web_search_forward_identity_hint() : m.mcp_forward_identity_hint()}
            </p>
          </div>

          <details class="border-dimmer mt-5 border-t pt-4">
            <summary class="text-default cursor-pointer text-sm font-medium">
              {m.mcp_catalog_safety()}
            </summary>
            <p class="text-muted mt-2 text-xs leading-relaxed">
              {m.mcp_catalog_safety_hint()}
            </p>
            <div class="mt-4 grid gap-4 sm:grid-cols-3">
              <div>
                <label
                  for="mcp-tool-catalog-max-count"
                  class="text-default mb-1.5 block text-sm font-medium"
                >
                  {m.mcp_catalog_max_count()}
                </label>
                <input
                  id="mcp-tool-catalog-max-count"
                  type="number"
                  min="1"
                  max="4096"
                  step="1"
                  bind:value={tool_catalog_max_count}
                  required
                  aria-describedby="mcp-tool-catalog-max-count-hint"
                  class="border-default bg-primary ring-accent-default focus:border-accent-default hover:border-stronger w-full rounded-lg border px-3 py-2.5 text-sm shadow-sm focus:ring-2 focus:outline-none"
                />
                <p id="mcp-tool-catalog-max-count-hint" class="text-muted mt-1.5 text-xs">
                  {m.mcp_catalog_max_count_hint()}
                </p>
              </div>
              <div>
                <label
                  for="mcp-tool-catalog-max-mib"
                  class="text-default mb-1.5 block text-sm font-medium"
                >
                  {m.mcp_catalog_max_mib()}
                </label>
                <input
                  id="mcp-tool-catalog-max-mib"
                  type="number"
                  min="1"
                  max="64"
                  step="1"
                  bind:value={tool_catalog_max_mib}
                  required
                  aria-describedby="mcp-tool-catalog-max-mib-hint"
                  class="border-default bg-primary ring-accent-default focus:border-accent-default hover:border-stronger w-full rounded-lg border px-3 py-2.5 text-sm shadow-sm focus:ring-2 focus:outline-none"
                />
                <p id="mcp-tool-catalog-max-mib-hint" class="text-muted mt-1.5 text-xs">
                  {m.mcp_catalog_max_mib_hint()}
                </p>
              </div>
              <div>
                <label
                  for="mcp-tool-definition-max-kib"
                  class="text-default mb-1.5 block text-sm font-medium"
                >
                  {m.mcp_tool_definition_max_kib()}
                </label>
                <input
                  id="mcp-tool-definition-max-kib"
                  type="number"
                  min="1"
                  max="1024"
                  step="1"
                  bind:value={tool_definition_max_kib}
                  required
                  aria-describedby="mcp-tool-definition-max-kib-hint"
                  class="border-default bg-primary ring-accent-default focus:border-accent-default hover:border-stronger w-full rounded-lg border px-3 py-2.5 text-sm shadow-sm focus:ring-2 focus:outline-none"
                />
                <p id="mcp-tool-definition-max-kib-hint" class="text-muted mt-1.5 text-xs">
                  {m.mcp_tool_definition_max_kib_hint()}
                </p>
              </div>
            </div>
          </details>
        </fieldset>

        <!-- Security Classification -->
        {#if classifications.length > 0}
          <fieldset class="border-dimmer bg-secondary/20 space-y-4 rounded-xl border p-4 pt-3">
            <legend
              class="bg-secondary text-muted -ml-1 flex items-center gap-2 rounded-md px-2 py-1 text-[11px] font-medium tracking-wider uppercase"
            >
              <svg
                class="h-3 w-3"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                stroke-width="2"
                aria-hidden="true"
              >
                <path
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  d="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z"
                />
              </svg>
              {m.security_classification()}
            </legend>

            <div class="classification-select border-default w-full rounded-lg border">
              <SelectSecurityClassification
                {classifications}
                bind:value={security_classification}
              />
            </div>
          </fieldset>
        {/if}
      </form>
    </Dialog.Section>

    <Dialog.Controls let:close>
      <Button is={close} variant="outlined">
        {m.cancel()}
      </Button>
      <Button
        variant="primary"
        onclick={handleSubmit}
        disabled={submitting ||
          !name ||
          !http_url ||
          (http_auth_type === "api_key_header" &&
            !isEditMode &&
            (!api_key_header_name || !api_key_token))}
        class="min-w-[140px]"
      >
        {#if submitting}
          <svg class="mr-2 h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24" aria-hidden="true">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"
            ></circle>
            <path
              class="opacity-75"
              fill="currentColor"
              d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
            ></path>
          </svg>
          {m.loading()}
        {:else}
          {submitLabel}
        {/if}
      </Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>

<style>
  .classification-select :global(button) {
    width: 100%;
    border-bottom: none;
    border-radius: 0.5rem;
    height: 2.75rem;
  }
</style>
