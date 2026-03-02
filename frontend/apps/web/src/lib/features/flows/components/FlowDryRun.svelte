<script lang="ts">
  import type { Flow } from "@intric/intric-js";
  import { getFlowUserMode } from "$lib/features/flows/FlowUserMode";
  import { Button } from "@intric/ui";
  import { IconPlay } from "@intric/icons/play";
  import { m } from "$lib/paraglide/messages";

  export let flow: Flow;

  const mode = getFlowUserMode();

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
      if (step.step_order === 1 && (step.input_source === "previous_step" || step.input_source === "all_previous_steps")) {
        errors.push("First step cannot use previous step as input source");
      }

      // Validate http sources are not used
      if (step.input_source === "http_get" || step.input_source === "http_post") {
        errors.push("HTTP input sources are not yet supported");
      }

      // Validate variable references
      if (step.input_bindings) {
        const bindingStr = JSON.stringify(step.input_bindings);
        const refRegex = /step_(\d+)/g;
        let match;
        while ((match = refRegex.exec(bindingStr)) !== null) {
          const refOrder = parseInt(match[1], 10);
          if (refOrder >= step.step_order) {
            errors.push(`Forward reference to step ${refOrder} (current step is ${step.step_order})`);
          }
        }
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
</script>

<div class="flex items-center gap-2">
  <Button
    variant="outlined"
    disabled={isRunning || flow.steps.length === 0}
    on:click={runDryRun}
  >
    <IconPlay class="size-3.5" />
    {m.flow_dry_run()}
  </Button>

  {#if hasRun}
    {#if errorCount === 0}
      <span class="text-positive text-xs font-medium">{m.flow_dry_run_ready()}</span>
    {:else}
      <span class="text-xs font-medium text-red-600">{m.flow_dry_run_issues({ count: String(errorCount) })}</span>
    {/if}
  {/if}
</div>

{#if hasRun && $mode === "power_user"}
  <div class="mt-2 flex flex-col gap-1">
    {#each dryRunResults as result}
      <div
        class="flex items-center gap-2 rounded px-2 py-1 text-xs"
        class:bg-green-50={result.valid}
        class:bg-red-50={!result.valid}
      >
        <span class="font-medium">Step {result.stepOrder}</span>
        {#if result.valid}
          <span class="text-green-600">&#10003;</span>
        {:else}
          <span class="text-red-600">&#10007; {result.errors.join(", ")}</span>
        {/if}
      </div>
    {/each}
  </div>
{/if}
