<script lang="ts">
  import type { SelectableAIModel } from "$lib/features/ai-models/components/SelectAIModelV2.svelte";
  import SelectAIModelV2 from "$lib/features/ai-models/components/SelectAIModelV2.svelte";
  import SelectBehaviourV2 from "$lib/features/ai-models/components/SelectBehaviourV2.svelte";
  import SelectModelSpecificSettings from "$lib/features/ai-models/components/SelectModelSpecificSettings.svelte";

  export let availableModels: SelectableAIModel[] = [];

  let firstAssistant = {
    completion_model: availableModels[0] ?? null,
    completion_model_kwargs: {
      reasoning_effort: "high",
      verbosity: null,
      temperature: null,
      top_p: null
    }
  };
  let secondAssistant = {
    completion_model: availableModels[0] ?? null,
    completion_model_kwargs: {
      reasoning_effort: "low",
      verbosity: null,
      temperature: null,
      top_p: null
    }
  };
  let activeAssistantId = "first";
  let currentAssistant = firstAssistant;

  let saveCalls: Array<Record<string, unknown>> = [];

  function saveAssistant(changes: Record<string, unknown>) {
    saveCalls = [...saveCalls, { assistantId: activeAssistantId, ...changes }];
  }

  function updateAssistantField(field: string, value: unknown) {
    currentAssistant = { ...currentAssistant, [field]: value };
    if (activeAssistantId === "first") {
      firstAssistant = currentAssistant;
    } else {
      secondAssistant = currentAssistant;
    }
    saveAssistant({ [field]: value });
  }

  function selectAssistant(assistantId: "first" | "second") {
    activeAssistantId = assistantId;
    currentAssistant = assistantId === "first" ? firstAssistant : secondAssistant;
  }
</script>

<button data-testid="select-first-assistant" on:click={() => selectAssistant("first")}>
  First assistant
</button>
<button data-testid="select-second-assistant" on:click={() => selectAssistant("second")}>
  Second assistant
</button>

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

<SelectModelSpecificSettings
  bind:kwArgs={currentAssistant.completion_model_kwargs}
  selectedModel={currentAssistant.completion_model}
  on:change={() =>
    updateAssistantField("completion_model_kwargs", currentAssistant.completion_model_kwargs)}
/>

<output data-testid="save-call-count">{saveCalls.length}</output>
<output data-testid="last-save">{JSON.stringify(saveCalls.at(-1) ?? null)}</output>
