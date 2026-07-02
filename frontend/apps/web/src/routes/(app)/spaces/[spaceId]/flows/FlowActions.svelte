<script lang="ts">
  import { getFlowsManager } from "$lib/features/flows/FlowsManager";
  import { IconTrash } from "@eneo/icons/trash";
  import { IconEllipsis } from "@eneo/icons/ellipsis";
  import type { FlowSparse } from "@eneo/eneo-js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu/index.js";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import { m } from "$lib/paraglide/messages";

  let {
    flow
  }: {
    flow: FlowSparse;
  } = $props();

  const flowsManager = getFlowsManager();

  let isProcessing = $state(false);
  let showDeleteDialog = $state(false);

  async function handleDelete() {
    isProcessing = true;
    try {
      if (flow.id) {
        await flowsManager.deleteFlow(flow.id);
      }
      showDeleteDialog = false;
    } catch (e) {
      console.error(e);
    }
    isProcessing = false;
  }
</script>

<DropdownMenu.Root>
  <DropdownMenu.Trigger>
    {#snippet child({ props })}
      <Button
        {...props}
        size="icon-sm"
        variant="ghost"
        class="text-muted hover:text-primary"
        aria-label={m.actions()}
        title={m.actions()}
      >
        <IconEllipsis />
      </Button>
    {/snippet}
  </DropdownMenu.Trigger>
  <DropdownMenu.Content align="end" class="min-w-[10rem]">
    <DropdownMenu.Item
      variant="destructive"
      onclick={() => {
        showDeleteDialog = true;
      }}
    >
      <IconTrash class="size-4" />
      {m.delete()}
    </DropdownMenu.Item>
  </DropdownMenu.Content>
</DropdownMenu.Root>

<AlertDialog.Root bind:open={showDeleteDialog}>
  <AlertDialog.Content>
    <AlertDialog.Header>
      <AlertDialog.Title>{m.delete()}</AlertDialog.Title>
      <AlertDialog.Description>{m.flow_delete_confirm()}</AlertDialog.Description>
    </AlertDialog.Header>
    <AlertDialog.Footer>
      <AlertDialog.Cancel>{m.cancel()}</AlertDialog.Cancel>
      <AlertDialog.Action variant="destructive" disabled={isProcessing} onclick={handleDelete}>
        {isProcessing ? m.deleting() : m.delete()}
      </AlertDialog.Action>
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>
