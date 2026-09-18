<script lang="ts">
  import { Badge } from "$lib/components/ui/badge/index.js";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import IconSparkles from "@lucide/svelte/icons/sparkles";
  import { m } from "$lib/paraglide/messages";
  import {
    getFlowRuntimeErrorMessageByCode,
    getFlowRunErrorMessage,
    getReviewPolicyAffectedStepsFromRunError,
    isReviewPolicyInvalidRunError,
    isReviewPolicyRunErrorStepExact,
    type FlowRunError,
    type FlowReviewPolicyAffectedStep,
    type FlowReviewPolicyErrorStep
  } from "$lib/features/flows/flowRuntimeErrorMapping";

  let {
    error = null,
    errorCode = null,
    message,
    steps = [],
    onrepair = null
  }: {
    error?: FlowRunError | null;
    errorCode?: string | null;
    message: string;
    steps?: readonly FlowReviewPolicyErrorStep[];
    /** Offered when the AI Builder may be asked to repair this step. */
    onrepair?: (() => void) | null;
  } = $props();

  const isReviewPolicyError = $derived(isReviewPolicyInvalidRunError(error));
  const localizedStepErrorMessage = $derived(getFlowRuntimeErrorMessageByCode(errorCode));
  const localizedRunErrorMessage = $derived(getFlowRunErrorMessage(error));
  const localizedErrorMessage = $derived(localizedStepErrorMessage ?? localizedRunErrorMessage);
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
            {#each reviewPolicySteps as step (step.step_order)}
              <li>
                <Badge variant="outline" class="max-w-full border-current text-current">
                  <span class="truncate">{reviewStepLabel(step)}</span>
                </Badge>
              </li>
            {/each}
          </ul>
        </div>
      {/if}
    {:else if localizedErrorMessage}
      <span>{localizedErrorMessage}</span>
    {:else}
      <span>{m.flow_run_error_desc()}</span>
    {/if}

    {#if onrepair}
      <!-- The border keeps the destructive association; the label does not.
           `text-current` inherited the alert's red onto this variant's own
           fill, which is 3.31:1 in dark against a 4.5:1 bar, while the same
           red on the card behind it is 5.05:1. The boundary can carry the
           colour because it only owes 3:1. -->
      <Button
        variant="outline"
        size="sm"
        class="text-foreground w-fit gap-1.5 border-current"
        onclick={onrepair}
      >
        <IconSparkles class="size-3.5" aria-hidden="true" />
        {m.flow_run_error_repair_action()}
      </Button>
    {/if}

    <details class="group">
      <!-- 15px tall with the repair button 7.5px above it, so the 2.5.8
           spacing exception could not rescue it. `w-fit` keeps the target on
           the words rather than spanning the whole card, where a stray click
           would have toggled it. -->
      <summary
        class="flex min-h-[24px] w-fit cursor-pointer items-center text-xs font-medium underline-offset-2 hover:underline focus-visible:ring-2 focus-visible:ring-current focus-visible:outline-none"
      >
        {m.flow_run_error_show_technical_detail()}
      </summary>
      <pre
        class="bg-primary/50 mt-2 max-h-60 overflow-auto rounded-md p-2 font-mono text-xs leading-relaxed break-words whitespace-pre-wrap opacity-80">{message}</pre>
    </details>
  </Alert.Description>
</Alert.Root>
