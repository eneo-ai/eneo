<script lang="ts">
  import { BUILDER_COLUMN } from "./builderColumns";
  import { FOLD_MIN_RUN } from "./builderStepRuns";
  import { Button } from "$lib/components/ui/button/index.js";
  import { m } from "$lib/paraglide/messages";
  import { Skeleton } from "$lib/components/ui/skeleton/index.js";
  import type { AIBuilderStatus, AIBuilderStepChoice } from "./protocol";

  interface Props {
    status: AIBuilderStatus | null;
    /** Create drafts a new flow; edit changes an existing one. */
    mode?: "create" | "edit";
    /** Edit: the flow's own steps, shown by name instead of placeholders. */
    flowSteps?: AIBuilderStepChoice[] | null;
    /** Edit scoped to one step: the step being changed; the others stay as they are. */
    targetStepNumber?: number | null;
    /** Number of skeleton rows: the last known plan length, or a typical five. */
    stepCount?: number;
    /** One-line recap of the confirmed task ("Ljud → PDF-dokument"). */
    confirmedLine?: string | null;
    onshowconfirmation?: () => void;
  }

  let {
    status,
    mode = "create",
    flowSteps = null,
    targetStepNumber = null,
    stepCount = 5,
    confirmedLine = null,
    onshowconfirmation
  }: Props = $props();

  const isEdit = $derived(mode === "edit");
  // An edit drafts against the flow the reader knows; five generic rows would
  // suggest a new flow of a size nobody asked for.
  const knownSteps = $derived(
    isEdit && flowSteps && flowSteps.length > 0
      ? [...flowSteps].sort((a, b) => a.order - b.order)
      : null
  );
  // A long flow keeps the rows that matter while Eneo works: a one-step change
  // shows its step and the steps around it, a whole-flow change its first
  // steps; the rest reads as one row.
  const WHOLE_FLOW_ROWS = 6;
  type PlanningRow =
    | { kind: "step"; step: AIBuilderStepChoice }
    | { kind: "gap"; first: number; last: number; unchanged: boolean };
  const planningRows = $derived.by((): PlanningRow[] => {
    if (!knownSteps) return [];
    const rows: PlanningRow[] = [];
    let run: AIBuilderStepChoice[] = [];
    const endRun = (unchanged: boolean) => {
      if (run.length >= FOLD_MIN_RUN) {
        rows.push({ kind: "gap", first: run[0].order, last: run[run.length - 1].order, unchanged });
      } else {
        rows.push(...run.map((step) => ({ kind: "step" as const, step })));
      }
      run = [];
    };
    knownSteps.forEach((step, index) => {
      const shown =
        targetStepNumber === null
          ? index < WHOLE_FLOW_ROWS || knownSteps.length <= WHOLE_FLOW_ROWS + 1
          : Math.abs(step.order - targetStepNumber) <= 1;
      if (shown) {
        endRun(targetStepNumber !== null);
        rows.push({ kind: "step", step });
      } else {
        run.push(step);
      }
    });
    endRun(targetStepNumber !== null);
    return rows;
  });

  // Planning usually finishes within a minute; past that the wait deserves a
  // calm word so nobody wonders whether the page froze. Real time, not progress.
  const SLOW_AFTER_MS = 45_000;
  let slow = $state(false);
  $effect(() => {
    slow = false;
    const timer = setTimeout(() => (slow = true), SLOW_AFTER_MS);
    return () => clearTimeout(timer);
  });

  // Only backend-reported phases are narrated; nothing here simulates progress.
  const narration = $derived.by(() => {
    switch (status) {
      case "architecture_committed":
      case "architecture_revised":
      case "drafting_flow":
        return m.ai_builder_build_narration_steps();
      case "checking_flow":
      case "repairing":
        return m.ai_builder_build_narration_checking();
      default:
        return m.ai_builder_build_narration_reading();
    }
  });
</script>

<div
  class="flex min-h-full shrink-0 justify-center px-7 pt-6 pb-12 max-lg:px-5 max-md:px-4 max-sm:pt-4"
