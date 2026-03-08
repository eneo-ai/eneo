<script lang="ts">
  import type { CompletionModel } from "@intric/intric-js";
  import SelectBehaviourV2 from "../SelectBehaviourV2.svelte";
  import type { ModelKwArgs } from "../../ModelBehaviours";

  export let kwArgs: ModelKwArgs = { temperature: null, top_p: null };
  export let selectedModel: CompletionModel | null | undefined = null;
  export let isDisabled = false;

  let changeCount = 0;

  function handleChange() {
    changeCount += 1;
  }
</script>

<SelectBehaviourV2 bind:kwArgs {selectedModel} {isDisabled} on:change={handleChange} />

<output data-testid="serialized-kwargs">{JSON.stringify(kwArgs)}</output>
<output data-testid="change-count">{changeCount}</output>
