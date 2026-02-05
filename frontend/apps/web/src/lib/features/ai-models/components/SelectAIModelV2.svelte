<script lang="ts" generics="T extends TranscriptionModel | CompletionModel">
  import type { CompletionModel, TranscriptionModel } from "@intric/intric-js";
  import ModelNameAndVendor from "./ModelNameAndVendor.svelte";
  import { sortModels } from "../sortModels";
  import { groupModelsByProvider } from "../groupModels";
  import { createSelect } from "@melt-ui/svelte";
  import { IconCheck } from "@intric/icons/check";
  import { IconCancel } from "@intric/icons/cancel";
  import { IconChevronDown } from "@intric/icons/chevron-down";
  import { m } from "$lib/paraglide/messages";
  import ProviderGlyph from "../../../../routes/(app)/admin/models/components/ProviderGlyph.svelte";

  /** An array of models the user can choose from, this component will sort in-place the models by vendor */
  export let availableModels: T[];
  sortModels(availableModels);
  /** Bindable id of the selected model*/
  export let selectedModel: T | undefined | null;

  export let aria: AriaProps = { "aria-label": m.select_ai_model() };

  // Check if models have provider info (provider_name field exists and at least one model has a provider)
  function hasProviderInfo(models: T[]): boolean {
    if (models.length === 0) return false;
    // Check if provider_name field exists in the model type
    return "provider_name" in models[0];
  }

  // Group models by provider if they have provider info
  $: modelGroups = hasProviderInfo(availableModels)
    ? groupModelsByProvider(availableModels as (T & { provider_id?: string | null; provider_name?: string | null; provider_type?: string | null })[], m.model_group_system())
    : null;

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
      selectedModel = next?.value ?? availableModels[0];
      return next;
    }
  });

  $: unsupportedModelSelected = !availableModels.some((model) => model.id === selectedModel?.id);

  function watchChanges(incomingModel: T | null | undefined) {
    // Use ID comparison instead of object reference comparison
    // to avoid Svelte 5 proxy equality issues
    const currentId = $selected?.value?.id;
    const incomingId = incomingModel?.id;

    if (currentId !== incomingId) {
      $selected = incomingModel ? { value: incomingModel } : undefined;
    }
  }
  // Watch outside changes
  $: watchChanges(selectedModel);
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
    <ModelNameAndVendor model={$selected.value}></ModelNameAndVendor>
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
    {m.select_completion_model()}
  </div>
  {#if modelGroups}
    {#each modelGroups as group (group.id ?? "system")}
      <div
        class="bg-surface-dimmer border-default sticky top-10 flex items-center gap-2 border-b px-4 py-2 font-mono text-xs uppercase tracking-wide"
      >
        {#if group.providerType}
          <ProviderGlyph providerType={group.providerType} size="sm" />
        {/if}
        <span class="text-secondary">{group.label}</span>
      </div>
      {#each group.models as model (model.id)}
        <div
          class="border-default hover:bg-hover-default flex min-h-16 items-center justify-between border-b px-4 hover:cursor-pointer"
          {...$option({ value: model, label: model.nickname })}
          use:option
        >
          <ModelNameAndVendor {model}></ModelNameAndVendor>
          <div class="check {$isSelected(model) ? 'block' : 'hidden'}">
            <IconCheck class="text-positive-default" />
          </div>
        </div>
      {/each}
    {/each}
  {:else}
    {#each availableModels as model (model.id)}
      <div
        class="border-default hover:bg-hover-default flex min-h-16 items-center justify-between border-b px-4 hover:cursor-pointer"
        {...$option({ value: model, label: model.nickname })}
        use:option
      >
        <ModelNameAndVendor {model}></ModelNameAndVendor>
        <div class="check {$isSelected(model) ? 'block' : 'hidden'}">
          <IconCheck class="text-positive-default" />
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
