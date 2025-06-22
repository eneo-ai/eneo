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
  import { m } from "$lib/paraglide/messages";

  export let service: ServiceSparse;

  const {
    state: { currentSpace, accessibleSpaces },
    refreshCurrentSpace
  } = getSpacesManager();

  const intric = getIntric();

  async function deleteService() {
    isProcessing = true;
    try {
      await intric.services.delete(service);
      refreshCurrentSpace();
      $showDeleteDialog = false;
    } catch (e) {
      alert(m.could_not_delete_service());
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
          {m.edit()}</Button
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
          {m.move()}</Button
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
{/if}

<Dialog.Root alert bind:isOpen={showDeleteDialog}>
  <Dialog.Content width="small">
    <Dialog.Title>{m.delete_service()}</Dialog.Title>
    <Dialog.Description
      >{m.confirm_delete_service({ serviceName: service.name })}</Dialog.Description
    >

    <Dialog.Controls let:close>
      <Button is={close}>{m.cancel()}</Button>
      <Button variant="destructive" on:click={deleteService}
        >{isProcessing ? m.deleting() : m.delete()}</Button
      >
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>

<Dialog.Root bind:isOpen={showMoveDialog}>
  <Dialog.Content width="medium" form>
    <Dialog.Title>{m.move_service()}</Dialog.Title>

    <Dialog.Section scrollable={false}>
      <Select.Simple
        required
        options={$moveTargets}
        bind:value={moveDestination}
        fitViewport={true}
        resourceName="space"
        class="border-default hover:bg-hover-dimmer rounded-t-md border-b px-4 py-4"
        >{m.destination()}</Select.Simple
      >
    </Dialog.Section>

    <Dialog.Controls let:close>
      <Button is={close}>{m.cancel()}</Button>
      <Button variant="destructive" on:click={moveService}
        >{isProcessing ? m.moving() : m.move_service()}</Button
      >
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
