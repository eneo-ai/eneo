<script lang="ts">
  import { Button, Dialog, Tooltip } from "@intric/ui";
  import { getAvailableIntegrations } from "../../AvailableIntegrations";
  import { writable } from "svelte/store";
  import type { UserIntegration } from "@intric/intric-js";
  import ImportBackdrop from "./ImportBackdrop.svelte";
  import IntegrationVendorIcon from "../IntegrationVendorIcon.svelte";
  import { integrationData } from "../../IntegrationData";
  import { m } from "$lib/paraglide/messages";

  const availableIntegrations = getAvailableIntegrations();

  let showSelectDialog = writable(false);
  let showImportDialog = writable(false);

  let selectedIntegration = $state<UserIntegration | null>(
    availableIntegrations.find(({ connected }) => connected) ?? null
  );

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
      <span class="text-lg font-extrabold">{integration.name}</span>
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
          {m.import_knowledge_from_third_party()}
          <a href="/account/integrations" class="underline">{m.personal_account()}</a>.
        </p>
        <!-- <div class="h-8"></div> -->
        <div class=" border-dimmer mt-14 mb-6 border-t"></div>

        <div class="flex flex-col gap-2">
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
