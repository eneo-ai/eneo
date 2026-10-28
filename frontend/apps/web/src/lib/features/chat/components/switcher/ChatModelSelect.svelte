<!--
    Copyright (c) 2026 Sundsvalls Kommun

    AI Elements-style model selector for the chat input toolbar: a command
    palette grouped by model vendor with provider logos and text search.
    Policy-filtered models, a locked label when the policy pins a single model,
    and a plain label when only one model is available. Selection belongs to
    the personal conversation, not the default assistant.
-->
<script lang="ts">
  import * as ModelSelector from "$lib/components/ai-elements/model-selector/index.js";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { getChatService } from "../../ChatService.svelte";
  import { sortModels } from "$lib/features/ai-models/sortModels";
  import { groupModelsByVendor } from "$lib/features/ai-models/groupModels";
  import { m } from "$lib/paraglide/messages";
  import Cpu from "@lucide/svelte/icons/cpu";
  import Lock from "@lucide/svelte/icons/lock";
  import ChatModelDetails from "./ChatModelDetails.svelte";

  const chat = getChatService();
  const { onNewConversation }: { onNewConversation: () => void } = $props();

  const visibleModels = $derived(sortModels(chat.settingsResolution?.available_models ?? []));
  const selectedModel = $derived(chat.settingsResolution?.effective_model ?? null);
  const lockedModel = $derived(chat.settingsResolution?.model_locked ? selectedModel : null);
  const selectedId = $derived(chat.settings?.completion_model_id ?? selectedModel?.id ?? "");
  const savedModelUnavailable = $derived(chat.settingsResolution?.model_unavailable ?? false);
  const selectedLabel = $derived(
    savedModelUnavailable
      ? m.conversation_settings_model_unavailable()
      : (selectedModel?.nickname ?? m.select_a_model())
  );
  let selectorOpen = $state(false);
  let pendingModelId = $state<string | null>(null);
  let previewedModelId = $state<string | null>(null);
  const previewedModel = $derived(
    visibleModels.find((model) => model.id === previewedModelId) ??
      visibleModels.find((model) => model.id === selectedId) ??
      visibleModels[0] ??
      null
  );

  $effect(() => {
    if (!selectorOpen) previewedModelId = null;
  });

  // Group by model vendor (org), falling back to the configured provider for
  // models without one. Shared with the settings model selector so both group
  // identically.
  const modelGroups = $derived(groupModelsByVendor(visibleModels, m.model_group_other()));

  $effect(() => chat.setModelCatalog(chat.settingsResolution?.available_models ?? []));

  async function applyModel(id: string, newConversation = false) {
    const model = visibleModels.find((candidate) => candidate.id === id);
    if (!model) return;
    pendingModelId = null;
    // Capture the model before resetting clears the current resolution/catalog.
    if (newConversation) onNewConversation();
    await chat.loadSettings();
    await chat.selectPersonalModel(model);
  }

  function selectModel(id: string) {
    if (
      !id ||
      id === selectedId ||
      chat.askQuestion.isLoading ||
      chat.settingsBusy ||
      !chat.settings
    )
      return;
    selectorOpen = false;
    if (chat.currentConversation.messages.length > 0) {
      pendingModelId = id;
    } else {
      applyModel(id);
    }
  }
</script>

