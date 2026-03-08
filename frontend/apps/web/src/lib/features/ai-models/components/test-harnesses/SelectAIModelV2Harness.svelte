<script lang="ts">
  import type { CompletionModel } from "@intric/intric-js";
  import SelectAIModelV2 from "../SelectAIModelV2.svelte";

  export let availableModels: CompletionModel[] = [];
  export let selectedModel: CompletionModel | null | undefined = null;

  let changeCount = 0;

  function handleChange() {
    changeCount += 1;
  }
</script>

<SelectAIModelV2 bind:selectedModel {availableModels} on:change={handleChange} />

<output data-testid="selected-model-id">{selectedModel?.id ?? ""}</output>
<output data-testid="change-count">{changeCount}</output>
