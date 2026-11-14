<script lang="ts">
  import { untrack } from "svelte";
  import { writable } from "svelte/store";
  import Info from "@lucide/svelte/icons/info";
  import EllipsisVertical from "@lucide/svelte/icons/ellipsis-vertical";
  import RefreshCw from "@lucide/svelte/icons/refresh-cw";
  import Trash2 from "@lucide/svelte/icons/trash-2";
  import { Page, Settings } from "$lib/components/layout";
  import type { PageProps } from "./$types";
  import IntegrationCard from "$lib/features/integrations/components/IntegrationCard.svelte";
  import IntegrationGrid from "$lib/features/integrations/components/IntegrationGrid.svelte";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu/index.js";
  import { createAsyncState } from "$lib/core/helpers/createAsyncState.svelte";
  import type { TenantIntegration, components } from "@eneo/eneo-js";
  import { m } from "$lib/paraglide/messages";
  import SharePointAppConfigDialog from "$lib/features/integrations/sharepoint/SharePointAppConfigDialog.svelte";
  import SharePointAuthHealth from "$lib/features/integrations/sharepoint/SharePointAuthHealth.svelte";
  import SharePointConnectionHealth from "$lib/features/integrations/sharepoint/SharePointConnectionHealth.svelte";
  import SharePointAppDeleteDialog from "$lib/features/integrations/sharepoint/SharePointAppDeleteDialog.svelte";
  import SharePointSetupFixtureLauncher from "$lib/features/integrations/sharepoint/SharePointSetupFixtureLauncher.svelte";
  import { SharePointSubscriptionList } from "$lib/features/integrations/sharepoint/SharePointSubscriptionList.svelte";
  import SharePointSubscriptions from "./SharePointSubscriptions.svelte";

  const { data }: PageProps = $props();

  let tenantIntegrations = $derived(
    data.tenantIntegrations.filter((i) => i.integration_type === "sharepoint")
  );

  let showSharePointConfigDialog = writable(false);
  let showDeleteAppDialog = writable(false);
  let sharePointConfigStatus = $state<"loading" | "configured" | "not_configured" | "error">(
    "loading"
  );
  let sharePointConfig = $state<components["schemas"]["TenantSharePointAppPublic"] | null>(null);
  let showWebhookManagement = $state(false);
  const subscriptionList = new SharePointSubscriptionList(untrack(() => data.eneo));

  const loadSharePointStatus = createAsyncState(async () => {
    // A reload keeps the configured view mounted, so open panels and a test result survive it.
    // Untracked: the effects that call this must not rerun when it stores the config.
    if (!untrack(() => sharePointConfig)) sharePointConfigStatus = "loading";
    try {
      const config = await data.eneo.client.fetch("/api/v1/admin/sharepoint/app", {
        method: "get"
      });
      sharePointConfig = config ?? null;
      sharePointConfigStatus = config ? "configured" : "not_configured";
    } catch {
      sharePointConfig = null;
      sharePointConfigStatus = "error";
    }
  });

  $effect(() => {
    loadSharePointStatus();
  });

  $effect(() => {
    if (!$showSharePointConfigDialog) loadSharePointStatus();
  });

  function handleAppDeleted() {
    showWebhookManagement = false;
    loadSharePointStatus();
  }

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
              <IntegrationCard {integration} tour="admin-integrations">
                {#snippet action()}
                  <div class="flex flex-col gap-2">
                    {#if isSharePoint(integration)}
                      <div class="flex flex-wrap items-center gap-2">
                        {#if sharePointConfigStatus === "loading"}
                          <Badge variant="secondary">{m.integration_status_loading()}</Badge>
                        {:else if sharePointConfigStatus === "configured"}
                          <Badge
                            class="bg-positive-dimmer text-positive-stronger border-transparent"
                          >
                            {m.integration_status_configured()}
                          </Badge>
                          {#if sharePointConfig}
                            <SharePointAuthHealth config={sharePointConfig} variant="badge" />
                          {/if}
                        {:else if sharePointConfigStatus === "error"}
                          <Badge variant="destructive">{m.integration_status_error()}</Badge>
                          <Button
                            variant="ghost"
                            size="icon-sm"
                            aria-label={m.retry()}
                            onclick={() => loadSharePointStatus()}
                          >
                            <RefreshCw aria-hidden="true" />
                          </Button>
                        {:else}
                          <Badge variant="outline">{m.integration_status_not_configured()}</Badge>
                        {/if}
                      </div>

                      <div class="flex min-w-0 items-center gap-2">
                        <Button
                          variant={sharePointConfigStatus === "configured" ? "outline" : "default"}
                          class="min-w-0 flex-1 truncate"
                          disabled={sharePointConfigStatus === "loading"}
                          onclick={() => ($showSharePointConfigDialog = true)}
                        >
                          {sharePointConfigStatus === "configured"
                            ? m.update_configuration()
                            : m.configure_sharepoint_app()}
                        </Button>

                        {#if sharePointConfigStatus === "configured"}
                          <DropdownMenu.Root>
                            <DropdownMenu.Trigger>
                              {#snippet child({ props })}
                                <Button
                                  {...props}
                                  variant="ghost"
                                  size="icon"
                                  aria-label={m.actions()}
                                >
                                  <EllipsisVertical aria-hidden="true" />
                                </Button>
                              {/snippet}
                            </DropdownMenu.Trigger>
                            <DropdownMenu.Content align="end">
                              <DropdownMenu.Item
                                variant="destructive"
                                onclick={() => ($showDeleteAppDialog = true)}
                              >
                                <Trash2 aria-hidden="true" />
                                {m.delete_sharepoint_app()}
                              </DropdownMenu.Item>
                            </DropdownMenu.Content>
                          </DropdownMenu.Root>
                        {/if}

                        {#if data.settings.sharepoint_fixture_mode_available}
                          <SharePointSetupFixtureLauncher />
                        {/if}
                      </div>

                      <p class="text-muted-foreground text-xs">
                        {sharePointConfigStatus === "configured"
                          ? m.organization_access_enabled()
                          : m.configure_azure_ad_app()}
                      </p>
                    {:else}
                      <Badge variant="secondary">{m.coming_soon()}</Badge>
                      <p class="text-muted-foreground text-xs">
                        {m.configuration_options_available_soon()}
                      </p>
                    {/if}
                  </div>
                {/snippet}
              </IntegrationCard>
            {/each}
          </IntegrationGrid>
        </Settings.Row>

        {#if sharePointConfigStatus === "configured" && sharePointConfig}
          <Settings.Row
            fullWidth
            title={m.sharepoint_health_row_title()}
            description={m.sharepoint_health_row_description()}
          >
            <SharePointConnectionHealth
              eneo={data.eneo}
              config={sharePointConfig}
              {subscriptionList}
              subscriptionsOpen={showWebhookManagement}
              onEdit={() => ($showSharePointConfigDialog = true)}
              onToggleSubscriptions={() => (showWebhookManagement = !showWebhookManagement)}
              onConfigChanged={() => loadSharePointStatus()}
            />
            {#if showWebhookManagement}
              <div class="border-default mt-4 rounded-lg border p-6">
                <SharePointSubscriptions eneo={data.eneo} {subscriptionList} />
              </div>
            {/if}
          </Settings.Row>
        {/if}

        <Settings.Row
          fullWidth
          title={m.personal_integrations()}
          description={m.personal_integrations_description()}
        >
          <Alert.Root>
            <Info aria-hidden="true" />
            <Alert.Title>{m.how_integrations_work()}</Alert.Title>
            <Alert.Description>
              <ul class="list-inside list-disc space-y-1">
                <li>{m.personal_spaces_description()}</li>
                <li>{m.shared_spaces_description()}</li>
                <li>{m.no_person_dependency_description()}</li>
              </ul>
            </Alert.Description>
          </Alert.Root>
        </Settings.Row>
      </Settings.Group>
    </Settings.Page>
  </Page.Main>
</Page.Root>

<SharePointAppConfigDialog
  openController={showSharePointConfigDialog}
  onDeleteRequested={() => ($showDeleteAppDialog = true)}
/>
<SharePointAppDeleteDialog openController={showDeleteAppDialog} onDeleted={handleAppDeleted} />
