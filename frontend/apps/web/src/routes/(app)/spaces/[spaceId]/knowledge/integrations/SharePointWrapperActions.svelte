<script lang="ts">
  import { getEneo } from "$lib/core/Eneo";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { m } from "$lib/paraglide/messages";
  import { toastError } from "$lib/core/errors";
  import { IconEdit } from "@eneo/icons/edit";
  import { IconEllipsis } from "@eneo/icons/ellipsis";
  import { IconTrash } from "@eneo/icons/trash";
  import { Button, Dialog, Dropdown, Input } from "@eneo/ui";
  import { untrack } from "svelte";

  interface Props {
    wrapperId: string;
    wrapperName: string;
    itemCount: number;
    canEdit: boolean;
    canDelete: boolean;
  }

  let { wrapperId, wrapperName, itemCount, canEdit, canDelete }: Props = $props();

  const eneo = getEneo();
  const {
    refreshCurrentSpace,
    state: { currentSpace }
  } = getSpacesManager();

  let isRenaming = $state(false);
  let isDeleting = $state(false);
  let newWrapperName = $state(untrack(() => wrapperName));

  let showRenameDialog = $state<Dialog.OpenState>();
  let showDeleteDialog = $state<Dialog.OpenState>();

  async function renameWrapper() {
    const nextName = newWrapperName.trim();
    if (!nextName) return;

    isRenaming = true;
    try {
      await eneo.integrations.knowledge.renameWrapper({
        space: $currentSpace,
        wrapper_id: wrapperId,
        name: nextName
      });
      refreshCurrentSpace();
      $showRenameDialog = false;
    } catch (error) {
      console.error(error);
      toastError(error, m.integration_rename_error());
    } finally {
      isRenaming = false;
    }
  }

  async function deleteWrapper() {
    isDeleting = true;
    try {
      await eneo.integrations.knowledge.deleteWrapper({
        space: $currentSpace,
        wrapper_id: wrapperId
      });
      refreshCurrentSpace();
      $showDeleteDialog = false;
    } catch (error) {
      console.error(error);
      toastError(error, m.integration_delete_error());
    } finally {
      isDeleting = false;
    }
  }

  function openRenameDialog() {
    newWrapperName = wrapperName;
    $showRenameDialog = true;
  }
</script>

{#if canEdit || canDelete}
  <Dropdown.Root>
    <Dropdown.Trigger let:trigger asFragment>
      <Button is={trigger} padding="icon" class="h-8 w-8">
        <IconEllipsis />
      </Button>
    </Dropdown.Trigger>
    <Dropdown.Menu let:item>
      {#if canEdit}
        <Button is={item} on:click={openRenameDialog} padding="icon-leading">
          <IconEdit size="sm" />{m.rename_wrapper()}
        </Button>
      {/if}
      {#if canDelete}
        <Button
          is={item}
          variant="destructive"
          on:click={() => {
            $showDeleteDialog = true;
          }}
          padding="icon-leading"
        >
          <IconTrash size="sm" />{m.delete_wrapper()}
        </Button>
      {/if}
    </Dropdown.Menu>
  </Dropdown.Root>
{/if}

<Dialog.Root bind:isOpen={showRenameDialog}>
  <Dialog.Content width="small">
    <Dialog.Title>{m.rename_wrapper()}</Dialog.Title>
    <Dialog.Section scrollable={false}>
      <Input.Text
        bind:value={newWrapperName}
        label={m.sharepoint_wrapper_name_label()}
        class="px-4 py-4"
      />
    </Dialog.Section>
    <Dialog.Controls let:close>
      <Button is={close}>{m.cancel()}</Button>
      <Button variant="primary" on:click={renameWrapper} disabled={!newWrapperName.trim()}>
        {isRenaming ? m.saving() : m.save()}
      </Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>

<Dialog.Root alert bind:isOpen={showDeleteDialog}>
  <Dialog.Content width="small">
    <Dialog.Title>{m.delete_wrapper()}</Dialog.Title>
    <Dialog.Description>
      {m.confirm_delete_sharepoint_wrapper({ wrapperName, count: itemCount })}
    </Dialog.Description>
    <Dialog.Controls let:close>
      <Button is={close}>{m.cancel()}</Button>
      <Button variant="destructive" on:click={deleteWrapper}>
        {isDeleting ? m.deleting() : m.delete()}
      </Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
