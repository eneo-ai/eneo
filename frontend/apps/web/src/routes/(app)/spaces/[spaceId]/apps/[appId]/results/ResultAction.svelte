<script lang="ts">
  import { type AppRun } from "@intric/intric-js";
  import { IconTrash } from "@intric/icons/trash";
  import { IconEllipsis } from "@intric/icons/ellipsis";
  import { Button, Dialog, Dropdown } from "@intric/ui";
  import { getIntric } from "$lib/core/Intric";
  import { getResultTitle } from "$lib/features/apps/getResultTitle";
  import { m } from "$lib/paraglide/messages";

  export let result: Pick<AppRun, "id" | "input">;
  export let onResultDeleted: ((result: Pick<AppRun, "id" | "input">) => void) | undefined =
    undefined;

  const intric = getIntric();

  let isProcessing = false;
  async function deleteResult() {
    isProcessing = true;
    try {
      await intric.apps.runs.delete(result);
      onResultDeleted?.(result);
      $showDeleteDialog = false;
    } catch (e) {
      alert(m.could_not_delete_result());
      console.error(e);
    }
    isProcessing = false;
  }

  let showDeleteDialog: Dialog.OpenState;
</script>

<Dropdown.Root>
  <Dropdown.Trigger let:trigger asFragment>
    <Button is={trigger} padding="icon">
      <IconEllipsis />
    </Button>
  </Dropdown.Trigger>
  <Dropdown.Menu let:item>
    <Button
      is={item}
      variant="destructive"
      on:click={() => {
        $showDeleteDialog = true;
      }}
      padding="icon-leading"
    >
      <IconTrash size="sm" />{m.delete()}</Button
    >
  </Dropdown.Menu>
</Dropdown.Root>

<Dialog.Root alert bind:isOpen={showDeleteDialog}>
  <Dialog.Content width="small">
    <Dialog.Title>{m.delete_result()}</Dialog.Title>
    <Dialog.Description
      >{m.confirm_delete_result({ resultTitle: getResultTitle(result) })}</Dialog.Description
    >
    <Dialog.Controls let:close>
      <Button is={close}>{m.cancel()}</Button>
      <Button variant="destructive" on:click={deleteResult}
        >{isProcessing ? m.deleting() : m.delete()}</Button
      >
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
