<script lang="ts">
  import { Page, Settings } from "$lib/components/layout";
  import type { PageProps } from "./$types";
  import IntegrationCard from "$lib/features/integrations/components/IntegrationCard.svelte";
  import IntegrationGrid from "$lib/features/integrations/components/IntegrationGrid.svelte";
  import { Button } from "@intric/ui";
  import { createAsyncState } from "$lib/core/helpers/createAsyncState.svelte";
  import type { TenantIntegration } from "@intric/intric-js";
  import { m } from "$lib/paraglide/messages";
  import SharePointAppConfigDialog from "$lib/features/integrations/sharepoint/SharePointAppConfigDialog.svelte";
  import SharePointAppDeleteDialog from "$lib/features/integrations/sharepoint/SharePointAppDeleteDialog.svelte";
  import SharePointSubscriptions from "./SharePointSubscriptions.svelte";
  import { writable } from "svelte/store";

  const { data }: PageProps = $props();

  let tenantIntegrations = $derived.by(() => {
    // Filter out integrations that are not yet ready (e.g., Confluence)
    let integrations = $state(data.tenantIntegrations.filter(i => i.integration_type === "sharepoint"));
    return integrations;
  });

  // SharePoint app configuration dialog
  let showSharePointConfigDialog = writable(false);
  let showDeleteAppDialog = writable(false);
  let sharePointConfigStatus = $state<"loading" | "configured" | "not_configured">("loading");
  let showWebhookManagement = $state(false);

  // Load SharePoint config status
  const loadSharePointStatus = createAsyncState(async () => {
    try {
      const config = await data.intric.client.fetch("/api/v1/admin/sharepoint/app", {
        method: "get",
        params: {}
      });
      sharePointConfigStatus = config ? "configured" : "not_configured";
    } catch (error) {
      console.error("Failed to load SharePoint config status:", error);
      sharePointConfigStatus = "not_configured";
    }
  });

  // Load status on mount
  $effect(() => {
    loadSharePointStatus();
  });

  // Reload status when dialog closes
  $effect(() => {
    if (!$showSharePointConfigDialog) {
      loadSharePointStatus();
    }
  });

  function isSharePoint(integration: TenantIntegration): boolean {
    return integration.integration_type === "sharepoint";
  }
</script>

<svelte:head>
  <title>Eneo.ai – {m.admin()} – {m.integrations()}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title={m.integrations()}></Page.Title>
  </Page.Header>
  <Page.Main>
    <Settings.Page>
      <Settings.Group title={m.configure_integrations()}>
        <Settings.Row
          fullWidth
          title={m.knowledge_providers()}
          description={m.admin_integrations_description()}
        >
          <IntegrationGrid>
            {#each tenantIntegrations as integration (integration.integration_id)}
              <IntegrationCard {integration}>
                {#snippet action()}
                  <div class="flex flex-col gap-2">
                    {#if isSharePoint(integration)}
                      <!-- SharePoint: Show config status and configure button -->
                      {#if sharePointConfigStatus === "loading"}
                        <span class="inline-flex items-center rounded-md bg-gray-100 px-2 py-1 text-xs font-medium text-gray-700">
                          {m.integration_status_loading()}
                        </span>
                      {:else if sharePointConfigStatus === "configured"}
                        <span class="inline-flex items-center rounded-md bg-green-100 px-2 py-1 text-xs font-medium text-green-800">
                          {m.integration_status_configured()}
                        </span>
                      {:else}
                        <span class="inline-flex items-center rounded-md bg-gray-100 px-2 py-1 text-xs font-medium text-gray-700">
                          {m.integration_status_not_configured()}
                        </span>
                      {/if}

                      <Button
                        variant={sharePointConfigStatus === "configured" ? "secondary" : "primary"}
                        onclick={() => $showSharePointConfigDialog = true}
                      >
                        {sharePointConfigStatus === "configured" ? m.update_configuration() : m.configure_sharepoint_app()}
                      </Button>

                      {#if sharePointConfigStatus === "configured"}
                        <Button
                          variant="secondary"
                          onclick={() => showWebhookManagement = !showWebhookManagement}
                        >
                          {showWebhookManagement ? m.hide_webhooks() : m.manage_webhooks()}
                        </Button>
                        <Button
                          variant="destructive"
                          onclick={() => {
                            console.log("Delete button clicked");
                            $showDeleteAppDialog = true;
                            console.log("showDeleteAppDialog set to:", $showDeleteAppDialog);
                          }}
                        >
                          {m.delete_sharepoint_app()}
                        </Button>
                        <p class="text-xs text-gray-600 mt-1">
                          {m.organization_access_enabled()}
                        </p>
                      {:else}
                        <p class="text-xs text-gray-600 mt-1">
                          {m.configure_azure_ad_app()}
                        </p>
                      {/if}
                    {:else}
                      <!-- Other integrations: Coming soon -->
                      <span class="inline-flex items-center rounded-md bg-gray-100 px-2 py-1 text-xs font-medium text-gray-700">
                        {m.coming_soon()}
                      </span>
                      <p class="text-xs text-gray-600 mt-1">
                        {m.configuration_options_available_soon()}
                      </p>
                    {/if}
                  </div>
                {/snippet}
              </IntegrationCard>
            {/each}
          </IntegrationGrid>

          <!-- SharePoint Webhook Management (expanded when button clicked) -->
          {#if showWebhookManagement && sharePointConfigStatus === "configured"}
            <div class="mt-6 rounded-lg border border-border bg-background p-6">
              <SharePointSubscriptions intric={data.intric} />
            </div>
          {/if}
        </Settings.Row>

        <!-- Information about personal vs organization integrations -->
        <Settings.Row
          fullWidth
          title={m.personal_integrations()}
          description={m.personal_integrations_description()}
        >
          <div class="rounded-md border border-blue-200 bg-blue-50 p-4">
            <div class="flex items-start gap-3">
              <div class="flex-shrink-0">
                <svg class="h-5 w-5 text-blue-600" viewBox="0 0 20 20" fill="currentColor">
                  <path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a.75.75 0 000 1.5h.253a.25.25 0 01.244.304l-.459 2.066A1.75 1.75 0 0010.747 15H11a.75.75 0 000-1.5h-.253a.25.25 0 01-.244-.304l.459-2.066A1.75 1.75 0 009.253 9H9z" clip-rule="evenodd" />
                </svg>
              </div>
              <div class="flex-1 text-sm">
                <h3 class="font-medium text-blue-800">{m.how_integrations_work()}</h3>
                <ul class="mt-2 space-y-1 text-blue-700 list-disc list-inside">
                  <li>{m.personal_spaces_description()}</li>
                  <li>{m.shared_spaces_description()}</li>
                  <li>{m.no_person_dependency_description()}</li>
                </ul>
              </div>
            </div>
          </div>
        </Settings.Row>
      </Settings.Group>
    </Settings.Page>
  </Page.Main>
</Page.Root>

<SharePointAppConfigDialog openController={showSharePointConfigDialog} />
<SharePointAppDeleteDialog openController={showDeleteAppDialog} />
