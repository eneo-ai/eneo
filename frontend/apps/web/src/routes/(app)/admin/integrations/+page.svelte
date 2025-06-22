<script lang="ts">
  import { Page, Settings } from "$lib/components/layout";
  import type { PageProps } from "./$types";
  import IntegrationCard from "$lib/features/integrations/components/IntegrationCard.svelte";
  import IntegrationGrid from "$lib/features/integrations/components/IntegrationGrid.svelte";
  import { Button } from "@intric/ui";
  import { createAsyncState } from "$lib/core/helpers/createAsyncState.svelte";
  import type { TenantIntegration } from "@intric/intric-js";
  import TenantConnectedSplitButton from "$lib/features/integrations/components/TenantConnectedSplitButton.svelte";
  import { m } from "$lib/paraglide/messages";

  const { data }: PageProps = $props();

  let tenantIntegrations = $derived.by(() => {
    let integrations = $state(data.tenantIntegrations);
    return integrations;
  });

  const enableIntegration = createAsyncState(async (integration: TenantIntegration) => {
    Object.assign(integration, await data.intric.integrations.tenant.enable(integration));
  });

  function onDisable(integration: TenantIntegration) {
    integration.is_linked_to_tenant = false;
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
          description={m.knowledge_providers_description()}
        >
          <IntegrationGrid>
            {#each tenantIntegrations as integration (integration.integration_id)}
              <IntegrationCard {integration}>
                {#snippet action()}
                  {#if integration.is_linked_to_tenant}
                    <TenantConnectedSplitButton {integration} {onDisable}
                    ></TenantConnectedSplitButton>
                  {:else}
                    <Button variant="primary" onclick={() => enableIntegration(integration)}
                      >{m.enable_integration()}</Button
                    >
                  {/if}
                {/snippet}
              </IntegrationCard>
            {/each}
          </IntegrationGrid>
        </Settings.Row>
      </Settings.Group>
    </Settings.Page>
  </Page.Main>
</Page.Root>
