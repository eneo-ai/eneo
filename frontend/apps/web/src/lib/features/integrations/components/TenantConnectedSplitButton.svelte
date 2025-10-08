<script lang="ts">
  import { createAsyncState } from "$lib/core/helpers/createAsyncState.svelte";
  import { getIntric } from "$lib/core/Intric";
  import { IconCancel } from "@intric/icons/cancel";
  import { IconChevronDown } from "@intric/icons/chevron-down";
  import { type TenantIntegration } from "@intric/intric-js";
  import { Button, Dialog, Dropdown } from "@intric/ui";
  import { writable } from "svelte/store";
  import { m } from "$lib/paraglide/messages";

  type Props = {
    integration: TenantIntegration;
    onDisable?: (integration: TenantIntegration) => void;
  };

  let { integration, onDisable }: Props = $props();

  const intric = getIntric();
  const showDisconnectDialog = writable(false);

  const disableIntegration = createAsyncState(async () => {
    const { id } = integration;
    if (id == null) return;
    try {
      await intric.integrations.tenant.disable({ id });
      onDisable?.(integration);
      $showDisconnectDialog = false;
    } catch (e) {
      console.error(e);
    }
  });
</script>

<div class="flex w-full gap-[1px]">
  <div
    class="border-positive-stronger bg-positive-default text-on-fill hover:bg-positive-stronger flex w-full cursor-default items-center justify-center rounded-l-lg border"
  >
    {m.enabled()}
  </div>
  <Dropdown.Root gutter={2} arrowSize={0} placement="bottom-end">
    <Dropdown.Trigger asFragment let:trigger>
      <Button padding="icon" variant="positive" is={trigger} class="!rounded-l-none !rounded-r-lg"
        ><IconChevronDown></IconChevronDown></Button
      >
    </Dropdown.Trigger>
    <Dropdown.Menu let:item>
      <Button is={item} onclick={() => ($showDisconnectDialog = true)} variant="destructive">
        <IconCancel></IconCancel>
        {m.disable_integration()}</Button
      >
    </Dropdown.Menu>
  </Dropdown.Root>
</div>

<Dialog.Root openController={showDisconnectDialog}>
  <Dialog.Content>
    <Dialog.Title>{m.disable_name_integration({ name: integration.name })}</Dialog.Title>
    <Dialog.Description>
      {m.do_you_really_want_to_disable_integration_for_name({ name: integration.name })}<br /><br />{m.disabling_integration_will_disconnect()}
    </Dialog.Description>

    <Dialog.Controls let:close>
      <Button is={close}>{m.cancel()}</Button>
      <Button on:click={disableIntegration} variant="destructive">
        {disableIntegration.isLoading ? m.loading() : m.disable()}
      </Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
