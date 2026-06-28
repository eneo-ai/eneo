<script lang="ts">
  import { getEneo } from "$lib/core/Eneo";
  import { IconCancel } from "@eneo/icons/cancel";
  import { IconChevronDown } from "@eneo/icons/chevron-down";
  import { type UserIntegration } from "@eneo/eneo-js";
  import { Button, Dialog, Dropdown } from "@eneo/ui";
  import { writable } from "svelte/store";
  import { m } from "$lib/paraglide/messages";
  import { toast } from "$lib/components/toast";

  type Props = {
    integration: UserIntegration;
    onDisconnect?: (integration: UserIntegration) => void;
  };

  const { integration, onDisconnect }: Props = $props();
  const eneo = getEneo();
  const showDisconnectDialog = writable(false);

  async function disconnect() {
    const { id } = integration;
    if (!id) {
      toast.warning(m.integration_not_setup_correctly());
      return;
    }
    await eneo.integrations.user.disconnect({ id });
    onDisconnect?.(integration);
    $showDisconnectDialog = false;
  }
</script>

<div class="flex w-full gap-[1px]">
  <div
    class="border-positive-stronger bg-positive-default text-on-fill hover:bg-positive-stronger flex w-full cursor-default items-center justify-center rounded-l-lg border"
  >
    {m.connected()}
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
        {m.disconnect_integration()}</Button
      >
    </Dropdown.Menu>
  </Dropdown.Root>
</div>

<Dialog.Root openController={showDisconnectDialog} alert>
  <Dialog.Content width="dynamic">
    <Dialog.Title>{m.disconnect_name({ name: integration.name })}</Dialog.Title>

    <Dialog.Description
      >{m.do_you_really_want_to_disconnect_name({ name: integration.name })}</Dialog.Description
    >
    <Dialog.Controls let:close>
      <Button is={close}>{m.cancel()}</Button>
      <Button is={close} onclick={disconnect} variant="destructive">{m.disconnect()}</Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
