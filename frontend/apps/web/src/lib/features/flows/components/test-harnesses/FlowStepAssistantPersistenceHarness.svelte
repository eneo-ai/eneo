<script lang="ts">
  import type { CompletionModel } from "@intric/intric-js";
  import SelectAIModelV2 from "$lib/features/ai-models/components/SelectAIModelV2.svelte";
  import SelectBehaviourV2 from "$lib/features/ai-models/components/SelectBehaviourV2.svelte";

  export let availableModels: CompletionModel[] = [];

  let currentAssistant = {
    completion_model: availableModels[0] ?? null,
    completion_model_kwargs: {
      temperature: null,
      top_p: null
    }
  };

  let saveCalls: Array<Record<string, unknown>> = [];

  function saveAssistant(changes: Record<string, unknown>) {
    saveCalls = [...saveCalls, changes];
  }

  function updateAssistantField(field: string, value: unknown) {
    saveAssistant({ [field]: value });
  }
</script>

<SelectAIModelV2
  bind:selectedModel={currentAssistant.completion_model}
  {availableModels}
  on:change={() => updateAssistantField("completion_model", currentAssistant.completion_model)}
/>

<SelectBehaviourV2
  bind:kwArgs={currentAssistant.completion_model_kwargs}
  selectedModel={currentAssistant.completion_model}
  isDisabled={false}
  on:change={() =>
    updateAssistantField("completion_model_kwargs", currentAssistant.completion_model_kwargs)}
/>

<output data-testid="save-call-count">{saveCalls.length}</output>
<output data-testid="last-save">{JSON.stringify(saveCalls.at(-1) ?? null)}</output>