{#if lockedModel && !savedModelUnavailable}
  <div
    class="text-muted-foreground flex min-w-0 items-center gap-1 rounded-lg px-2 py-1.5 text-sm @[36rem]/composer:gap-1.5 @[36rem]/composer:px-2.5"
    title={`${lockedModel.nickname} · ${m.governance_locked_by_admin()}`}
  >
    <Lock class="size-3.5 shrink-0" aria-hidden="true" />
    <span
      class="text-foreground sr-only font-medium @[26rem]/composer:not-sr-only @[26rem]/composer:max-w-[10rem] @[26rem]/composer:truncate"
      >{lockedModel.nickname}</span
    >
  </div>
{:else if visibleModels.length === 0 || (visibleModels.length === 1 && !savedModelUnavailable)}
  <div
    class="flex min-w-0 items-center gap-1 rounded-lg px-2 py-1.5 text-sm @[36rem]/composer:px-2.5"
    title={selectedLabel}
  >
    <Cpu class="size-3.5 shrink-0 @[26rem]/composer:hidden" aria-hidden="true" />
    <span
      class="sr-only font-medium @[26rem]/composer:not-sr-only @[26rem]/composer:max-w-[12rem] @[26rem]/composer:truncate"
      >{selectedLabel}</span
    >
  </div>
{:else}
  <ModelSelector.Root bind:open={selectorOpen}>
    <ModelSelector.Trigger
      disabled={chat.settingsBusy ||
        !chat.settings ||
        chat.askQuestion.isLoading ||
        chat.settingsResolution?.settings_compatible === false}
      class="min-w-0 gap-1 px-2 @[36rem]/composer:gap-1.5 @[36rem]/composer:px-2.5 [&>svg:last-child]:hidden @[26rem]/composer:[&>svg:last-child]:block"
      aria-label={`${m.choose_a_completion_model()}: ${selectedLabel}`}
      title={selectedLabel}
    >
      {#if selectedModel}
        <ModelSelector.Logo provider={selectedModel.org ?? selectedModel.provider_type} />
      {:else}
        <Cpu class="size-4 shrink-0" aria-hidden="true" />
      {/if}
      <ModelSelector.Name class="hidden @[26rem]/composer:inline"
        >{selectedLabel}</ModelSelector.Name
      >
    </ModelSelector.Trigger>
    <ModelSelector.Content
      class="w-auto max-w-[calc(100vw-1rem)] gap-0 overflow-hidden rounded-xl p-0 shadow-lg"
      commandClass="size-auto overflow-visible rounded-none! bg-transparent p-0"
    >
      <div class="flex items-stretch">
        {#if previewedModel}
          <ChatModelDetails model={previewedModel} class="border-border border-r" />
        {/if}
        <div class="w-72 shrink-0">
          <ModelSelector.Input placeholder={m.search_models()} />
          <ModelSelector.List class="max-h-[20rem] p-1 pt-0">
            <ModelSelector.Empty>{m.no_models_found()}</ModelSelector.Empty>
            {#each modelGroups as group (group.label)}
              <ModelSelector.Group heading={group.label}>
                {#each group.models as model (model.id)}
                  <ModelSelector.Item
                    value={`${model.nickname ?? model.name} ${group.label}`}
                    selected={model.id === selectedId}
                    onSelect={() => selectModel(model.id)}
                    onHighlight={() => (previewedModelId = model.id)}
                    class="min-h-10"
                  >
                    <ModelSelector.Logo provider={model.org ?? model.provider_type} />
                    <ModelSelector.Name>{model.nickname}</ModelSelector.Name>
                  </ModelSelector.Item>
                {/each}
              </ModelSelector.Group>
            {/each}
          </ModelSelector.List>
        </div>
      </div>
    </ModelSelector.Content>
  </ModelSelector.Root>
{/if}

<AlertDialog.Root
  open={pendingModelId !== null}
  onOpenChange={(open) => {
    if (!open) pendingModelId = null;
  }}
>
  <AlertDialog.Content>
    <AlertDialog.Header>
      <AlertDialog.Title>{m.personal_chat_model_change_title()}</AlertDialog.Title>
      <AlertDialog.Description>{m.personal_chat_model_change_description()}</AlertDialog.Description
      >
    </AlertDialog.Header>
    <AlertDialog.Footer>
      <AlertDialog.Cancel>{m.cancel()}</AlertDialog.Cancel>
      <Button
        variant="outline"
        onclick={() => {
          const id = pendingModelId;
          if (!id) return;
          applyModel(id, true);
        }}>{m.personal_chat_model_new_conversation()}</Button
      >
      <AlertDialog.Action
        onclick={() => {
          if (pendingModelId) applyModel(pendingModelId);
        }}
      >
        {m.personal_chat_model_change_anyway()}
      </AlertDialog.Action>
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>
