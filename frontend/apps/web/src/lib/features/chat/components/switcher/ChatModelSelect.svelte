<!--
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the MIT License.

    AI Elements-style model selector for the chat input toolbar: a command
    palette grouped by model vendor with provider logos and text search.
    Policy-filtered models, a locked label when the policy pins a single model,
    and a plain label when only one model is available. Switching updates the
    personal space's default assistant. Only meaningful for the default
    assistant — callers gate on partner.type.
-->
<script lang="ts">
  import * as ModelSelector from "$lib/components/ai-elements/model-selector/index.js";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { sortModels } from "$lib/features/ai-models/sortModels";
  import { selectEffectiveChatModel } from "$lib/features/chat/selectEffectiveChatModel";
  import { m } from "$lib/paraglide/messages";
  import { Lock } from "lucide-svelte";
  import { SvelteMap } from "svelte/reactivity";
  import ChatModelDetails from "./ChatModelDetails.svelte";

  const {
    state: { currentSpace },
    updateDefaultAssistant
  } = getSpacesManager();

  // Only rendered when chat.partner.type === "default-assistant", which
  // guarantees the personal space's default_assistant is present.
  const defaultAssistant = $derived($currentSpace.default_assistant!);
  const effectiveConfig = $derived(defaultAssistant.effective_config);

  // When the admin policy locks the model to one option, show the locked name
  // instead of a picker.
  const lockedModel = $derived(
    effectiveConfig?.models_enforced && effectiveConfig.locked_model
      ? ($currentSpace.completion_models.find(
          (model) => model.id === effectiveConfig.locked_model?.id
        ) ?? effectiveConfig.locked_model)
      : null
  );
  const policyAllowedModelIds = $derived(
    effectiveConfig?.models_enforced
      ? new Set(effectiveConfig.available_models.map((model) => model.id))
      : null
  );
  const visibleModels = $derived(
    sortModels(
      policyAllowedModelIds
        ? $currentSpace.completion_models.filter((model) => policyAllowedModelIds.has(model.id))
        : $currentSpace.completion_models
    )
  );
  const selectedModel = $derived.by(() => {
    return (
      selectEffectiveChatModel(
        defaultAssistant.completion_model,
        effectiveConfig,
        $currentSpace.completion_models
      ) ?? null
    );
  });
  const selectedId = $derived(selectedModel?.id ?? "");
  const selectedLabel = $derived(selectedModel?.nickname ?? m.select_a_model());
  let selectorOpen = $state(false);
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

  function prettifyProviderType(type: string | null | undefined): string | null {
    if (!type) return null;
    return type
      .split("_")
      .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
      .join(" ");
  }

  // Group by model vendor (org), falling back to the configured provider for
  // models without one. Groups sorted alphabetically, models within a group
  // keep sortModels' nickname order.
  const modelGroups = $derived.by(() => {
    const groups = new SvelteMap<string, { label: string; models: typeof visibleModels }>();
    for (const model of visibleModels) {
      const label =
        model.org?.trim() ||
        model.provider_name?.trim() ||
        prettifyProviderType(model.provider_type) ||
        m.model_group_other();
      let group = groups.get(label);
      if (!group) {
        group = { label, models: [] };
        groups.set(label, group);
      }
      group.models.push(model);
    }
    return Array.from(groups.values()).sort((a, b) => a.label.localeCompare(b.label));
  });

  function selectModel(id: string) {
    if (!id || id === selectedId) return;
    // Persist the model on the personal default assistant. The chat page keeps
    // the chat partner synced with SpacesManager, so no manual partner update
    // is needed here.
    updateDefaultAssistant({ completionModel: { id } });
  }
</script>

{#if lockedModel}
  <div
    class="text-muted-foreground flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-sm"
    title={m.governance_locked_by_admin()}
  >
    <Lock class="size-3.5" aria-hidden="true" />
    <span class="text-foreground max-w-[10rem] truncate font-medium">{lockedModel.nickname}</span>
  </div>
{:else if visibleModels.length <= 1}
  <div class="rounded-lg px-2.5 py-1.5 text-sm" title={m.choose_a_completion_model()}>
    <span class="max-w-[12rem] truncate font-medium">{selectedLabel}</span>
  </div>
{:else}
  <ModelSelector.Root bind:open={selectorOpen}>
    <ModelSelector.Trigger aria-label={m.choose_a_completion_model()}>
      {#if selectedModel}
        <ModelSelector.Logo provider={selectedModel.org ?? selectedModel.provider_type} />
      {/if}
      <ModelSelector.Name>{selectedLabel}</ModelSelector.Name>
    </ModelSelector.Trigger>
    <ModelSelector.Content
      class="w-auto max-w-[calc(100vw-1rem)] border-0 bg-transparent p-0 shadow-none ring-0"
      commandClass="size-auto overflow-visible rounded-none! bg-transparent p-0"
    >
      <div class="flex items-start gap-2">
        <div
          class="bg-popover/95 ring-foreground/10 w-72 shrink-0 overflow-hidden rounded-xl shadow-lg ring-1 backdrop-blur-xl"
        >
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
        {#if previewedModel}
          <ChatModelDetails model={previewedModel} />
        {/if}
      </div>
    </ModelSelector.Content>
  </ModelSelector.Root>
{/if}
