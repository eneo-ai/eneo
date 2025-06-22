<script lang="ts">
  import type { AssistantSparse } from "@intric/intric-js";
  import { IconEdit } from "@intric/icons/edit";
  import { IconTrash } from "@intric/icons/trash";
  import { IconEllipsis } from "@intric/icons/ellipsis";
  import { IconMove } from "@intric/icons/move";
  import { Button, Dialog, Dropdown, Input, Select } from "@intric/ui";
  import { getIntric } from "$lib/core/Intric";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { derived, writable } from "svelte/store";
  import PublishingDialog from "$lib/features/publishing/components/PublishingDialog.svelte";
  import { IconArrowUpToLine } from "@intric/icons/arrow-up-to-line";
  import { IconArrowDownToLine } from "@intric/icons/arrow-down-to-line";
  import { m } from "$lib/paraglide/messages";

  export let assistant: AssistantSparse;

  const {
    state: { currentSpace, accessibleSpaces },
    refreshCurrentSpace
  } = getSpacesManager();

  const intric = getIntric();

  async function deleteAssistant() {
    isProcessing = true;
    try {
      await intric.assistants.delete(assistant);
      refreshCurrentSpace("applications");
      $showDeleteDialog = false;
    } catch (e) {
      alert(m.could_not_delete_assistant());
      console.error(e);
    }
    isProcessing = false;
  }

  async function moveAssistant() {
    if (!moveDestination) return;
    isProcessing = true;
    try {
      await intric.assistants.transfer({ assistant, moveResources, targetSpace: moveDestination });
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
  const showPublishDialog = writable(false);

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
  let moveResources: boolean = false;

  let showActions = (["edit", "publish", "delete"] as const).some((permission) =>
    assistant.permissions?.includes(permission)
  );
</script>

{#if showActions}
  <Dropdown.Root>
    <Dropdown.Trigger let:trigger asFragment>
      <Button variant="on-fill" is={trigger} disabled={false} padding="icon">
        <IconEllipsis />
      </Button>
    </Dropdown.Trigger>
    <Dropdown.Menu let:item>
      {#if assistant.permissions?.includes("edit")}
        <Button
          is={item}
          href="/spaces/{$currentSpace.routeId}/assistants/{assistant.id}/edit"
          padding="icon-leading"
        >
          <IconEdit size="sm" />
          {m.edit()}</Button
        >
      {/if}
      {#if assistant.permissions?.includes("publish")}
        <Button
          is={item}
          on:click={() => {
            $showPublishDialog = true;
          }}
          padding="icon-leading"
        >
          {#if assistant.published}
            <IconArrowDownToLine size="sm"></IconArrowDownToLine>
            {m.unpublish()}
          {:else}
            <IconArrowUpToLine size="sm"></IconArrowUpToLine>
            {m.publish()}
          {/if}
        </Button>
      {/if}
      {#if assistant.permissions?.includes("delete")}
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
    <Dialog.Title>{m.delete_assistant()}</Dialog.Title>
    <Dialog.Description
      >{m.confirm_delete_assistant({ name: assistant.name })}</Dialog.Description
    >

    <Dialog.Controls let:close>
      <Button is={close}>{m.cancel()}</Button>
      <Button variant="destructive" on:click={deleteAssistant}
        >{isProcessing ? m.deleting() : m.delete()}</Button
      >
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>

<Dialog.Root bind:isOpen={showMoveDialog}>
  <Dialog.Content width="medium" form>
    <Dialog.Title>{m.move_assistant()}</Dialog.Title>

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
      <Input.Switch bind:value={moveResources} class="hover:bg-hover-dimmer px-4 py-4"
        >{m.include_assistants_knowledge()}</Input.Switch
      >
      {#if moveResources}
        <p
          class="label-warning border-label-default bg-label-dimmer text-label-stronger mx-4 mb-3 rounded-md border px-2 py-1 text-sm"
        >
          <span class="font-bold">{m.hint()}:</span>
          {m.move_assistant_hint()}
        </p>
      {/if}
    </Dialog.Section>

    <Dialog.Controls let:close>
      <Button is={close}>{m.cancel()}</Button>
      <Button variant="destructive" on:click={moveAssistant}
        >{isProcessing ? m.moving() : m.move_assistant()}</Button
      >
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>

<PublishingDialog
  resource={assistant}
  endpoints={intric.assistants}
  openController={showPublishDialog}
  awaitUpdate
></PublishingDialog>
