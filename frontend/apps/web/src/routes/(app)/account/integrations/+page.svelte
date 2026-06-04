<script lang="ts">
  import { Page, Settings } from "$lib/components/layout";
  import { Button } from "@intric/ui";
  import type { PageProps } from "./$types";
  import { onDestroy } from "svelte";
  import { IntegrationAuthService } from "$lib/features/integrations/IntegrationAuthService.svelte";
  import IntegrationCard from "$lib/features/integrations/components/IntegrationCard.svelte";
  import IntegrationGrid from "$lib/features/integrations/components/IntegrationGrid.svelte";
  import type { UserIntegration } from "@intric/intric-js";
  import UserConnectedSplitButton from "$lib/features/integrations/components/UserConnectedSplitButton.svelte";
  import { getAppContext } from "$lib/core/AppContext";
  import { m } from "$lib/paraglide/messages";
  import { toastError } from "$lib/core/errors";
  import { resolve } from "$app/paths";
  import { writable } from "svelte/store";
  import WebsiteIntegrationConfigDialog from "$lib/features/integrations/website/WebsiteIntegrationConfigDialog.svelte";

  const { data }: PageProps = $props();

  const { user } = getAppContext();

  let integrations = $derived.by(() => {
    // Filter out integrations that are not yet ready (e.g., Confluence)
    let integrations = $state(
      data.myIntegrations.filter(
        (i) => i.integration_type === "sharepoint" || i.integration_type === "website"
      )
    );
    return integrations;
  });
  let showWebsiteConfigDialog = writable(false);

  const auth = new IntegrationAuthService({
    onConnected(result) {
      if (!result.success) {
        toastError(result.error);
        return;
      }

      const idx = integrations.findIndex(
        // Id does not exist on non-connected integrations
        ({ tenant_integration_id }) =>
          tenant_integration_id === result.integration.tenant_integration_id
      );

      if (idx === -1) return;
      integrations[idx] = result.integration;
    }
  });

  async function onDisconnect(integration: UserIntegration) {
    integration.connected = false;
  }

  onDestroy(() => {
    auth.destroy();
  });
</script>

<svelte:head>
  <title>Eneo.ai – {m.account()} – {m.my_integrations()}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title={m.my_integrations()}></Page.Title>
  </Page.Header>
  <Page.Main>
    <Settings.Page>
      <Settings.Group title={m.configure_your_integrations()}>
        <Settings.Row
          title={m.available_integrations()}
          fullWidth
          description={m.connect_account_description()}
        >
          {#if integrations.length > 0}
            <IntegrationGrid>
              {#each integrations as integration (`${integration.tenant_integration_id}-${integration.auth_type || "user_oauth"}`)}
                <IntegrationCard {integration}>
                  {#snippet action()}
                    {#if integration.tenant_app_configured === false}
                      <div class="flex flex-col gap-1">
                        <Button disabled variant="outlined">{m.not_available()}</Button>
                        <p class="text-secondary text-xs">
                          {m.contact_admin_to_configure()}
                        </p>
                      </div>
                    {:else if integration.connected && integration.id}
                      <UserConnectedSplitButton {integration} {onDisconnect}
                      ></UserConnectedSplitButton>
                    {:else if integration.integration_type === "website"}
                      <Button variant="primary" onclick={() => ($showWebsiteConfigDialog = true)}
                        >Manage integrations</Button
                      >
                    {:else}
                      <Button
                        on:click={() => {
                          auth.connect(integration);
                        }}
                        variant="primary"
                        >{auth.isConnecting(integration) ? m.connecting() : m.connect()}</Button
                      >
                    {/if}
                  {/snippet}
                </IntegrationCard>
              {/each}
            </IntegrationGrid>
          {:else}
            <div
              class="border-default text-muted flex h-48 w-full items-center justify-center rounded-lg border"
            >
              <div class="text-center">
                {m.no_integrations_enabled()}
                {#if user.hasPermission("admin")}
                  <br />{m.enable_integrations_admin()}
                  <a href={resolve("/admin/integrations?tab=providers")} class="underline"
                    >{m.integrations_admin_menu()}</a
                  >.
                {/if}
              </div>
            </div>
          {/if}
        </Settings.Row>
      </Settings.Group>
    </Settings.Page>
  </Page.Main>
</Page.Root>

<WebsiteIntegrationConfigDialog
  openController={showWebsiteConfigDialog}
  scope="me"
  title="Manage personal website integrations"
/>
