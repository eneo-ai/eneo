<script lang="ts">
  import type { ServiceSparse } from "@intric/intric-js";
  import { IconEdit } from "@intric/icons/edit";
  import { IconTrash } from "@intric/icons/trash";
  import { IconEllipsis } from "@intric/icons/ellipsis";
  import { IconMove } from "@intric/icons/move";
  import { Button, Dialog, Dropdown, Select } from "@intric/ui";
  import { getIntric } from "$lib/core/Intric";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { derived } from "svelte/store";

  export let service: ServiceSparse;

  const {
    state: { currentSpace, accessibleSpaces },
    refreshCurrentSpace
  } = getSpacesManager();

  const intric = getIntric();
  $: isOrgSpace = $currentSpace.organization === true;

  async function deleteService() {
    isProcessing = true;
    try {
      await intric.services.delete(service);
      refreshCurrentSpace();
      $showDeleteDialog = false;
    } catch (e) {
      alert("Could not delete service.");
      console.error(e);
    }
    isProcessing = false;
  }

  async function moveService() {
    if (!moveDestination) return;
    isProcessing = true;
    try {
      await intric.services.transfer({
        service,
        moveResources: false,
        targetSpace: moveDestination
      });
      refreshCurrentSpace();
      $showMoveDialog = false;
    } catch (e) {
      alert(e);
      console.error(e);
    }
    isProcessing = false;
  }

  let isProcessing = false;
  let showDeleteDialog: Dialog.OpenState;
  let showMoveDialog: Dialog.OpenState;

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

  let showActions = (["edit", "delete"] as const).some((permission) =>
    service.permissions?.includes(permission)
  );
</script>

{#if showActions}
  <Dropdown.Root>
    <Dropdown.Trigger let:trigger asFragment>
      <Button is={trigger} disabled={false} padding="icon">
        <IconEllipsis />
      </Button>
    </Dropdown.Trigger>
    <Dropdown.Menu let:item>
      {#if service.permissions?.includes("edit")}
        <Button
          is={item}
          href="/spaces/{$currentSpace.routeId}/services/{service.id}?tab=edit"
          padding="icon-leading"
        >
          <IconEdit size="sm" />
          Edit</Button
        >
      {/if}
      {#if service.permissions?.includes("delete")}
        <Button
          is={item}
          on:click={() => {
            $showMoveDialog = true;
          }}
          padding="icon-leading"
        >
          <IconMove size="sm" />
          Move</Button
        >
        <Button
          is={item}
          variant="destructive"
          on:click={() => {
            $showDeleteDialog = true;
          }}
          padding="icon-leading"
        >
          <IconTrash size="sm" />Delete</Button
        >
      {/if}
    </Dropdown.Menu>
  </Dropdown.Root>
{/if}

<Dialog.Root alert bind:isOpen={showDeleteDialog}>
  <Dialog.Content width="small">
    <Dialog.Title>Delete service</Dialog.Title>
    <Dialog.Description
      >Do you really want to delete <span class="italic">{service.name}</span>?</Dialog.Description
    >

    <Dialog.Controls let:close>
      <Button is={close}>Cancel</Button>
      <Button variant="destructive" on:click={deleteService}
        >{isProcessing ? "Deleting..." : "Delete"}</Button
      >
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>

<Dialog.Root bind:isOpen={showMoveDialog}>
  <Dialog.Content width="medium" form>
    <Dialog.Title>Move service</Dialog.Title>

    <Dialog.Section scrollable={false}>
      <Select.Simple
        required
        options={$moveTargets}
        bind:value={moveDestination}
        fitViewport={true}
        resourceName="space"
        class="border-default hover:bg-hover-dimmer rounded-t-md border-b px-4 py-4"
        >Destination</Select.Simple
      >
    </Dialog.Section>

    <Dialog.Controls let:close>
      <Button is={close}>Cancel</Button>
      <Button variant="destructive" on:click={moveService}
        >{isProcessing ? "Moving..." : "Move service"}</Button
      >
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
