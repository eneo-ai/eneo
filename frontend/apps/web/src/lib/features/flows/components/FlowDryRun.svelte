<script lang="ts">
  import type { Flow } from "@intric/intric-js";
  import { getFlowUserMode } from "$lib/features/flows/FlowUserMode";
  import { getTemplateFillDryRunIssues } from "$lib/features/flows/templateFillConfig";
  import { Button } from "@intric/ui";
  import { IconPlay } from "@intric/icons/play";
  import { m } from "$lib/paraglide/messages";

  export let flow: Flow;

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

  let dryRunResults: StepValidation[] = [];
  let isRunning = false;
  let hasRun = false;

  async function runDryRun() {
    isRunning = true;
    dryRunResults = [];

    // Compile-time validation — no backend call needed for basic validation
    const results: StepValidation[] = [];

    for (const step of flow.steps) {
      const errors: string[] = [];

      // Validate assistant_id is set
      if (!step.assistant_id) {
        errors.push("Missing assistant");
      }

      // Validate step 1 doesn't use previous_step
      if (
        step.step_order === 1 &&
        (step.input_source === "previous_step" || step.input_source === "all_previous_steps")
      ) {
        errors.push("First step cannot use previous step as input source");
      }

      // Validate variable references
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

  $: errorCount = dryRunResults.filter((r) => !r.valid).length;

  function getStepByOrder(order: number) {
    return flow.steps.find((s) => s.step_order === order);
  }
</script>

<div class="contents">
  <Button variant="outlined" disabled={isRunning || flow.steps.length === 0} on:click={runDryRun}>
    <IconPlay class="size-3.5" />
    {m.flow_dry_run()}
  </Button>

  {#if hasRun}
    <div
      class="border-default divide-default order-1 w-full divide-y overflow-hidden rounded-lg border"
    >
      {#each dryRunResults as result (result.stepId ?? result.stepOrder)}
        {@const step = getStepByOrder(result.stepOrder)}
        <div class="flex items-start justify-between gap-3 px-4 py-3">
          <div class="flex min-w-0 items-start gap-3">
            <span
              class="bg-hover-default mt-0.5 flex size-6 shrink-0 items-center justify-center rounded text-xs font-bold tabular-nums"
            >
              {result.stepOrder}
            </span>
            <div class="flex min-w-0 flex-col gap-0.5">
              <span class="text-sm font-medium">
                {step?.user_description ||
                  m.flow_step_fallback_label({ order: String(result.stepOrder) })}
              </span>
              <span class="text-secondary truncate text-xs">
                {step?.input_type ?? "text"} &rarr; {step?.output_type ?? "text"}
                <span class="text-tertiary">&middot;</span>
                {INPUT_SOURCE_LABELS[step?.input_source ?? ""]?.() ?? step?.input_source ?? ""}
              </span>
              {#if !result.valid && $mode === "power_user"}
                {#each result.errors as error (`${result.stepOrder}:${error}`)}
                  <span class="text-negative-stronger text-xs">{error}</span>
                {/each}
              {/if}
            </div>
          </div>
          <span
            class="mt-1 shrink-0 text-sm font-medium"
            class:text-positive-stronger={result.valid}
            class:text-negative-stronger={!result.valid}
          >
            {#if result.valid}&#10003;{:else}&#10007;{/if}
          </span>
        </div>
      {/each}
    </div>

    <div
      class="order-2 w-full rounded-lg px-3 py-2 text-xs font-medium"
      class:bg-positive-dimmer={errorCount === 0}
      class:text-positive-stronger={errorCount === 0}
      class:bg-negative-dimmer={errorCount > 0}
      class:text-negative-stronger={errorCount > 0}
    >
      {#if errorCount === 0}
        &#10003; {m.flow_dry_run_ready()}
      {:else}
        &#10007; {m.flow_dry_run_issues({ count: String(errorCount) })}
      {/if}
    </div>
  {/if}
</div>
