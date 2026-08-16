<script lang="ts">
  import FlowAIBuilderRequirementsSummary from "./FlowAIBuilderRequirementsSummary.svelte";
  import type { AIBuilderStepScopePresentation, RequirementsSummary } from "./protocol";

  interface Props {
    summary: RequirementsSummary;
    userRequest: string | null;
    savedFlowStepScope: AIBuilderStepScopePresentation | null;
    confirmed: boolean;
    disabled?: boolean;
    onconfirm: () => void;
    onchange: () => void;
  }

  let {
    summary,
    userRequest,
    savedFlowStepScope,
    confirmed,
    disabled = false,
    onconfirm,
    onchange
  }: Props = $props();
</script>

<div class="flex justify-center px-7 pt-6 pb-10 max-sm:px-3 max-sm:pt-4">
  <div class="w-full max-w-[43.75rem]">
    <FlowAIBuilderRequirementsSummary
      {summary}
      {userRequest}
      {savedFlowStepScope}
      {confirmed}
      active={true}
      {disabled}
      onconfirm={confirmed ? undefined : onconfirm}
      onchange={confirmed ? undefined : onchange}
    />
  </div>
</div>
