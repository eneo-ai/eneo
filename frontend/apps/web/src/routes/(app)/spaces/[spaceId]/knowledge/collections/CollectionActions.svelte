<script lang="ts">
  import type { GroupSparse } from "@eneo/eneo-js";
  import { IconEllipsis } from "@eneo/icons/ellipsis";
  import { IconEdit } from "@eneo/icons/edit";
  import { IconTrash } from "@eneo/icons/trash";
  import { IconMove } from "@eneo/icons/move";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu/index.js";
  import ConfirmDialog from "$lib/components/ConfirmDialog.svelte";
  import MoveToSpaceDialog from "$lib/features/spaces/components/MoveToSpaceDialog.svelte";
  import CollectionEditor from "./CollectionEditor.svelte";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { getEneo } from "$lib/core/Eneo";
  import { writable } from "svelte/store";
  import { m } from "$lib/paraglide/messages";

  const {
    refreshCurrentSpace,
    state: { currentSpace }
  } = getSpacesManager();
  const eneo = getEneo();

  export let collection: GroupSparse;
  $: isOrgSpace = $currentSpace.organization === true;

  async function deleteCollection() {
    await eneo.groups.delete({ id: collection.id });
    refreshCurrentSpace();
  }

  async function moveCollection(targetSpace: { id: string }) {
    await eneo.groups.transfer({ group: collection, targetSpace });
    refreshCurrentSpace();
  }

  const showEditDialog = writable(false);
  let showDeleteDialog = false;
  let showMoveDialog = false;
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
      {#if !isOrgSpace}
        <DropdownMenu.Item onSelect={() => (showMoveDialog = true)}>
          <IconMove size="sm" />{m.move()}
        </DropdownMenu.Item>
      {/if}

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

<MoveToSpaceDialog
  bind:open={showMoveDialog}
  title={m.move_collection()}
  submitLabel={m.move_collection()}
  hint={m.move_collection_hint()}
  onMove={moveCollection}
/>
