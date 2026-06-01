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
  import {
    filterSupportedModelKwargs,
    hasModelSpecificSettings
  } from "$lib/features/ai-models/ModelKwargCapabilities";
  import { m } from "$lib/paraglide/messages";
  import RetentionPolicyInput from "$lib/components/settings/RetentionPolicyInput.svelte";
  import IconUpload from "$lib/features/icons/IconUpload.svelte";
  import ApiKeysSettingsSection from "$lib/features/api-keys/ApiKeysSettingsSection.svelte";
  import { untrack } from "svelte";

  let { data } = $props();

  const {
    state: { currentSpace },
    refreshCurrentSpace
  } = getSpacesManager();

  const {
    state: { resource, update, currentChanges, isSaving },
    saveChanges,
    discardChanges
  } = untrack(() =>
    initAssistantEditor({
      assistant: data.assistant,
      intric: data.intric,
      onUpdateDone() {
        refreshCurrentSpace("applications");
      }
    })
  );

  let cancelUploadsAndClearQueue = $state<() => void>(() => {});

  // Icon state
  let currentIconId = $state<string | null>($resource.icon_id ?? null);
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

  let hasBehaviorChanges = $derived.by(() => {
    if (!$currentChanges.diff.completion_model_kwargs) return false;

    if (hasModelSpecificSettings($update.completion_model)) {
      const original = $resource.completion_model_kwargs || {};
      const updated = $update.completion_model_kwargs || {};

      return original.temperature !== updated.temperature;
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

  let showSavesChangedNotice = $state(false);

  let previousRoute = $state(
    untrack(
      () =>
        `/spaces/${$currentSpace.routeId}/chat/?${getChatQueryParams({ chatPartner: data.assistant, tab: "chat" })}`
    )
  );
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

            $update.completion_model_kwargs = filterSupportedModelKwargs(
              $update.completion_model_kwargs,
              $update.completion_model
            );

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
            onchange={() => {
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

        <!-- Knowledge and MCP are mutually exclusive. Only disable knowledge when MCP is active
             AND no knowledge exists. If both somehow exist (legacy data), allow editing both
             so the user can remove one to resolve the conflict. -->
        {@const hasAnyKnowledge =
          ($update.groups?.length ?? 0) > 0 ||
          ($update.websites?.length ?? 0) > 0 ||
          ($update.integration_knowledge_list?.length ?? 0) > 0}
        {@const hasAnyMCP = ($update.mcp_servers?.length ?? 0) > 0}
        {@const knowledgeDisabledByMCP = hasAnyMCP && !hasAnyKnowledge}
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
          {#if knowledgeDisabledByMCP}
            <p
              class="label-warning border-label-default bg-label-dimmer text-label-stronger mb-2 rounded-md border px-2 py-1 text-sm"
            >
              <span class="font-bold">{m.warning()}:&nbsp;</span
              >{m.knowledge_disabled_when_mcp_active()}
            </p>
          {/if}
          <div class={knowledgeDisabledByMCP ? "pointer-events-none opacity-50" : ""}>
            <SelectKnowledgeV2
              originMode="personal"
              bind:selectedWebsites={$update.websites}
              bind:selectedCollections={$update.groups}
              bind:selectedIntegrationKnowledge={$update.integration_knowledge_list}
            />
          </div>
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
          {#if knowledgeDisabledByMCP}
            <p
              class="label-warning border-label-default bg-label-dimmer text-label-stronger mb-2 rounded-md border px-2 py-1 text-sm"
            >
              <span class="font-bold">{m.warning()}:&nbsp;</span
              >{m.knowledge_disabled_when_mcp_active()}
            </p>
          {/if}
          <div class={knowledgeDisabledByMCP ? "pointer-events-none opacity-50" : ""}>
            <SelectKnowledgeV2
              originMode="organization"
              bind:selectedWebsites={$update.websites}
              bind:selectedCollections={$update.groups}
              bind:selectedIntegrationKnowledge={$update.integration_knowledge_list}
            />
          </div>
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
            showCost={false}
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
            isDisabled={!$update.completion_model}
            {aria}
          ></SelectBehaviourV2>
        </Settings.Row>

        {#if hasModelSpecificSettings($update.completion_model)}
          <Settings.Row
            title={m.model_settings()}
            description={m.model_settings_description()}
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

      <!-- Same mutual exclusivity logic as above: only disable MCP when knowledge
           is active AND no MCP exists. If both exist (legacy data), keep both editable. -->
      {@const mcpDisabledByKnowledge =
        (($update.groups?.length ?? 0) > 0 ||
          ($update.websites?.length ?? 0) > 0 ||
          ($update.integration_knowledge_list?.length ?? 0) > 0) &&
        ($update.mcp_servers?.length ?? 0) === 0}
      <Settings.Group title={m.mcp_servers()}>
        <Settings.Row
          title={m.mcp_servers()}
          description={m.select_mcp_servers_description()}
          hasChanges={$currentChanges.diff.mcp_servers !== undefined ||
            $currentChanges.diff.mcp_tools !== undefined}
          revertFn={() => {
            discardChanges("mcp_servers");
            discardChanges("mcp_tools");
          }}
        >
          {#if mcpDisabledByKnowledge}
            <p
              class="label-warning border-label-default bg-label-dimmer text-label-stronger mb-2 rounded-md border px-2 py-1 text-sm"
            >
              <span class="font-bold">{m.warning()}:&nbsp;</span
              >{m.mcp_disabled_when_knowledge_active()}
            </p>
          {/if}
          <div class={mcpDisabledByKnowledge ? "pointer-events-none opacity-50" : ""}>
            <SelectMCPServers
              bind:selectedMCPServers={$update.mcp_servers}
              bind:selectedMCPTools={$update.mcp_tools}
              selectedModel={$update.completion_model}
            />
          </div>
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
          <!-- @ts-ignore data_retention_days nullability -->
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

      {#if data.assistant.permissions?.includes("edit")}
        <Settings.Group title={m.api_access()}>
          <Settings.Row
            title={m.api_keys()}
            description={m.api_keys_assistant_settings_desc()}
            fullWidth
          >
            <ApiKeysSettingsSection
              scopeType="assistant"
              scopeId={data.assistant.id}
              scopeName={$resource.name}
            />
          </Settings.Row>
        </Settings.Group>
      {/if}

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
