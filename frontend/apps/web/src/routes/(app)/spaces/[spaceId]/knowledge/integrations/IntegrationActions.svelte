<script lang="ts">
  import { type IntegrationKnowledge } from "@eneo/eneo-js";
  import { IconEllipsis } from "@eneo/icons/ellipsis";
  import { IconTrash } from "@eneo/icons/trash";
  import { IconEdit } from "@eneo/icons/edit";
  import { IconRefresh } from "@eneo/icons/refresh";
  import { IconCog } from "@eneo/icons/cog";
  import { Button, buttonVariants } from "$lib/components/ui/button/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu/index.js";
  import { dialogLayout } from "$lib/components/dialogLayout.js";
  import ConfirmDialog from "$lib/components/ConfirmDialog.svelte";
  import NameDialog from "$lib/components/NameDialog.svelte";
  import ChunkSettings from "$lib/features/knowledge/components/ChunkSettings.svelte";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { getEneo } from "$lib/core/Eneo";
  import { m } from "$lib/paraglide/messages";
  import { toastError } from "$lib/core/errors";

  export let knowledgeItem: IntegrationKnowledge;

  const eneo = getEneo();
  const {
    refreshCurrentSpace,
    state: { currentSpace }
  } = getSpacesManager();

  async function deleteKnowledge() {
    await eneo.integrations.knowledge.delete({
      knowledge: knowledgeItem,
      space: $currentSpace
    });
    refreshCurrentSpace();
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
    await eneo.integrations.knowledge.triggerFullSync({
      knowledge: knowledgeItem,
      space: $currentSpace
    });
    refreshCurrentSpace();
  }

  // An imported source always holds indexed material, so a change here always costs a
  // re-embedding of its documents at the next sync. ChunkSettings says so.
  let chunkSize: number | null = knowledgeItem.chunk_size ?? null;
  let chunkOverlap: number | null = knowledgeItem.chunk_overlap ?? null;
  let isSavingChunkSettings = false;

  async function saveChunkSettings() {
    isSavingChunkSettings = true;
    try {
      await eneo.integrations.knowledge.updateChunkSettings({
        knowledge: knowledgeItem,
        space: $currentSpace,
        chunk_size: chunkSize,
        chunk_overlap: chunkOverlap
      });
      refreshCurrentSpace();
      showChunkSettingsDialog = false;
    } catch (e) {
      toastError(e);
      console.error(e);
    }
    isSavingChunkSettings = false;
  }

  function openChunkSettings() {
    chunkSize = knowledgeItem.chunk_size ?? null;
    chunkOverlap = knowledgeItem.chunk_overlap ?? null;
    showChunkSettingsDialog = true;
  }

  let showDeleteDialog = false;
  let showRenameDialog = false;
  let showSyncDialog = false;
  let showChunkSettingsDialog = false;
</script>

<DropdownMenu.Root>
  <DropdownMenu.Trigger>
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
      <DropdownMenu.Item onSelect={openChunkSettings}>
        <IconCog size="sm" />{m.chunk_settings_customize()}
      </DropdownMenu.Item>
    {/if}
    {#if knowledgeItem.integration_type === "sharepoint" && knowledgeItem.permissions?.includes("edit")}
      <DropdownMenu.Item onSelect={() => (showSyncDialog = true)}>
        <IconRefresh size="sm" />{m.trigger_full_sync()}
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
  label={m.name()}
  initial={knowledgeItem.name}
  submitLabel={m.save()}
  pendingLabel={m.saving()}
  errorContext={m.integration_rename_error()}
  onSubmit={renameKnowledge}
/>

<Dialog.Root bind:open={showChunkSettingsDialog}>
  <Dialog.Content class={dialogLayout.content("medium")} closeLabel={m.close()}>
    <Dialog.Header class={dialogLayout.header}>
      <Dialog.Title>{m.chunk_settings_customize()}</Dialog.Title>
      <Dialog.Description class="sr-only">{m.chunk_settings_description()}</Dialog.Description>
    </Dialog.Header>

    <div class={dialogLayout.body}>
      <div class={dialogLayout.section}>
        {#key showChunkSettingsDialog}
          <ChunkSettings
            bind:chunkSize
            bind:chunkOverlap
            maxInput={knowledgeItem.embedding_model?.max_input}
            hasIndexedContent={true}
          />
        {/key}
      </div>
    </div>

    <Dialog.Footer class={dialogLayout.footer}>
      <Dialog.Close class={buttonVariants({ variant: "outline" })} disabled={isSavingChunkSettings}>
        {m.cancel()}
      </Dialog.Close>
      <Button onclick={saveChunkSettings} disabled={isSavingChunkSettings}>
        {isSavingChunkSettings ? m.saving() : m.save()}
      </Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>

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
/>
