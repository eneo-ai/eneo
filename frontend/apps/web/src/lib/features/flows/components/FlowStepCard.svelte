<script lang="ts">
  import type { FlowStep } from "@eneo/eneo-js";
  import { IconTrash } from "@eneo/icons/trash";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { m } from "$lib/paraglide/messages";
  import { getDownstreamKindForOutput } from "$lib/features/flows/flowStepPresentation";
  import {
    getTemplateFillOutputConfig,
    getTemplateFillReadiness,
    getTemplateFillTemplateName
  } from "$lib/features/flows/templateFillConfig";
  import type { FlowStepMcpSummary } from "$lib/features/flows/flowStepMcpConfig";

  let {
    step,
    mcpSummary = null,
    isActive,
    isPublished,
    isPowerUser,
    canMoveUp,
    canMoveDown,
    hasValidationError = false,
    index = 0,
    onClick,
    onMoveUp,
    onMoveDown,
    onRemove
  }: {
    step: FlowStep;
    mcpSummary?: FlowStepMcpSummary | null;
    isActive: boolean;
    isPublished: boolean;
    isPowerUser: boolean;
    canMoveUp: boolean;
    canMoveDown: boolean;
    hasValidationError?: boolean;
    index?: number;
    onClick?: () => void;
    onMoveUp?: () => void;
    onMoveDown?: () => void;
    onRemove?: () => void;
  } = $props();

  const INPUT_SOURCE_LABELS: Record<string, () => string> = {
    flow_input: () => m.flow_input_source_flow_input(),
    previous_step: () => m.flow_input_source_previous_step(),
    all_previous_steps: () => m.flow_input_source_all_previous_steps()
  };

  function handleKeydown(e: KeyboardEvent) {
    if ((e.key === "Enter" || e.key === " ") && !e.altKey) {
      e.preventDefault();
      onClick?.();
      return;
    }
    if (isPublished) return;
    if (e.altKey && e.key === "ArrowUp" && canMoveUp) {
      e.preventDefault();
      onMoveUp?.();
    }
    if (e.altKey && e.key === "ArrowDown" && canMoveDown) {
      e.preventDefault();
      onMoveDown?.();
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

  const label = $derived(
    step.user_description || m.flow_step_fallback_label({ order: String(step.step_order) })
  );
  const inputLabel = $derived(INPUT_SOURCE_LABELS[step.input_source]?.() ?? step.input_source);
  const outputLabel = $derived(OUTPUT_TYPE_LABELS[step.output_type]?.() ?? step.output_type);
  const railOutputLabel = $derived(RAIL_OUTPUT_LABELS[step.output_type] ?? outputLabel);
  const nextChannelLabel = $derived(
    step.output_mode === "transcribe_only"
      ? m.flow_step_summary_next_channel_transcript_short()
      : getDownstreamKindForOutput(step.output_type) === "text_and_structured"
        ? m.flow_step_summary_next_channel_text_and_structured_short()
        : m.flow_step_summary_next_channel_text_short()
  );
  const inputTypeLabel = $derived(INPUT_TYPE_LABELS[step.input_type]?.() ?? step.input_type);
  const sourceSummary = $derived.by(() => {
    if (step.output_mode === "template_fill") {
      return getTemplateFillTemplateName(step) ?? m.flow_template_fill_card_secondary();
    }
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
  });
  const inputBadgeClass = $derived(
    INPUT_BADGE_CLASSES[step.input_type] ?? "bg-hover-dimmer text-secondary"
  );
  const outputBadgeClass = $derived(
    OUTPUT_BADGE_CLASSES[step.output_type] ?? "bg-hover-dimmer text-secondary"
  );
  const templateReadiness = $derived(
    step.output_mode === "template_fill"
      ? getTemplateFillReadiness(getTemplateFillOutputConfig(step))
      : null
  );
</script>

<div
  role="listitem"
  class="step-card-row group flex w-full items-start gap-2.5 border-b px-3.5 py-3 text-left transition-colors duration-150
    {isActive ? 'border-b-default bg-accent-dimmer/40' : 'border-default hover:bg-hover-dimmer/40'}
    active:bg-hover-default"
  style:animation-delay="{Math.min(index, 10) * 50}ms"
  style:animation-fill-mode="both"
>
  <button
    type="button"
    class="focus-visible:ring-accent-default flex min-w-0 flex-1 items-start gap-2.5 rounded text-left focus-visible:ring-2 focus-visible:outline-none"
    aria-current={isActive ? "true" : undefined}
    onclick={() => onClick?.()}
    onkeydown={handleKeydown}
  >
    <!-- Step order tile — rounded square (matches AI Builder rhythm) -->
    <div
      class="relative flex size-7 shrink-0 items-center justify-center rounded-lg text-[13px] font-semibold tabular-nums transition-colors duration-150"
      class:bg-accent-default={isActive}
      class:text-on-fill={isActive}
      class:bg-hover-default={!isActive}
      class:text-secondary={!isActive}
    >
      <span>{step.step_order}</span>
      {#if hasValidationError}
        <span
          class="bg-negative-stronger absolute -top-0.5 -right-0.5 size-2 rounded-full shadow-[0_0_0_2px_var(--background-primary)]"
          aria-label={m.flow_validation_step_has_error()}
        ></span>
      {/if}
    </div>

    <div class="flex min-w-0 flex-1 flex-col gap-0.5">
      <span
        class="truncate text-sm leading-snug tracking-[-0.005em]"
        class:font-semibold={isActive}
        class:font-medium={!isActive}
        title={label}>{label}</span
      >

      <div class="text-secondary truncate text-xs leading-snug">
        {sourceSummary}
      </div>

      {#if step.output_mode === "template_fill" || step.output_mode === "transcribe_only"}
        <div class="mt-0.5 flex flex-wrap items-center gap-1.5">
          {#if step.output_mode === "template_fill"}
            <Badge
              variant="secondary"
              class="bg-accent-dimmer text-accent-stronger h-5 px-1.5 text-[10px] font-semibold tracking-wide uppercase"
            >
              {m.flow_template_fill_card_badge()}
            </Badge>
            {#if templateReadiness}
              <Badge
                variant="secondary"
                class="h-5 px-1.5 text-[10px] font-semibold tabular-nums {templateReadiness.incomplete
                  ? 'bg-warning-dimmer text-warning-stronger'
                  : 'bg-positive-dimmer text-positive-stronger'}"
              >
                {templateReadiness.matched}/{templateReadiness.total || 0}
              </Badge>
            {/if}
          {:else}
            <Badge
              variant="secondary"
              class="bg-accent-dimmer text-accent-stronger h-5 px-1.5 text-[10px] font-semibold tracking-wide uppercase"
            >
              {m.flow_transcribe_only_title()}
            </Badge>
          {/if}
        </div>
      {/if}

      {#if isPowerUser}
        <div class="mt-1 flex flex-wrap items-center gap-x-1.5 gap-y-1">
          <Badge
            variant="secondary"
            class="h-5 px-1.5 text-[10px] font-semibold tracking-wide {inputBadgeClass}"
            >{inputTypeLabel}</Badge
          >
          <span class="text-muted text-[10px]" aria-hidden="true">&rarr;</span>
          <Badge
            variant="secondary"
            class="h-5 px-1.5 text-[10px] font-semibold tracking-wide {outputBadgeClass}"
            >{railOutputLabel}</Badge
          >
          <span class="text-muted text-[10px]" aria-hidden="true">&middot;</span>
          <span class="text-accent-stronger text-[10px] font-medium tabular-nums">
            {m.flow_step_card_chain_short()}: {nextChannelLabel}
          </span>
          {#if mcpSummary?.hasActiveMcp}
            <Badge
              variant="secondary"
              class="bg-warning-dimmer text-warning-stronger h-5 px-1.5 text-[10px] font-semibold tabular-nums"
              >{m.flow_step_mcp_tools_badge({
                count: String(mcpSummary.enabledToolCount)
              })}</Badge
            >
          {/if}
        </div>
      {/if}
    </div>
  </button>

  {#if !isPublished}
    <div
      class="flex shrink-0 items-center gap-0.5 opacity-0 transition-opacity duration-150 group-focus-within:opacity-100 group-hover:opacity-100"
      class:opacity-100={isActive}
    >
      <button
        type="button"
        class="text-secondary hover:bg-hover-dimmer focus-visible:ring-accent-default inline-flex size-7 items-center justify-center rounded-md transition-colors focus-visible:ring-2 focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-40"
        onclick={(e) => {
          e.stopPropagation();
          onMoveUp?.();
        }}
        disabled={!canMoveUp}
        title={m.flow_step_move_up()}
        aria-label={m.flow_step_move_up()}
      >
        <svg
          class="size-3"
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          stroke-width="2.5"
          stroke-linecap="round"
          stroke-linejoin="round"
          aria-hidden="true"
        >
          <path d="M8 12V4M4 7l4-3 4 3" />
        </svg>
      </button>
      <button
        type="button"
        class="text-secondary hover:bg-hover-dimmer focus-visible:ring-accent-default inline-flex size-7 items-center justify-center rounded-md transition-colors focus-visible:ring-2 focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-40"
        onclick={(e) => {
          e.stopPropagation();
          onMoveDown?.();
        }}
        disabled={!canMoveDown}
        title={m.flow_step_move_down()}
        aria-label={m.flow_step_move_down()}
      >
        <svg
          class="size-3"
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          stroke-width="2.5"
          stroke-linecap="round"
          stroke-linejoin="round"
          aria-hidden="true"
        >
          <path d="M8 4v8M4 9l4 3 4-3" />
        </svg>
      </button>
      <button
        type="button"
        class="text-secondary hover:bg-hover-dimmer hover:text-negative-stronger focus-visible:ring-accent-default inline-flex size-7 items-center justify-center rounded-md transition-colors focus-visible:ring-2 focus-visible:outline-none"
        onclick={(e) => {
          e.stopPropagation();
          onRemove?.();
        }}
        title={m.flow_step_remove()}
        aria-label={m.flow_step_remove()}
      >
        <IconTrash class="size-3" />
      </button>
    </div>
  {/if}
</div>

<style>
  @media (prefers-reduced-motion: no-preference) {
    .step-card-row {
      animation: step-card-in 280ms cubic-bezier(0.22, 1, 0.36, 1);
    }
  }

  @keyframes step-card-in {
    from {
      opacity: 0;
      transform: translateX(-4px);
    }
    to {
      opacity: 1;
      transform: translateX(0);
    }
  }
</style>
