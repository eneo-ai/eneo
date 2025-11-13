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

  let { openController }: { openController: Writable<boolean> } = $props();

  const intric = getIntric();

  // Form state
  let clientId = $state("");
  let clientSecret = $state("");
  let tenantDomain = $state("");
  let existingConfig = $state<TenantSharePointAppPublic | null>(null);
  let testResult = $state<TenantAppTestResult | null>(null);

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
            label={m.tenant_domain()}
            bind:value={tenantDomain}
            required
            placeholder="contoso.onmicrosoft.com"
            description={m.tenant_domain_description()}
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
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
