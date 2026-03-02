<script lang="ts">
  import type { FlowStep } from "@intric/intric-js";
  import { createEventDispatcher } from "svelte";
  import { IconChevronUpDown } from "@intric/icons/chevron-up-down";
  import { m } from "$lib/paraglide/messages";

  export let step: FlowStep;
  export let index: number;
  export let isActive: boolean;
  export let isPublished: boolean;
  export let isPowerUser: boolean;
  export let canMoveUp: boolean;
  export let canMoveDown: boolean;
  export let isDragging: boolean = false;

  const dispatch = createEventDispatcher();

  const INPUT_SOURCE_LABELS: Record<string, () => string> = {
    flow_input: () => m.flow_input_source_flow_input(),
    previous_step: () => m.flow_input_source_previous_step(),
    all_previous_steps: () => m.flow_input_source_all_previous_steps()
  };

  function handleKeydown(e: KeyboardEvent) {
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

  function handleDragStart(e: DragEvent) {
    if (isPublished || !e.dataTransfer) return;
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", String(index));
    dispatch("dragstart", index);
  }

  function handleDragEnd() {
    dispatch("dragend");
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
</script>

<div
  role="option"
  tabindex="0"
  aria-selected={isActive}
  draggable={!isPublished}
  class="group flex w-full cursor-pointer items-start gap-2.5 border-b px-3.5 py-3 text-left transition-all duration-150
    {isActive ? 'bg-accent-dimmer border-l-[3px] border-l-accent-default border-b-default' : 'border-default'}
    {isDragging ? 'opacity-40' : 'hover:bg-hover-dimmer active:bg-hover-default'}"
  on:click={() => dispatch("click")}
  on:keydown={handleKeydown}
  on:dragstart={handleDragStart}
  on:dragend={handleDragEnd}
>
  <!-- Drag handle / step order badge -->
  <div class="flex size-6 shrink-0 items-center justify-center rounded-md bg-hover-default text-xs font-semibold text-secondary transition-colors duration-150"
    class:cursor-grab={!isPublished}
  >
    {#if !isPublished}
      <span class="group-hover:hidden">{step.step_order}</span>
      <IconChevronUpDown class="hidden size-3.5 group-hover:block" />
    {:else}
      <span>{step.step_order}</span>
    {/if}
  </div>

  <div class="flex min-w-0 flex-1 flex-col gap-0.5">
    <span class="truncate text-sm font-medium leading-snug">{label}</span>

    <div class="text-secondary truncate text-xs">
      {inputLabel} &rarr; {outputLabel}
    </div>

    {#if isPowerUser}
      <div class="flex flex-wrap gap-1 pt-0.5">
        <span class="bg-hover-dimmer rounded px-1.5 py-0.5 text-[10px] font-medium">
          {step.input_type}
        </span>
        <span class="bg-hover-dimmer rounded px-1.5 py-0.5 text-[10px] font-medium">
          {step.output_type}
        </span>
        {#if step.mcp_policy === "restricted"}
          <span class="bg-amber-50 text-amber-700 rounded px-1.5 py-0.5 text-[10px] font-medium">
            MCP
          </span>
        {/if}
      </div>
    {/if}
  </div>
</div>
