<!--
  Model picker for the config surfaces (assistant/app/service editors, admin
  templates and help assistants). Uses the same model selector as the personal
  chat — provider logos, a searchable vendor-grouped command palette and the
  model details preview — behind a bordered trigger that fits the settings
  forms. Works for both completion and transcription models.
-->
<script lang="ts" generics="T extends TranscriptionModel | CompletionModel">
  import type { CompletionModel, TranscriptionModel } from "@eneo/eneo-js";
  import { uid } from "uid";
  import { Ban, ChevronsUpDown } from "lucide-svelte";
  import * as Popover from "$lib/components/ui/popover/index.js";
  import * as ModelSelector from "$lib/components/ai-elements/model-selector/index.js";
  import { sortModels } from "../sortModels";
  import { groupModelsByVendor } from "../groupModels";
  import { m } from "$lib/paraglide/messages";
  import ChatModelDetails from "$lib/features/chat/components/switcher/ChatModelDetails.svelte";

  type Props = {
    /** Models the user can choose from. Sorted by vendor for display. */
    availableModels: T[];
    /** Bindable id-bearing model that is currently selected. */
    selectedModel: T | undefined | null;
    /** Forwarded to the trigger; surfaces (e.g. Settings.Row) pass labelling ids. */
    aria?: Record<string, string>;
  };

  let { availableModels, selectedModel = $bindable(), aria = {} }: Props = $props();

  // Sort a copy so we never mutate the caller's array.
  const sortedModels = $derived(sortModels([...availableModels]));
  const modelGroups = $derived(groupModelsByVendor(sortedModels, m.model_group_other()));

  const selectedId = $derived(selectedModel?.id ?? "");
  const unsupportedModelSelected = $derived(
    selectedModel != null && !availableModels.some((model) => model.id === selectedModel?.id)
  );

  let open = $state(false);
  const valueId = uid(8);
  // Compose the accessible name so screen readers announce the *selected* model,
  // not only the field label a surface supplies via aria-labelledby.
  const labelledBy = $derived([aria["aria-labelledby"], valueId].filter(Boolean).join(" "));

  // Drive the details preview from the highlighted row, falling back to the
  // selected model so the panel is populated the moment the dropdown opens.
  let previewedModelId = $state<string | null>(null);
  const previewedModel = $derived(
    sortedModels.find((model) => model.id === previewedModelId) ??
      sortedModels.find((model) => model.id === selectedId) ??
      sortedModels[0] ??
      null
  );
  // The details card renders completion-model metadata; transcription models have none.
  const detailModel = $derived(
    previewedModel && "max_input_tokens" in previewedModel
      ? (previewedModel as CompletionModel)
      : null
  );

  $effect(() => {
    if (!open) previewedModelId = null;
  });

  function pick(model: T) {
    selectedModel = model;
  }
</script>

<ModelSelector.Root bind:open>
  <Popover.Trigger>
    {#snippet child({ props })}
      <button
        {...props}
        {...aria}
        aria-labelledby={labelledBy || undefined}
        type="button"
        class="border-default text-primary hover:border-stronger hover:bg-hover-dimmer focus-visible:ring-stronger flex h-12 items-center justify-between gap-2 rounded-xl border px-3 text-sm transition-colors focus-visible:ring-2 focus-visible:outline-none"
      >
        {#if unsupportedModelSelected}
          <span id={valueId} class="text-negative-default flex min-w-0 items-center gap-2 truncate">
            <Ban class="size-4 shrink-0" aria-hidden="true" />
            {m.unsupported_model_selected()}
          </span>
        {:else if selectedModel}
          <span id={valueId} class="flex min-w-0 items-center gap-2 truncate">
            <ModelSelector.Logo provider={selectedModel.org ?? selectedModel.provider_type} />
            <span class="truncate font-medium">{selectedModel.nickname ?? selectedModel.name}</span>
          </span>
        {:else}
          <span id={valueId} class="text-secondary truncate">{m.select_a_model()}</span>
        {/if}
        <ChevronsUpDown class="text-muted size-4 shrink-0" aria-hidden="true" />
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
        <ModelSelector.Input placeholder={m.search_models()} />
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
                  <ModelSelector.Logo provider={model.org ?? model.provider_type} />
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
