<script lang="ts">
  import { onDestroy, tick, untrack } from "svelte";

  import type { Eneo } from "@eneo/eneo-js";

  import FlowAIBuilder from "./FlowAIBuilder.svelte";
  import { initAIBuilderService } from "./FlowAIBuilderService.svelte.ts";
  import type { AIBuilderSavedFlowStepScope } from "./protocol";

  interface Props {
    eneo: Eneo;
    spaceId: string;
    flowId: string;
    onapplied?: (detail: { flow_id: string; focusStepIndex: number | null }) => void;
    /** Whether the user may review the published version's runs. */
    canReview?: boolean;
  }

  let { eneo, spaceId, flowId, onapplied, canReview = false }: Props = $props();

  const service = untrack(() => initAIBuilderService(eneo, spaceId, flowId));
  let builder = $state<FlowAIBuilder | undefined>();

  /** A change is being prepared: answers given, or a plan already proposed.
   *  The flow header uses it to stop competing with the change's own action. */
  export function hasChangeInProgress(): boolean {
    return service.messages.length > 0 || service.currentPlan !== null;
  }

  export async function openReview() {
    await tick();
    await builder?.openReview();
  }

  export async function focusSavedFlowStep(scope: AIBuilderSavedFlowStepScope) {
    // The host and its lazily rendered Builder child bind in separate update
    // flushes when the user opens the tab for the first time.
    await tick();
    await builder?.focusSavedFlowStep(scope);
  }

  onDestroy(() => {
    service.destroy();
  });
</script>

<FlowAIBuilder
  bind:this={builder}
  targetKind="edit"
  {canReview}
  onapplied={(detail) => onapplied?.(detail)}
/>
