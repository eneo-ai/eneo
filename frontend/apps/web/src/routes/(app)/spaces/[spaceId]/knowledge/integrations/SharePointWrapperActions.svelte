<script lang="ts">
  import { getEneo } from "$lib/core/Eneo";
  import { focusAfterRemoval } from "$lib/core/focus/focusAfterRemoval";
  import { settleWithLimit } from "$lib/core/async/settleWithLimit";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { getJobManager } from "$lib/features/jobs/JobManager";
  import { trackSyncs } from "$lib/features/integrations/pendingSyncs";
  import { toast } from "$lib/components/toast";
  import { m } from "$lib/paraglide/messages";
  import { KNOWLEDGE_NAME_MAX_LENGTH } from "$lib/features/integrations/knowledgeNames";
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
    /** A sync of one of the items is queued or running. */
    syncActive?: boolean;
  }

  let {
    wrapperId,
    wrapperName,
    itemCount,
    items = [],
    canEdit,
    canDelete,
    syncActive = false
  }: Props = $props();

  const eneo = getEneo();
  const { addJob, startFastUpdatePolling } = getJobManager();
  const {
    refreshCurrentSpace,
    state: { currentSpace }
  } = getSpacesManager();

  let showRenameDialog = $state(false);
  let showDeleteDialog = $state(false);
  let trigger = $state<HTMLElement | null>(null);
  let removal: ReturnType<typeof focusAfterRemoval> | null = null;
  let showResyncDialog = $state(false);

  let resyncableItems = $derived(
    items.filter(
      (item) => item.integration_type === "sharepoint" && item.permissions?.includes("edit")
    )
  );
  let canResync = $derived(canEdit && resyncableItems.length > 0);

  // A few at a time: each request also checks the site's change subscription.
  const RESYNC_CONCURRENCY = 4;
  // Names of folders that could not be queued, beyond which the toast only counts.
  const NAMED_FAILURES = 5;

  // Never throws: a throw would keep the dialog open and a second confirm
  // would queue the items that already succeeded once more.
  async function resyncAll() {
    const total = resyncableItems.length;
    const results = await settleWithLimit(resyncableItems, RESYNC_CONCURRENCY, (knowledge) =>
      eneo.integrations.knowledge.triggerFullSync({ knowledge, space: $currentSpace })
    );
    const queued = resyncableItems.flatMap((item, index) => {
      const result = results[index];
      return result.status === "fulfilled" ? [{ item, job: result.value }] : [];
    });
    for (const { job } of queued) addJob(job);
    trackSyncs(queued.map(({ item, job }) => ({ jobId: job.id, knowledgeId: item.id })));
    if (queued.length > 0) void startFastUpdatePolling();
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
          names:
            failedNames.slice(0, NAMED_FAILURES).join(", ") +
            (failedNames.length > NAMED_FAILURES ? ", …" : "")
        })
      );
    } else {
      toast.success(
        total === 1
          ? m.resync_all_wrapper_queued_one()
          : m.resync_all_wrapper_queued({ count: total })
      );
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
    removal = focusAfterRemoval(trigger);
    await eneo.integrations.knowledge.deleteWrapper({
      space: $currentSpace,
      wrapper_id: wrapperId
    });
    // Awaited so the row is gone by the time the dialog hands focus back.
    await refreshCurrentSpace();
  }
</script>

{#if canEdit || canDelete || canResync}
  <DropdownMenu.Root>
    <DropdownMenu.Trigger bind:ref={trigger}>
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
        <!-- Stays reachable by keyboard while unavailable, so the reason is heard. -->
        <DropdownMenu.Item
          class="aria-disabled:pointer-events-none aria-disabled:opacity-50"
          onSelect={(event) => {
            if (syncActive) event.preventDefault();
            else showResyncDialog = true;
          }}
        >
          <!-- bits writes its own aria-disabled; the element states ours last. -->
          {#snippet child({ props })}
            <div {...props} aria-disabled={syncActive ? "true" : undefined}>
              <IconRefresh size="sm" />{syncActive
                ? m.integration_sync_already_running()
                : m.resync_all_wrapper()}
            </div>
          {/snippet}
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
  maxlength={KNOWLEDGE_NAME_MAX_LENGTH}
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
  description={resyncableItems.length === 1
    ? m.confirm_resync_all_wrapper_one({ wrapperName })
    : m.confirm_resync_all_wrapper({ wrapperName, count: resyncableItems.length })}
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
  onCloseAutoFocus={(event) => {
    if (removal?.settle()) event.preventDefault();
    removal = null;
  }}
/>
