<script lang="ts">
  import { Badge } from "$lib/components/ui/badge/index.js";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { m } from "$lib/paraglide/messages";
  import {
    FLOW_API_ERROR_CODE,
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
    steps = []
  }: {
    error?: FlowRunError | null;
    errorCode?: string | null;
    message: string;
    steps?: readonly FlowReviewPolicyErrorStep[];
  } = $props();

  const isReviewPolicyError = $derived(isReviewPolicyInvalidRunError(error));
  const localizedStepErrorMessage = $derived(getFlowRuntimeErrorMessageByCode(errorCode));
  const localizedRunErrorMessage = $derived(getFlowRunErrorMessage(error));
  // The run error is about this alert's failure unless the step failed with a
  // code of its own. Its sentence then comes first: it is chosen with facts
  // the bare code lacks, such as which level refused a tool.
  const runErrorIsThisFailure = $derived(
    error != null && (errorCode === null || errorCode === error.code)
  );
  const localizedErrorMessage = $derived(
    runErrorIsThisFailure
      ? (localizedRunErrorMessage ?? localizedStepErrorMessage)
      : (localizedStepErrorMessage ?? localizedRunErrorMessage)
  );
  const runErrorFacts = $derived(runErrorIsThisFailure ? (error?.details ?? null) : null);
  // A step that ran out of its time budget reports where it was and what it
  // had finished; those facts replace the generic catalog sentence so the
  // provider caveat is only shown when a request really was interrupted.
  const stepTimeoutFacts = $derived(
    error?.code === FLOW_API_ERROR_CODE.STEP_TIMEOUT ? runErrorFacts : null
  );
  const toolErrorText = $derived(runErrorFacts?.tool_error_text || null);
  const stepTimeoutPhaseLabels: Record<string, () => string> = {
    input_resolution: () => m.flow_run_error_phase_input_resolution(),
    transcription: () => m.flow_run_error_phase_transcription(),
    retrieval: () => m.flow_run_error_phase_retrieval(),
    provider_request: () => m.flow_run_error_phase_provider_request(),
    mapped_item: () => m.flow_run_error_phase_mapped_item(),
    finalization: () => m.flow_run_error_phase_finalization(),
    step_execution: () => m.flow_run_error_phase_step_execution()
  };
  const stepTimeoutPhaseLabel = $derived(
    stepTimeoutFacts?.phase ? stepTimeoutPhaseLabels[stepTimeoutFacts.phase]?.() : undefined
  );
  const stepTimeoutProgress = $derived(
    stepTimeoutFacts &&
      typeof stepTimeoutFacts.completed_items === "number" &&
      typeof stepTimeoutFacts.total_items === "number"
      ? m.flow_run_error_step_timeout_progress_value({
          completed: String(stepTimeoutFacts.completed_items),
          total: String(stepTimeoutFacts.total_items)
        })
      : null
  );
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
  <Alert.Title class="text-xs font-semibold">
    {isReviewPolicyError ? m.flow_run_error_not_started() : m.flow_run_error()}
  </Alert.Title>
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
    {:else if stepTimeoutFacts}
      <span>{m.flow_run_error_step_timeout_summary()}</span>
      {#if stepTimeoutPhaseLabel || stepTimeoutProgress}
        <dl class="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
          {#if stepTimeoutPhaseLabel}
            <dt class="font-medium">{m.flow_run_error_step_timeout_phase()}</dt>
            <dd>{stepTimeoutPhaseLabel}</dd>
          {/if}
          {#if stepTimeoutProgress}
            <dt class="font-medium">{m.flow_run_error_step_timeout_progress()}</dt>
            <dd class="tabular-nums">{stepTimeoutProgress}</dd>
          {/if}
        </dl>
      {/if}
      {#if stepTimeoutFacts.provider_work_may_have_completed}
        <span>{m.flow_run_error_step_timeout_provider_unknown()}</span>
      {/if}
      <span>{m.flow_run_error_step_timeout_action()}</span>
    {:else if localizedErrorMessage}
      <span>{localizedErrorMessage}</span>
    {:else}
      <span>{m.flow_run_error_desc()}</span>
    {/if}

    {#if toolErrorText}
      <div class="flex flex-col gap-1">
        <span class="font-medium">{m.flow_run_error_tool_text_label()}</span>
        <span class="break-words whitespace-pre-wrap">{toolErrorText}</span>
      </div>
    {/if}

    <details class="group">
      <!-- `w-fit` keeps the target on the words rather than spanning the
           whole card, where a stray click would have toggled it. -->
      <summary
        class="flex min-h-[24px] w-fit cursor-pointer items-center text-xs font-medium underline-offset-2 hover:underline focus-visible:ring-2 focus-visible:ring-current focus-visible:outline-none"
      >
        {m.flow_run_error_show_technical_detail()}
      </summary>
      <pre
        class="bg-primary/50 text-foreground mt-2 max-h-60 overflow-auto rounded-md p-2 font-mono text-xs leading-relaxed break-words whitespace-pre-wrap">{message}</pre>
    </details>
  </Alert.Description>
</Alert.Root>
