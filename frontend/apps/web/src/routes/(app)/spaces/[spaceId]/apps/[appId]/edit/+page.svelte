<script lang="ts">
  import { Page, Settings } from "$lib/components/layout";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager.js";

  import { Button } from "@intric/ui";
  import AppSettingsInput from "./AppSettingsInput.svelte";
  import { afterNavigate, beforeNavigate } from "$app/navigation";

  import { fade } from "svelte/transition";
  import { initAppEditor } from "$lib/features/apps/AppEditor";
  import AppSettingsAttachments from "./AppSettingsAttachments.svelte";
  import SelectAIModelV2 from "$lib/features/ai-models/components/SelectAIModelV2.svelte";
  import SelectBehaviourV2 from "$lib/features/ai-models/components/SelectBehaviourV2.svelte";
  import PromptVersionDialog from "$lib/features/prompts/components/PromptVersionDialog.svelte";
  import dayjs from "dayjs";
  import PublishingSetting from "$lib/features/publishing/components/PublishingSetting.svelte";
  import { page } from "$app/state";
  import { m } from "$lib/paraglide/messages";

  export let data;
  const {
    state: { currentSpace },
    refreshCurrentSpace
  } = getSpacesManager();

  const {
    state: { resource, update, currentChanges, isSaving },
    saveChanges,
    discardChanges
  } = initAppEditor({
    app: data.app,
    intric: data.intric,
    onUpdateDone() {
      refreshCurrentSpace("applications");
    }
  });

  let cancelUploadsAndClearQueue: () => void;

  beforeNavigate((navigate) => {
    if (
      $currentChanges.hasUnsavedChanges &&
      !confirm(m.confirm_discard())
    ) {
      navigate.cancel();
      return;
    }
    // Discard changes that have been made, this is only important so we delete uploaded
    // files that have not been saved to the app
    discardChanges();
  });

  let previousRoute = `/spaces/${$currentSpace.routeId}/apps/${data.app.id}`;
  afterNavigate(({ from }) => {
    if (page.url.searchParams.get("next") === "default") return;
    if (from) previousRoute = from.url.toString();
  });

  let showSavesChangedNotice = false;
</script>

