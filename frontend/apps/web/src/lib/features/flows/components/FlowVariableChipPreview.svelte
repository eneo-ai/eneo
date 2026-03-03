<script lang="ts">
  import type { FlowStep } from "@intric/intric-js";
  import { parsePromptSegments, getChipClasses, type VariableClassificationContext } from "$lib/features/flows/flowVariableTokens";

  export let text: string;
  export let steps: FlowStep[];
  export let compact: boolean = false;
  export let formSchema: { fields: { name: string }[] } | undefined = undefined;
  export let transcriptionEnabled: boolean = true;
  export let currentStepOrder: number = 1;

  $: classificationContext = buildContext(steps, formSchema, transcriptionEnabled, currentStepOrder);

  function buildContext(
    steps: FlowStep[],
    formSchema: { fields: { name: string }[] } | undefined,
    transcriptionEnabled: boolean,
    currentStepOrder: number,
  ): VariableClassificationContext {
    const knownFieldNames = new Set<string>();
    for (const field of formSchema?.fields ?? []) {
      const name = (field.name ?? "").trim();
      if (name) knownFieldNames.add(name);
    }

    const knownStepNames = new Map<number, string>();
    for (const step of steps) {
      const name = (step.user_description ?? "").trim();
      if (name) knownStepNames.set(step.step_order, name);
    }

    return { knownFieldNames, knownStepNames, transcriptionEnabled, currentStepOrder };
  }

  $: segments = parsePromptSegments(text, classificationContext);
</script>

{#if segments.some((s) => s.type === "variable")}
  <div class="flex flex-wrap items-center gap-1" class:text-xs={compact} class:py-1={!compact} class:py-0.5={compact}>
    {#each segments as segment}
      {#if segment.type === "text"}
        {#if !compact}
          <span class="text-xs text-secondary">{segment.value}</span>
        {/if}
      {:else}
        <span class="{getChipClasses(segment.category)} inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium">
          {segment.value}
        </span>
      {/if}
    {/each}
  </div>
{/if}
