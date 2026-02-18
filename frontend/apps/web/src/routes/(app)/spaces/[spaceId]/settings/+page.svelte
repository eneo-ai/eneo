<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { beforeNavigate } from "$app/navigation";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { initSpaceSettingsEditor } from "$lib/features/spaces/SpaceSettingsEditor";
  import { Button, Dialog, Input } from "@intric/ui";
  import SelectEmbeddingModels from "./SelectEmbeddingModels.svelte";
  import EditNameAndDescription from "./EditNameAndDescription.svelte";
  import SelectCompletionModels from "./SelectCompletionModels.svelte";
  import SelectMCPServers from "./SelectMCPServers.svelte";
  import { Page, Settings } from "$lib/components/layout";
  import SpaceStorageOverview from "./SpaceStorageOverview.svelte";
  import SelectTranscriptionModels from "./SelectTranscriptionModels.svelte";
  import { writable } from "svelte/store";
  import { getIntric } from "$lib/core/Intric.js";
  import ChangeSecurityClassification from "./ChangeSecurityClassification.svelte";
  import EditRetentionPolicy from "./EditRetentionPolicy.svelte";
  import { m } from "$lib/paraglide/messages";
  import IconUpload from "$lib/features/icons/IconUpload.svelte";
  import { fade } from "svelte/transition";

  const intric = getIntric();

  let { data } = $props();
  let models = $state(data.models);
  let completionModels = $derived(models.completionModels.filter((model) => model.is_org_enabled));
  let embeddingModels = $derived(models.embeddingModels.filter((model) => model.is_org_enabled));
  let transcriptionModels = $derived(
    models.transcriptionModels.filter((model) => model.is_org_enabled)
  );

  const spaces = getSpacesManager();
  const currentSpace = spaces.state.currentSpace;

  // Get tenant-enabled MCP servers from space data
  let mcpServers = $derived($currentSpace.mcp_servers ?? []);
  // Initialize the Space Settings Editor for page-level save
  const {
    state: { update, currentChanges, isSaving },
    saveChanges,
    discardChanges
  } = initSpaceSettingsEditor({
    space: $currentSpace,
    intric,
    onUpdateDone: async (updatedSpace) => {
      // Sync with SpacesManager so sidebar and other components update
      await spaces.refreshCurrentSpace();
    }
  });

  // Track success message
  let showSaveSuccess = $state(false);
  let saveSuccessTimeout: ReturnType<typeof setTimeout>;

  // Navigation guard for unsaved changes
  beforeNavigate((navigate) => {
    if ($currentChanges.hasUnsavedChanges) {
      const confirmMessage = m.unsaved_changes_warning?.() ?? "Du har osparade ändringar. Vill du lämna sidan?";
      if (!confirm(confirmMessage)) {
        navigate.cancel();
        return;
      }
    }
    discardChanges();
  });

  // Handle save with success feedback
  async function handleSave() {
    await saveChanges();
    showSaveSuccess = true;
    clearTimeout(saveSuccessTimeout);
    saveSuccessTimeout = setTimeout(() => {
      showSaveSuccess = false;
    }, 5000);
  }

  let showDeleteDialog = writable(false);
  let deleteConfirmation = $state("");
  let isDeleting = $state(false);
  let showStillDeletingMessage = $state(false);
  let deletionMessageTimeout: ReturnType<typeof setTimeout>;
  let isOrgSpace = $currentSpace.organization;

  // Icon state - uses editor for icon_id but handles upload separately
  let iconUploading = $state(false);
  let iconError = $state<string | null>(null);

  function getIconUrl(id: string | null | undefined): string | null {
    return id ? intric.icons.url({ id }) : null;
  }

  // Use the update store's icon_id for displaying current icon
  let iconUrl = $derived(getIconUrl($update.icon_id));

  async function handleIconUpload(event: CustomEvent<File>) {
    const file = event.detail;
    iconUploading = true;
    iconError = null;
    try {
      const newIcon = await intric.icons.upload({ file });
      // Update the editor's update store - will be saved with other changes
      $update.icon_id = newIcon.id;
    } catch (error) {
      console.error("Failed to upload icon:", error);
      iconError = m.avatar_upload_failed();
    } finally {
      iconUploading = false;
    }
  }

  async function handleIconDelete() {
    iconError = null;
    try {
      // Delete the icon file from server
      if ($update.icon_id) {
        await intric.icons.delete({ id: $update.icon_id });
      }
      // Update the editor's update store - will be saved with other changes
      $update.icon_id = null;
    } catch (error) {
      console.error("Failed to delete icon:", error);
      iconError = m.avatar_delete_failed();
    }
  }

  async function deleteSpace() {
    if (deleteConfirmation === "") return;
    if (deleteConfirmation !== $currentSpace.name) {
      alert(m.wrong_space_name());
      return;
    }
    isDeleting = true;
    deletionMessageTimeout = setTimeout(() => {
      showStillDeletingMessage = true;
    }, 5000);
    try {
      await spaces.deleteSpace($currentSpace);
    } catch (e) {
      alert(m.error_deleting_space());
      console.error(e);
    }
    clearTimeout(deletionMessageTimeout);
    showStillDeletingMessage = false;
    isDeleting = false;
  }
