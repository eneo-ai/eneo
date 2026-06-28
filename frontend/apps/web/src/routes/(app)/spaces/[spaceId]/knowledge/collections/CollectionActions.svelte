<script lang="ts">
  import type { GroupSparse } from "@eneo/eneo-js";
  import { IconEllipsis } from "@eneo/icons/ellipsis";
  import { IconEdit } from "@eneo/icons/edit";
  import { IconTrash } from "@eneo/icons/trash";
  import { IconMove } from "@eneo/icons/move";
  import { Button, Dialog, Dropdown, Select } from "@eneo/ui";
  import CollectionEditor from "./CollectionEditor.svelte";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { getEneo } from "$lib/core/Eneo";
  import { derived } from "svelte/store";
  import { m } from "$lib/paraglide/messages";
  import { toastError } from "$lib/core/errors";

  const {
    refreshCurrentSpace,
    state: { accessibleSpaces, currentSpace }
  } = getSpacesManager();
  const eneo = getEneo();

  export let collection: GroupSparse;
  $: isOrgSpace = $currentSpace.organization === true;

  async function deleteResource() {
    isProcessing = true;
    try {
      await eneo.groups.delete({ id: collection.id });
      refreshCurrentSpace();
      $showDeleteDialog = false;
    } catch (e) {
      toastError(e, m.could_not_delete_collection());
      console.error(e);
    }
  }

  async function moveCollection() {
    if (!moveDestination) return;
    isProcessing = true;
    try {
      await eneo.groups.transfer({ group: collection, targetSpace: moveDestination });
      refreshCurrentSpace();
      $showMoveDialog = false;
    } catch (e) {
      toastError(e);
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
      {#if !isOrgSpace}
        <Button
          is={item}
          on:click={() => {
            $showMoveDialog = true;
          }}
          padding="icon-leading"
        >
          <IconMove size="sm" />{m.move()}</Button
        >
      {/if}

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
    <Dialog.Description>{m.confirm_delete_collection({ name: collection.name })}</Dialog.Description
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
