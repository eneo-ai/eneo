<script lang="ts">
  import type { Flow } from "@intric/intric-js";

  // Stands in for the heavy xyflow FlowGraph in jsdom integration tests so the
  // canvas state machine and the draft adapter can be asserted without a real
  // graph render. Exposes the props the canvas wiring depends on.
  let { flow, direction }: { flow: Flow; direction?: "LR" | "TB" } = $props();

  const allStepsAreDrafts = $derived(flow.steps.every((step) => step.assistant_id === ""));
</script>

<div
  data-testid="flow-graph"
  data-steps={flow.steps.length}
  data-direction={direction}
  data-all-draft={allStepsAreDrafts}
></div>
