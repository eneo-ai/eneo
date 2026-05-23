<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Dialog, Button, Select } from "@intric/ui";
  import { m } from "$lib/paraglide/messages";
  import type { SecurityClassification, components } from "@intric/intric-js";
  import SelectSecurityClassification from "$lib/features/security-classifications/components/SelectSecurityClassification.svelte";
  import { getSecurityContext } from "$lib/features/security-classifications/SecurityContext.js";
  import type { Writable } from "svelte/store";

  type MCPServerSettings = components["schemas"]["MCPServerSettingsPublic"];

  type Props = {
    openController: Writable<boolean>;
    mcpServer?: MCPServerSettings | null;
    onSubmit: (data: Record<string, unknown>, id?: string) => Promise<void>;
  };

  const { openController, mcpServer, onSubmit }: Props = $props();

  const isEditMode = $derived(!!mcpServer);

  const classifications = getSecurityContext().security_classifications;

  let name = $state("");
  let description = $state("");
  let http_url = $state("");
  let documentation_url = $state("");
  let security_classification = $state<SecurityClassification | null>(null);

  // Authentication credentials
  let bearer_token = $state("");

  // Top-level authentication mode is a single flat choice. ``auth_mode``
  // collapses the backend's two-axis model (http_auth_type × auth_scope)
  // into one selector so administrators don't have to reason about both:
  //   public  → http_auth_type=none,   auth_scope=static_bearer
  //   bearer  → http_auth_type=bearer, auth_scope=static_bearer
  //   sso     → http_auth_type=bearer, auth_scope=per_user | per_tenant
  let auth_mode = $state<"public" | "bearer" | "sso">("public");
  // Sub-choice that only matters when ``auth_mode === "sso"``. Holds
  // ``per_user`` or ``per_tenant``; rolls up into auth_scope at submit.
  let sso_scope = $state<"per_user" | "per_tenant">("per_user");
  let expected_idp_issuer = $state("");
  let target_resource_or_scope = $state("");

  let submitting = $state(false);
  let errorMessage = $state("");

  // Reset/populate form when dialog opens or mcpServer changes
  $effect(() => {
    if (mcpServer) {
      name = mcpServer.name || "";
      description = mcpServer.description || "";
      http_url = mcpServer.http_url || "";
      const existingAuthType = (mcpServer.http_auth_type as "none" | "bearer") || "none";
      const existingScope =
        ((mcpServer as { auth_scope?: string }).auth_scope as
          | "static_bearer"
          | "per_user"
          | "per_tenant"
          | undefined) ?? "static_bearer";
      if (existingScope === "per_user" || existingScope === "per_tenant") {
        auth_mode = "sso";
        sso_scope = existingScope;
      } else if (existingAuthType === "bearer") {
        auth_mode = "bearer";
        sso_scope = "per_user";
      } else {
        auth_mode = "public";
        sso_scope = "per_user";
      }
      documentation_url = mcpServer.documentation_url || "";
      security_classification = mcpServer.security_classification ?? null;
      expected_idp_issuer =
        (mcpServer as { expected_idp_issuer?: string | null }).expected_idp_issuer ?? "";
      target_resource_or_scope =
        (mcpServer as { target_resource_or_scope?: string | null }).target_resource_or_scope ?? "";
    } else {
      name = "";
      description = "";
      http_url = "";
      auth_mode = "public";
      sso_scope = "per_user";
      documentation_url = "";
      security_classification = null;
      expected_idp_issuer = "";
      target_resource_or_scope = "";
    }
    // Always clear auth credentials (they're stored securely, not shown)
    bearer_token = "";
    errorMessage = "";
  });

  async function handleSubmit() {
    submitting = true;
    errorMessage = "";

    // Roll the flat auth_mode UI back up to the backend's two-axis model.
    const http_auth_type: "none" | "bearer" = auth_mode === "public" ? "none" : "bearer";
    const auth_scope: "static_bearer" | "per_user" | "per_tenant" =
      auth_mode === "sso" ? sso_scope : "static_bearer";

    try {
      const data: Record<string, unknown> = { name };

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

      // Security classification — send id or null
      data.security_classification = security_classification
        ? { id: security_classification.id }
        : null;

      // Add auth config if provided
      if (auth_mode === "bearer" && bearer_token) {
        data.http_auth_config_schema = { token: bearer_token };
      }

      // OAuth scope and same-IdP fields. Only send when they meaningfully
      // differ from the current state (avoid touching unrelated rows).
      if (!isEditMode || auth_scope !== (mcpServer as { auth_scope?: string })?.auth_scope) {
        data.auth_scope = auth_scope;
      }
      if (auth_mode === "sso") {
        data.expected_idp_issuer = expected_idp_issuer || null;
        data.target_resource_or_scope = target_resource_or_scope || null;
      } else if (isEditMode) {
        // Switched away from SSO — clear the OAuth-only fields.
        data.expected_idp_issuer = null;
        data.target_resource_or_scope = null;
      }

      await onSubmit(data, mcpServer?.mcp_server_id);

      // Reset form on success (for add mode)
      if (!isEditMode) {
        name = "";
        description = "";
        http_url = "";
        auth_mode = "public";
        sso_scope = "per_user";
        documentation_url = "";
        bearer_token = "";
        security_classification = null;
        expected_idp_issuer = "";
        target_resource_or_scope = "";
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
        {isEditMode ? m.edit_mcp_server() : m.add_mcp_server()}
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

        <!-- Server Identity Section -->
        <fieldset class="space-y-4">
          <legend class="sr-only">Serverinformation</legend>

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
              placeholder="Min MCP-server"
              class="border-default bg-primary ring-accent-default focus:border-accent-default hover:border-stronger w-full rounded-lg border px-3 py-2.5 text-sm shadow-sm transition-shadow focus:ring-2 focus:outline-none"
            />
          </div>

          <div>
            <label for="mcp-description" class="text-default mb-1.5 block text-sm font-medium">
              {m.description()}
              <span class="text-muted ml-1 text-xs font-normal">(valfritt)</span>
            </label>
            <textarea
              id="mcp-description"
              bind:value={description}
              rows="2"
              placeholder="Beskriv vad denna MCP-server gör..."
              class="border-default bg-primary ring-accent-default focus:border-accent-default hover:border-stronger w-full resize-none rounded-lg border px-3 py-2.5 text-sm shadow-sm transition-shadow focus:ring-2 focus:outline-none"
            ></textarea>
          </div>
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
            Anslutning
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
                placeholder="https://example.com/mcp"
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
            Autentisering
          </legend>

          <Select.Simple
            options={[
              { value: "public", label: "Publik (ingen autentisering)" },
              { value: "bearer", label: "Bearer Token (statisk)" },
              { value: "sso", label: "SSO (zero-trust via samma IdP)" }
            ]}
            bind:value={auth_mode}
          >
            {m.authentication_type()}
          </Select.Simple>

          {#if auth_mode === "sso"}
            <div>
              <Select.Simple
                options={[
                  { value: "per_user", label: "Per användare" },
                  { value: "per_tenant", label: "Delad tjänst" }
                ]}
                bind:value={sso_scope}
              >
                SSO-omfattning
              </Select.Simple>
              <p class="text-muted mt-1.5 text-xs">
                SSO-utbyte använder samma IdP som eneo. Kräver MCP_OAUTH_ENABLED på servern och
                konfigurerad federation_config för organisationen.
              </p>
            </div>
          {/if}

          {#if auth_mode === "sso"}
            <p class="text-muted text-xs">
              IdP-issuer ärvs från organisationens
              <span class="font-mono">federation_config</span>. För Keycloak räcker det. För Entra
              ID behöver du sätta API-scope nedan.
            </p>

            <details class="border-default bg-secondary/30 rounded-lg border px-3 py-2">
              <summary class="text-default cursor-pointer text-sm font-medium">
                Avancerat (krävs för Entra ID)
              </summary>
              <div class="mt-3 space-y-3">
                <div>
                  <label for="mcp-target-aud" class="text-default mb-1.5 block text-sm font-medium">
                    Audience / scope (mål-URI)
                    <span class="text-muted ml-1 text-xs font-normal">(valfritt)</span>
                  </label>
                  <input
                    id="mcp-target-aud"
                    type="text"
                    bind:value={target_resource_or_scope}
                    aria-describedby="mcp-target-aud-hint"
                    placeholder="https://mcp.exempel.se/srv  eller  api://abc/.default"
                    class="border-default bg-primary ring-accent-default focus:border-accent-default hover:border-stronger w-full rounded-lg border px-3 py-2.5 font-mono text-sm shadow-sm transition-shadow focus:ring-2 focus:outline-none"
                  />
                  <p id="mcp-target-aud-hint" class="text-muted mt-1.5 text-xs">
                    Keycloak: lämna tomt — broker använder MCP-serverns URL som RFC 8707 resource.
                    Entra: API-scope krävs (t.ex. <span class="font-mono"
                      >api://&lt;app-id&gt;/.default</span
                    >).
                  </p>
                </div>

                <div>
                  <label
                    for="mcp-expected-idp"
                    class="text-default mb-1.5 block text-sm font-medium"
                  >
                    Override för IdP-issuer
                    <span class="text-muted ml-1 text-xs font-normal">(valfritt)</span>
                  </label>
                  <input
                    id="mcp-expected-idp"
                    type="url"
                    bind:value={expected_idp_issuer}
                    aria-describedby="mcp-expected-idp-hint"
                    placeholder="https://keycloak.exempel.se/realms/eneo"
                    class="border-default bg-primary ring-accent-default focus:border-accent-default hover:border-stronger w-full rounded-lg border px-3 py-2.5 font-mono text-sm shadow-sm transition-shadow focus:ring-2 focus:outline-none"
                  />
                  <p id="mcp-expected-idp-hint" class="text-muted mt-1.5 text-xs">
                    Lämna tomt för att använda organisationens vanliga IdP. Sätt enbart om denna
                    MCP-server federerar mot en annan IdP än resten av eneo.
                  </p>
                </div>
              </div>
            </details>
          {/if}

          {#if auth_mode === "bearer"}
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
          <legend class="sr-only">Tillvalsuppgifter</legend>
          <div>
            <label
              for="mcp-documentation_url"
              class="text-default mb-1.5 block text-sm font-medium"
            >
              {m.documentation_url()}
              <span class="text-muted ml-1 text-xs font-normal">(valfritt)</span>
            </label>
            <input
              id="mcp-documentation_url"
              type="url"
              bind:value={documentation_url}
              placeholder="https://docs.example.com"
              class="border-default bg-primary ring-accent-default focus:border-accent-default hover:border-stronger w-full rounded-lg border px-3 py-2.5 text-sm shadow-sm transition-shadow focus:ring-2 focus:outline-none"
            />
          </div>
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
        disabled={submitting || !name || !http_url}
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
          {isEditMode ? m.save() : m.add_mcp_server()}
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
