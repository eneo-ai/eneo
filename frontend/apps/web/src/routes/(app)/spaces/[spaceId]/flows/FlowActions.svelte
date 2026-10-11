<script lang="ts">
  import { getFlowsManager } from "$lib/features/flows/FlowsManager";
  import { IconTrash } from "@eneo/icons/trash";
  import { IconEllipsis } from "@eneo/icons/ellipsis";
  import { type FlowSparse } from "@eneo/eneo-js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu/index.js";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { toast } from "$lib/components/toast";
  import { m } from "$lib/paraglide/messages";
  import { getFlowRuntimeErrorMessage } from "$lib/features/flows/flowRuntimeErrorMapping";

  let {
    flow
  }: {
    flow: FlowSparse;
  } = $props();

  const flowsManager = getFlowsManager();

  let isProcessing = $state(false);
  let showDeleteDialog = $state(false);
  // Null until read. A deleted flow can no longer be changed, so the person
  // deleting it is told when its runs' evidence could then never be downloaded.
  let evidenceExportAllowed = $state<boolean | null>(null);

  async function openDeleteDialog() {
    evidenceExportAllowed = null;
    showDeleteDialog = true;
    try {
      evidenceExportAllowed = await flowsManager.readEvidenceExportAllowed(flow.id);
    } catch {
      // Not knowing is no reason to stay silent about something irreversible.
      evidenceExportAllowed = false;
    }
  }

  async function handleDelete() {
    isProcessing = true;
    try {
      if (flow.id) {
        await flowsManager.deleteFlow(flow.id);
      }
      showDeleteDialog = false;
    } catch (error) {
      toast.error(getFlowRuntimeErrorMessage(error, m.request_failed()));
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
        class="text-secondary hover:text-primary"
        aria-label={m.actions()}
      >
        <IconEllipsis />
      </Button>
    {/snippet}
  </DropdownMenu.Trigger>
  <DropdownMenu.Content align="end" class="min-w-[10rem]">
    <DropdownMenu.Item variant="destructive" onclick={() => void openDeleteDialog()}>
      <IconTrash class="size-4" />
      {m.delete()}
    </DropdownMenu.Item>
  </DropdownMenu.Content>
</DropdownMenu.Root>

<AlertDialog.Root bind:open={showDeleteDialog}>
  <AlertDialog.Content>
    <AlertDialog.Header>
      <AlertDialog.Title>{m.flow_list_delete_title({ name: flow.name })}</AlertDialog.Title>
      <AlertDialog.Description>{m.flow_delete_confirm()}</AlertDialog.Description>
    </AlertDialog.Header>
    {#if evidenceExportAllowed === false}
      <Alert.Root class="border-warning-default/30 bg-warning-dimmer text-warning-stronger">
        <Alert.Description class="text-warning-stronger">
          {m.flow_delete_evidence_export_off()}
        </Alert.Description>
      </Alert.Root>
    {/if}
    <AlertDialog.Footer class="border-border">
      <AlertDialog.Cancel>{m.cancel()}</AlertDialog.Cancel>
      <AlertDialog.Action
        variant="destructive"
        disabled={isProcessing || evidenceExportAllowed === null}
        onclick={handleDelete}
      >
        {isProcessing ? m.deleting() : m.delete()}
      </AlertDialog.Action>
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>
