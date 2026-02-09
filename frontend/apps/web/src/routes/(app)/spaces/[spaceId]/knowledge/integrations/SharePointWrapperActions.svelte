<script lang="ts">
  import { getIntric } from "$lib/core/Intric";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { m } from "$lib/paraglide/messages";
  import { IconEdit } from "@intric/icons/edit";
  import { IconEllipsis } from "@intric/icons/ellipsis";
  import { IconTrash } from "@intric/icons/trash";
  import { Button, Dialog, Dropdown, Input } from "@intric/ui";

  interface Props {
    wrapperId: string;
    wrapperName: string;
    itemCount: number;
    canEdit: boolean;
    canDelete: boolean;
  }

  let { wrapperId, wrapperName, itemCount, canEdit, canDelete }: Props = $props();

  const intric = getIntric();
  const {
    refreshCurrentSpace,
    state: { currentSpace }
  } = getSpacesManager();

  let isRenaming = false;
  let isDeleting = false;
  let newWrapperName = wrapperName;

  let showRenameDialog: Dialog.OpenState;
  let showDeleteDialog: Dialog.OpenState;

  type MessageFn = (args?: Record<string, unknown>) => string;

  function resolveMessage(
    key: string,
    fallback: string,
    args?: Record<string, unknown>
  ): string {
    const maybeFn = (m as unknown as Record<string, MessageFn | undefined>)[key];
    if (typeof maybeFn === "function") {
      return maybeFn(args);
    }
    return fallback;
  }

  function renameWrapperLabel(): string {
    return resolveMessage("rename_wrapper", m.rename());
  }

  function deleteWrapperLabel(): string {
    return resolveMessage("delete_wrapper", m.delete());
  }

  function wrapperNameLabel(): string {
    return resolveMessage("sharepoint_wrapper_name_label", m.name());
  }

  function confirmDeleteWrapperMessage(): string {
    return resolveMessage(
      "confirm_delete_sharepoint_wrapper",
      m.confirm_delete_integration_knowledge({ knowledgeName: wrapperName }),
      { wrapperName, count: itemCount }
    );
  }

  async function renameWrapper() {
    const nextName = newWrapperName.trim();
    if (!nextName) return;

    isRenaming = true;
    try {
      await intric.integrations.knowledge.renameWrapper({
        space: $currentSpace,
        wrapper_id: wrapperId,
        name: nextName
      });
      refreshCurrentSpace();
      $showRenameDialog = false;
    } catch (error) {
      console.error(error);
      alert(m.integration_rename_error());
    } finally {
      isRenaming = false;
    }
  }

  async function deleteWrapper() {
    isDeleting = true;
    try {
      await intric.integrations.knowledge.deleteWrapper({
        space: $currentSpace,
        wrapper_id: wrapperId
      });
      refreshCurrentSpace();
      $showDeleteDialog = false;
    } catch (error) {
      console.error(error);
      alert(m.integration_delete_error());
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
        <Button
          is={item}
          on:click={openRenameDialog}
          padding="icon-leading"
        >
          <IconEdit size="sm" />{renameWrapperLabel()}
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
          <IconTrash size="sm" />{deleteWrapperLabel()}
        </Button>
      {/if}
    </Dropdown.Menu>
  </Dropdown.Root>
{/if}

<Dialog.Root bind:isOpen={showRenameDialog}>
  <Dialog.Content width="small">
    <Dialog.Title>{renameWrapperLabel()}</Dialog.Title>
    <Dialog.Section scrollable={false}>
      <Input.Text bind:value={newWrapperName} label={wrapperNameLabel()} class="px-4 py-4" />
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
    <Dialog.Title>{deleteWrapperLabel()}</Dialog.Title>
    <Dialog.Description>
      {confirmDeleteWrapperMessage()}
    </Dialog.Description>
    <Dialog.Controls let:close>
      <Button is={close}>{m.cancel()}</Button>
      <Button variant="destructive" on:click={deleteWrapper}>
        {isDeleting ? m.deleting() : m.delete()}
      </Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
