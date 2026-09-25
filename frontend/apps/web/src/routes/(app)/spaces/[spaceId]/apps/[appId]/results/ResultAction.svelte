<script lang="ts">
  import { type AppRun } from "@eneo/eneo-js";
  import { IconTrash } from "@eneo/icons/trash";
  import { IconEllipsis } from "@eneo/icons/ellipsis";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu/index.js";
  import ConfirmDialog from "$lib/components/ConfirmDialog.svelte";
  import { getEneo } from "$lib/core/Eneo";
  import { getResultTitle } from "$lib/features/apps/getResultTitle";
  import { m } from "$lib/paraglide/messages";

  export let result: Pick<AppRun, "id" | "input">;
  export let onResultDeleted: ((result: Pick<AppRun, "id" | "input">) => void) | undefined =
    undefined;

  const eneo = getEneo();

  async function deleteResult() {
    await eneo.apps.runs.delete(result);
    onResultDeleted?.(result);
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

<ConfirmDialog
  bind:open={showDeleteDialog}
  title={m.delete_result()}
  description={m.confirm_delete_result({ resultTitle: getResultTitle(result) })}
  confirmLabel={m.delete()}
  pendingLabel={m.deleting()}
  errorContext={m.could_not_delete_result()}
  onConfirm={deleteResult}
/>
