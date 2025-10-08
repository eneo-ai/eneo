<script lang="ts">
  import { IconQuestionMark } from "@intric/icons/question-mark";
  import { Input, Tooltip } from "@intric/ui";
  import type { ModelKwargs } from "@intric/intric-js";

  export let kwArgs: ModelKwargs;
  export let selectedModel: any = null; // CompletionModel from the parent
  
  // Determine which parameters to show based on model capabilities
  // Show reasoning effort for models that support reasoning
  $: showReasoningEffort = selectedModel?.reasoning === true;
  
  // Show verbosity for models that use LiteLLM or specific models that support it
  $: showVerbosity = selectedModel?.litellm_model_name || selectedModel?.name?.toLowerCase().includes('gpt-5');
  
  // Local state for the custom parameters
  let customReasoningEffort: string = "";
  let customVerbosity: string = "";
  let initialized = false;
  
  // Initialize custom values from kwArgs only once
  $: if (kwArgs && !initialized) {
    customReasoningEffort = kwArgs.reasoning_effort || "";
    customVerbosity = kwArgs.verbosity || "";
    initialized = true;
  }
  
  function updateKwArgs() {
    const args = { ...kwArgs };

    // Update reasoning effort
    if (customReasoningEffort) {
      args.reasoning_effort = customReasoningEffort;
    } else {
      args.reasoning_effort = null;
    }

    // Update verbosity
    if (customVerbosity) {
      args.verbosity = customVerbosity;
    } else {
      args.verbosity = null;
    }

    kwArgs = args;
  }
  
  // Reactive updates for verbosity (since event handlers don't work reliably)
  let previousVerbosity = customVerbosity;
  $: if (customVerbosity !== previousVerbosity) {
    previousVerbosity = customVerbosity;
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

<!-- Verbosity Control -->
{#if showVerbosity}
<div
  class="border-default hover:bg-hover-stronger flex h-[4.125rem] items-center justify-between gap-8 border-b px-4"
>
  <div class="flex items-center gap-2">
    <p class="w-24" aria-label="Verbosity setting">Verbosity</p>
    <Tooltip
      text="Controls response length and detail level (Default: medium)\nLow: Concise and to the point\nMedium: Balanced detail\nHigh: Comprehensive and detailed"
    >
      <IconQuestionMark class="text-muted hover:text-primary" />
    </Tooltip>
  </div>
  <select 
    bind:value={customVerbosity}
    on:change={updateKwArgs}
    class="border-default bg-primary ring-default rounded border px-3 py-2 focus:ring-2"
  >
    <option value="">Default</option>
    <option value="low">Low</option>
    <option value="medium">Medium</option>
    <option value="high">High</option>
  </select>
</div>
{/if}