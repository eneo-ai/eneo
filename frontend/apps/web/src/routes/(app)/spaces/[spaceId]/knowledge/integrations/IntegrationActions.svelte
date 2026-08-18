<script lang="ts">
  import { type IntegrationKnowledge } from "@eneo/eneo-js";
  import { IconEllipsis } from "@eneo/icons/ellipsis";
  import { IconTrash } from "@eneo/icons/trash";
  import { IconEdit } from "@eneo/icons/edit";
  import { IconRefresh } from "@eneo/icons/refresh";
  import { Button, Dialog, Dropdown, Input } from "@eneo/ui";
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

  let isDeleting = false;
  let isRenaming = false;
  let isSyncing = false;
  let newName = knowledgeItem.name;

  async function deleteKnowledge() {
    isDeleting = true;
    try {
      await eneo.integrations.knowledge.delete({
        knowledge: knowledgeItem,
        space: $currentSpace
      });
      refreshCurrentSpace();
      $showDeleteDialog = false;
    } catch (e) {
      toastError(e, m.integration_delete_error());
      console.error(e);
    }
    isDeleting = false;
  }

  async function renameKnowledge() {
    isRenaming = true;
    try {
      await eneo.integrations.knowledge.rename({
        knowledge: knowledgeItem,
        space: $currentSpace,
        name: newName
      });
      refreshCurrentSpace();
      $showRenameDialog = false;
    } catch (e) {
      toastError(e, m.integration_rename_error());
      console.error(e);
    }
    isRenaming = false;
  }

  async function triggerFullSync() {
    isSyncing = true;
    try {
      await eneo.integrations.knowledge.triggerFullSync({
        knowledge: knowledgeItem,
        space: $currentSpace
      });
      refreshCurrentSpace();
      $showSyncDialog = false;
    } catch (e) {
      console.error(e);
    }
    isSyncing = false;
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
      $showChunkSettingsDialog = false;
    } catch (e) {
      toastError(e);
      console.error(e);
    }
    isSavingChunkSettings = false;
  }

  let showChunkSettingsDialog: Dialog.OpenState;
  let showDeleteDialog: Dialog.OpenState;
  let showRenameDialog: Dialog.OpenState;
  let showSyncDialog: Dialog.OpenState;
</script>

<Dropdown.Root>
  <Dropdown.Trigger let:trigger asFragment>
    <Button is={trigger} padding="icon">
      <IconEllipsis />
    </Button>
  </Dropdown.Trigger>
  <Dropdown.Menu let:item>
    {#if knowledgeItem.permissions?.includes("edit")}
      <Button
        is={item}
        on:click={() => {
          newName = knowledgeItem.name;
          $showRenameDialog = true;
        }}
        padding="icon-leading"
      >
        <IconEdit size="sm" />{m.rename()}</Button
      >
      <Button
        is={item}
        on:click={() => {
          chunkSize = knowledgeItem.chunk_size ?? null;
          chunkOverlap = knowledgeItem.chunk_overlap ?? null;
          $showChunkSettingsDialog = true;
        }}
        padding="icon-leading"
      >
        <IconEdit size="sm" />{m.chunk_settings_customize()}</Button
      >
    {/if}
    {#if knowledgeItem.integration_type === "sharepoint" && knowledgeItem.permissions?.includes("edit")}
      <Button
        is={item}
        on:click={() => {
          $showSyncDialog = true;
        }}
        padding="icon-leading"
      >
        <IconRefresh size="sm" />{m.trigger_full_sync()}</Button
      >
    {/if}
    {#if knowledgeItem.permissions?.includes("delete")}
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

<Dialog.Root bind:isOpen={showChunkSettingsDialog}>
  <Dialog.Content width="medium">
    <Dialog.Title>{m.chunk_settings_customize()}</Dialog.Title>
    <Dialog.Section scrollable={false}>
      <ChunkSettings
        bind:chunkSize
        bind:chunkOverlap
        maxInput={knowledgeItem.embedding_model?.max_input}
        hasIndexedContent={true}
      />
    </Dialog.Section>
    <Dialog.Controls let:close>
      <Button is={close}>{m.cancel()}</Button>
      <Button variant="primary" on:click={saveChunkSettings}
        >{isSavingChunkSettings ? m.saving() : m.save()}</Button
      >
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>

<Dialog.Root bind:isOpen={showRenameDialog}>
  <Dialog.Content width="small">
    <Dialog.Title>{m.integration_rename_title()}</Dialog.Title>
    <Dialog.Section scrollable={false}>
      <Input.Text bind:value={newName} label={m.name()} class="px-4 py-4" />
    </Dialog.Section>
    <Dialog.Controls let:close>
      <Button is={close}>{m.cancel()}</Button>
      <Button variant="primary" on:click={renameKnowledge} disabled={!newName.trim()}
        >{isRenaming ? m.saving() : m.save()}</Button
      >
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>

<Dialog.Root alert bind:isOpen={showSyncDialog}>
  <Dialog.Content width="small">
    <Dialog.Title>{m.trigger_full_sync()}</Dialog.Title>
    <Dialog.Description>
      {m.confirm_full_sync({ knowledgeName: knowledgeItem.name })}
    </Dialog.Description>
    <Dialog.Controls let:close>
      <Button is={close}>{m.cancel()}</Button>
      <Button variant="primary" on:click={triggerFullSync}
        >{isSyncing ? m.syncing() : m.start_full_sync()}</Button
      >
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>

<Dialog.Root alert bind:isOpen={showDeleteDialog}>
  <Dialog.Content width="small">
    <Dialog.Title>{m.delete_integration_knowledge()}</Dialog.Title>
    <Dialog.Description>
      {m.confirm_delete_integration_knowledge({ knowledgeName: knowledgeItem.name })}
    </Dialog.Description>
    <Dialog.Controls let:close>
      <Button is={close}>{m.cancel()}</Button>
      <Button variant="destructive" on:click={deleteKnowledge}
        >{isDeleting ? m.deleting() : m.delete()}</Button
      >
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
