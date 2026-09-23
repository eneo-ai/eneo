<script lang="ts">
  import { type AppRun } from "@eneo/eneo-js";
  import { IconTrash } from "@eneo/icons/trash";
  import { IconEllipsis } from "@eneo/icons/ellipsis";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu/index.js";
  import { dialogLayout } from "$lib/components/dialogLayout.js";
  import { getEneo } from "$lib/core/Eneo";
  import { getResultTitle } from "$lib/features/apps/getResultTitle";
  import { m } from "$lib/paraglide/messages";
  import { toastError } from "$lib/core/errors";

  export let result: Pick<AppRun, "id" | "input">;
  export let onResultDeleted: ((result: Pick<AppRun, "id" | "input">) => void) | undefined =
    undefined;

  const eneo = getEneo();

  let isProcessing = false;
  async function deleteResult() {
    isProcessing = true;
    try {
      await eneo.apps.runs.delete(result);
      onResultDeleted?.(result);
      showDeleteDialog = false;
    } catch (e) {
      toastError(e, m.could_not_delete_result());
      console.error(e);
    }
    isProcessing = false;
  }

  let showDeleteDialog = false;
</script>

<DropdownMenu.Root>
  <DropdownMenu.Trigger>
    {#snippet child({ props })}
      <Button {...props} variant="ghost" size="icon" aria-label={m.actions()}>
        <IconEllipsis />
      </Button>
    {/snippet}
  </DropdownMenu.Trigger>
  <DropdownMenu.Content align="end">
    <DropdownMenu.Item
      variant="destructive"
      onSelect={() => {
        showDeleteDialog = true;
      }}
    >
      <IconTrash size="sm" />{m.delete()}
    </DropdownMenu.Item>
  </DropdownMenu.Content>
</DropdownMenu.Root>

<AlertDialog.Root bind:open={showDeleteDialog}>
  <AlertDialog.Content class={dialogLayout.content("small")}>
    <AlertDialog.Header class={dialogLayout.header}>
      <AlertDialog.Title>{m.delete_result()}</AlertDialog.Title>
      <AlertDialog.Description
        >{m.confirm_delete_result({ resultTitle: getResultTitle(result) })}</AlertDialog.Description
      >
    </AlertDialog.Header>
    <AlertDialog.Footer class={dialogLayout.footer}>
      <AlertDialog.Cancel>{m.cancel()}</AlertDialog.Cancel>
      <Button variant="destructive" onclick={deleteResult}
        >{isProcessing ? m.deleting() : m.delete()}</Button
      >
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>
