<script lang="ts">
  import type { GroupSparse } from "@intric/intric-js";
  import { IconEllipsis } from "@intric/icons/ellipsis";
  import { IconEdit } from "@intric/icons/edit";
  import { IconTrash } from "@intric/icons/trash";
  import { IconMove } from "@intric/icons/move";
  import { Button, Dialog, Dropdown, Select } from "@intric/ui";
  import CollectionEditor from "./CollectionEditor.svelte";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { getIntric } from "$lib/core/Intric";
  import { derived } from "svelte/store";
  import { m } from "$lib/paraglide/messages";

  const {
    refreshCurrentSpace,
    state: { accessibleSpaces, currentSpace }
  } = getSpacesManager();
  const intric = getIntric();

  export let collection: GroupSparse;

  async function deleteResource() {
    isProcessing = true;
    try {
      await intric.groups.delete(collection);
      refreshCurrentSpace();
      $showDeleteDialog = false;
    } catch (e) {
      alert(m.could_not_delete_collection());
      console.error(e);
    }
    isProcessing = false;
  }

  async function moveCollection() {
    if (!moveDestination) return;
    isProcessing = true;
    try {
      await intric.groups.transfer({ group: collection, targetSpace: moveDestination });
      refreshCurrentSpace();
      $showMoveDialog = false;
    } catch (e) {
      alert(e);
      console.error(e);
    }
    isProcessing = false;
  }

  const moveTargets = derived(accessibleSpaces, ($accessibleSpaces) => {
    return $accessibleSpaces.reduce(
      (acc, curr) => {
        if (curr.id !== $currentSpace.id) {
          acc.push({ label: curr.name, value: { id: curr.id } });
        }
        return acc;
      },
      [] as Array<{ label: string; value: { id: string } }>
    );
  });
  let moveDestination: { id: string } | undefined = undefined;

  let isProcessing = false;
  let showEditDialog: Dialog.OpenState;
  let showDeleteDialog: Dialog.OpenState;
  let showMoveDialog: Dialog.OpenState;
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
      on:click={() => {
        $showEditDialog = true;
      }}
      padding="icon-leading"
    >
      <IconEdit size="sm" />
      {m.edit()}</Button
    >
    {#if collection.permissions?.includes("delete")}
      <Button
        is={item}
        on:click={() => {
          $showMoveDialog = true;
        }}
        padding="icon-leading"
      >
        <IconMove size="sm" />{m.move()}</Button
      >
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
    {/if}
  </Dropdown.Menu>
</Dropdown.Root>

<CollectionEditor mode="update" {collection} bind:showDialog={showEditDialog}></CollectionEditor>

<Dialog.Root alert bind:isOpen={showDeleteDialog}>
  <Dialog.Content width="small">
    <Dialog.Title>{m.delete_collection()}</Dialog.Title>
    <Dialog.Description
      >{m.confirm_delete_collection({ name: collection.name })}</Dialog.Description
    >

    <Dialog.Controls let:close>
      <Button is={close}>{m.cancel()}</Button>
      <Button variant="destructive" on:click={deleteResource}
        >{isProcessing ? m.deleting() : m.delete()}</Button
      >
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>

<Dialog.Root bind:isOpen={showMoveDialog}>
  <Dialog.Content width="medium" form>
    <Dialog.Title>{m.move_collection()}</Dialog.Title>

    <Dialog.Section scrollable={false}>
      <Select.Simple
        required
        options={$moveTargets}
        bind:value={moveDestination}
        fitViewport={true}
        class="border-default hover:bg-hover-dimmer rounded-t-md px-4 pt-4"
        >{m.destination()}</Select.Simple
      >
      <p
        class="label-warning border-label-default bg-label-dimmer text-label-stronger mx-4 mt-1.5 mb-4 rounded-md border px-2 py-1 text-sm"
      >
        <span class="font-bold">{m.hint()}:</span>
        {m.move_collection_hint()}
      </p>
    </Dialog.Section>

    <Dialog.Controls let:close>
      <Button is={close}>{m.cancel()}</Button>
      <Button variant="destructive" on:click={moveCollection}
        >{isProcessing ? m.moving() : m.move_collection()}</Button
      >
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