<svelte:head>
  <title
    >Eneo.ai – {data.currentSpace.personal ? m.personal() : data.currentSpace.name} – {$resource.name}</title
  >
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title
      parent={{
        title: $resource.name,
        href: `/spaces/${$currentSpace.routeId}/apps/${data.app.id}`
      }}
      title={m.edit()}
    ></Page.Title>
    <Page.Flex>
      {#if $currentChanges.hasUnsavedChanges}
        <Button
          variant="destructive"
          disabled={$isSaving}
          on:click={() => {
            cancelUploadsAndClearQueue();
            discardChanges();
          }}>{m.discard_all_changes()}</Button
        >
        <Button
          variant="positive"
          class="w-32"
          on:click={async () => {
            cancelUploadsAndClearQueue();
            await saveChanges();
            showSavesChangedNotice = true;
            setTimeout(() => {
              showSavesChangedNotice = false;
            }, 5000);
          }}>{$isSaving ? m.saving() : m.save_changes()}</Button
        >
      {:else}
        {#if showSavesChangedNotice}
          <p class="text-positive-stronger px-4" transition:fade>{m.all_changes_saved()}</p>
        {/if}
        <Button variant="primary" class="w-32" href={previousRoute}>{m.done()}</Button>
      {/if}
    </Page.Flex>
  </Page.Header>

  <Page.Main>
    <Settings.Page>
      <Settings.Group title={m.general()}>
        <Settings.Row
          title={m.name()}
          description={m.app_name_description()}
          hasChanges={$currentChanges.diff.name !== undefined}
          revertFn={() => {
            discardChanges("name");
          }}
          let:aria
        >
          <input
            type="text"
            {...aria}
            bind:value={$update.name}
            class="border-stronger bg-primary text-primary ring-default rounded-lg border px-3 py-2 shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
          />
        </Settings.Row>

        <Settings.Row
          title={m.description()}
          description={m.app_description_description()}
          hasChanges={$currentChanges.diff.description !== undefined}
          revertFn={() => {
            discardChanges("description");
          }}
          let:aria
        >
          <textarea
            {...aria}
            bind:value={$update.description}
            class=" border-stronger bg-primary text-primary ring-default min-h-24 rounded-lg border px-3 py-2 shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
          ></textarea>
        </Settings.Row>

        {#if data.app.permissions?.includes("publish")}
          <Settings.Row
            title={m.status()}
            description={m.publishing_description()}
          >
            <PublishingSetting
              endpoints={data.intric.apps}
              resource={data.app}
              hasUnsavedChanges={$currentChanges.hasUnsavedChanges}
            />
          </Settings.Row>
        {/if}
      </Settings.Group>

      <Settings.Group title={m.input()}>
        <AppSettingsInput></AppSettingsInput>
      </Settings.Group>

      <Settings.Group title={m.instructions()}>
        <Settings.Row
          title={m.prompt()}
          description={m.app_prompt_description()}
          hasChanges={$currentChanges.diff.prompt !== undefined}
          revertFn={() => {
            discardChanges("prompt");
          }}
          fullWidth
          let:aria
        >
          <div slot="toolbar" class="text-secondary">
            <PromptVersionDialog
              title={m.prompt_history_for({ name: $resource.name })}
              loadPromptVersionHistory={() => {
                return data.intric.apps.listPrompts({ id: data.app.id });
              }}
              onPromptSelected={(prompt) => {
                const restoredDate = dayjs(prompt.created_at).format("YYYY-MM-DD HH:mm");
                $update.prompt.text = prompt.text;
                $update.prompt.description = `Restored prompt from ${restoredDate}`;
              }}
            ></PromptVersionDialog>
          </div>
          <textarea
            rows={4}
            {...aria}
            bind:value={$update.prompt.text}
            on:change={() => {
              $update.prompt.description = "";
            }}
            class="border-stronger bg-primary text-primary ring-default min-h-24 rounded-lg border px-6 py-4 text-lg shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
          ></textarea>
        </Settings.Row>

        <Settings.Row
          title={m.attachments()}
          description={m.app_attachments_description()}
          hasChanges={$currentChanges.diff.attachments !== undefined}
          revertFn={() => {
            cancelUploadsAndClearQueue();
            discardChanges("attachments");
          }}
        >
          <AppSettingsAttachments bind:cancelUploadsAndClearQueue></AppSettingsAttachments>
        </Settings.Row>
      </Settings.Group>

      <Settings.Group title={m.ai_settings()}>
        {#if $update.input_fields.some( (field) => ["audio-recorder", "audio-upload"].includes(field.type) )}
          <Settings.Row
            title={m.transcription_model()}
            description={m.transcription_model_description()}
            hasChanges={$currentChanges.diff.transcription_model !== undefined}
            revertFn={() => {
              discardChanges("transcription_model");
            }}
            let:aria
          >
            <SelectAIModelV2
              bind:selectedModel={$update.transcription_model}
              availableModels={$currentSpace.transcription_models}
              {aria}
            ></SelectAIModelV2>
          </Settings.Row>
        {/if}

        <Settings.Row
          title={m.completion_model()}
          description={m.completion_model_description()}
          hasChanges={$currentChanges.diff.completion_model !== undefined}
          revertFn={() => {
            discardChanges("completion_model");
          }}
          let:aria
        >
          <SelectAIModelV2
            bind:selectedModel={$update.completion_model}
            availableModels={$currentSpace.completion_models}
            {aria}
          ></SelectAIModelV2>
        </Settings.Row>

        <Settings.Row
          title={m.model_behaviour()}
          description={m.model_behaviour_description()}
          hasChanges={$currentChanges.diff.completion_model_kwargs !== undefined}
          revertFn={() => {
            discardChanges("completion_model_kwargs");
          }}
          let:aria
        >
          <SelectBehaviourV2
            bind:kwArgs={$update.completion_model_kwargs}
            isDisabled={false}
            {aria}
          ></SelectBehaviourV2>
        </Settings.Row>
      </Settings.Group>
    </Settings.Page>
  </Page.Main>
</Page.Root>
