<script module lang="ts">
  export type SelectableAIModel = {
    id: string;
    name: string;
    nickname?: string | null;
    description?: string | null;
    token_limit?: number;
    max_input_tokens?: number;
    org?: string | null;
    provider_id?: string | null;
    provider_name?: string | null;
    provider_type?: string | null;
  };
</script>

<script lang="ts" generics="T extends SelectableAIModel">
  import { createEventDispatcher } from "svelte";
  import type { CompletionModel } from "@eneo/eneo-js";
  import { uid } from "uid";
  import Ban from "lucide-svelte/icons/ban";
  import ChevronsUpDown from "lucide-svelte/icons/chevrons-up-down";
  import * as Popover from "$lib/components/ui/popover/index.js";
  import * as ModelSelector from "$lib/components/ai-elements/model-selector/index.js";
  import { sortModels } from "../sortModels";
  import { groupModelsByVendor } from "../groupModels";
  import { m } from "$lib/paraglide/messages";
  import ChatModelDetails from "$lib/features/chat/components/switcher/ChatModelDetails.svelte";

  type Props = {
    availableModels: T[];
    selectedModel?: T | undefined | null;
    aria?: AriaProps;
    dropdownLabel?: string;
    showCost?: boolean;
  };

  let {
    availableModels,
    selectedModel = $bindable(null),
    aria = { "aria-label": m.select_ai_model() },
    dropdownLabel = m.select_completion_model(),
    showCost = true
  }: Props = $props();

  const dispatch = createEventDispatcher<{
    change: { selectedModel: T | undefined | null };
  }>();

  let open = $state(false);
  let previewedModelId = $state<string | null>(null);
  const valueId = uid(8);

  const sortedAvailableModels = $derived.by(() => {
    const models = [...availableModels];
    sortModels(models);
    return models;
  });

  const modelGroups = $derived.by(() =>
    groupModelsByVendor(sortedAvailableModels, m.model_group_other())
  );
  const selectedId = $derived(selectedModel?.id ?? "");
  const unsupportedModelSelected = $derived(
    selectedModel != null && !availableModels.some((model) => model.id === selectedModel?.id)
  );
  const labelledBy = $derived([aria["aria-labelledby"], valueId].filter(Boolean).join(" "));
  const triggerLabel = $derived(aria["aria-label"] ?? (labelledBy ? undefined : dropdownLabel));
  const previewedModel = $derived(
    sortedAvailableModels.find((model) => model.id === previewedModelId) ?? null
  );
  const detailModel = $derived.by(() => {
    if (!showCost || !previewedModel || !hasCompletionDetails(previewedModel)) {
      return null;
    }
    return previewedModel;
  });

  $effect(() => {
    if (!open) previewedModelId = null;
  });

  function pick(model: T) {
    if (model.id !== selectedModel?.id) {
      selectedModel = model;
      dispatch("change", { selectedModel });
    }
    open = false;
  }

  function providerFor(model: SelectableAIModel) {
    return model.org ?? model.provider_type ?? model.provider_name;
  }

  function hasCompletionDetails(
    model: SelectableAIModel
  ): model is SelectableAIModel & CompletionModel {
    return typeof model.max_input_tokens === "number";
  }
</script>

<ModelSelector.Root bind:open>
  <Popover.Trigger>
    {#snippet child({ props })}
      <button
        {...props}
        {...aria}
        aria-label={triggerLabel}
        aria-labelledby={labelledBy || undefined}
        type="button"
        class="border-input bg-background hover:bg-accent focus-visible:ring-ring inline-flex h-10 w-full items-center justify-between rounded-md border px-3 py-2 text-sm shadow-xs transition-colors focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50"
      >
        {#if unsupportedModelSelected}
          <span id={valueId} class="text-negative-default flex min-w-0 items-center gap-2 truncate">
            <Ban class="size-4 shrink-0" aria-hidden="true" />
            {m.unsupported_model_selected()}
          </span>
        {:else if selectedModel}
          <span id={valueId} class="flex min-w-0 items-center gap-2 truncate">
            <ModelSelector.Logo provider={providerFor(selectedModel)} class="size-4 shrink-0" />
            <span class="truncate font-medium">{selectedModel.nickname ?? selectedModel.name}</span>
          </span>
        {:else}
          <span id={valueId} class="text-secondary truncate">{m.select_a_model()}</span>
        {/if}
        <ChevronsUpDown class="text-muted-foreground ml-2 size-4 shrink-0 opacity-60" />
      </button>
    {/snippet}
  </Popover.Trigger>

  <ModelSelector.Content
    align="start"
    class="w-auto max-w-[calc(100vw-1rem)] border-0 bg-transparent p-0 shadow-none ring-0"
    commandClass="size-auto overflow-visible rounded-none! bg-transparent p-0"
  >
    <div class="flex items-start gap-2">
      <div
        class="bg-popover/95 ring-foreground/10 w-72 shrink-0 overflow-hidden rounded-xl shadow-lg ring-1 backdrop-blur-xl"
      >
        <ModelSelector.Input placeholder={dropdownLabel} />
        <ModelSelector.List class="max-h-[20rem] p-1 pt-0">
          <ModelSelector.Empty>{m.no_models_found()}</ModelSelector.Empty>
          {#each modelGroups as group (group.label)}
            <ModelSelector.Group heading={group.label}>
              {#each group.models as model (model.id)}
                <ModelSelector.Item
                  value={`${model.nickname ?? model.name} ${group.label}`}
                  selected={model.id === selectedId}
                  onSelect={() => pick(model)}
                  onHighlight={() => (previewedModelId = model.id)}
                  class="min-h-10"
                >
                  <ModelSelector.Logo provider={providerFor(model)} />
                  <ModelSelector.Name>{model.nickname ?? model.name}</ModelSelector.Name>
                </ModelSelector.Item>
              {/each}
            </ModelSelector.Group>
          {/each}
        </ModelSelector.List>
      </div>

      {#if detailModel}
        <ChatModelDetails model={detailModel} />
      {/if}
    </div>
  </ModelSelector.Content>
</ModelSelector.Root>
