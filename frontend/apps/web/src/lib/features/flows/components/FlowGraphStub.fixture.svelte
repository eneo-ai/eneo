<script lang="ts">
  // Stands in for FlowGraph in tests: the real one needs @xyflow/svelte, dagre
  // and a layout engine jsdom does not have. It renders something visible so a
  // test can tell "the graph arrived" from "the error went away".
  let { flow }: { flow?: { name?: string } } = $props();
</script>

<div data-testid="flow-graph-stub">{flow?.name ?? "graph"}</div>
