<script lang="ts">
  import { Page, Settings } from "$lib/components/layout";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager.js";

  import { Button, Input, Tooltip } from "@intric/ui";
  import { afterNavigate, beforeNavigate } from "$app/navigation";

  import { initAssistantEditor } from "$lib/features/assistants/AssistantEditor.js";
  import { fade } from "svelte/transition";

  import AssistantSettingsAttachments from "./AssistantSettingsAttachments.svelte";
  import SelectAIModelV2 from "$lib/features/ai-models/components/SelectAIModelV2.svelte";
  import SelectBehaviourV2 from "$lib/features/ai-models/components/SelectBehaviourV2.svelte";
  import SelectModelSpecificSettings from "$lib/features/ai-models/components/SelectModelSpecificSettings.svelte";
  import SelectKnowledgeV2 from "$lib/features/knowledge/components/SelectKnowledgeV2.svelte";
  import PromptVersionDialog from "$lib/features/prompts/components/PromptVersionDialog.svelte";
  import dayjs from "dayjs";
  import PublishingSetting from "$lib/features/publishing/components/PublishingSetting.svelte";
  import { page } from "$app/state";
  import { getChatQueryParams } from "$lib/features/chat/getChatQueryParams.js";
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
  } = initAssistantEditor({
    assistant: data.assistant,
    intric: data.intric,
    onUpdateDone() {
      refreshCurrentSpace("applications");
    }
  });

  let cancelUploadsAndClearQueue: () => void;

  // Behavior-specific change detection for models with model-specific parameters
  $: hasBehaviorChanges = (() => {
    if (!$currentChanges.diff.completion_model_kwargs) return false;
    
    // For reasoning models or LiteLLM models, only show behavior changes if behavior-relevant fields changed
    const hasModelSpecificParams = $update.completion_model?.reasoning || $update.completion_model?.litellm_model_name;
    if (hasModelSpecificParams) {
      const original = $resource.completion_model_kwargs || {};
      const updated = $update.completion_model_kwargs || {};
      
      // Only check temperature and top_p for behavior changes
      const behaviorFieldsChanged = 
        original.temperature !== updated.temperature || 
        original.top_p !== updated.top_p;
      
      return behaviorFieldsChanged;
    }
    
    // For regular models, show changes if any kwargs changed
    return true;
  })();

  beforeNavigate((navigate) => {
    if (
      $currentChanges.hasUnsavedChanges &&
      !confirm("You have unsaved changes. Do you want to discard all changes?")
    ) {
      navigate.cancel();
      return;
    }
    // Discard changes that have been made, this is only important so we delete uploaded
    // files that have not been saved to the assistant
    discardChanges();
  });

  let showSavesChangedNotice = false;

  let previousRoute = `/spaces/${$currentSpace.routeId}/chat/?${getChatQueryParams({ chatPartner: data.assistant, tab: "chat" })}`;
  afterNavigate(({ from }) => {
    if (page.url.searchParams.get("next") === "default") return;
    if (from) previousRoute = from.url.toString();
  });
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
        href: `/spaces/${$currentSpace.routeId}/chat/?${getChatQueryParams({ chatPartner: data.assistant, tab: "chat" })}`
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
          description="Give this assistant a name that will be displayed to its users."
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
            class="border-default bg-primary ring-default rounded-lg border px-3 py-2 shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
          />
        </Settings.Row>

        <Settings.Row
          title="Description"
          description="A brief introducion to this assistant that will be shown when starting a new session."
          hasChanges={$currentChanges.diff.description !== undefined}
          revertFn={() => {
            discardChanges("description");
          }}
          let:aria
        >
          <textarea
            placeholder={`Hi, I'm ${$update.name}!\nAsk me anything to get started.`}
            {...aria}
            bind:value={$update.description}
            class="border-default bg-primary ring-default placeholder:text-muted min-h-24 rounded-lg border px-3 py-2 shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
          ></textarea>
        </Settings.Row>
      </Settings.Group>

      <Settings.Group title="Instructions">
        <Settings.Row
          title="Prompt"
          description="Describe how this assistant should behave and how it will answer questions."
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
                return data.intric.assistants.listPrompts({ id: data.assistant.id });
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
            class="border-default bg-primary ring-default min-h-24 rounded-lg border px-6 py-4 text-lg shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
          ></textarea>
        </Settings.Row>

        <Settings.Row
          title="Attachments"
          description="Attach further instructions, for example guidelines or important information. The assistant will always see everything included as an attachment."
          hasChanges={$currentChanges.diff.attachments !== undefined}
          revertFn={() => {
            cancelUploadsAndClearQueue();
            discardChanges("attachments");
          }}
        >
          <AssistantSettingsAttachments bind:cancelUploadsAndClearQueue
          ></AssistantSettingsAttachments>
        </Settings.Row>

        <Settings.Row
          title="Knowledge"
          description="Select additional knowledge sources that this assistant will be able to search for relevant answers."
          hasChanges={$currentChanges.diff.groups !== undefined ||
            $currentChanges.diff.websites !== undefined ||
            $currentChanges.diff.integration_knowledge_list !== undefined}
          revertFn={() => {
            discardChanges("groups");
            discardChanges("websites");
            discardChanges("integration_knowledge_list");
          }}
        >
          <SelectKnowledgeV2
            bind:selectedWebsites={$update.websites}
            bind:selectedCollections={$update.groups}
            bind:selectedIntegrationKnowledge={$update.integration_knowledge_list}
          ></SelectKnowledgeV2>
        </Settings.Row>
      </Settings.Group>

      <Settings.Group title="AI Settings">
        <Settings.Row
          title="Completion model"
          description="This model will be used to process the assistant's input and generate a response."
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
          description="Select a preset for how this model should behave, or configure its parameters manually."
          hasChanges={hasBehaviorChanges}
          revertFn={() => {
            discardChanges("completion_model_kwargs");
          }}
          let:aria
        >
          <SelectBehaviourV2
            bind:kwArgs={$update.completion_model_kwargs}
            selectedModel={$update.completion_model}
            isDisabled={!supportsTemperature($update.completion_model?.name)}
            {aria}
          ></SelectBehaviourV2>
        </Settings.Row>

        {#if $update.completion_model?.reasoning || $update.completion_model?.litellm_model_name}
        <Settings.Row
          title="Model settings"
          description="Configure model-specific parameters for advanced control over the response."
          hasChanges={$currentChanges.diff.completion_model_kwargs !== undefined}
          revertFn={() => {
            discardChanges("completion_model_kwargs");
          }}
        >
          <SelectModelSpecificSettings
            bind:kwArgs={$update.completion_model_kwargs}
            selectedModel={$update.completion_model}
          ></SelectModelSpecificSettings>
        </Settings.Row>
        {/if}
      </Settings.Group>

      {#if data.assistant.permissions?.some((permission) => permission === "insight_toggle" || permission === "publish")}
        <Settings.Group title="Publishing">
          {#if data.assistant.permissions?.includes("publish")}
            <Settings.Row
              title="Status"
              description="Publishing your assistant will make it available to all users of this space, including viewers."
            >
              <PublishingSetting
                endpoints={data.intric.assistants}
                resource={data.assistant}
                hasUnsavedChanges={$currentChanges.hasUnsavedChanges}
              />
            </Settings.Row>
          {/if}

          <Settings.Row
            hasChanges={$currentChanges.diff.insight_enabled !== undefined}
            revertFn={() => {
              discardChanges("insight_enabled");
            }}
            title="Insights"
            description="Collect insights about this assistant's usage and allow space editors and admins to access the full history of user questions."
          >
            <div class="border-default flex h-14 border-b py-2">
              <Tooltip
                text={data.assistant.permissions?.includes("insight_toggle")
                  ? undefined
                  : "Only space admins can toggle insights."}
                class="w-full"
              >
                <Input.RadioSwitch
                  bind:value={$update.insight_enabled}
                  labelTrue="Enable insights"
                  labelFalse="Disable insights"
                  disabled={!data.assistant.permissions?.includes("insight_toggle")}
                ></Input.RadioSwitch>
              </Tooltip>
            </div>
          </Settings.Row>
        </Settings.Group>
      {/if}

      <div class="min-h-24"></div>
    </Settings.Page>
  </Page.Main>
</Page.Root>
