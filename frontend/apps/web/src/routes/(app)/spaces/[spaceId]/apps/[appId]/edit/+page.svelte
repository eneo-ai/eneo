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
  import { supportsTemperature } from "$lib/features/ai-models/supportsTemperature.js";

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
      !confirm("You have unsaved changes. Do you want to discard all changes?")
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
    >Eneo.ai – {data.currentSpace.personal ? "Personal" : data.currentSpace.name} – {$resource.name}</title
  >
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title
      parent={{
        title: $resource.name,
        href: `/spaces/${$currentSpace.routeId}/apps/${data.app.id}`
      }}
      title="Edit"
    ></Page.Title>
    <Page.Flex>
      {#if $currentChanges.hasUnsavedChanges}
        <Button
          variant="destructive"
          disabled={$isSaving}
          on:click={() => {
            cancelUploadsAndClearQueue();
            discardChanges();
          }}>Discard all changes</Button
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
          }}>{$isSaving ? "Saving..." : "Save changes"}</Button
        >
      {:else}
        {#if showSavesChangedNotice}
          <p class="text-positive-stronger px-4" transition:fade>All changes saved!</p>
        {/if}
        <Button variant="primary" class="w-32" href={previousRoute}>Done</Button>
      {/if}
    </Page.Flex>
  </Page.Header>

  <Page.Main>
    <Settings.Page>
      <Settings.Group title="General">
        <Settings.Row
          title="Name"
          description="A brief name of this app that will be displayed to its users."
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
          title="Description"
          description="A brief description of this app that will be displayed to its users."
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
            title="Status"
            description="Publishing your app will make it available to all users of this space, including viewers."
          >
            <PublishingSetting
              endpoints={data.intric.apps}
              resource={data.app}
              hasUnsavedChanges={$currentChanges.hasUnsavedChanges}
            />
          </Settings.Row>
        {/if}
      </Settings.Group>

      <Settings.Group title="Input">
        <AppSettingsInput></AppSettingsInput>
      </Settings.Group>

      <Settings.Group title="Instructions">
        <Settings.Row
          title="Prompt"
          description="Describe what this app should do with the input data."
          hasChanges={$currentChanges.diff.prompt !== undefined}
          revertFn={() => {
            discardChanges("prompt");
          }}
          fullWidth
          let:aria
        >
          <div slot="toolbar" class="text-secondary">
            <PromptVersionDialog
              title="Prompt history for {$resource.name}"
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
          title="Attachments"
          description="Attach files to your instructions, for example guidelines, background information or formatting templates."
          hasChanges={$currentChanges.diff.attachments !== undefined}
          revertFn={() => {
            cancelUploadsAndClearQueue();
            discardChanges("attachments");
          }}
        >
          <AppSettingsAttachments bind:cancelUploadsAndClearQueue></AppSettingsAttachments>
        </Settings.Row>
      </Settings.Group>

      <Settings.Group title="AI Settings">
        {#if $update.input_fields.some( (field) => ["audio-recorder", "audio-upload"].includes(field.type) )}
          <Settings.Row
            title="Transcription model"
            description="This model will be used to transcribe audio input to text before processing it further."
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
          title="Completion model"
          description="This model will be used to process the app's input and generate a response."
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
          title="Model behaviour"
          description="Select a preset for how the completion model should behave, or configure its parameters manually."
          hasChanges={$currentChanges.diff.completion_model_kwargs !== undefined}
          revertFn={() => {
            discardChanges("completion_model_kwargs");
          }}
          let:aria
        >
          <SelectBehaviourV2
            bind:kwArgs={$update.completion_model_kwargs}
            isDisabled={!supportsTemperature($update.completion_model?.name)}
            selectedModel={$update.completion_model}
            {aria}
          ></SelectBehaviourV2>
        </Settings.Row>
      </Settings.Group>
    </Settings.Page>
  </Page.Main>
</Page.Root>
