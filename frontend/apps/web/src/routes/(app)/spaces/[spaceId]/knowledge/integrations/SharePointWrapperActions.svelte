<script lang="ts">
  import { getEneo } from "$lib/core/Eneo";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { m } from "$lib/paraglide/messages";
  import { IconEdit } from "@eneo/icons/edit";
  import { IconEllipsis } from "@eneo/icons/ellipsis";
  import { IconTrash } from "@eneo/icons/trash";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu/index.js";
  import ConfirmDialog from "$lib/components/ConfirmDialog.svelte";
  import NameDialog from "$lib/components/NameDialog.svelte";

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

  let showRenameDialog = $state(false);
  let showDeleteDialog = $state(false);

  async function renameWrapper(name: string) {
    await eneo.integrations.knowledge.renameWrapper({
      space: $currentSpace,
      wrapper_id: wrapperId,
      name
    });
    refreshCurrentSpace();
  }

  async function deleteWrapper() {
    await eneo.integrations.knowledge.deleteWrapper({
      space: $currentSpace,
      wrapper_id: wrapperId
    });
    refreshCurrentSpace();
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
        <DropdownMenu.Item onSelect={() => (showRenameDialog = true)}>
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

<NameDialog
  bind:open={showRenameDialog}
  title={m.rename_wrapper()}
  label={m.sharepoint_wrapper_name_label()}
  initial={wrapperName}
  submitLabel={m.save()}
  pendingLabel={m.saving()}
  errorContext={m.integration_rename_error()}
  onSubmit={renameWrapper}
/>

<ConfirmDialog
  bind:open={showDeleteDialog}
  title={m.delete_wrapper()}
  description={m.confirm_delete_sharepoint_wrapper({ wrapperName, count: itemCount })}
  confirmLabel={m.delete()}
  pendingLabel={m.deleting()}
  errorContext={m.integration_delete_error()}
  onConfirm={deleteWrapper}
/>
