<script lang="ts">
  import type { FlowStep } from "@intric/intric-js";
  import { createEventDispatcher } from "svelte";
  import { IconTrash } from "@intric/icons/trash";
  import { m } from "$lib/paraglide/messages";
  import { getDownstreamKindForOutput } from "$lib/features/flows/flowStepPresentation";

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
  const RAIL_OUTPUT_LABELS: Record<string, string> = {
    text: m.flow_output_type_text(),
    json: m.flow_output_type_json(),
    pdf: "PDF",
    docx: "Word"
  };
  const INPUT_TYPE_LABELS: Record<string, () => string> = {
    text: () => m.flow_type_text(),
    json: () => m.flow_type_json(),
    document: () => m.flow_type_document(),
    file: () => m.flow_type_file(),
    image: () => m.flow_type_image(),
    audio: () => m.flow_type_audio(),
    any: () => m.flow_type_any()
  };
  const BADGE_BASE = "inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium";
  const INPUT_BADGE_CLASSES: Record<string, string> = {
    text: "bg-hover-dimmer text-secondary",
    json: "bg-positive-dimmer text-positive-stronger",
    document: "bg-warning-dimmer text-warning-stronger",
    file: "bg-warning-dimmer text-warning-stronger",
    image: "bg-hover-dimmer text-secondary",
    audio: "bg-accent-dimmer text-accent-stronger",
    any: "bg-warning-dimmer text-warning-stronger"
  };
  const OUTPUT_BADGE_CLASSES: Record<string, string> = {
    text: "bg-hover-dimmer text-secondary",
    json: "bg-positive-dimmer text-positive-stronger",
    pdf: "bg-warning-dimmer text-warning-stronger",
    docx: "bg-warning-dimmer text-warning-stronger"
  };

  $: label =
    step.user_description || m.flow_step_fallback_label({ order: String(step.step_order) });
  $: inputLabel = INPUT_SOURCE_LABELS[step.input_source]?.() ?? step.input_source;
  $: outputLabel = OUTPUT_TYPE_LABELS[step.output_type]?.() ?? step.output_type;
  $: railOutputLabel = RAIL_OUTPUT_LABELS[step.output_type] ?? outputLabel;
  $: nextChannelLabel =
    step.output_mode === "transcribe_only"
      ? m.flow_step_summary_next_channel_transcript_short()
      : getDownstreamKindForOutput(step.output_type) === "text_and_structured"
      ? m.flow_step_summary_next_channel_text_and_structured_short()
      : m.flow_step_summary_next_channel_text_short();
  $: inputTypeLabel = INPUT_TYPE_LABELS[step.input_type]?.() ?? step.input_type;
  $: sourceSummary = (() => {
    switch (step.input_source) {
      case "flow_input":
        return m.flow_step_card_source_flow_input();
      case "previous_step":
        return m.flow_step_card_source_previous_step();
      case "all_previous_steps":
        return m.flow_step_card_source_all_previous_steps();
      case "http_get":
        return m.flow_step_card_source_http_get();
      case "http_post":
        return m.flow_step_card_source_http_post();
      default:
        return inputLabel;
    }
  })();
  $: inputBadgeClass = INPUT_BADGE_CLASSES[step.input_type] ?? "bg-hover-dimmer text-secondary";
  $: outputBadgeClass = OUTPUT_BADGE_CLASSES[step.output_type] ?? "bg-hover-dimmer text-secondary";
</script>

<div
  role="listitem"
  class="group flex w-full items-start gap-2.5 border-b px-3.5 py-3 text-left transition-colors duration-150
    {isActive
    ? 'border-b-default border-l-accent-default bg-accent-dimmer/65 border-l-[3px]'
    : 'border-default hover:bg-hover-dimmer/40 border-l-[3px] border-l-transparent'}
    active:bg-hover-default"
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
          title={label}>{label}</span
        >
      </div>

      <div class="text-secondary truncate text-xs">
        {sourceSummary}
      </div>

      {#if isPowerUser}
        <div class="mt-1 flex flex-wrap items-center gap-1.5">
          <span class={`${BADGE_BASE} ${inputBadgeClass}`}>{inputTypeLabel}</span>
          <span class="text-muted text-[11px]">→</span>
          <span class={`${BADGE_BASE} ${outputBadgeClass}`}>{railOutputLabel}</span>
          <span class="text-muted text-[11px]">·</span>
          <span class="text-accent-stronger text-[11px] font-medium">
            {m.flow_step_card_chain_short()}: {nextChannelLabel}
          </span>
          {#if step.mcp_policy === "restricted"}
            <span class={`${BADGE_BASE} bg-warning-dimmer text-warning-stronger`}> MCP </span>
          {/if}
        </div>
      {/if}
    </div>
  </button>

  {#if !isPublished}
    <div
      class="ml-1 flex shrink-0 items-center gap-1 opacity-35 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100"
      class:opacity-100={isActive}
    >
      <button
        type="button"
        class="text-secondary hover:bg-hover-dimmer inline-flex size-7 items-center justify-center rounded text-xs disabled:cursor-not-allowed disabled:opacity-40"
        on:click|stopPropagation={() => dispatch("moveUp")}
        disabled={!canMoveUp}
        title={m.flow_step_move_up()}
        aria-label={m.flow_step_move_up()}
      >
        <svg
          class="size-3.5"
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <path d="M8 12V4M4 7l4-3 4 3" />
        </svg>
      </button>
      <button
        type="button"
        class="text-secondary hover:bg-hover-dimmer inline-flex size-7 items-center justify-center rounded text-xs disabled:cursor-not-allowed disabled:opacity-40"
        on:click|stopPropagation={() => dispatch("moveDown")}
        disabled={!canMoveDown}
        title={m.flow_step_move_down()}
        aria-label={m.flow_step_move_down()}
      >
        <svg
          class="size-3.5"
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <path d="M8 4v8M4 9l4 3 4-3" />
        </svg>
      </button>
      <button
        type="button"
        class="text-secondary hover:bg-hover-dimmer inline-flex size-7 items-center justify-center rounded hover:text-red-600"
        on:click|stopPropagation={() => dispatch("remove")}
        title={m.flow_step_remove()}
        aria-label={m.flow_step_remove()}
      >
        <IconTrash class="size-3.5" />
      </button>
    </div>
  {/if}
</div>
