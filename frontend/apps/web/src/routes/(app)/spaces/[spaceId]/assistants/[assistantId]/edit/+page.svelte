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
  import SelectMCPServers from "$lib/features/mcp/components/SelectMCPServers.svelte";
  import PromptVersionDialog from "$lib/features/prompts/components/PromptVersionDialog.svelte";
  import dayjs from "dayjs";
  import PublishingSetting from "$lib/features/publishing/components/PublishingSetting.svelte";
  import { page } from "$app/state";
  import { getChatQueryParams } from "$lib/features/chat/getChatQueryParams.js";
  import { supportsTemperature } from "$lib/features/ai-models/supportsTemperature.js";
  import { m } from "$lib/paraglide/messages";
  import RetentionPolicyInput from "$lib/components/settings/RetentionPolicyInput.svelte";
  import IconUpload from "$lib/features/icons/IconUpload.svelte";

  let { data } = $props();

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

  // Icon state
  let currentIconId = $state<string | null>($resource.icon_id);
  let iconUploading = $state(false);
  let iconError = $state<string | null>(null);

  function getIconUrl(id: string | null): string | null {
    return id ? data.intric.icons.url({ id }) : null;
  }

  let iconUrl = $derived(getIconUrl(currentIconId));

  async function handleIconUpload(event: CustomEvent<File>) {
    const file = event.detail;
    iconUploading = true;
    iconError = null;
    try {
      const newIcon = await data.intric.icons.upload({ file });
      await data.intric.assistants.update({
        assistant: { id: $resource.id },
        update: { icon_id: newIcon.id }
      });
      currentIconId = newIcon.id;
      await refreshCurrentSpace("applications");
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
      if (currentIconId) {
        await data.intric.icons.delete({ id: currentIconId });
      }
      await data.intric.assistants.update({
        assistant: { id: $resource.id },
        update: { icon_id: null }
      });
      currentIconId = null;
      await refreshCurrentSpace("applications");
    } catch (error) {
      console.error("Failed to delete icon:", error);
      iconError = m.avatar_delete_failed();
    }
  }

  // Behavior-specific change detection for models with model-specific parameters
  let hasBehaviorChanges = $derived.by(() => {
    if (!$currentChanges.diff.completion_model_kwargs) return false;

    // For reasoning models or LiteLLM models, only show behavior changes if behavior-relevant fields changed
    const hasModelSpecificParams =
      $update.completion_model?.reasoning || $update.completion_model?.litellm_model_name;
    if (hasModelSpecificParams) {
      const original = $resource.completion_model_kwargs || {};
      const updated = $update.completion_model_kwargs || {};

      // Only check temperature and top_p for behavior changes
      const behaviorFieldsChanged =
        original.temperature !== updated.temperature || original.top_p !== updated.top_p;

      return behaviorFieldsChanged;
    }

    // For regular models, show changes if any kwargs changed
    return true;
  });

  beforeNavigate((navigate) => {
    if ($currentChanges.hasUnsavedChanges && !confirm(m.unsaved_changes_warning())) {
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
    >Eneo.ai – {data.currentSpace.personal ? m.personal() : data.currentSpace.name} – {$resource.name}</title
  >
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title
      parent={{
        title: $resource.name,
        href: `/spaces/${$currentSpace.routeId}/chat/?${getChatQueryParams({ chatPartner: data.assistant, tab: "chat" })}`
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
          class="h-8 w-32 whitespace-nowrap"
          on:click={async () => {
            cancelUploadsAndClearQueue();

            // Clean up incompatible parameters when switching models
            if ($update.completion_model_kwargs && $currentChanges.diff.completion_model) {
              const cleanedKwargs = { ...$update.completion_model_kwargs };

              // If model changed, reset to safe defaults for the new model
              const newModel = $update.completion_model;
              const originalModel = $resource.completion_model;

              // Check if we switched between different model families/types
              const modelChanged = newModel?.id !== originalModel?.id;

              if (modelChanged) {
                // Reset model-specific parameters that may not be compatible

                // Remove reasoning_effort if new model doesn't support reasoning
                if (!newModel?.reasoning) {
                  delete cleanedKwargs.reasoning_effort;
                }

                // Remove verbosity if new model doesn't support it
                const supportsVerbosity =
                  newModel?.litellm_model_name || newModel?.name?.toLowerCase().includes("gpt-5");
                if (!supportsVerbosity) {
                  delete cleanedKwargs.verbosity;
                }

                // Note: Behavior parameter reset is now handled by SelectBehaviourV2 component
                // when models are switched, so we don't need to reset them here during save
              }

              $update.completion_model_kwargs = cleanedKwargs;
            }

            await saveChanges();
            showSavesChangedNotice = true;
            setTimeout(() => {
              showSavesChangedNotice = false;
            }, 5000);
          }}>{$isSaving ? m.loading() : m.save_changes()}</Button
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
          description={m.assistant_name_description()}
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
          title={m.description()}
          description={m.assistant_description_description()}
          hasChanges={$currentChanges.diff.description !== undefined}
          revertFn={() => {
            discardChanges("description");
          }}
          let:aria
        >
          <textarea
            placeholder={m.assistant_placeholder({ name: $update.name })}
            {...aria}
            bind:value={$update.description}
            class="border-default bg-primary ring-default placeholder:text-muted min-h-24 rounded-lg border px-3 py-2 shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
          ></textarea>
        </Settings.Row>

        <Settings.Row title={m.avatar()} description={m.avatar_description()}>
          <IconUpload
            {iconUrl}
            uploading={iconUploading}
            error={iconError}
            on:upload={handleIconUpload}
            on:delete={handleIconDelete}
          />
        </Settings.Row>
      </Settings.Group>

      <Settings.Group title={m.instructions()}>
        <Settings.Row
          title={m.prompt()}
          description={m.describe_assistant_behavior()}
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
          title={m.attachments()}
          description={m.attach_further_instructions()}
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
          title={m.knowledge()}
          description={m.select_additional_knowledge()}
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
            originMode="personal"
            bind:selectedWebsites={$update.websites}
            bind:selectedCollections={$update.groups}
            bind:selectedIntegrationKnowledge={$update.integration_knowledge_list}
          />
        </Settings.Row>

        <Settings.Row
          title={m.organization_knowledge()}
          description={m.organization_knowledge_description()}
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
            originMode="organization"
            bind:selectedWebsites={$update.websites}
            bind:selectedCollections={$update.groups}
            bind:selectedIntegrationKnowledge={$update.integration_knowledge_list}
          />
        </Settings.Row>
      </Settings.Group>

      <Settings.Group title={m.ai_settings()}>
        <Settings.Row
          title={m.completion_model()}
          description={m.this_model_will_be_used()}
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
          description={m.select_preset_behavior()}
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

      <Settings.Group title={m.mcp_servers()}>
        <Settings.Row
          title={m.mcp_servers()}
          description={m.select_mcp_servers_description()}
          hasChanges={$currentChanges.diff.mcp_servers !== undefined || $currentChanges.diff.mcp_tools !== undefined}
          revertFn={() => {
            discardChanges("mcp_servers");
            discardChanges("mcp_tools");
          }}
        >
          <SelectMCPServers bind:selectedMCPServers={$update.mcp_servers} bind:selectedMCPTools={$update.mcp_tools} />
       </Settings.Row>
      </Settings.Group>

      <Settings.Group title={m.security_and_privacy()}>
        <Settings.Row
          hasChanges={$currentChanges.diff.data_retention_days !== undefined}
          revertFn={() => {
            discardChanges("data_retention_days");
          }}
          title={m.conversation_retention_title()}
          description={m.conversation_retention_assistant_description()}
          let:labelId
          let:descriptionId
        >
          <RetentionPolicyInput
            bind:value={$update.data_retention_days}
            hasChanges={$currentChanges.diff.data_retention_days !== undefined}
            inheritedDays={$currentSpace.data_retention_days}
            inheritedFrom="space"
            {labelId}
            {descriptionId}
          />
        </Settings.Row>
      </Settings.Group>

      {#if data.assistant.permissions?.some((permission) => permission === "insight_toggle" || permission === "publish")}
        <Settings.Group title={m.publishing()}>
          {#if data.assistant.permissions?.includes("publish")}
            <Settings.Row title={m.status()} description={m.publishing_description()}>
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
            title={m.insights()}
            description={m.insights_description()}
          >
            <div class="border-default flex h-14 border-b py-2">
              <Tooltip
                text={data.assistant.permissions?.includes("insight_toggle")
                  ? undefined
                  : m.only_space_admins_toggle()}
                class="w-full"
              >
                <Input.RadioSwitch
                  bind:value={$update.insight_enabled}
                  labelTrue={m.enable_insights()}
                  labelFalse={m.disable_insights()}
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
