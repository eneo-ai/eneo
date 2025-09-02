<script lang="ts">
  import { IconQuestionMark } from "@intric/icons/question-mark";
  import { Input, Tooltip } from "@intric/ui";
  import type { ModelKwargs } from "@intric/intric-js";

  export let kwArgs: ModelKwargs;
  export let selectedModel: any = null; // CompletionModel from the parent
  
  // Determine which parameters to show based on model capabilities
  // Show reasoning effort for models that support reasoning
  $: showReasoningEffort = selectedModel?.reasoning === true;
  
  // Show max tokens for models that use LiteLLM or specific models that support it
  $: showMaxTokens = selectedModel?.litellm_model_name || selectedModel?.name?.toLowerCase().includes('gpt-5');
  
  // Local state for the custom parameters
  let customReasoningEffort: string = "";
  let customMaxTokens: number = 0;
  let initialized = false;
  
  // Initialize custom values from kwArgs only once
  $: if (kwArgs && !initialized) {
    customReasoningEffort = kwArgs.reasoning_effort || "";
    customMaxTokens = kwArgs.max_completion_tokens || 0;
    initialized = true;
  }
  
  function updateKwArgs() {
    const args = { ...kwArgs };
    
    // Update reasoning effort
    if (customReasoningEffort) {
      args.reasoning_effort = customReasoningEffort;
    } else {
      delete args.reasoning_effort;
    }
    
    // Update max completion tokens
    if (customMaxTokens > 0) {
      args.max_completion_tokens = customMaxTokens;
    } else {
      delete args.max_completion_tokens;
    }
    
    kwArgs = args;
  }
  
  // Reactive updates for max tokens (since event handlers don't work reliably)
  let previousMaxTokens = customMaxTokens;
  $: if (customMaxTokens !== previousMaxTokens) {
    previousMaxTokens = customMaxTokens;
    updateKwArgs();
  }
</script>


<!-- Reasoning Effort Control (for GPT-5 reasoning models) -->
{#if showReasoningEffort}
<div
  class="border-default hover:bg-hover-stronger flex h-[4.125rem] items-center justify-between gap-8 border-b px-4"
>
  <div class="flex items-center gap-2">
    <p class="w-24" aria-label="Reasoning effort setting">Reasoning</p>
    <Tooltip
      text="How much reasoning effort to apply (Default: medium)\nHigher effort improves accuracy but increases response time."
    >
      <IconQuestionMark class="text-muted hover:text-primary" />
    </Tooltip>
  </div>
  <select 
    bind:value={customReasoningEffort}
    on:change={updateKwArgs}
    class="border-default bg-primary ring-default rounded border px-3 py-2 focus:ring-2"
  >
    <option value="">Default</option>
    <option value="minimal">Minimal</option>
    <option value="low">Low</option>
    <option value="medium">Medium</option>
    <option value="high">High</option>
  </select>
</div>
{/if}

<!-- Max Completion Tokens Control -->
{#if showMaxTokens}
<div
  class="border-default hover:bg-hover-stronger flex h-[4.125rem] items-center justify-between gap-8 border-b px-4"
>
  <div class="flex items-center gap-2">
    <p class="w-24" aria-label="Max tokens setting">Max Tokens</p>
    <Tooltip
      text="Maximum tokens in the response (Default: model default)\nSet to 0 for no limit.\nLower values create shorter responses."
    >
      <IconQuestionMark class="text-muted hover:text-primary" />
    </Tooltip>
  </div>
  <Input.Number
    bind:value={customMaxTokens}
    step={1}
    max={200000}
    min={0}
    hiddenLabel={true}
  ></Input.Number>
</div>
{/if}