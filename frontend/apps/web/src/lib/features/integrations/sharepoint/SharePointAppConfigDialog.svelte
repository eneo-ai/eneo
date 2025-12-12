<script lang="ts">
  import { createAsyncState } from "$lib/core/helpers/createAsyncState.svelte";
  import { getIntric } from "$lib/core/Intric";
  import { IconLoadingSpinner } from "@intric/icons/loading-spinner";
  import { IntricError } from "@intric/intric-js";
  import { Button, Dialog, Input } from "@intric/ui";
  import { m } from "$lib/paraglide/messages";
  import type { Writable } from "svelte/store";

  // Types for SharePoint app configuration (until OpenAPI types are regenerated)
  type TenantSharePointAppCreate = {
    client_id: string;
    client_secret: string;
    tenant_domain: string;
    certificate_path?: string | null;
  };

  type TenantSharePointAppPublic = {
    id: string;
    tenant_id: string;
    client_id: string;
    client_secret_masked: string;
    tenant_domain: string;
    is_active: boolean;
    auth_method: "tenant_app" | "service_account";
    service_account_email?: string | null;
    certificate_path?: string | null;
    created_by?: string | null;
    created_at: string;
    updated_at: string;
  };

  type TenantAppTestResult = {
    success: boolean;
    error_message?: string | null;
    details?: string | null;
  };

  type ServiceAccountAuthStartResponse = {
    auth_url: string;
    state: string;
  };

  type AuthMethod = "tenant_app" | "service_account";

  let { openController }: { openController: Writable<boolean> } = $props();

  const intric = getIntric();

  // Form state
  let authMethod = $state<AuthMethod>("service_account"); // Default to recommended
  let clientId = $state("");
  let clientSecret = $state("");
  let tenantDomain = $state("");
  let existingConfig = $state<TenantSharePointAppPublic | null>(null);
  let testResult = $state<TenantAppTestResult | null>(null);
  let oauthState = $state<string | null>(null);
  let isOAuthInProgress = $state(false);

  // Load existing configuration
  const loadConfig = createAsyncState(async () => {
    try {
      const data = await intric.client.fetch("/api/v1/admin/sharepoint/app", {
        method: "get",
        params: {}
      });

      if (data) {
        existingConfig = data as TenantSharePointAppPublic;
        clientId = data.client_id;
        tenantDomain = data.tenant_domain;
        authMethod = data.auth_method || "tenant_app";
        // Don't populate secret - require user to re-enter if updating
      }
    } catch (error) {
      console.error("Failed to load SharePoint app config:", error);
    }
  });

  // Test credentials
  const testCredentials = createAsyncState(async () => {
    testResult = null;

    if (!clientId || !clientSecret || !tenantDomain) {
      alert(m.fill_required_fields());
      return;
    }

    try {
      const payload: TenantSharePointAppCreate = {
        client_id: clientId,
        client_secret: clientSecret,
        tenant_domain: tenantDomain,
      };

      const result = await intric.client.fetch("/api/v1/admin/sharepoint/app/test", {
        method: "post",
        params: {},
        requestBody: {
          "application/json": payload
        }
      }) as TenantAppTestResult;

      testResult = result;

      if (!result.success) {
        alert(
          m.connection_test_failed({ message: result.error_message || "Unknown error" })
        );
      }
    } catch (error) {
      const errorMessage =
        error instanceof IntricError ? error.getReadableMessage() : String(error);
      alert(m.failed_to_test_credentials({ message: errorMessage }));
      testResult = {
        success: false,
        error_message: errorMessage,
      };
    }
  });

  // Save configuration
  const saveConfig = createAsyncState(async () => {
    if (!clientId || !clientSecret || !tenantDomain) {
      alert(m.fill_required_fields());
      return;
    }

    try {
      const payload: TenantSharePointAppCreate = {
        client_id: clientId,
        client_secret: clientSecret,
        tenant_domain: tenantDomain,
      };

      const result = await intric.client.fetch("/api/v1/admin/sharepoint/app", {
        method: "post",
        params: {},
        requestBody: {
          "application/json": payload
        }
      }) as TenantSharePointAppPublic;

      existingConfig = result;

      alert(m.sharepoint_app_configured_successfully());
      $openController = false;
    } catch (error) {
      const errorMessage =
        error instanceof IntricError ? error.getReadableMessage() : String(error);
      alert(m.failed_to_save_configuration({ message: errorMessage }));
    }
  });

  // Start service account OAuth flow
  const startServiceAccountOAuth = createAsyncState(async () => {
    if (!clientId || !clientSecret || !tenantDomain) {
      alert(m.fill_required_fields());
      return;
    }

    try {
      const payload = {
        client_id: clientId,
        client_secret: clientSecret,
        tenant_domain: tenantDomain,
      };

      const result = await intric.client.fetch("/api/v1/admin/sharepoint/service-account/auth/start", {
        method: "post",
        params: {},
        requestBody: {
          "application/json": payload
        }
      }) as ServiceAccountAuthStartResponse;

      // Store state for callback verification
      oauthState = result.state;
      isOAuthInProgress = true;

      // Store credentials in sessionStorage for callback
      sessionStorage.setItem("sharepoint_service_account_oauth", JSON.stringify({
        state: result.state,
        client_id: clientId,
        client_secret: clientSecret,
        tenant_domain: tenantDomain,
      }));

      // Redirect to Microsoft OAuth
      window.location.href = result.auth_url;
    } catch (error) {
      const errorMessage =
        error instanceof IntricError ? error.getReadableMessage() : String(error);
      alert(m.failed_to_start_oauth({ message: errorMessage }));
    }
  });

  // Load config when dialog opens
  $effect(() => {
    if ($openController && existingConfig === null) {
      loadConfig();
    }
  });
