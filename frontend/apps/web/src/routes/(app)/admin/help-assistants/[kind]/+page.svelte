<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.

    Settings page for a single Help Assistant, hosted inside the admin UI
    (not under /spaces/). Visually distinct from a normal assistant editor so
    it is clear you are editing a behind-the-scenes helper. Reuses the shared
    assistant editor state machine; trimmed to the fields a helper needs.
-->

<script lang="ts">
  import { Page, Settings } from "$lib/components/layout";
  import { Button, Tooltip } from "@intric/ui";
  import { IconSparkles } from "@intric/icons/sparkles";
  import { IconInfo } from "@intric/icons/info";
  import { beforeNavigate, invalidate } from "$app/navigation";
  import { resolve } from "$app/paths";
  import { fade } from "svelte/transition";
  import { untrack } from "svelte";
  import dayjs from "dayjs";

  import { initAssistantEditor } from "$lib/features/assistants/AssistantEditor.js";
  import SelectAIModelV2 from "$lib/features/ai-models/components/SelectAIModelV2.svelte";
  import PromptVersionDialog from "$lib/features/prompts/components/PromptVersionDialog.svelte";
  import PromptGuideModal from "$lib/features/prompt-guide/components/PromptGuideModal.svelte";
  import RetentionPolicyInput from "$lib/components/settings/RetentionPolicyInput.svelte";
  import { filterSupportedModelKwargs } from "$lib/features/ai-models/ModelKwargCapabilities";
  import { m } from "$lib/paraglide/messages";

  let { data } = $props();

  // The Prompt Guide helper must not offer to edit *itself* with the Prompt
  // Guide; other helpers may (PRD / repo-owner feedback).
  const isPromptGuide = $derived(data.kind === "prompt_guide");

  const {
    state: { resource, update, currentChanges, isSaving },
    saveChanges,
    discardChanges
  } = untrack(() =>
    initAssistantEditor({
      assistant: data.assistant,
      intric: data.intric,
      onUpdateDone() {
        // Keep the admin table's displayed name fresh after a rename.
        invalidate("admin:help-assistants:load");
      }
    })
  );

  let isModalOpen = $state(false);
  let promptGuideRunId = $state<string | null>(null);

  const backHref = resolve("/admin/help-assistants");
  let showSavedNotice = $state(false);

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
    discardChanges();
  });
</script>

<svelte:head>
  <title>Eneo.ai – {m.admin()} – {$resource.name}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title
      parent={{ title: m.admin_help_assistants_page_title(), href: backHref }}
      title={m.edit()}
    ></Page.Title>

    <Page.Flex>
      {#if $currentChanges.hasUnsavedChanges}
        <Button variant="destructive" disabled={$isSaving} on:click={() => discardChanges()}>
          {m.discard_all_changes()}
        </Button>
        <Button
          variant="positive"
          class="h-8 w-32 whitespace-nowrap"
          on:click={async () => {
            $update.completion_model_kwargs = filterSupportedModelKwargs(
              $update.completion_model_kwargs,
              $update.completion_model
            );
            await saveChanges();
            showSavedNotice = true;
            setTimeout(() => {
              showSavedNotice = false;
            }, 5000);
          }}>{$isSaving ? m.loading() : m.save_changes()}</Button
        >
      {:else}
        {#if showSavedNotice}
          <p class="text-positive-stronger px-4" transition:fade>{m.all_changes_saved()}</p>
        {/if}
        <Button variant="primary" class="w-32" href={backHref}>{m.done()}</Button>
      {/if}
    </Page.Flex>
  </Page.Header>

  <Page.Main>
    <Settings.Page>
      <!-- Distinct banner: this is a behind-the-scenes helper, not a normal assistant. -->
      <div
        class="border-accent-default bg-accent-dimmer text-accent-stronger mx-4 mt-4 flex items-center gap-3 rounded-xl border px-4 py-3 lg:mx-2.5"
      >
        <IconSparkles class="!size-5 shrink-0" />
        <p class="text-sm">{m.admin_help_assistants_edit_banner()}</p>
      </div>

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
            {#if !isPromptGuide && data.promptGuideAvailability}
              <Tooltip
                text={data.promptGuideAvailability.available
                  ? m.prompt_guide_button_tooltip()
                  : promptGuideDisabledTooltip(data.promptGuideAvailability.disabled_reason)}
              >
                <Button
                  variant="simple"
                  padding="icon-leading"
                  disabled={!data.promptGuideAvailability.available}
                  on:click={() => (isModalOpen = true)}
                >
                  <IconSparkles />
                  {m.prompt_guide_button()}
                </Button>
              </Tooltip>
            {/if}
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
            {#if !isPromptGuide}
              <PromptGuideModal
                bind:open={isModalOpen}
                bind:runId={promptGuideRunId}
                targetType="assistant"
                targetId={data.assistant.id}
                targetPrompt={$update.prompt.text}
                hasUnsavedPromptChanges={$currentChanges.diff.prompt !== undefined}
                onApply={(text) => {
                  $update.prompt.text = text;
                  $update.prompt.description = m.prompt_guide_apply_description({
                    date: dayjs().format("YYYY-MM-DD HH:mm")
                  });
                  isModalOpen = false;
                  if (promptGuideRunId) {
                    data.intric.helpAssistants.runs
                      .setStatus({ run_id: promptGuideRunId, status: "completed" })
                      .catch(() => {});
                  }
                }}
              />
            {/if}
          </div>
          <div
            class="border-warning-default/40 bg-warning-dimmer/40 text-warning-stronger mb-3 flex items-start gap-2.5 rounded-lg border px-3 py-2.5 text-sm"
          >
            <IconInfo class="mt-0.5 !size-5 shrink-0" />
            <p>{m.admin_help_assistants_edit_prompt_warning()}</p>
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
            availableModels={data.orgSpace.completion_models}
            {aria}
          ></SelectAIModelV2>
        </Settings.Row>
      </Settings.Group>

      <Settings.Group title={m.security_and_privacy()}>
        <p
          class="border-default bg-primary text-secondary mb-2 rounded-lg border px-3 py-2 text-sm"
        >
          {m.admin_help_assistants_edit_logging_explanation()}
        </p>
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
            inheritedDays={data.orgSpace.data_retention_days}
            inheritedFrom="space"
            {labelId}
            {descriptionId}
          />
        </Settings.Row>
      </Settings.Group>

      <div class="min-h-24"></div>
    </Settings.Page>
  </Page.Main>
</Page.Root>
