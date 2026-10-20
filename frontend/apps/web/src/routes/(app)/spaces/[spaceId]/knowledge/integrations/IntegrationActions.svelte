<script lang="ts">
  import { type IntegrationKnowledge } from "@eneo/eneo-js";
  import { IconEllipsis } from "@eneo/icons/ellipsis";
  import { IconTrash } from "@eneo/icons/trash";
  import { IconEdit } from "@eneo/icons/edit";
  import { IconRefresh } from "@eneo/icons/refresh";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu/index.js";
  import ConfirmDialog from "$lib/components/ConfirmDialog.svelte";
  import NameDialog from "$lib/components/NameDialog.svelte";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { getJobManager } from "$lib/features/jobs/JobManager";
  import { trackSyncs } from "$lib/features/integrations/pendingSyncs";
  import { getEneo } from "$lib/core/Eneo";
  import { focusAfterRemoval } from "$lib/core/focus/focusAfterRemoval";
  import { m } from "$lib/paraglide/messages";
  import { KNOWLEDGE_NAME_MAX_LENGTH } from "$lib/features/integrations/knowledgeNames";

  interface Props {
    knowledgeItem: IntegrationKnowledge;
    /** A sync of the item is queued or running: starting another would only queue a second. */
    syncActive?: boolean;
  }

  let { knowledgeItem, syncActive = false }: Props = $props();

  const eneo = getEneo();
  const { addJob, startFastUpdatePolling } = getJobManager();
  const {
    refreshCurrentSpace,
    state: { currentSpace }
  } = getSpacesManager();

  async function deleteKnowledge() {
    removal = focusAfterRemoval(trigger);
    await eneo.integrations.knowledge.delete({
      knowledge: knowledgeItem,
      space: $currentSpace
    });
    // Awaited so the row is gone by the time the dialog hands focus back.
    await refreshCurrentSpace();
  }

  async function renameKnowledge(name: string) {
    await eneo.integrations.knowledge.rename({
      knowledge: knowledgeItem,
      space: $currentSpace,
      name
    });
    refreshCurrentSpace();
  }

  async function triggerFullSync() {
    const job = await eneo.integrations.knowledge.triggerFullSync({
      knowledge: knowledgeItem,
      space: $currentSpace
    });
    // The item reads as queued until the worker reports on it or the job ends.
    addJob(job);
    trackSyncs([{ jobId: job.id, knowledgeId: knowledgeItem.id }]);
    void startFastUpdatePolling();
    refreshCurrentSpace();
  }

  let showDeleteDialog = $state(false);
  let trigger = $state<HTMLElement | null>(null);
  let removal: ReturnType<typeof focusAfterRemoval> | null = null;
  let showRenameDialog = $state(false);
  let showSyncDialog = $state(false);
</script>

<DropdownMenu.Root>
  <DropdownMenu.Trigger bind:ref={trigger}>
    {#snippet child({ props })}
      <Button {...props} variant="ghost" size="icon" aria-label={m.actions()}>
        <IconEllipsis />
      </Button>
    {/snippet}
  </DropdownMenu.Trigger>
  <DropdownMenu.Content align="end">
    {#if knowledgeItem.permissions?.includes("edit")}
      <DropdownMenu.Item onSelect={() => (showRenameDialog = true)}>
        <IconEdit size="sm" />{m.rename()}
      </DropdownMenu.Item>
    {/if}
    {#if knowledgeItem.integration_type === "sharepoint" && knowledgeItem.permissions?.includes("edit")}
      <!-- Stays reachable by keyboard while unavailable, so the reason is heard. -->
      <DropdownMenu.Item
        class="aria-disabled:pointer-events-none aria-disabled:opacity-50"
        onSelect={(event) => {
          if (syncActive) event.preventDefault();
          else showSyncDialog = true;
        }}
      >
        <!-- bits writes its own aria-disabled; the element states ours last. -->
        {#snippet child({ props })}
          <div {...props} aria-disabled={syncActive ? "true" : undefined}>
            <IconRefresh size="sm" />{syncActive
              ? m.integration_sync_already_running()
              : m.trigger_full_sync()}
          </div>
        {/snippet}
      </DropdownMenu.Item>
    {/if}
    {#if knowledgeItem.permissions?.includes("delete")}
      <DropdownMenu.Item variant="destructive" onSelect={() => (showDeleteDialog = true)}>
        <IconTrash size="sm" />{m.delete()}
      </DropdownMenu.Item>
    {/if}
  </DropdownMenu.Content>
</DropdownMenu.Root>

<NameDialog
  bind:open={showRenameDialog}
  title={m.integration_rename_title()}
  maxlength={KNOWLEDGE_NAME_MAX_LENGTH}
  label={m.name()}
  initial={knowledgeItem.name}
  submitLabel={m.save()}
  pendingLabel={m.saving()}
  errorContext={m.integration_rename_error()}
  onSubmit={renameKnowledge}
/>

<ConfirmDialog
  bind:open={showSyncDialog}
  title={m.trigger_full_sync()}
  description={m.confirm_full_sync({ knowledgeName: knowledgeItem.name })}
  confirmLabel={m.start_full_sync()}
  pendingLabel={m.syncing()}
  errorContext={m.sync_failed()}
  variant="default"
  onConfirm={triggerFullSync}
/>

<ConfirmDialog
  bind:open={showDeleteDialog}
  title={m.delete_integration_knowledge()}
  description={m.confirm_delete_integration_knowledge({ knowledgeName: knowledgeItem.name })}
  confirmLabel={m.delete()}
  pendingLabel={m.deleting()}
  errorContext={m.integration_delete_error()}
  onConfirm={deleteKnowledge}
  onCloseAutoFocus={(event) => {
    if (removal?.settle()) event.preventDefault();
    removal = null;
  }}
/>
