<script lang="ts">
  import {
    behaviourList,
    getBehaviour,
    getKwargs,
    type ModelBehaviour,
    type ModelKwArgs
  } from "../ModelBehaviours";
  import { createSelect } from "@melt-ui/svelte";
  import { IconChevronDown } from "@intric/icons/chevron-down";
  import { IconCheck } from "@intric/icons/check";
  import { IconQuestionMark } from "@intric/icons/question-mark";
  import { Input, Tooltip } from "@intric/ui";

  export let kwArgs: ModelKwArgs;
  export let isDisabled: boolean;
  export let aria: AriaProps = { "aria-label": "Select model behaviour" };
  export let selectedModel: any = null; // CompletionModel from the parent
  
  // Determine which parameters to show based on model capabilities
  $: showReasoningEffort = selectedModel?.reasoning ?? false;
  $: showVerbosity = selectedModel?.supports_verbosity ?? false;
  $: showMaxTokens = true; // All models support this

  const {
    elements: { trigger, menu, option },
    helpers: { isSelected },
    states: { selected }
  } = createSelect<ModelBehaviour>({
    defaultSelected: { value: getBehaviour(kwArgs, selectedModel) },
    positioning: {
      placement: "bottom",
      fitViewport: true,
      sameWidth: true
    },
    portal: null,
    onSelectedChange: ({ next }) => {
      if (!next?.value) return next;
      
      if (next.value === "custom") {
        // If selecting custom, preserve current settings if already custom, otherwise initialize
        const newArgs = getBehaviour(kwArgs, selectedModel) === "custom" ? kwArgs : { temperature: 1, top_p: null };
        kwArgs = newArgs;
      } else {
        // For non-custom behaviors, merge preset values with current structure
        const presetValues = getKwargs(next.value, selectedModel) || getKwargs("default", selectedModel);
        
        // Create new object that preserves the current structure but updates preset fields
        const newArgs = { ...kwArgs };
        Object.entries(presetValues).forEach(([key, value]) => {
          newArgs[key] = value;
        });
        
        // Only update kwArgs if the values would actually be different
        const currentStr = JSON.stringify(kwArgs);
        const newStr = JSON.stringify(newArgs);
        
        if (currentStr !== newStr) {
          kwArgs = newArgs;
        }
      }
      
      return next;
    }
  });

  // This function will only be called on direct user input of custom parameters
  // If the selected value is not a named value, it will set the Kwargs
  // This can't be a declarative statement with $: as it would fire in too many situations
  let customTemp: number = 1;
  let customReasoningEffort: string = "";
  let customVerbosity: string = "";
  let customMaxTokens: number = 0;
  
  function maybeSetKwArgsCustom() {
    // Start with existing kwArgs to preserve server structure
    const args = { ...kwArgs };
    
    // Update only the values that changed
    args.temperature = customTemp;
    if (customReasoningEffort) {
      args.reasoning_effort = customReasoningEffort;
    }
    if (customVerbosity) {
      args.verbosity = customVerbosity;
    }
    if (customMaxTokens > 0) {
      args.max_completion_tokens = customMaxTokens;
    } else {
      // 0 or null means no limit
      args.max_completion_tokens = null;
    }
    
    
    if (getBehaviour(args, selectedModel) === "custom") {
      kwArgs = args;
    }
  }

  function watchChanges(currentKwArgs: ModelKwArgs) {
    if (isDisabled) {
      $selected = { value: "default" };
      return;
    }

    const behaviour = getBehaviour(currentKwArgs, selectedModel);

    if ($selected?.value !== behaviour) {
      $selected = { value: behaviour };
    }

    if (behaviour === "custom") {
      if (currentKwArgs.temperature && currentKwArgs.temperature !== customTemp) {
        customTemp = currentKwArgs.temperature;
      }
      if (currentKwArgs.reasoning_effort !== customReasoningEffort) {
        customReasoningEffort = currentKwArgs.reasoning_effort || "";
      }
      if (currentKwArgs.verbosity !== customVerbosity) {
        customVerbosity = currentKwArgs.verbosity || "";
      }
      const currentMaxTokens = currentKwArgs.max_completion_tokens || 0;
      if (currentMaxTokens !== customMaxTokens) {
        customMaxTokens = currentMaxTokens;
      }
    }
  }

  $: watchChanges(kwArgs);
  
  // Reactive approach for max tokens changes (since event handlers don't work reliably)
  let previousMaxTokens = customMaxTokens;
  $: if (customMaxTokens !== previousMaxTokens) {
    previousMaxTokens = customMaxTokens;
    maybeSetKwArgsCustom();
  }
  