>
  <div class="w-full {BUILDER_COLUMN.sheet}">
    {#if confirmedLine}
      <div
        class="border-default bg-primary mb-4 flex flex-wrap items-center gap-2.5 rounded-[10px] border px-3.5 py-2.5"
      >
        <span class="text-secondary text-[0.8125rem]">{m.ai_builder_build_confirmed_label()}</span>
        <span class="text-primary text-[0.8125rem] font-semibold">{confirmedLine}</span>
        {#if onshowconfirmation}
          <Button
            variant="link"
            size="xs"
            class="text-accent-stronger ml-auto h-auto p-0 text-[0.8125rem] font-semibold"
            onclick={onshowconfirmation}
          >
            {m.ai_builder_build_show_confirmation()}
          </Button>
        {/if}
      </div>
    {/if}
    <div class="border-default bg-primary overflow-hidden rounded-xl border">
      <div class="px-5 pt-[1.125rem] pb-4 max-sm:px-4">
        <h2
          class="text-primary text-[1.0625rem] font-bold tracking-[-0.015em]"
          tabindex="-1"
          data-builder-screen-heading
        >
          {isEdit ? m.ai_builder_rail_planning_edit() : m.ai_builder_build_title()}
        </h2>
        <p class="text-secondary mt-1 text-[0.8125rem] text-pretty">
          {isEdit ? m.ai_builder_build_subtitle_edit() : m.ai_builder_build_subtitle()}
        </p>
        <p class="text-secondary mt-2.5 text-[0.8125rem]" role="status" aria-live="polite">
          <!-- Each stage fades in rather than snapping: the reader sees the
               work move on, not the text jump. -->
          {#key narration}<span class="narration-step">{narration} …</span>{/key}
        </p>
        {#if slow}
          <p class="text-warning-stronger mt-2 text-[0.8125rem]" role="status">
            {m.ai_builder_build_slow_note()}
          </p>
        {/if}
      </div>
      <div
        class="border-dimmer flex flex-col gap-2 border-t px-5 pt-4 pb-5 max-sm:px-4"
        aria-hidden="true"
      >
        {#if knownSteps}
          {#each planningRows as row (row.kind === "gap" ? `gap-${row.first}` : row.step.id)}
            {#if row.kind === "gap"}
              <div
                class="border-default text-secondary flex min-h-11 items-center rounded-[10px] border border-dashed px-3 py-2.5 text-xs"
              >
                {row.unchanged
                  ? m.ai_builder_diagram_gap({ first: String(row.first), last: String(row.last) })
                  : m.ai_builder_build_more_steps({
                      first: String(row.first),
                      last: String(row.last)
                    })}
              </div>
            {:else}
              {@const step = row.step}
              {@const changing = targetStepNumber === null || targetStepNumber === step.order}
              <div
                class="flex min-h-[3.625rem] items-center gap-3 rounded-[10px] border px-3 py-3 {changing
                  ? 'border-accent-default/30 bg-accent-dimmer/40'
                  : 'border-dimmer bg-primary'}"
              >
                <span
                  class="inline-flex size-6 shrink-0 items-center justify-center rounded-md text-xs font-bold {changing
                    ? 'bg-accent-dimmer text-accent-stronger'
                    : 'bg-secondary text-secondary'}"
                >
                  {step.order}
                </span>
                <div class="flex min-w-0 flex-1 flex-col gap-0.5">
                  <span class="text-primary truncate text-[0.8125rem] font-semibold">
                    {step.name}
                  </span>
                  {#if step.reads}
                    <span class="text-secondary truncate text-xs">{step.reads}</span>
                  {/if}
                  {#if changing}
                    <Skeleton class="bg-tertiary mt-1.5 h-[0.5625rem] w-2/5 rounded" />
                  {/if}
                </div>
                <span
                  class="inline-flex h-[1.3125rem] shrink-0 items-center rounded-full px-2 text-xs font-semibold {changing
                    ? 'bg-accent-dimmer text-accent-stronger'
                    : 'bg-secondary text-secondary'}"
                >
                  {changing ? m.ai_builder_node_changes() : m.ai_builder_node_unchanged()}
                </span>
              </div>
            {/if}
          {/each}
        {:else}
          {#each Array.from({ length: Math.max(1, Math.min(stepCount, 12)) }) as _, i (i)}
            <div
              class="border-dimmer bg-secondary flex min-h-[3.625rem] items-center gap-3 rounded-[10px] border px-3 py-3"
            >
              <span
                class="bg-tertiary text-secondary inline-flex size-6 shrink-0 items-center justify-center rounded-md text-xs font-bold"
              >
                {i + 1}
              </span>
              <div class="flex flex-1 flex-col gap-[0.4375rem]">
                <Skeleton
                  class="bg-tertiary h-[0.6875rem] rounded"
                  style="width: {[62, 74, 58, 68, 48][i % 5]}%"
                />
                <Skeleton
                  class="bg-tertiary h-[0.5625rem] rounded"
                  style="width: {[38, 44, 34, 40, 30][i % 5]}%"
                />
              </div>
            </div>
          {/each}
        {/if}
      </div>
      <div class="border-default bg-secondary border-t px-5 py-3 max-sm:px-4">
        <p class="text-secondary text-[0.8125rem]">
          {isEdit ? m.ai_builder_build_footer_edit() : m.ai_builder_build_footer()}
        </p>
      </div>
    </div>
  </div>
</div>

<style lang="postcss">
  .narration-step {
    display: inline-block;
    animation: narration-in var(--duration-fast) var(--ease-smooth-out);
  }
  @keyframes narration-in {
    from {
      opacity: 0;
      transform: translateY(var(--distance-micro));
    }
    to {
      opacity: 1;
      transform: none;
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .narration-step {
      animation: none;
    }
  }
</style>
