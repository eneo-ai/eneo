<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { Button, Dialog, Input } from "@intric/ui";
  import SelectEmbeddingModels from "./SelectEmbeddingModels.svelte";
  import EditNameAndDescription from "./EditNameAndDescription.svelte";
  import SelectCompletionModels from "./SelectCompletionModels.svelte";
  import { Page, Settings } from "$lib/components/layout";
  import SpaceStorageOverview from "./SpaceStorageOverview.svelte";
  import SelectTranscriptionModels from "./SelectTranscriptionModels.svelte";
  import { writable } from "svelte/store";
  import { getIntric } from "$lib/core/Intric.js";
  import ChangeSecurityClassification from "./ChangeSecurityClassification.svelte";
  import { m } from "$lib/paraglide/messages";

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

  let showDeleteDialog = writable(false);
  let deleteConfirmation = $state("");
  let isDeleting = $state(false);
  let showStillDeletingMessage = $state(false);
  let deletionMessageTimeout: ReturnType<typeof setTimeout>;

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
  </Page.Header>

  <Page.Main>
    <Settings.Page>
      <Settings.Group title={m.general()}>
        <EditNameAndDescription></EditNameAndDescription>
        <SpaceStorageOverview></SpaceStorageOverview>
      </Settings.Group>

      <Settings.Group title={m.advanced_settings()}>
        {#if data.isSecurityEnabled}
          <ChangeSecurityClassification
            classifications={data.classifications}
            onUpdateDone={async () => {
              // If the classification was changed we update the models to get their availability
              models = await intric.models.list({ space: $currentSpace });
            }}
          ></ChangeSecurityClassification>
        {/if}

        <SelectCompletionModels selectableModels={completionModels}></SelectCompletionModels>

        <SelectEmbeddingModels selectableModels={embeddingModels}></SelectEmbeddingModels>

        <SelectTranscriptionModels selectableModels={transcriptionModels}
        ></SelectTranscriptionModels>
      </Settings.Group>

      {#if $currentSpace.permissions?.includes("delete")}
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
