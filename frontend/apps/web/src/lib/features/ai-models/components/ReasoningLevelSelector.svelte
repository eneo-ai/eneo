<script lang="ts">
  import type { ReasoningLevel } from "../ModelBehaviours.js";
  import type { CompletionModel } from "@intric/intric-js";
  import { IconQuestionMark } from "@intric/icons/question-mark";
  import { Tooltip } from "@intric/ui";

  // Props using Svelte 5 $props() pattern  
  let { 
    value = $bindable("disabled" as ReasoningLevel),
    model,
    disabled = false
  }: {
    value?: ReasoningLevel;
    model?: CompletionModel | null;
    disabled?: boolean;
  } = $props();

  // Internal state for radio group binding
  let selectedLevel = $state(value);

  // Sync internal state with external prop using Svelte 5 $effect
  $effect(() => {
    selectedLevel = value;
  });

  // Update external prop when internal state changes
  $effect(() => {
    value = selectedLevel;
  });

  // Model-specific logic using $derived.by
  const isGeminiInteractive = $derived.by(() => {
    return model?.name === "gemini-2.5-flash" || model?.name === "gemini-2.5-flash-preview-05-20";
  });

  const isAlwaysOnReasoning = $derived.by(() => {
    return model?.reasoning && !isGeminiInteractive;
  });

  // Reasoning level options
  const reasoningOptions = [
    { value: "disabled" as ReasoningLevel, label: "Off" },
    { value: "low" as ReasoningLevel, label: "Low" },
    { value: "medium" as ReasoningLevel, label: "Medium" },
    { value: "high" as ReasoningLevel, label: "High" }
  ];

  function getTooltipText(): string {
    if (isAlwaysOnReasoning) {
      return "This model has reasoning capabilities that are always enabled. The model will automatically think through complex problems before responding.";
    }
    
    if (isGeminiInteractive) {
      return "Control reasoning intensity: Low (1K tokens), Medium (8K tokens), High (24K tokens). Higher levels provide more thorough analysis but take longer.";
    }
    
    return "Configure the reasoning intensity for this model. Different levels balance speed, thoroughness, and cost.";
  }
</script>

<!-- Main reasoning level selector matching existing design patterns -->
<div class="flex items-center gap-2">
  <p class="w-24" aria-label="Reasoning setting" id="reasoning_label">Reasoning</p>
  <Tooltip text={getTooltipText()}>
    <IconQuestionMark class="text-muted hover:text-primary" />
  </Tooltip>
</div>

<div class="flex items-center gap-2 ml-auto">
  {#if isAlwaysOnReasoning}
    <!-- Always-on reasoning indicator -->
    <div class="px-3 py-1.5 rounded-md border bg-accent-dimmer text-accent-stronger border-accent-default text-sm">
      Always On
    </div>
  {:else}
    <!-- Interactive reasoning level selector -->
    {#each reasoningOptions as option (option.value)}
      <label class="flex items-center cursor-pointer">
        <input
          type="radio"
          bind:group={selectedLevel}
          value={option.value}
          {disabled}
          class="sr-only"
        />
        <div
          class="px-3 py-1.5 rounded-md border text-sm transition-all duration-200
          {selectedLevel === option.value 
            ? 'bg-accent-default text-on-fill border-accent-default shadow-sm' 
            : 'bg-primary border-default hover:border-accent-default hover:bg-hover-default'
          }
          {disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}"
        >
          {option.label}
        </div>
      </label>
    {/each}
  {/if}
</div>

<style>
  /* Screen reader only - proper accessibility */
  .sr-only {
    position: absolute;
    width: 1px;
    height: 1px;
    padding: 0;
    margin: -1px;
    overflow: hidden;
    clip: rect(0, 0, 0, 0);
    white-space: nowrap;
    border: 0;
  }
</style>