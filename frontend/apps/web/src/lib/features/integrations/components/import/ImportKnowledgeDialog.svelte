<script lang="ts">
  import { Button, Dialog, Tooltip } from "@intric/ui";
  import { getAvailableIntegrations } from "../../AvailableIntegrations";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { writable } from "svelte/store";
  import type { UserIntegration } from "@intric/intric-js";
  import ImportBackdrop from "./ImportBackdrop.svelte";
  import IntegrationVendorIcon from "../IntegrationVendorIcon.svelte";
  import { integrationData } from "../../IntegrationData";
  import { m } from "$lib/paraglide/messages";
  import { localizeHref } from "$lib/paraglide/runtime";

  const contextIntegrations = getAvailableIntegrations();
  const { state: { currentSpace } } = getSpacesManager();

  let isPersonalSpace = $derived($currentSpace.personal);
  let isOrgSpace = $derived($currentSpace.organization);

  // Filter integrations based on current space type
  // This ensures the dialog always shows the correct integrations even if space changes
  let availableIntegrations = $derived.by(() => {
    // Guard against undefined/empty context data (race condition on initial load)
    const integrations = contextIntegrations || [];

    if (isPersonalSpace) {
      // Personal spaces: only user_oauth integrations
      return integrations.filter(i => i.auth_type === "user_oauth" || !i.connected);
    } else if (isOrgSpace) {
      // Organization spaces: only tenant_app integrations
      return integrations.filter(i => i.connected && i.auth_type === "tenant_app");
    }

    // Fallback: all connected integrations
    return integrations.filter(i => i.connected);
  });

  // Check if integrations are still loading
  let isLoading = $derived(availableIntegrations.length === 0 && contextIntegrations !== undefined);

  let showSelectDialog = writable(false);
  let showImportDialog = writable(false);

  // Reset selected integration when available integrations change
  let selectedIntegration = $state<UserIntegration | null>(null);
  $effect(() => {
    // Find first connected integration when space or integrations change
    const firstConnected = availableIntegrations.find(({ connected }) => connected) ?? null;
    if (!selectedIntegration || !availableIntegrations.some(i => i.id === selectedIntegration.id)) {
      selectedIntegration = firstConnected;
    }
  });

  function goImport() {
    $showSelectDialog = false;
    $showImportDialog = true;
    setTimeout(() => {}, 0);
  }

  function goBack() {
    $showImportDialog = false;
    setTimeout(() => {
      $showSelectDialog = true;
    }, 0);
  }
</script>

{#snippet integrationSelector(integration: UserIntegration)}
  <div class="selector gap-4" data-selected={selectedIntegration?.id === integration.id}>
    <IntegrationVendorIcon size="lg" type={integration.integration_type}></IntegrationVendorIcon>
    <div class="flex w-full flex-col items-start justify-end text-left">
      <div class="flex items-center gap-2">
        <span class="text-lg font-extrabold">{integration.name}</span>
        {#if integration.auth_type === "tenant_app"}
          <span class="text-accent-stronger bg-accent-dimmer border-accent-default rounded px-1.5 py-0.5 text-xs font-semibold border">
            Organization
          </span>
        {:else}
          <span class="text-secondary bg-dimmer border-default rounded px-1.5 py-0.5 text-xs font-semibold border">
            Personal
          </span>
        {/if}
      </div>
      <span class="text-dynamic-stronger line-clamp-2"
        >{integrationData[integration.integration_type].importHint}</span
      >
    </div>
  </div>
{/snippet}

<Dialog.Root openController={showSelectDialog}>
  <Dialog.Trigger asFragment let:trigger>
    <Button variant="primary" is={trigger}>{m.import_knowledge()}</Button>
  </Dialog.Trigger>

  <Dialog.Content width="dynamic">
    <Dialog.Section class="relative mt-2 -mb-0.5">
      <div class="absolute top-0 right-0 h-52 w-72 overflow-hidden">
        <ImportBackdrop></ImportBackdrop>
      </div>
      <div class=" border-default flex w-full flex-col px-10 pt-12 pb-10">
        <h3 class="px-4 pb-1 text-2xl font-extrabold">{m.import_knowledge()}</h3>
        <p class="text-secondary max-w-[60ch] pr-48 pl-4">
          {#if isPersonalSpace}
            {m.import_knowledge_from_third_party()}
            <a href={localizeHref("/account/integrations?tab=providers")} class="underline">{m.personal_account()}</a>.
          {:else}
            Import knowledge from organization-wide integrations. Configure them in
            <a href={localizeHref("/admin/integrations?tab=providers")} class="underline">admin settings</a>.
          {/if}
        </p>
        <!-- <div class="h-8"></div> -->
        <div class=" border-dimmer mt-14 mb-6 border-t"></div>

        <div class="flex flex-col gap-2">
          {#if isLoading}
            <div class="text-secondary flex items-center justify-center py-8 text-center">
              <p>Loading integrations...</p>
            </div>
          {:else if availableIntegrations.length === 0}
            <div class="text-secondary flex flex-col items-center justify-center py-8 text-center">
              <p class="mb-2">No integrations available.</p>
              <p class="text-sm">
                {#if isPersonalSpace}
                  <a href="/account/integrations?tab=providers" class="underline">Connect a personal integration</a>
                  to get started.
                {:else}
                  Configure a
                  <a href="/admin/integrations?tab=providers" class="underline">tenant app integration</a>
                  in admin settings.
                {/if}
              </p>
            </div>
          {:else}
            {#each availableIntegrations as integration (integration.id)}
              {#if integration.connected}
                <button onclick={() => (selectedIntegration = integration)}>
                  {@render integrationSelector(integration)}
                </button>
              {:else}
                <Tooltip
                  text={integration.connected
                    ? undefined
                    : m.enable_integration_in_account_settings({ name: integration.name })}
                  class="cursor-not-allowed opacity-70 *:pointer-events-none"
                >
                  {@render integrationSelector(integration)}
                </Tooltip>
              {/if}
            {/each}
          {/if}
        </div>
      </div>
    </Dialog.Section>

    <Dialog.Controls let:close>
      <Button is={close}>{m.cancel()}</Button>
      <Button variant="primary" onclick={goImport} disabled={selectedIntegration === null}
        >{m.continue()}</Button
      >
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>

{#if selectedIntegration}
  {@const { ImportDialog } = integrationData[selectedIntegration.integration_type]}
  <ImportDialog {goBack} openController={showImportDialog} integration={selectedIntegration}
  ></ImportDialog>
{/if}

<style lang="postcss">
  @reference "@intric/ui/styles";
  .selector {
    @apply border-default flex h-[5.25rem] flex-grow items-center justify-between overflow-hidden rounded-lg border p-3 pr-2 shadow;
  }

  .selector:hover {
    @apply border-stronger bg-hover-default text-primary ring-default cursor-pointer ring-2;
  }

  [data-selected="true"].selector {
    @apply border-accent-default bg-accent-dimmer text-accent-stronger shadow-accent-dimmer ring-accent-default shadow-lg ring-1 focus:outline-offset-4;
  }
</style>
