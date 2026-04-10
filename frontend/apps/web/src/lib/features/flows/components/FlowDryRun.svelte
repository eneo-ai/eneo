<script lang="ts">
  import type { Flow } from "@intric/intric-js";
  import { getFlowUserMode } from "$lib/features/flows/FlowUserMode";
  import { getTemplateFillDryRunIssues } from "$lib/features/flows/templateFillConfig";
  import { Button } from "$lib/components/ui/button/index.js";
  import { IconPlay } from "@intric/icons/play";
  import { m } from "$lib/paraglide/messages";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import * as Card from "$lib/components/ui/card/index.js";

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
  <Button variant="outline" disabled={isRunning || flow.steps.length === 0} onclick={runDryRun}>
    <IconPlay class="size-3.5" />
    {m.flow_dry_run()}
  </Button>

  {#if hasRun}
    <Card.Root class="divide-default order-1 w-full divide-y overflow-hidden">
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
    </Card.Root>

    {#if errorCount === 0}
      <Alert.Root class="bg-positive-dimmer text-positive-stronger order-2 w-full">
        <Alert.Description class="text-xs font-medium">
          &#10003; {m.flow_dry_run_ready()}
        </Alert.Description>
      </Alert.Root>
    {:else}
      <Alert.Root
        variant="destructive"
        class="bg-negative-dimmer text-negative-stronger order-2 w-full"
      >
        <Alert.Description class="text-xs font-medium">
          &#10007; {m.flow_dry_run_issues({ count: String(errorCount) })}
        </Alert.Description>
      </Alert.Root>
    {/if}
  {/if}
</div>
