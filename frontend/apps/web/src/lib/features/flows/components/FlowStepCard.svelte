<script lang="ts">
  import type { FlowStep } from "@eneo/eneo-js";
  import { IconTrash } from "@eneo/icons/trash";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { getTextProcessingMode } from "$lib/features/flows/flowTextProcessingConfig";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu/index.js";
  import { m } from "$lib/paraglide/messages";
  import { prefersReducedMotion } from "$lib/core/prefersReducedMotion";
  import {
    getTemplateFillOutputConfig,
    getTemplateFillReadiness,
    getTemplateFillTemplateName
  } from "$lib/features/flows/templateFillConfig";
  let {
    step,
    isActive,
    isPublished,
    isPowerUser,
    canMoveUp,
    canMoveDown,
    hasValidationError = false,
    describedBy,
    index = 0,
    onClick,
    onMoveUp,
    onMoveDown,
    onRemove
  }: {
    step: FlowStep;
    isActive: boolean;
    isPublished: boolean;
    isPowerUser: boolean;
    canMoveUp: boolean;
    canMoveDown: boolean;
    hasValidationError?: boolean;
    /** The caption of the group this step belongs to: what it reads. */
    describedBy?: string;
    index?: number;
    onClick?: () => void;
    onMoveUp?: () => void;
    onMoveDown?: () => void;
    onRemove?: () => void;
  } = $props();

  let menuOpen = $state(false);

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

  // Short labels keep the chain on one line in the narrow list.
  const RAIL_OUTPUT_LABELS: Record<string, string> = {
    text: m.flow_output_type_text(),
    json: m.flow_type_json(),
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
  const label = $derived(
    step.user_description || m.flow_step_fallback_label({ order: String(step.step_order) })
  );
  const railOutputLabel = $derived(RAIL_OUTPUT_LABELS[step.output_type] ?? step.output_type);
  const inputTypeLabel = $derived(INPUT_TYPE_LABELS[step.input_type]?.() ?? step.input_type);
  const readsInSections = $derived(getTextProcessingMode(step) === "process_each_section");
  const isTemplateFill = $derived(step.output_mode === "template_fill");
  const templateSummary = $derived(
    isTemplateFill
      ? (getTemplateFillTemplateName(step) ?? m.flow_template_fill_card_secondary())
      : ""
  );
  const templateReadiness = $derived(
    step.output_mode === "template_fill"
      ? getTemplateFillReadiness(getTemplateFillOutputConfig(step))
      : null
  );
  // The selected step stays in view: a step added at the end of a long list is
  // otherwise selected off-screen. "nearest" leaves a visible row where it is,
  // so the remount after the temp→real id reconciliation moves nothing.
  let rowEl = $state<HTMLDivElement | null>(null);
  $effect(() => {
    if (!isActive || !rowEl) return;
    rowEl.scrollIntoView({
      block: "nearest",
      behavior: prefersReducedMotion() ? "auto" : "smooth"
    });
  });
</script>

<div
  bind:this={rowEl}
  role="listitem"
  class="step-card-row group flex w-full items-start gap-2.5 border-b px-3.5 py-3 text-left transition-colors duration-(--duration-quick)
    {isActive ? 'border-b-default bg-accent-dimmer/40' : 'border-default hover:bg-hover-dimmer/40'}
    active:bg-hover-default"
  style:animation-delay="calc(var(--duration-stagger) * {Math.min(index, 6)})"
  style:animation-fill-mode="both"
>
  <button
    type="button"
    class="focus-visible:ring-ring flex min-w-0 flex-1 items-start gap-2.5 rounded text-left focus-visible:ring-2 focus-visible:outline-none"
    aria-current={isActive ? "true" : undefined}
    aria-describedby={describedBy}
    onclick={() => onClick?.()}
    onkeydown={handleKeydown}
  >
    <!-- Step order tile — rounded square (matches AI Builder rhythm) -->
    <div
      class="relative flex size-7 shrink-0 items-center justify-center rounded-lg text-[13px] font-semibold tabular-nums transition-colors duration-(--duration-quick)"
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
        class="line-clamp-2 text-sm leading-snug tracking-[-0.005em] break-words"
        class:font-semibold={isActive}
        class:font-medium={!isActive}
        title={label}>{label}</span
      >

      {#if isTemplateFill}
        <div class="text-secondary line-clamp-2 text-xs leading-snug">{templateSummary}</div>
      {/if}

      {#if isTemplateFill || step.output_mode === "transcribe_only" || readsInSections || isPowerUser}
        <div class="mt-0.5 flex flex-wrap items-center gap-x-1.5 gap-y-1">
          {#if readsInSections}
            <Badge
              variant="secondary"
              class="bg-accent-dimmer text-accent-stronger h-5 px-1.5 text-xs font-semibold"
            >
              {m.flow_reading_mode_sections()}
            </Badge>
          {/if}
          {#if step.output_mode === "template_fill"}
            <Badge
              variant="secondary"
              class="bg-accent-dimmer text-accent-stronger h-5 px-1.5 text-xs font-semibold"
            >
              {m.flow_template_fill_card_badge()}
            </Badge>
            {#if templateReadiness}
              <Badge
                variant="secondary"
                class="h-5 px-1.5 text-xs font-semibold tabular-nums {templateReadiness.incomplete
                  ? 'bg-warning-dimmer text-warning-stronger'
                  : 'bg-positive-dimmer text-positive-stronger'}"
              >
                {templateReadiness.matched}/{templateReadiness.total || 0}
              </Badge>
            {/if}
          {:else if step.output_mode === "transcribe_only"}
            <Badge
              variant="secondary"
              class="bg-accent-dimmer text-accent-stronger h-5 px-1.5 text-xs font-semibold"
            >
              {m.flow_transcribe_only_title()}
            </Badge>
          {/if}
          {#if isPowerUser}
            <!-- What the step takes in and hands on, in the short Avancerad words. -->
            <span class="text-secondary text-xs whitespace-nowrap tabular-nums"
              >{inputTypeLabel} → {railOutputLabel}</span
            >
          {/if}
        </div>
      {/if}
    </div>
  </button>

  {#if !isPublished}
    <div
      class="flex shrink-0 items-center gap-0.5 opacity-0 transition-opacity duration-(--duration-quick) group-focus-within:opacity-100 group-hover:opacity-100"
      class:opacity-100={isActive || menuOpen}
    >
      <button
        type="button"
        class="text-secondary hover:bg-hover-dimmer focus-visible:ring-ring inline-flex size-7 items-center justify-center rounded-md transition-colors focus-visible:ring-2 focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-40"
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
        class="text-secondary hover:bg-hover-dimmer focus-visible:ring-ring inline-flex size-7 items-center justify-center rounded-md transition-colors focus-visible:ring-2 focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-40"
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
      <DropdownMenu.Root bind:open={menuOpen}>
        <DropdownMenu.Trigger>
          {#snippet child({ props })}
            <button
              {...props}
              type="button"
              class="text-secondary hover:bg-hover-dimmer focus-visible:ring-ring inline-flex size-7 items-center justify-center rounded-md transition-colors focus-visible:ring-2 focus-visible:outline-none"
              title={m.flow_step_more_actions()}
              aria-label={m.flow_step_more_actions()}
            >
              <svg class="size-3.5" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
                <circle cx="3" cy="8" r="1.3" />
                <circle cx="8" cy="8" r="1.3" />
                <circle cx="13" cy="8" r="1.3" />
              </svg>
            </button>
          {/snippet}
        </DropdownMenu.Trigger>
        <DropdownMenu.Content align="end">
          <DropdownMenu.Item variant="destructive" onclick={() => onRemove?.()}>
            <IconTrash class="size-3.5" />
            {m.flow_step_remove()}
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Root>
    </div>
  {/if}
</div>

<style>
  @media (prefers-reduced-motion: no-preference) {
    .step-card-row {
      animation: step-card-in var(--duration-fast) var(--ease-smooth-out);
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
