<script module lang="ts">
  export type SelectableAIModel = {
    id: string;
    name: string;
    nickname?: string | null;
    description?: string | null;
    token_limit?: number;
    org?: string | null;
    provider_id?: string | null;
    provider_name?: string | null;
    provider_type?: string | null;
  };
</script>

<script lang="ts" generics="T extends SelectableAIModel">
  import { createEventDispatcher } from "svelte";
  import ModelNameAndVendor from "./ModelNameAndVendor.svelte";
  import { sortModels } from "../sortModels";
  import { groupModelsByProvider } from "../groupModels";
  import { createSelect } from "@melt-ui/svelte";
  import { IconCheck } from "@intric/icons/check";
  import { IconCancel } from "@intric/icons/cancel";
  import { IconChevronDown } from "@intric/icons/chevron-down";
  import { m } from "$lib/paraglide/messages";
  import ProviderGlyph from "../../../../routes/(app)/admin/models/components/ProviderGlyph.svelte";
  import ModelCostBadge from "./ModelCostBadge.svelte";
  import type { CompletionModel } from "@intric/intric-js";

  let {
    availableModels,
    selectedModel = $bindable(null),
    aria = { "aria-label": m.select_ai_model() },
    dropdownLabel = m.select_completion_model(),
    showCost = true
  }: {
    /** An array of models the user can choose from */
    availableModels: T[];
    /** Bindable selected model */
    selectedModel?: T | undefined | null;
    aria?: AriaProps;
    /** Optional label for the dropdown menu header */
    dropdownLabel?: string;
    /** Hide the inline cost chip on dropdown rows. Useful for surfaces where
     *  cost is irrelevant or the row is too narrow. */
    showCost?: boolean;
  } = $props();

  const sortedAvailableModels = $derived.by(() => {
    const models = [...availableModels];
    sortModels(models);
    return models;
  });

  const dispatch = createEventDispatcher<{
    change: { selectedModel: T | undefined | null };
  }>();

  // Check if models have provider info (provider_name field exists and at least one model has a provider)
  function hasProviderInfo(models: T[]): boolean {
    if (models.length === 0) return false;
    // Check if provider_name field exists in the model type
    return "provider_name" in models[0];
  }

  // ModelCostBadge types its prop as the full model union; the rows we render
  // are real CompletionModel/TranscriptionModel objects, so widening the
  // structural SelectableAIModel view for the cost chip is safe.
  function asCostModel(model: T): CompletionModel {
    return model as unknown as CompletionModel;
  }

  const modelGroups = $derived.by(() =>
    hasProviderInfo(sortedAvailableModels)
      ? groupModelsByProvider(
          sortedAvailableModels as unknown as Parameters<typeof groupModelsByProvider>[0],
          m.model_group_system()
        )
      : null
  );

  const {
    elements: { trigger, menu, option },
    states: { selected },
    helpers: { isSelected }
  } = createSelect<T>({
    positioning: {
      placement: "bottom",
      fitViewport: true,
      sameWidth: true
    },
    defaultSelected: selectedModel ? { value: selectedModel } : undefined,
    portal: null,
    onSelectedChange: ({ next }) => {
      const newModel = next?.value ?? sortedAvailableModels[0];
      if (newModel?.id !== selectedModel?.id) {
        selectedModel = newModel;
        dispatch("change", { selectedModel });
      }
      return next;
    }
  });

  const unsupportedModelSelected = $derived(
    !sortedAvailableModels.some((model) => model.id === selectedModel?.id)
  );

  function watchChanges(incomingModel: T | null | undefined) {
    // Use ID comparison instead of object reference comparison
    // to avoid Svelte 5 proxy equality issues
    const currentId = $selected?.value?.id;
    const incomingId = incomingModel?.id;

    if (currentId !== incomingId) {
      $selected = incomingModel ? { value: incomingModel } : undefined;
    }
  }
  $effect(() => {
    watchChanges(selectedModel);
  });
</script>

<button
  {...$trigger}
  {...aria}
  use:trigger
  class="border-default hover:bg-hover-default flex h-16 items-center justify-between border-b px-4"
>
  {#if unsupportedModelSelected}
    <div class="text-negative-default flex gap-3 truncate pl-1">
      <IconCancel />{m.unsupported_model_selected()} ({selectedModel?.name ?? m.no_model_found()})
    </div>
  {:else if $selected}
    <ModelNameAndVendor model={$selected.value} descriptionMode="hidden"></ModelNameAndVendor>
  {:else}
    <div class="text-negative-default flex gap-3 truncate pl-1">
      <IconCancel />{m.no_model_selected()}
    </div>
  {/if}
  <IconChevronDown />
</button>

<div
  class="border-default bg-primary z-20 flex flex-col overflow-y-auto rounded-lg border shadow-xl"
  {...$menu}
  use:menu
>
  <div
    class="bg-frosted-glass-secondary border-default sticky top-0 border-b px-4 py-2 font-mono text-sm"
  >
    {dropdownLabel}
  </div>
  {#if modelGroups}
    {#each modelGroups as group (group.id ?? "system")}
      <div
        class="bg-surface-dimmer border-default sticky top-10 flex items-center gap-2 border-b px-4 py-2 font-mono text-xs tracking-wide uppercase"
      >
        {#if group.providerType}
          <ProviderGlyph providerType={group.providerType} size="sm" />
        {/if}
        <span class="text-secondary">{group.label}</span>
      </div>
      {#each group.models as model (model.id)}
        <div
          class="border-default hover:bg-hover-default flex min-h-16 items-center justify-between gap-3 border-b px-4 hover:cursor-pointer"
          {...$option({ value: model, label: model.nickname ?? undefined })}
          use:option
        >
          <ModelNameAndVendor model={model as T} descriptionMode="non-tabbable"
          ></ModelNameAndVendor>
          <div class="flex items-center gap-3">
            {#if showCost}
              <ModelCostBadge model={asCostModel(model as T)} dense />
            {/if}
            <div class="check {$isSelected(model) ? 'block' : 'hidden'}">
              <IconCheck class="text-positive-default" />
            </div>
          </div>
        </div>
      {/each}
    {/each}
  {:else}
    {#each sortedAvailableModels as model (model.id)}
      <div
        class="border-default hover:bg-hover-default flex min-h-16 items-center justify-between gap-3 border-b px-4 hover:cursor-pointer"
        {...$option({ value: model, label: model.nickname ?? undefined })}
        use:option
      >
        <ModelNameAndVendor {model} descriptionMode="non-tabbable"></ModelNameAndVendor>
        <div class="flex items-center gap-3">
          {#if showCost}
            <ModelCostBadge model={asCostModel(model)} dense />
          {/if}
          <div class="check {$isSelected(model) ? 'block' : 'hidden'}">
            <IconCheck class="text-positive-default" />
          </div>
        </div>
      </div>
    {/each}
  {/if}
</div>

<style lang="postcss">
  @reference "@intric/ui/styles";
  div[data-highlighted] {
    @apply bg-hover-default;
  }

  /* div[data-selected] { } */

  div[data-disabled] {
    @apply opacity-30 hover:bg-transparent;
  }
</style>
