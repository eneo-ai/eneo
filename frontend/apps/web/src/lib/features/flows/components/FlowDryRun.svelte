<script lang="ts">
  import type { Flow } from "@intric/intric-js";
  import { getFlowUserMode } from "$lib/features/flows/FlowUserMode";
  import { getTemplateFillDryRunIssues } from "$lib/features/flows/templateFillConfig";
  import { Button } from "$lib/components/ui/button/index.js";
  import { IconPlay } from "@intric/icons/play";
  import { m } from "$lib/paraglide/messages";
  import * as Card from "$lib/components/ui/card/index.js";
  import { CheckCircle2, AlertCircle, Loader2 } from "lucide-svelte";

  let {
    flow
  }: {
    flow: Flow;
  } = $props();

  const mode = getFlowUserMode();

  const INPUT_SOURCE_LABELS: Record<string, () => string> = {
    flow_input: () => m.flow_input_source_flow_input(),
    previous_step: () => m.flow_input_source_previous_step(),
    all_previous_steps: () => m.flow_input_source_all_previous_steps(),
    http_get: () => m.flow_input_source_http_get(),
    http_post: () => m.flow_input_source_http_post()
  };

  type StepValidation = {
    stepOrder: number;
    stepId: string | null;
    valid: boolean;
    errors: string[];
  };

  let dryRunResults: StepValidation[] = $state([]);
  let isRunning = $state(false);
  let hasRun = $state(false);

  async function runDryRun() {
    isRunning = true;
    dryRunResults = [];

    const results: StepValidation[] = [];

    for (const step of flow.steps) {
      const errors: string[] = [];

      if (!step.assistant_id) {
        errors.push("Missing assistant");
      }

      if (
        step.step_order === 1 &&
        (step.input_source === "previous_step" || step.input_source === "all_previous_steps")
      ) {
        errors.push("First step cannot use previous step as input source");
      }

      if (step.input_bindings) {
        const bindingStr = JSON.stringify(step.input_bindings);
        const refRegex = /step_(\d+)/g;
        let match;
        while ((match = refRegex.exec(bindingStr)) !== null) {
          const refOrder = parseInt(match[1], 10);
          if (refOrder >= step.step_order) {
            errors.push(
              `Forward reference to step ${refOrder} (current step is ${step.step_order})`
            );
          }
        }
      }

      if (step.output_mode === "template_fill") {
        errors.push(...getTemplateFillDryRunIssues({ step }));
      }

      results.push({
        stepOrder: step.step_order,
        stepId: step.id ?? null,
        valid: errors.length === 0,
        errors
      });
    }

    dryRunResults = results;
    isRunning = false;
    hasRun = true;
  }

  const errorCount = $derived(dryRunResults.filter((r) => !r.valid).length);

  function getStepByOrder(order: number) {
    return flow.steps.find((s) => s.step_order === order);
  }
</script>

<div class="contents">
  <Button
    variant="default"
    disabled={isRunning || flow.steps.length === 0}
    onclick={runDryRun}
    class="h-9 gap-2"
  >
    {#if isRunning}
      <Loader2 class="size-3.5 animate-spin" aria-hidden="true" />
    {:else}
      <IconPlay class="size-3.5" aria-hidden="true" />
    {/if}
    {m.flow_dry_run()}
  </Button>

  {#if hasRun}
    <Card.Root
      class="divide-default border-default/80 bg-secondary/20 order-1 w-full divide-y overflow-hidden rounded-xl"
    >
      {#each dryRunResults as result, i (result.stepId ?? result.stepOrder)}
        {@const step = getStepByOrder(result.stepOrder)}
        <div
          class="dry-run-row flex items-start justify-between gap-3 bg-transparent px-4 py-3"
          style:animation-delay="{i * 35}ms"
          style:animation-fill-mode="both"
        >
          <div class="flex min-w-0 items-start gap-3">
            <span
              class="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-lg text-xs font-semibold tabular-nums {result.valid
                ? 'bg-positive-dimmer text-positive-stronger'
                : 'bg-negative-dimmer text-negative-stronger'}"
              aria-hidden="true"
            >
              {result.stepOrder}
            </span>
            <div class="flex min-w-0 flex-col gap-1">
              <span class="text-primary truncate text-sm leading-snug font-medium">
                {step?.user_description ||
                  m.flow_step_fallback_label({ order: String(result.stepOrder) })}
              </span>
              <span
                class="text-secondary flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-[11px] tracking-[0.015em]"
              >
                <span class="truncate">{step?.input_type ?? "text"}</span>
                <span class="text-muted" aria-hidden="true">&rarr;</span>
                <span class="truncate">{step?.output_type ?? "text"}</span>
                <span class="text-muted" aria-hidden="true">&middot;</span>
                <span class="truncate">
                  {INPUT_SOURCE_LABELS[step?.input_source ?? ""]?.() ?? step?.input_source ?? ""}
                </span>
              </span>
              {#if !result.valid && $mode === "power_user"}
                {#each result.errors as error (`${result.stepOrder}:${error}`)}
                  <span class="text-negative-stronger mt-0.5 text-xs leading-snug">{error}</span>
                {/each}
              {/if}
            </div>
          </div>
          <span
            class="mt-0.5 flex size-6 shrink-0 items-center justify-center"
            aria-label={result.valid
              ? m.flow_dry_run_ready()
              : m.flow_dry_run_issues({ count: "1" })}
          >
            {#if result.valid}
              <CheckCircle2 class="text-positive-stronger size-4" aria-hidden="true" />
            {:else}
              <AlertCircle class="text-negative-stronger size-4" aria-hidden="true" />
            {/if}
          </span>
        </div>
      {/each}
    </Card.Root>

    {#if errorCount === 0}
      <div
        class="border-positive-default/30 bg-positive-dimmer/70 text-positive-stronger order-2 flex w-full items-center gap-2 rounded-xl border px-3.5 py-2.5"
        role="status"
      >
        <CheckCircle2 class="size-4 shrink-0" aria-hidden="true" />
        <span class="text-[13px] font-medium tracking-[-0.005em]">{m.flow_dry_run_ready()}</span>
      </div>
    {:else}
      <div
        class="border-negative-default/30 bg-negative-dimmer/70 text-negative-stronger order-2 flex w-full items-center gap-2 rounded-xl border px-3.5 py-2.5"
        role="alert"
      >
        <AlertCircle class="size-4 shrink-0" aria-hidden="true" />
        <span class="text-[13px] font-medium tracking-[-0.005em]"
          >{errorCount === 1
            ? m.flow_dry_run_issues({ count: "1" })
            : m.flow_dry_run_issues_plural({ count: String(errorCount) })}</span
        >
      </div>
    {/if}
  {/if}
</div>

<style>
  @media (prefers-reduced-motion: no-preference) {
    .dry-run-row {
      animation: dry-run-row-in 260ms cubic-bezier(0.22, 1, 0.36, 1);
    }
  }

  @keyframes dry-run-row-in {
    from {
      opacity: 0;
      transform: translateY(4px);
    }
    to {
      opacity: 1;
      transform: translateY(0);
    }
  }
</style>
