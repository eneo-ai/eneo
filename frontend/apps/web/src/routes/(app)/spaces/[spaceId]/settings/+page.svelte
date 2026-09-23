<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { beforeNavigate } from "$app/navigation";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { initSpaceSettingsEditor } from "$lib/features/spaces/SpaceSettingsEditor";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import { dialogLayout } from "$lib/components/dialogLayout.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import SelectSpaceModels from "./SelectSpaceModels.svelte";
  import Hint from "$lib/components/Hint.svelte";
  import EditNameAndDescription from "./EditNameAndDescription.svelte";
  import SelectMCPServers from "./SelectMCPServers.svelte";
  import CapabilityRow from "./CapabilityRow.svelte";
  import { CAPABILITIES } from "$lib/features/mcp/capabilities";
  import { Page, Settings } from "$lib/components/layout";
  import SpaceStorageOverview from "./SpaceStorageOverview.svelte";
  import { getEneo } from "$lib/core/Eneo.js";
  import ChangeSecurityClassification from "./ChangeSecurityClassification.svelte";
  import EditRetentionPolicy from "./EditRetentionPolicy.svelte";
  import { m } from "$lib/paraglide/messages";
  import { toast } from "$lib/components/toast";
  import { toastError } from "$lib/core/errors";
  import IconUpload from "$lib/features/icons/IconUpload.svelte";
  import ApiKeysSettingsSection from "$lib/features/api-keys/ApiKeysSettingsSection.svelte";
  import { fade } from "svelte/transition";
  import { untrack } from "svelte";

  const eneo = getEneo();

  let { data } = $props();
  const uid = $props.id();
  let models = $state(untrack(() => data.models));
  let completionModels = $derived(
    models.completionModels.filter(
      (model) => model.is_org_enabled && !model.is_deprecated && !model.migrated_to_model_id
    )
  );
  let embeddingModels = $derived(
    models.embeddingModels.filter((model) => model.is_org_enabled && !model.is_deprecated)
  );
  let transcriptionModels = $derived(
    models.transcriptionModels.filter(
      (model) => model.is_org_enabled && !model.is_deprecated && !model.migrated_to_model_id
    )
  );

  const spaces = getSpacesManager();
  const currentSpace = spaces.state.currentSpace;

  // Initialize the Space Settings Editor for page-level save
  const {
    state: { update, currentChanges, isSaving },
    saveChanges,
    discardChanges
  } = initSpaceSettingsEditor({
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    space: $currentSpace as any,
    eneo,
    onUpdateDone: async () => {
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
      const confirmMessage = m.unsaved_changes_warning();
      if (!confirm(confirmMessage)) {
        navigate.cancel();
        return;
      }
    }
    discardChanges();
  });

  // Handle save with success feedback
  async function handleSave() {
    if (!(await saveChanges())) return;
    showSaveSuccess = true;
    clearTimeout(saveSuccessTimeout);
    saveSuccessTimeout = setTimeout(() => {
      showSaveSuccess = false;
    }, 5000);
  }

  let showDeleteDialog = $state(false);
  let deleteConfirmation = $state("");
  let isDeleting = $state(false);
  let showStillDeletingMessage = $state(false);
  let deletionMessageTimeout: ReturnType<typeof setTimeout>;
  let isOrgSpace = $currentSpace.organization;

  // Icon state - uses editor for icon_id but handles upload separately
  let iconUploading = $state(false);
  let iconError = $state<string | null>(null);

  function getIconUrl(id: string | null | undefined): string | null {
    return id ? eneo.icons.url({ id }) : null;
  }

  // Use the update store's icon_id for displaying current icon
  let iconUrl = $derived(getIconUrl($update.icon_id));

  async function handleIconUpload(event: CustomEvent<File>) {
    const file = event.detail;
    iconUploading = true;
    iconError = null;
    try {
      const newIcon = await eneo.icons.upload({ file });
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
        await eneo.icons.delete({ id: $update.icon_id });
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
      toast.warning(m.wrong_space_name());
      return;
    }
    isDeleting = true;
    deletionMessageTimeout = setTimeout(() => {
      showStillDeletingMessage = true;
    }, 5000);
    try {
      await spaces.deleteSpace($currentSpace);
    } catch (e) {
      toastError(e, m.error_deleting_space());
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
        <Button variant="destructive" disabled={$isSaving} onclick={() => discardChanges()}
          >{m.discard_all_changes()}</Button
        >
        <Button
          class="bg-positive-default hover:bg-positive-stronger h-8 w-32 whitespace-nowrap"
          disabled={$isSaving}
          onclick={handleSave}>{$isSaving ? m.loading() : m.save_changes()}</Button
        >
      {:else}
        {#if showSaveSuccess}
          <p class="text-positive-stronger px-4" transition:fade>{m.all_changes_saved()}</p>
        {/if}
        <Button class="w-32" href={`/spaces/${$currentSpace.routeId}`}>{m.done()}</Button>
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
                models = await eneo.models.list({ space: $currentSpace });
              }}
            ></ChangeSecurityClassification>
          {/if}

          <EditRetentionPolicy />
        </Settings.Group>
      {/if}

      <Settings.Group title={m.advanced_settings()}>
        <SelectSpaceModels
          field="completion_models"
          selectableModels={completionModels}
          title={m.completion_models()}
          description={m.completion_models_description()}
          hint={m.enable_completion_model_for_assistants()}
        />

        <SelectSpaceModels
          field="embedding_models"
          selectableModels={embeddingModels}
          title={m.embedding_models()}
          description={m.embedding_models_description()}
          hint={m.embedding_models_hint()}
        >
          {#snippet extra()}
            {#if $currentSpace.embedding_models.length > 1}
              <Hint class="mt-2.5">
                {isOrgSpace
                  ? m.embedding_models_multiple_warning_organization()
                  : m.embedding_models_multiple_warning()}
              </Hint>
            {/if}
          {/snippet}
        </SelectSpaceModels>

        <SelectSpaceModels
          field="transcription_models"
          selectableModels={transcriptionModels}
          title={m.transcription_models()}
          description={m.transcription_models_description()}
          hint={m.transcription_models_hint()}
        />

        <SelectMCPServers selectableServers={data.mcpServers}></SelectMCPServers>

        <Settings.Row title={m.capabilities()} description={m.capabilities_space_description()}>
          <div class="border-default overflow-hidden rounded-xl border">
            {#each CAPABILITIES as capability (capability.purpose)}
              <CapabilityRow {capability} />
            {/each}
          </div>
        </Settings.Row>
      </Settings.Group>

      {#if !isOrgSpace && $currentSpace.permissions?.includes("edit")}
        <Settings.Group title={m.api_access()}>
          <Settings.Row
            title={m.api_keys()}
            description={m.api_keys_space_settings_desc()}
            fullWidth
          >
            <ApiKeysSettingsSection
              scopeType="space"
              scopeId={$currentSpace.id}
              scopeName={$currentSpace.name}
            />
          </Settings.Row>
        </Settings.Group>
      {/if}

      {#if !isOrgSpace && $currentSpace.permissions?.includes("delete")}
        <Settings.Group title={m.danger_zone()}>
          <Settings.Row title={m.delete_space()} description={m.delete_space_description()}>
            <AlertDialog.Root bind:open={showDeleteDialog}>
              <AlertDialog.Trigger>
                {#snippet child({ props })}
                  <Button {...props} variant="destructive" class="flex-grow"
                    >{m.delete_this_space()}</Button
                  >
                {/snippet}
              </AlertDialog.Trigger>
              <AlertDialog.Content class={dialogLayout.content("medium")}>
                <form
                  class="contents"
                  onsubmit={(event) => {
                    event.preventDefault();
                    deleteSpace();
                  }}
                >
                  <AlertDialog.Header class={dialogLayout.header}>
                    <AlertDialog.Title>{m.delete_space()}</AlertDialog.Title>
                  </AlertDialog.Header>

                  <div class={dialogLayout.body}>
                    <div class={dialogLayout.section}>
                      <p class="border-default hover:bg-hover-dimmer border-b px-7 py-4">
                        {m.confirm_delete_space_message({ space: $currentSpace.name })}
                      </p>
                      <Field.Field class="border-default hover:bg-hover-dimmer px-4 py-4">
                        <Field.Label for={`${uid}-delete-confirmation`}>
                          {m.enter_space_name_to_confirm()}
                          <span class="text-muted font-normal" aria-hidden="true"
                            >({m.required()})</span
                          >
                        </Field.Label>
                        <Input
                          id={`${uid}-delete-confirmation`}
                          bind:value={deleteConfirmation}
                          required
                          placeholder={$currentSpace.name}
                        />
                      </Field.Field>
                    </div>

                    {#if showStillDeletingMessage}
                      <p
                        class="label-info border-label-default bg-label-dimmer text-label-stronger rounded-md border p-2"
                      >
                        <span class="font-bold">{m.hint()}:</span>
                        {m.delete_space_hint()}
                      </p>
                    {/if}
                  </div>

                  <AlertDialog.Footer class={dialogLayout.footer}>
                    <AlertDialog.Cancel type="button" disabled={isDeleting}
                      >{m.cancel()}</AlertDialog.Cancel
                    >
                    <Button type="submit" variant="destructive" disabled={isDeleting}
                      >{isDeleting ? m.deleting() : m.confirm_deletion()}</Button
                    >
                  </AlertDialog.Footer>
                </form>
              </AlertDialog.Content>
            </AlertDialog.Root>
          </Settings.Row>
        </Settings.Group>
      {/if}
    </Settings.Page>
  </Page.Main>
</Page.Root>
