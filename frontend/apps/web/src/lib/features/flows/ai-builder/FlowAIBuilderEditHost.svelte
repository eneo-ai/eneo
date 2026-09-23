<script lang="ts">
  import { onDestroy, tick, untrack } from "svelte";

  import type { Eneo } from "@eneo/eneo-js";

  import FlowAIBuilder from "./FlowAIBuilder.svelte";
  import { initAIBuilderService } from "./FlowAIBuilderService.svelte.ts";
  import type {
    AIBuilderCarriedRequest,
    AIBuilderSavedFlowStepScope,
    AIBuilderStepChoice
  } from "./protocol";
  import type { FlowRunFailureRepairTarget } from "$lib/features/flows/flowRunFailureRepair";

  interface Props {
    eneo: Eneo;
    spaceId: string;
    flowId: string;
    onapplied?: (detail: {
      flow_id: string;
      focusStepIndex: number | null;
    }) => void | Promise<void>;
    /** The flow is published: the Builder says so before an apply is refused. */
    flowIsPublished?: boolean;
    /** Whether the user may review the published version's runs. */
    canReview?: boolean;
    /** The flow's saved steps, for the composer's step picker. */
    stepChoices?: AIBuilderStepChoice[] | null;
  }

  let {
    eneo,
    spaceId,
    flowId,
    onapplied,
    flowIsPublished = false,
    canReview = false,
    stepChoices = null
  }: Props = $props();

  const service = untrack(() => initAIBuilderService(eneo, spaceId, flowId));
  let builder = $state<FlowAIBuilder | undefined>();

  /** A change is being prepared: answers given, or a plan already proposed.
   *  The flow header uses it to stop competing with the change's own action. */
  export function hasChangeInProgress(): boolean {
    return service.hasOpenWork;
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

  /** Hand a failed step of a run to the Builder (from the run history). */
  export async function launchFailureRepair(target: FlowRunFailureRepairTarget) {
    await tick();
    await builder?.launchFailureRepair(target);
  }

  /** Bring a request from outside the Builder (a package's change request)
   *  into the composer; it is sent only once a step is chosen. */
  export async function carryRequest(request: AIBuilderCarriedRequest) {
    await tick();
    builder?.carryRequest(request);
  }

  onDestroy(() => {
    service.destroy();
  });
</script>

<FlowAIBuilder
  bind:this={builder}
  targetKind="edit"
  {canReview}
  {stepChoices}
  onapplied={(detail) => onapplied?.(detail)}
  {flowIsPublished}
/>
