<script lang="ts">
  import { getEneo } from "$lib/core/Eneo";
  import { IconCancel } from "@eneo/icons/cancel";
  import { IconChevronDown } from "@eneo/icons/chevron-down";
  import { type UserIntegration } from "@eneo/eneo-js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu/index.js";
  import { dialogLayout } from "$lib/components/dialogLayout.js";
  import { m } from "$lib/paraglide/messages";
  import { toast } from "$lib/components/toast";

  type Props = {
    integration: UserIntegration;
    onDisconnect?: (integration: UserIntegration) => void;
  };

  const { integration, onDisconnect }: Props = $props();
  const eneo = getEneo();
  let showDisconnectDialog = $state(false);

  async function disconnect() {
    const { id } = integration;
    if (!id) {
      toast.warning(m.integration_not_setup_correctly());
      return;
    }
    showDisconnectDialog = false;
    await eneo.integrations.user.disconnect({ id });
    onDisconnect?.(integration);
  }
</script>

<div class="flex w-full gap-[1px]">
  <div
    class="border-positive-stronger bg-positive-default text-on-fill hover:bg-positive-stronger flex w-full cursor-default items-center justify-center rounded-l-lg border"
  >
    {m.connected()}
  </div>
  <DropdownMenu.Root>
    <DropdownMenu.Trigger>
      {#snippet child({ props })}
        <Button
          {...props}
          size="icon"
          class="bg-positive-default hover:bg-positive-stronger aria-expanded:bg-positive-stronger rounded-l-none"
          aria-label={m.actions()}><IconChevronDown></IconChevronDown></Button
        >
      {/snippet}
    </DropdownMenu.Trigger>
    <DropdownMenu.Content align="end">
      <DropdownMenu.Item variant="destructive" onSelect={() => (showDisconnectDialog = true)}>
        <IconCancel></IconCancel>
        {m.disconnect_integration()}
      </DropdownMenu.Item>
    </DropdownMenu.Content>
  </DropdownMenu.Root>
</div>

<AlertDialog.Root bind:open={showDisconnectDialog}>
  <AlertDialog.Content class={dialogLayout.content("dynamic")}>
    <AlertDialog.Header class={dialogLayout.header}>
      <AlertDialog.Title>{m.disconnect_name({ name: integration.name })}</AlertDialog.Title>
      <AlertDialog.Description>
        {m.do_you_really_want_to_disconnect_name({ name: integration.name })}
      </AlertDialog.Description>
    </AlertDialog.Header>
    <AlertDialog.Footer class={dialogLayout.footer}>
      <AlertDialog.Cancel>{m.cancel()}</AlertDialog.Cancel>
      <Button variant="destructive" onclick={disconnect}>{m.disconnect()}</Button>
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>
