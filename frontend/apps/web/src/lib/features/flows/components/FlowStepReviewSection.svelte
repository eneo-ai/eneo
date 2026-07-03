<script lang="ts">
  import FlowStepSection from "$lib/features/flows/components/FlowStepSection.svelte";
  import type { FlowStep } from "@eneo/eneo-js";
  import { Settings } from "$lib/components/layout";
  import * as Select from "$lib/components/ui/select/index.js";
  import { m } from "$lib/paraglide/messages";
  import {
    FLOW_STEP_REVIEW_MODE_CHOICES,
    getFlowStepReviewModeChoice,
    isFlowStepReviewPolicySupported,
    parseFlowStepReviewModeChoice,
    type FlowStepReviewModeChoice
  } from "$lib/features/flows/flowStepReviewPolicy";

  let {
    step,
    isPublished,
    onReviewModeChange
  }: {
    step: FlowStep;
    isPublished: boolean;
    onReviewModeChange?: (detail: { value: FlowStepReviewModeChoice }) => void;
  } = $props();

  const reviewMode = $derived(getFlowStepReviewModeChoice(step));
  const reviewSupported = $derived(isFlowStepReviewPolicySupported(step));
  const reviewModeLabel = $derived(getReviewModeLabel(reviewMode));

  function getReviewModeLabel(mode: FlowStepReviewModeChoice): string {
    switch (mode) {
      case "view":
        return m.flow_step_review_policy_view();
      case "edit":
        return m.flow_step_review_policy_edit();
      case "none":
      default:
        return m.flow_step_review_policy_none();
    }
  }
</script>

<FlowStepSection title={m.flow_step_review_section()}>
  <Settings.Row title={m.flow_step_review_policy()} description={m.flow_step_review_policy_desc()}>
    <div class="flex flex-col gap-2">
      <Select.Root
        type="single"
        value={reviewMode}
        disabled={isPublished || !reviewSupported}
        onValueChange={(value) =>
          onReviewModeChange?.({
            value: parseFlowStepReviewModeChoice(value ?? "none")
          })}
      >
        <Select.Trigger class="w-full" aria-label={m.flow_step_review_policy()}>
          {reviewModeLabel}
        </Select.Trigger>
        <Select.Content>
          <Select.Group>
            {#each FLOW_STEP_REVIEW_MODE_CHOICES as mode (mode)}
              <Select.Item value={mode} label={getReviewModeLabel(mode)}>
                {getReviewModeLabel(mode)}
              </Select.Item>
            {/each}
          </Select.Group>
        </Select.Content>
      </Select.Root>
      <p
        class={reviewSupported
          ? "text-muted text-xs leading-relaxed"
          : "text-warning-stronger text-xs leading-relaxed"}
        aria-live="polite"
      >
        {reviewSupported
          ? m.flow_step_review_policy_help()
          : m.flow_step_review_policy_outbound_disabled()}
      </p>
    </div>
  </Settings.Row>
</FlowStepSection>
