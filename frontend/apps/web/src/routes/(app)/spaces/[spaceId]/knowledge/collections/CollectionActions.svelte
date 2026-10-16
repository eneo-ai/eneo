<script lang="ts">
  import type { GroupSparse } from "@eneo/eneo-js";
  import { IconEllipsis } from "@eneo/icons/ellipsis";
  import { IconEdit } from "@eneo/icons/edit";
  import { IconTrash } from "@eneo/icons/trash";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu/index.js";
  import ConfirmDialog from "$lib/components/ConfirmDialog.svelte";
  import CollectionEditor from "./CollectionEditor.svelte";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { getEneo } from "$lib/core/Eneo";
  import { writable } from "svelte/store";
  import { m } from "$lib/paraglide/messages";

  const { refreshCurrentSpace } = getSpacesManager();
  const eneo = getEneo();

  export let collection: GroupSparse;

  async function deleteCollection() {
    await eneo.groups.delete({ id: collection.id });
    refreshCurrentSpace();
  }

  const showEditDialog = writable(false);
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
    <DropdownMenu.Item onSelect={() => ($showEditDialog = true)}>
      <IconEdit size="sm" />
      {m.edit()}
    </DropdownMenu.Item>
    {#if collection.permissions?.includes("delete")}
      <DropdownMenu.Item variant="destructive" onSelect={() => (showDeleteDialog = true)}>
        <IconTrash size="sm" />{m.delete()}
      </DropdownMenu.Item>
    {/if}
  </DropdownMenu.Content>
</DropdownMenu.Root>

<CollectionEditor mode="update" {collection} showDialog={showEditDialog}></CollectionEditor>

<ConfirmDialog
  bind:open={showDeleteDialog}
  title={m.delete_collection()}
  description={m.confirm_delete_collection({ name: collection.name })}
  confirmLabel={m.delete()}
  pendingLabel={m.deleting()}
  errorContext={m.could_not_delete_collection()}
  onConfirm={deleteCollection}
/>
