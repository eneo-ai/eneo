<script lang="ts">
  import { Page, Settings } from "$lib/components/layout";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager.js";

  import { Button, Input, Tooltip } from "@intric/ui";
  import { IconSparkles } from "@intric/icons/sparkles";
  import { afterNavigate, beforeNavigate } from "$app/navigation";

  import { initAssistantEditor } from "$lib/features/assistants/AssistantEditor.js";
  import { fade } from "svelte/transition";

  import AssistantSettingsAttachments from "./AssistantSettingsAttachments.svelte";
  import SelectAIModelV2 from "$lib/features/ai-models/components/SelectAIModelV2.svelte";
  import SelectBehaviourV2 from "$lib/features/ai-models/components/SelectBehaviourV2.svelte";
  import SelectModelSpecificSettings from "$lib/features/ai-models/components/SelectModelSpecificSettings.svelte";
  import SelectKnowledge from "$lib/features/knowledge/components/select/SelectKnowledge.svelte";
  import SelectMCPServers from "$lib/features/mcp/components/SelectMCPServers.svelte";
  import PromptVersionDialog from "$lib/features/prompts/components/PromptVersionDialog.svelte";
  import PromptGuideModal from "$lib/features/prompt-guide/components/PromptGuideModal.svelte";
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

  // Help assistants have logging permanently disabled (PRD §6); surface the
  // explanation in the security section on their edit page. `is_help_assistant`
  // is computed by the single-assistant GET endpoint and is not yet part of the
  // generated OpenAPI schema, hence the local cast.
  const isHelpAssistant = $derived(
    (data.assistant as { is_help_assistant?: boolean }).is_help_assistant ?? false
  );

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

  const effectiveConfig = $derived($resource.effective_config);
  const promptLocked = $derived(effectiveConfig?.prompt_locked === true);
  const modelsEnforced = $derived(effectiveConfig?.models_enforced === true);
  const policyAllowedModelIds = $derived(
    modelsEnforced ? new Set(effectiveConfig?.available_models.map((model) => model.id)) : null
  );
  const availableModels = $derived(
    policyAllowedModelIds
      ? $currentSpace.completion_models.filter((model) => policyAllowedModelIds.has(model.id))
      : $currentSpace.completion_models
  );
  const lockedModel = $derived(
    modelsEnforced && effectiveConfig?.locked_model
      ? ($currentSpace.completion_models.find(
          (model) => model.id === effectiveConfig?.locked_model?.id
        ) ?? effectiveConfig.locked_model)
      : null
  );
  const mcpEnforced = $derived(effectiveConfig?.mcp_enforced === true);
  const availableMCPServers = $derived(
    mcpEnforced ? (effectiveConfig?.available_mcp_servers ?? []) : undefined
  );

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

  // Prompt Guide (help-assistants): an availability-gated toolbar action.
  // The availability endpoint is the single source of truth for whether the
  // helper is usable here (role assigned + enabled + visible + a usable
  // completion model + caller has EDIT on this assistant) and is prefetched
  // in `+page.ts` so the button renders with its real state on first paint —
  // same cadence as the History button next to it, with no post-mount flash.
  // SvelteKit re-runs the load on navigation between assistants, so the
  // value tracks `data.assistant.id` automatically.
  let isModalOpen = $state(false);
  // Bound to the modal's active run so the Apply handler can mark it completed.
  let promptGuideRunId = $state<string | null>(null);
  const promptGuideAvailability = $derived(data.promptGuideAvailability);

  function promptGuideDisabledTooltip(reason: string | null | undefined): string {
    switch (reason) {
      case "role_disabled":
        return m.prompt_guide_disabled_role_disabled();
      case "role_not_visible":
        return m.prompt_guide_disabled_role_not_visible();
      case "no_completion_model":
        return m.prompt_guide_disabled_no_completion_model();
      case "no_edit_rights":
        return m.prompt_guide_disabled_no_edit_rights();
      case "no_assignment":
      default:
        return m.prompt_guide_disabled_no_assignment();
    }
  }

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
          <div slot="toolbar" class="text-secondary flex items-center gap-1">
            {#if promptGuideAvailability}
              <Tooltip
                text={promptGuideAvailability.available
                  ? m.prompt_guide_button_tooltip()
                  : promptGuideDisabledTooltip(promptGuideAvailability.disabled_reason)}
              >
                <Button
                  variant="simple"
                  padding="icon-leading"
                  disabled={!promptGuideAvailability.available}
                  on:click={() => (isModalOpen = true)}
                >
                  <IconSparkles />
                  {m.prompt_guide_button()}
                </Button>
              </Tooltip>
            {/if}
            {#if !promptLocked}
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
            {/if}
            <PromptGuideModal
              bind:open={isModalOpen}
              bind:runId={promptGuideRunId}
              targetType="assistant"
              targetId={data.assistant.id}
              targetPrompt={$update.prompt.text}
              hasUnsavedPromptChanges={$currentChanges.diff.prompt !== undefined}
              onApply={(text) => {
                // Apply only mutates local editor state (PRD §10): the produced
                // prompt is written into $update.prompt.text and persisted later
                // through the normal Save button (intric.assistants.update),
                // exactly like a manual edit. There is no parallel
                // apply-and-save path here.
                $update.prompt.text = text;
                $update.prompt.description = m.prompt_guide_apply_description({
                  date: dayjs().format("YYYY-MM-DD HH:mm")
                });
                isModalOpen = false;
                // Mark the Q&A run completed — best-effort, must not block Apply.
                if (promptGuideRunId) {
                  data.intric.helpAssistants.runs
                    .setStatus({ run_id: promptGuideRunId, status: "completed" })
                    .catch(() => {});
                }
              }}
            />
          </div>
          {#if promptLocked}
            <p
              class="label-warning border-label-default bg-label-dimmer text-label-stronger mb-2 rounded-md border px-2 py-1 text-sm"
            >
              <span class="font-bold">{m.warning()}:&nbsp;</span>
              {m.governance_assistant_prompt_locked_hint()}
            </p>
          {/if}
          <textarea
            rows={4}
            {...aria}
            bind:value={$update.prompt.text}
            disabled={promptLocked}
            onchange={() => {
              $update.prompt.description = "";
            }}
            class="border-default bg-primary ring-default min-h-24 rounded-lg border px-6 py-4 text-lg shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2 disabled:opacity-60"
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
            <SelectKnowledge
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
            <SelectKnowledge
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
          {#if lockedModel}
            <div class="border-default bg-secondary/30 rounded-lg border px-3 py-2">
              <p class="text-default text-sm font-medium">
                {lockedModel.nickname ?? lockedModel.name}
              </p>
              <p class="text-muted text-xs">{m.governance_assistant_locked_by_policy()}</p>
            </div>
          {:else}
            <SelectAIModelV2 bind:selectedModel={$update.completion_model} {availableModels} {aria}
            ></SelectAIModelV2>
            {#if modelsEnforced}
              <p class="text-muted mt-2 text-xs">
                {m.governance_assistant_models_filtered_hint()}
              </p>
            {/if}
          {/if}
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
          {#if mcpEnforced}
            <!-- Policy GRANTs these servers to the personal assistant; they are
                 applied automatically at ask-time, so the picker is read-only. -->
            {#if availableMCPServers && availableMCPServers.length > 0}
              <div class="border-default bg-secondary/30 divide-default divide-y rounded-lg border">
                {#each availableMCPServers as server (server.id)}
                  <p class="text-default px-3 py-2 text-sm font-medium">{server.name}</p>
                {/each}
              </div>
            {:else}
              <p class="text-muted text-sm">{m.governance_assistant_mcp_none()}</p>
            {/if}
            <p class="text-muted mt-2 text-xs">
              {m.governance_assistant_mcp_provided_by_policy()}
            </p>
          {:else}
            <div class={mcpDisabledByKnowledge ? "pointer-events-none opacity-50" : ""}>
              <SelectMCPServers
                bind:selectedMCPServers={$update.mcp_servers}
                bind:selectedMCPTools={$update.mcp_tools}
                selectedModel={$update.completion_model}
                allowedMCPServers={availableMCPServers}
              />
            </div>
          {/if}
        </Settings.Row>
      </Settings.Group>

      <Settings.Group title={m.security_and_privacy()}>
        {#if isHelpAssistant}
          <p
            class="border-default bg-primary text-secondary mb-2 rounded-lg border px-3 py-2 text-sm"
          >
            {m.admin_help_assistants_edit_logging_explanation()}
          </p>
        {/if}
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
