<script lang="ts">
  import { getFlowsManager } from "$lib/features/flows/FlowsManager";
  import { IconTrash } from "@intric/icons/trash";
  import { IconEllipsis } from "@intric/icons/ellipsis";
  import type { FlowSparse } from "@intric/intric-js";
  import { Button, Dialog, Dropdown } from "@intric/ui";
  import { m } from "$lib/paraglide/messages";

  export let flow: FlowSparse;

  const flowsManager = getFlowsManager();

  let isProcessing = false;
  let showDeleteDialog: Dialog.OpenState;

  async function handleDelete() {
    isProcessing = true;
    try {
      if (flow.id) {
        await flowsManager.deleteFlow(flow.id);
      }
      $showDeleteDialog = false;
    } catch (e) {
      console.error(e);
    }
    isProcessing = false;
  }
</script>

<Dropdown.Root>
  <Dropdown.Trigger asFragment let:trigger>
    <Button is={trigger} padding="icon" variant="on-fill">
      <IconEllipsis />
    </Button>
  </Dropdown.Trigger>
  <Dropdown.Menu let:item>
    <Button is={item} variant="destructive" on:click={() => { $showDeleteDialog = true; }} padding="icon-leading">
      <IconTrash size="sm" />
      {m.delete()}
    </Button>
  </Dropdown.Menu>
</Dropdown.Root>

<Dialog.Root alert bind:isOpen={showDeleteDialog}>
  <Dialog.Content width="small">
    <Dialog.Title>{m.delete()}</Dialog.Title>
    <Dialog.Description>{m.flow_delete_confirm()}</Dialog.Description>
    <Dialog.Controls let:close>
      <Button is={close}>{m.cancel()}</Button>
      <Button variant="destructive" on:click={handleDelete}>
        {isProcessing ? m.deleting() : m.delete()}
      </Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
