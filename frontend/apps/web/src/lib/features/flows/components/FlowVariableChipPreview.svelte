<script lang="ts">
  import type { FlowStep } from "@eneo/eneo-js";
  import {
    parsePromptSegments,
    getChipClasses,
    type VariableClassificationContext
  } from "$lib/features/flows/flowVariableTokens";

  let {
    text,
    steps,
    compact = false,
    formSchema = undefined,
    transcriptionEnabled = true,
    currentStepOrder = 1
  }: {
    text: string;
    steps: FlowStep[];
    compact?: boolean;
    formSchema?: { fields: { name: string }[] } | undefined;
    transcriptionEnabled?: boolean;
    currentStepOrder?: number;
  } = $props();

  const classificationContext = $derived.by(() => {
    const knownFieldNames = new Set<string>();
    for (const field of formSchema?.fields ?? []) {
      const name = (field.name ?? "").trim();
      if (name) knownFieldNames.add(name);
    }

    const knownStepNames = new Map<number, string>();
    const stepOutputTypes = new Map<number, string>();
    for (const step of steps) {
      const name = (step.user_description ?? "").trim();
      if (name) knownStepNames.set(step.step_order, name);
      stepOutputTypes.set(step.step_order, step.output_type);
    }

    return {
      knownFieldNames,
      knownStepNames,
      stepOutputTypes,
      transcriptionEnabled,
      currentStepOrder
    } satisfies VariableClassificationContext;
  });

  const segments = $derived(parsePromptSegments(text, classificationContext));
</script>

{#if segments.some((s) => s.type === "variable")}
  <div
    class="flex flex-wrap items-center gap-1"
    class:text-xs={compact}
    class:py-1={!compact}
    class:py-0.5={compact}
  >
    {#each segments as segment}
      {#if segment.type === "text"}
        {#if !compact}
          <span class="text-secondary text-xs">{segment.value}</span>
        {/if}
      {:else}
        <span
          class="{getChipClasses(
            segment.category
          )} inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium"
        >
          {segment.value}
        </span>
      {/if}
    {/each}
  </div>
{/if}