</script>

<svelte:head>
  <title>{m.app_name()} – {$currentSpace.name} – {m.settings()}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title={m.settings()}></Page.Title>
    <Page.Flex>
      {#if $currentChanges.hasUnsavedChanges}
        <Button
          variant="destructive"
          disabled={$isSaving}
          on:click={() => discardChanges()}
        >{m.discard_all_changes()}</Button>
        <Button
          variant="positive"
          class="h-8 w-32 whitespace-nowrap"
          disabled={$isSaving}
          on:click={handleSave}
        >{$isSaving ? m.loading() : m.save_changes()}</Button>
      {:else}
        {#if showSaveSuccess}
          <p class="text-positive-stronger px-4" transition:fade>{m.all_changes_saved()}</p>
        {/if}
        <Button variant="primary" class="w-32" href={`/spaces/${$currentSpace.routeId}`}>{m.done()}</Button>
      {/if}
    </Page.Flex>
  </Page.Header>

  <Page.Main>
    <Settings.Page>
      {#if !isOrgSpace}
      <Settings.Group title={m.general()}>
        <EditNameAndDescription></EditNameAndDescription>
        <Settings.Row
          title={m.avatar()}
          description={m.avatar_description()}
          hasChanges={$currentChanges.diff.icon_id !== undefined}
          revertFn={() => discardChanges("icon_id")}
        >
          <IconUpload
            {iconUrl}
            uploading={iconUploading}
            error={iconError}
            on:upload={handleIconUpload}
            on:delete={handleIconDelete}
          />
        </Settings.Row>
        <SpaceStorageOverview></SpaceStorageOverview>
      </Settings.Group>
      {/if}
      {#if !isOrgSpace}
        <Settings.Group title={m.security_and_privacy()}>
          {#if data.isSecurityEnabled}
            <ChangeSecurityClassification
              classifications={data.classifications}
              onUpdateDone={async () => {
                // If the classification was changed we update the models to get their availability
                models = await intric.models.list({ space: $currentSpace });
              }}
            ></ChangeSecurityClassification>
          {/if}

          <EditRetentionPolicy />
        </Settings.Group>
      {/if}

      <Settings.Group title={m.advanced_settings()}>
        <SelectCompletionModels selectableModels={completionModels}></SelectCompletionModels>

        <SelectEmbeddingModels selectableModels={embeddingModels}></SelectEmbeddingModels>

        <SelectTranscriptionModels selectableModels={transcriptionModels}
        ></SelectTranscriptionModels>

        <SelectMCPServers selectableServers={data.mcpServers}></SelectMCPServers>
      </Settings.Group>

      {#if !isOrgSpace && $currentSpace.permissions?.includes("delete")}
        <Settings.Group title={m.danger_zone()}>
          <Settings.Row title={m.delete_space()} description={m.delete_space_description()}>
            <Dialog.Root alert openController={showDeleteDialog}>
              <Dialog.Trigger asFragment let:trigger>
                <Button is={trigger} variant="destructive" class="flex-grow"
                  >{m.delete_this_space()}</Button
                >
              </Dialog.Trigger>
              <Dialog.Content width="medium" form>
                <Dialog.Title>{m.delete_space()}</Dialog.Title>

                <Dialog.Section>
                  <p class="border-default hover:bg-hover-dimmer border-b px-7 py-4">
                    {m.confirm_delete_space_message({ space: $currentSpace.name })}
                  </p>
                  <Input.Text
                    bind:value={deleteConfirmation}
                    label={m.enter_space_name_to_confirm()}
                    required
                    placeholder={$currentSpace.name}
                    class=" border-default hover:bg-hover-dimmer px-4 py-4"
                  ></Input.Text>
                </Dialog.Section>

                {#if showStillDeletingMessage}
                  <p
                    class="label-info border-label-default bg-label-dimmer text-label-stronger mt-2 rounded-md border p-2"
                  >
                    <span class="font-bold">{m.hint()}:</span>
                    {m.delete_space_hint()}
                  </p>
                {/if}

                <Dialog.Controls let:close>
                  <Button is={close} disabled={isDeleting}>{m.cancel()}</Button>
                  <Button variant="destructive" on:click={deleteSpace} disabled={isDeleting}
                    >{isDeleting ? m.deleting() : m.confirm_deletion()}</Button
                  >
                </Dialog.Controls>
              </Dialog.Content>
            </Dialog.Root>
          </Settings.Row>
        </Settings.Group>
      {/if}
    </Settings.Page>
  </Page.Main>
</Page.Root>
