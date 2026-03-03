<script lang="ts">
  import type { FlowStep } from "@intric/intric-js";
  import { createEventDispatcher } from "svelte";
  import { IconTrash } from "@intric/icons/trash";
  import { m } from "$lib/paraglide/messages";

  export let step: FlowStep;
  export let isActive: boolean;
  export let isPublished: boolean;
  export let isPowerUser: boolean;
  export let canMoveUp: boolean;
  export let canMoveDown: boolean;

  const dispatch = createEventDispatcher();

  const INPUT_SOURCE_LABELS: Record<string, () => string> = {
    flow_input: () => m.flow_input_source_flow_input(),
    previous_step: () => m.flow_input_source_previous_step(),
    all_previous_steps: () => m.flow_input_source_all_previous_steps()
  };

  function handleKeydown(e: KeyboardEvent) {
    if ((e.key === "Enter" || e.key === " ") && !e.altKey) {
      e.preventDefault();
      dispatch("click");
      return;
    }
    if (isPublished) return;
    if (e.altKey && e.key === "ArrowUp" && canMoveUp) {
      e.preventDefault();
      dispatch("moveUp");
    }
    if (e.altKey && e.key === "ArrowDown" && canMoveDown) {
      e.preventDefault();
      dispatch("moveDown");
    }
  }

  const OUTPUT_TYPE_LABELS: Record<string, () => string> = {
    text: () => m.flow_output_type_text(),
    json: () => m.flow_output_type_json(),
    pdf: () => m.flow_output_type_pdf(),
    docx: () => m.flow_output_type_docx()
  };

  $: label = step.user_description || m.flow_step_fallback_label({ order: String(step.step_order) });
  $: inputLabel = INPUT_SOURCE_LABELS[step.input_source]?.() ?? step.input_source;
  $: outputLabel = OUTPUT_TYPE_LABELS[step.output_type]?.() ?? step.output_type;
  $: modelName = (() => {
    // Try to extract model name from the step's assistant model
    const model = (step as any).completion_model?.name ?? (step as any).model_name;
    return typeof model === "string" ? model : null;
  })();
</script>

<div
  role="listitem"
  class="group flex w-full items-start gap-2.5 border-b px-3.5 py-3 text-left transition-all duration-150
    {isActive ? 'bg-accent-dimmer border-l-[3px] border-l-accent-default border-b-default' : 'border-default border-l-[3px] border-l-transparent'}
    {'hover:bg-hover-dimmer active:bg-hover-default'}"
>
  <button
    type="button"
    class="flex min-w-0 flex-1 items-start gap-2.5 text-left"
    aria-current={isActive ? "true" : undefined}
    on:click={() => dispatch("click")}
    on:keydown={handleKeydown}
  >
    <!-- Step order badge — filled circle -->
    <div
      class="flex size-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold transition-colors duration-150"
      class:bg-accent-default={isActive}
      class:text-on-fill={isActive}
      class:bg-hover-default={!isActive}
      class:text-secondary={!isActive}
    >
      <span>{step.step_order}</span>
    </div>

    <div class="flex min-w-0 flex-1 flex-col gap-0.5">
      <div class="flex items-center gap-2">
        <span
          class="truncate text-sm leading-snug"
          class:font-semibold={isActive}
          class:font-medium={!isActive}
          title={label}
        >{label}</span>

        {#if modelName}
          <span class="shrink-0 rounded-full bg-secondary px-2 py-0.5 text-xs text-muted">
            {modelName}
          </span>
        {/if}
      </div>

      <div class="truncate text-xs text-secondary">
        {#if isPowerUser}
          {inputLabel} &rarr; {outputLabel}
        {:else if modelName}
          {modelName}
        {:else}
          <span class="text-muted">{m.flow_step_not_configured()}</span>
        {/if}
      </div>

      {#if isPowerUser}
        <div class="flex flex-wrap gap-1 pt-0.5">
          <span class="rounded bg-hover-dimmer px-1.5 py-0.5 text-xs font-medium">
            {step.input_type}
          </span>
          <span class="rounded bg-hover-dimmer px-1.5 py-0.5 text-xs font-medium">
            {step.output_type}
          </span>
          {#if step.mcp_policy === "restricted"}
            <span class="rounded bg-warning-dimmer px-1.5 py-0.5 text-xs font-medium text-warning-stronger">
              MCP
            </span>
          {/if}
        </div>
      {/if}
    </div>
  </button>

  {#if !isPublished}
    <div class="ml-1 flex shrink-0 items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100" class:opacity-100={isActive}>
      <button
        type="button"
        class="inline-flex size-7 items-center justify-center rounded text-xs text-secondary hover:bg-hover-dimmer disabled:cursor-not-allowed disabled:opacity-40"
        on:click|stopPropagation={() => dispatch("moveUp")}
        disabled={!canMoveUp}
        title={m.flow_step_move_up()}
        aria-label={m.flow_step_move_up()}
      >
        <svg class="size-3.5" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M8 12V4M4 7l4-3 4 3"/>
        </svg>
      </button>
      <button
        type="button"
        class="inline-flex size-7 items-center justify-center rounded text-xs text-secondary hover:bg-hover-dimmer disabled:cursor-not-allowed disabled:opacity-40"
        on:click|stopPropagation={() => dispatch("moveDown")}
        disabled={!canMoveDown}
        title={m.flow_step_move_down()}
        aria-label={m.flow_step_move_down()}
      >
        <svg class="size-3.5" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M8 4v8M4 9l4 3 4-3"/>
        </svg>
      </button>
      <button
        type="button"
        class="inline-flex size-7 items-center justify-center rounded text-secondary hover:bg-hover-dimmer hover:text-red-600"
        on:click|stopPropagation={() => dispatch("remove")}
        title={m.flow_step_remove()}
        aria-label={m.flow_step_remove()}
      >
        <IconTrash class="size-3.5" />
      </button>
    </div>
  {/if}
</div>
