<script lang="ts">
  import { createAsyncState } from "$lib/core/helpers/createAsyncState.svelte";
  import { getIntric } from "$lib/core/Intric";
  import type { TenantIntegration } from "@intric/intric-js";
  import { Button, Dialog } from "@intric/ui";
  import { m } from "$lib/paraglide/messages";

  type Props = {
    integration: TenantIntegration;
    update: (integration: Partial<TenantIntegration>) => void;
  };

  let { integration, update }: Props = $props();

  const intric = getIntric();

  const disableIntegration = createAsyncState(async () => {
    const { id } = integration;
    if (id == null) return;
    try {
      await intric.integrations.tenant.disable({ id });
      $isOpen = false;

      setTimeout(() => {
        update({ is_linked_to_tenant: false });
      }, 250);
    } catch (e) {
      console.error(e);
    }
  });

  let isOpen = $state<Dialog.OpenState>();
</script>

<Dialog.Root bind:isOpen>
  <Dialog.Trigger asFragment let:trigger>
    <Button variant="destructive" is={trigger}>{m.disable_integration()}</Button>
  </Dialog.Trigger>

  <Dialog.Content>
    <Dialog.Title>{m.disable_name_integration({ name: integration.name })}</Dialog.Title>
    <Dialog.Description>
      {m.do_you_really_want_to_disable_integration_for_name({ name: integration.name })}<br /><br />{m.disabling_integration_warning()}
    </Dialog.Description>

    <Dialog.Controls let:close>
      <Button is={close}>{m.cancel()}</Button>
      <Button on:click={disableIntegration} variant="destructive">
        {disableIntegration.isLoading ? m.loading() : m.disable()}
      </Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
