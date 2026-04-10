<script lang="ts">
  import SelectAIModelV2, { type SelectableAIModel } from "../SelectAIModelV2.svelte";

  export let availableModels: SelectableAIModel[] = [];
  export let selectedModel: SelectableAIModel | null | undefined = null;

  let changeCount = 0;

  function handleChange() {
    changeCount += 1;
  }
</script>

<SelectAIModelV2 bind:selectedModel {availableModels} on:change={handleChange} />

<output data-testid="selected-model-id">{selectedModel?.id ?? ""}</output>
<output data-testid="change-count">{changeCount}</output>