</script>

<Dialog.Root {openController}>
  <Dialog.Content width="medium">
    <Dialog.Title>{m.configure_sharepoint_app_title()}</Dialog.Title>

    <Dialog.Section scrollable={false}>
      {#if loadConfig.isLoading}
        <div class="flex items-center justify-center gap-2 p-8">
          <IconLoadingSpinner class="animate-spin" />
          <span class="text-secondary">{m.loading_configuration()}</span>
        </div>
      {:else}
        <div class="space-y-4 p-4">
          <!-- Auth Method Selector -->
          <div class="space-y-3">
            <div class="text-sm font-medium text-primary">
              {m.choose_auth_method()}
            </div>

            <!-- Service Account (Recommended) -->
            <label
              class="flex cursor-pointer items-start gap-3 rounded-lg border p-4 transition-colors
                {authMethod === 'service_account'
                  ? 'border-blue-500 bg-blue-50'
                  : 'border-default hover:border-gray-400'}"
            >
              <input
                type="radio"
                name="auth_method"
                value="service_account"
                bind:group={authMethod}
                class="mt-1"
              />
              <div class="flex-1">
                <div class="flex items-center gap-2">
                  <span class="font-medium text-primary">
                    {m.service_account_option()}
                  </span>
                  <span class="rounded bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-800">
                    {m.recommended()}
                  </span>
                </div>
                <p class="mt-1 text-sm text-secondary">
                  {m.service_account_description()}
                </p>
              </div>
            </label>

            <!-- Tenant App -->
            <label
              class="flex cursor-pointer items-start gap-3 rounded-lg border p-4 transition-colors
                {authMethod === 'tenant_app'
                  ? 'border-blue-500 bg-blue-50'
                  : 'border-default hover:border-gray-400'}"
            >
              <input
                type="radio"
                name="auth_method"
                value="tenant_app"
                bind:group={authMethod}
                class="mt-1"
              />
              <div class="flex-1">
                <span class="font-medium text-primary">
                  {m.tenant_app_option()}
                </span>
                <p class="mt-1 text-sm text-secondary">
                  {m.tenant_app_description()}
                </p>
              </div>
            </label>
          </div>

          <hr class="my-4 border-default" />

          <!-- Credentials Form (same for both) -->
          <p class="text-sm text-secondary">
            {m.sharepoint_app_config_description()}
          </p>

          <Input.Text
            label={m.client_id()}
            bind:value={clientId}
            required
            placeholder="12345678-1234-1234-1234-123456789012"
            description={m.client_id_description()}
          />

          <Input.Text
            label={m.client_secret()}
            bind:value={clientSecret}
            required
            type="password"
            placeholder="Enter client secret"
            description={existingConfig
              ? m.client_secret_keep_existing()
              : m.client_secret_description()}
          />

          <Input.Text
            label={m.tenant_id_or_domain()}
            bind:value={tenantDomain}
            required
            placeholder="contoso.onmicrosoft.com"
            description={m.tenant_id_or_domain_description()}
          />

          {#if existingConfig}
            <div class="rounded-md border border-default bg-secondary p-3">
              <div class="text-sm">
                <div class="font-medium text-primary">{m.current_configuration()}</div>
                <div class="mt-2 space-y-1 text-secondary">
                  <div>{m.client_id()}: {existingConfig.client_id}</div>
                  <div>{m.secret()}: {existingConfig.client_secret_masked}</div>
                  <div>{m.domain()}: {existingConfig.tenant_domain}</div>
                  <div>
                    {m.auth_method()}:
                    <span class="font-medium">
                      {existingConfig.auth_method === "service_account"
                        ? m.service_account_option()
                        : m.tenant_app_option()}
                    </span>
                  </div>
                  {#if existingConfig.service_account_email}
                    <div>
                      {m.service_account_email()}:
                      {existingConfig.service_account_email}
                    </div>
                  {/if}
                  <div>
                    {m.status()}: <span
                      class={existingConfig.is_active
                        ? "text-green-600"
                        : "text-red-600"}
                      >{existingConfig.is_active ? m.active() : m.inactive()}</span
                    >
                  </div>
                </div>
              </div>
            </div>
          {/if}

          {#if testResult}
            <div
              class="rounded-md border p-3 {testResult.success
                ? 'border-green-500 bg-green-50 text-green-800'
                : 'border-red-500 bg-red-50 text-red-800'}"
            >
              <div class="text-sm font-medium">
                {testResult.success ? m.connection_successful() : m.connection_failed()}
              </div>
              {#if testResult.error_message}
                <div class="mt-1 text-xs">{testResult.error_message}</div>
              {/if}
              {#if testResult.details}
                <div class="mt-1 text-xs">{testResult.details}</div>
              {/if}
            </div>
          {/if}
        </div>
      {/if}
    </Dialog.Section>

    <Dialog.Controls>
      <Button
        onclick={() => {
          $openController = false;
        }}>{m.cancel()}</Button
      >

      {#if authMethod === "tenant_app"}
        <!-- Tenant App: Test + Save flow -->
        <Button
          variant="secondary"
          disabled={testCredentials.isLoading ||
            !clientId ||
            !clientSecret ||
            !tenantDomain}
          onclick={testCredentials}
        >
          {testCredentials.isLoading ? m.testing() : m.test_connection()}
        </Button>
        <Button
          variant="primary"
          disabled={saveConfig.isLoading ||
            !clientId ||
            !clientSecret ||
            !tenantDomain}
          onclick={saveConfig}
        >
          {saveConfig.isLoading ? m.saving() : m.save()}
        </Button>
      {:else}
        <!-- Service Account: Sign in with Microsoft -->
        <Button
          variant="primary"
          disabled={startServiceAccountOAuth.isLoading ||
            !clientId ||
            !clientSecret ||
            !tenantDomain}
          onclick={startServiceAccountOAuth}
        >
          {startServiceAccountOAuth.isLoading
            ? m.redirecting()
            : m.sign_in_with_microsoft()}
        </Button>
      {/if}
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
