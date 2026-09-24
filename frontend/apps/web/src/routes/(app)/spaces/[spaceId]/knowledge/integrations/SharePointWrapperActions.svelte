<script lang="ts">
  import { getEneo } from "$lib/core/Eneo";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { m } from "$lib/paraglide/messages";
  import { toastError } from "$lib/core/errors";
  import { IconEdit } from "@eneo/icons/edit";
  import { IconEllipsis } from "@eneo/icons/ellipsis";
  import { IconTrash } from "@eneo/icons/trash";
  import { Button, buttonVariants } from "$lib/components/ui/button/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu/index.js";
  import { dialogLayout } from "$lib/components/dialogLayout.js";
  import ConfirmDialog from "$lib/components/ConfirmDialog.svelte";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { untrack } from "svelte";

  interface Props {
    wrapperId: string;
    wrapperName: string;
    itemCount: number;
    canEdit: boolean;
    canDelete: boolean;
  }

  let { wrapperId, wrapperName, itemCount, canEdit, canDelete }: Props = $props();
  const uid = $props.id();

  const eneo = getEneo();
  const {
    refreshCurrentSpace,
    state: { currentSpace }
  } = getSpacesManager();

  let isRenaming = $state(false);
  let newWrapperName = $state(untrack(() => wrapperName));

  let showRenameDialog = $state(false);
  let showDeleteDialog = $state(false);

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
      showRenameDialog = false;
    } catch (error) {
      console.error(error);
      toastError(error, m.integration_rename_error());
    } finally {
      isRenaming = false;
    }
  }

  async function deleteWrapper() {
    await eneo.integrations.knowledge.deleteWrapper({
      space: $currentSpace,
      wrapper_id: wrapperId
    });
    refreshCurrentSpace();
  }

  function openRenameDialog() {
    newWrapperName = wrapperName;
    showRenameDialog = true;
  }
</script>

{#if canEdit || canDelete}
  <DropdownMenu.Root>
    <DropdownMenu.Trigger>
      {#snippet child({ props })}
        <Button {...props} variant="ghost" size="icon" aria-label={m.actions()}>
          <IconEllipsis />
        </Button>
      {/snippet}
    </DropdownMenu.Trigger>
    <DropdownMenu.Content align="end">
      {#if canEdit}
        <DropdownMenu.Item onSelect={openRenameDialog}>
          <IconEdit size="sm" />{m.rename_wrapper()}
        </DropdownMenu.Item>
      {/if}
      {#if canDelete}
        <DropdownMenu.Item variant="destructive" onSelect={() => (showDeleteDialog = true)}>
          <IconTrash size="sm" />{m.delete_wrapper()}
        </DropdownMenu.Item>
      {/if}
    </DropdownMenu.Content>
  </DropdownMenu.Root>
{/if}

<Dialog.Root bind:open={showRenameDialog}>
  <Dialog.Content class={dialogLayout.content()} closeLabel={m.close()}>
    <Dialog.Header class={dialogLayout.header}>
      <Dialog.Title>{m.rename_wrapper()}</Dialog.Title>
    </Dialog.Header>
    <div class={dialogLayout.body}>
      <div class={dialogLayout.section}>
        <Field.Field class="px-4 py-4">
          <Field.Label for={`${uid}-name`}>{m.sharepoint_wrapper_name_label()}</Field.Label>
          <Input id={`${uid}-name`} bind:value={newWrapperName} />
        </Field.Field>
      </div>
    </div>
    <Dialog.Footer class={dialogLayout.footer}>
      <Dialog.Close class={buttonVariants({ variant: "outline" })}>{m.cancel()}</Dialog.Close>
      <Button onclick={renameWrapper} disabled={!newWrapperName.trim()}>
        {isRenaming ? m.saving() : m.save()}
      </Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>

<ConfirmDialog
  bind:open={showDeleteDialog}
  title={m.delete_wrapper()}
  description={m.confirm_delete_sharepoint_wrapper({ wrapperName, count: itemCount })}
  confirmLabel={m.delete()}
  pendingLabel={m.deleting()}
  errorContext={m.integration_delete_error()}
  onConfirm={deleteWrapper}
/>
