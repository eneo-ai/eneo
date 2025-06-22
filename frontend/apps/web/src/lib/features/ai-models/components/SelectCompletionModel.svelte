<script lang="ts">
  import { browser } from "$app/environment";
  import type { CompletionModel } from "@intric/intric-js";
  import { Select } from "@intric/ui";
  import { writable, type Writable } from "svelte/store";
  import { m } from "$lib/paraglide/messages";

  /** Id of currently selected Completion Model */
  export let value: { id: string } | null | undefined;
  export let selectableModels: CompletionModel[];

  const stableModels = selectableModels.filter((model) => model.stability === "stable");

  const experimentalModels = selectableModels.filter((model) => model.stability === "experimental");

  function getModelDisplayName(model: CompletionModel) {
    if (model.name === model.nickname) {
      return model.nickname;
    }
    return `${model.nickname} (${model.name})`;
  }

  let modelSelectStore: Writable<{ value: CompletionModel | undefined; label: string }>;
  let unsupportedModelSelected = false;

  if (value) {
    const selectedModel = selectableModels.find((model) => model.id === value!.id);
    if (!selectedModel) {
      unsupportedModelSelected = true;
      if (browser) {
        setTimeout(() => {
          alert(m.model_no_longer_supported());
        }, 400);
      }
    }
    modelSelectStore = writable({
      value: selectedModel,
      label: selectedModel ? getModelDisplayName(selectedModel) : m.no_model_selected()
    });
  } else {
    modelSelectStore = writable({
      value: selectableModels[0],
      label: selectableModels[0] ? getModelDisplayName(selectableModels[0]) : m.no_model_selected()
    });
  }

  function setValue(currentlySelected: { value: CompletionModel | undefined; label: string }) {
    if (currentlySelected.value) {
      value = { id: currentlySelected.value.id };
    }
  }

  $: setValue($modelSelectStore);
</script>

<Select.Root
  customStore={modelSelectStore}
  class="border-dimmer hover:bg-hover-dimmer relative w-full border-b px-4 py-4"
>
  <Select.Label>{m.completion_model()}</Select.Label>
  <Select.Trigger placeholder={m.select_ellipsis()} error={unsupportedModelSelected}></Select.Trigger>
  <Select.Options>
    <Select.OptionGroup label={m.stable_completion_models()}>
      {#each stableModels as model (model.id)}
        {@const modelName = getModelDisplayName(model)}
        <Select.Item value={model} label={modelName}>
          <div class="flex w-full items-center justify-between py-1">
            <span>
              {modelName}
            </span>
          </div>
        </Select.Item>
      {/each}
      {#if !stableModels.length}
        <Select.Item disabled label={m.no_enabled_completion_models()} value={null}
        ></Select.Item>
      {/if}
    </Select.OptionGroup>
    {#if experimentalModels.length > 0}
      <Select.OptionGroup label={m.experimental_completion_models()}>
        {#each experimentalModels as model (model.id)}
          {@const modelName = getModelDisplayName(model)}
          <Select.Item value={model} label={modelName}>
            <div class="flex w-full items-center justify-between py-1">
              <span>
                {modelName}
              </span>
            </div>
          </Select.Item>
        {/each}
      </Select.OptionGroup>
    {/if}
  </Select.Options>
</Select.Root>
