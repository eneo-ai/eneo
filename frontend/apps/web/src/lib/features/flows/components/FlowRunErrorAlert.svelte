<script lang="ts">
  import { Badge } from "$lib/components/ui/badge/index.js";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { m } from "$lib/paraglide/messages";
  import {
    getReviewPolicyAffectedStepsFromRunError,
    isReviewPolicyInvalidRunError,
    isReviewPolicyRunErrorStepExact,
    type FlowRunError,
    type FlowReviewPolicyAffectedStep,
    type FlowReviewPolicyErrorStep
  } from "$lib/features/flows/flowRuntimeErrorMapping";

  let {
    error = null,
    message,
    steps = []
  }: {
    error?: FlowRunError | null;
    message: string;
    steps?: readonly FlowReviewPolicyErrorStep[];
  } = $props();

  const isReviewPolicyError = $derived(isReviewPolicyInvalidRunError(error));
  const reviewPolicySteps = $derived(getReviewPolicyAffectedStepsFromRunError(error, steps));
  const hasExactReviewPolicyStep = $derived(isReviewPolicyRunErrorStepExact(error));
  const affectedStepsLabel = $derived(
    hasExactReviewPolicyStep
      ? m.flow_run_error_affected_step()
      : m.flow_run_error_possible_affected_steps()
  );

  function reviewStepLabel(step: FlowReviewPolicyAffectedStep): string {
    return step.user_description
      ? m.flow_run_error_step_label_with_name({
          step: String(step.step_order),
          name: step.user_description
        })
      : m.flow_run_error_step_label({ step: String(step.step_order) });
  }
</script>

<Alert.Root variant="destructive">
  <Alert.Title class="text-xs font-semibold">{m.flow_run_error()}</Alert.Title>
  <Alert.Description class="flex flex-col gap-2 text-xs">
    {#if isReviewPolicyError}
      <span>{m.flow_run_error_review_policy_invalid_summary()}</span>
      <span>{m.flow_run_error_review_policy_invalid_action()}</span>
      {#if reviewPolicySteps.length > 0}
        <div class="flex flex-col gap-1">
          <span class="font-medium">{affectedStepsLabel}</span>
          <ul class="flex flex-wrap gap-1.5" aria-label={affectedStepsLabel}>
            {#each reviewPolicySteps as step}
              <li>
                <Badge variant="outline" class="max-w-full border-current text-current">
                  <span class="truncate">{reviewStepLabel(step)}</span>
                </Badge>
              </li>
            {/each}
          </ul>
        </div>
      {/if}
    {:else}
      <span>{m.flow_run_error_desc()}</span>
    {/if}

    <details class="group">
      <summary
        class="cursor-pointer text-xs font-medium underline-offset-2 hover:underline focus-visible:ring-2 focus-visible:ring-current focus-visible:outline-none"
      >
        {m.flow_run_error_show_technical_detail()}
      </summary>
      <pre
        class="bg-primary/50 mt-2 max-h-60 overflow-auto rounded-md p-2 font-mono text-xs leading-relaxed break-words whitespace-pre-wrap opacity-80">{message}</pre>
    </details>
  </Alert.Description>
</Alert.Root>