</script>

<button
  {...$trigger}
  {...aria}
  use:trigger
  disabled={isDisabled}
  class:hover:cursor-default={isDisabled}
  class:text-secondary={isDisabled}
  class="border-default hover:bg-hover-default flex h-16 items-center justify-between border-b px-4"
>
  <span class="capitalize">{$selected?.value ?? "No behaviour found"}</span>
  <IconChevronDown />
</button>

<div
  class="border-stronger bg-primary z-20 flex flex-col overflow-y-auto rounded-lg border shadow-xl"
  {...$menu}
  use:menu
>
  <div
    class="bg-frosted-glass-secondary border-default sticky top-0 border-b px-4 py-2 font-mono text-sm"
  >
    Select a model behaviour
  </div>
  {#each behaviourList as behavior (behavior)}
    <div
      class="border-default hover:bg-hover-stronger flex min-h-16 items-center justify-between border-b px-4 hover:cursor-pointer"
      {...$option({ value: behavior })}
      use:option
    >
      <span class="capitalize">
        {behavior}
      </span>
      <div class="check {$isSelected(behavior) ? 'block' : 'hidden'}">
        <IconCheck class="text-positive-default" />
      </div>
    </div>
  {/each}
</div>

{#if $selected?.value === "custom"}
  <!-- Temperature Control -->
  <div
    class="border-default hover:bg-hover-stronger flex h-[4.125rem] items-center justify-between gap-8 border-b px-4"
  >
    <div class="flex items-center gap-2">
      <p class="w-24" aria-label="Temperature setting" id="temperature_label">Temperature</p>
      <Tooltip
        text="Randomness: A value between 0 and 2 (Default: 1)\nHigher values will create more creative responses.\nLower values will be more deterministic."
      >
        <IconQuestionMark class="text-muted hover:text-primary" />
      </Tooltip>
    </div>
    <Input.Slider
      bind:value={customTemp}
      max={2}
      min={0}
      step={0.01}
      onInput={maybeSetKwArgsCustom}
    />
    <Input.Number
      onInput={maybeSetKwArgsCustom}
      bind:value={customTemp}
      step={0.01}
      max={2}
      min={0}
      hiddenLabel={true}
    ></Input.Number>
  </div>

  <!-- Reasoning Effort Control (for reasoning models) -->
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
      on:change={maybeSetKwArgsCustom}
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

  <!-- Verbosity Control (for GPT-5) -->
  {#if showVerbosity}
  <div
    class="border-default hover:bg-hover-stronger flex h-[4.125rem] items-center justify-between gap-8 border-b px-4"
  >
    <div class="flex items-center gap-2">
      <p class="w-24" aria-label="Verbosity setting">Verbosity</p>
      <Tooltip
        text="Control response verbosity (Default: medium)\nHigher verbosity provides more detailed explanations."
      >
        <IconQuestionMark class="text-muted hover:text-primary" />
      </Tooltip>
    </div>
    <select 
      bind:value={customVerbosity}
      on:change={maybeSetKwArgsCustom}
      class="border-default bg-primary ring-default rounded border px-3 py-2 focus:ring-2"
    >
      <option value="">Default</option>
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
{/if}

{#if isDisabled}
  <p
    class="label-warning border-label-default bg-label-dimmer text-label-stronger mt-2.5 rounded-md border px-2 py-1 text-sm"
  >
    <span class="font-bold">Warning:&nbsp;</span>Temperature settings not available for this model.
  </p>
{/if}

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
