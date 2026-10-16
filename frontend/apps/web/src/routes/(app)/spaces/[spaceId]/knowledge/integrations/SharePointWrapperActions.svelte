<script lang="ts">
  import { getEneo } from "$lib/core/Eneo";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { toast } from "$lib/components/toast";
  import { m } from "$lib/paraglide/messages";
  import type { IntegrationKnowledge } from "@eneo/eneo-js";
  import { IconEdit } from "@eneo/icons/edit";
  import { IconEllipsis } from "@eneo/icons/ellipsis";
  import { IconRefresh } from "@eneo/icons/refresh";
  import { IconTrash } from "@eneo/icons/trash";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu/index.js";
  import ConfirmDialog from "$lib/components/ConfirmDialog.svelte";
  import NameDialog from "$lib/components/NameDialog.svelte";

  interface Props {
    wrapperId: string;
    wrapperName: string;
    itemCount: number;
    /** The wrapper's items; a resync queues one full sync per item. */
    items?: IntegrationKnowledge[];
    canEdit: boolean;
    canDelete: boolean;
  }

  let { wrapperId, wrapperName, itemCount, items = [], canEdit, canDelete }: Props = $props();

  const eneo = getEneo();
  const {
    refreshCurrentSpace,
    state: { currentSpace }
  } = getSpacesManager();

  let showRenameDialog = $state(false);
  let showDeleteDialog = $state(false);
  let showResyncDialog = $state(false);

  let resyncableItems = $derived(
    items.filter(
      (item) => item.integration_type === "sharepoint" && item.permissions?.includes("edit")
    )
  );
  let canResync = $derived(canEdit && resyncableItems.length > 0);

  // Never throws: a throw would keep the dialog open and a second confirm
  // would queue the items that already succeeded once more.
  async function resyncAll() {
    const total = resyncableItems.length;
    const results = await Promise.allSettled(
      resyncableItems.map((knowledge) =>
        eneo.integrations.knowledge.triggerFullSync({ knowledge, space: $currentSpace })
      )
    );
    // Awaited so the dialog closes on statuses that already show the queued syncs.
    await refreshCurrentSpace();
    const failedNames = resyncableItems
      .filter((_, index) => results[index].status === "rejected")
      .map((item) => item.name);
    if (failedNames.length > 0) {
      toast.error(
        m.resync_all_wrapper_partial_failure({
          failed: failedNames.length,
          total,
          names: failedNames.join(", ")
        })
      );
    } else {
      toast.success(m.resync_all_wrapper_queued({ count: total }));
    }
  }

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

{#if canEdit || canDelete || canResync}
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
      {#if canResync}
        <DropdownMenu.Item onSelect={() => (showResyncDialog = true)}>
          <IconRefresh size="sm" />{m.resync_all_wrapper()}
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
  bind:open={showResyncDialog}
  title={m.resync_all_wrapper()}
  description={m.confirm_resync_all_wrapper({ wrapperName, count: resyncableItems.length })}
  confirmLabel={m.start_full_sync()}
  pendingLabel={m.syncing()}
  errorContext={m.sync_failed()}
  variant="default"
  onConfirm={resyncAll}
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
