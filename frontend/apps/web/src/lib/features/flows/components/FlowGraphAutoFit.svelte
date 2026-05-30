<script lang="ts">
  import { onMount } from "svelte";
  import { useSvelteFlow } from "@xyflow/svelte";

  // The draft canvas mounts inside a tab panel that is zero-sized on its first
  // frame, so SvelteFlow's built-in initial fitView no-ops and leaves the graph
  // pinned top-left and unzoomed. Re-fit once the container has a real size, then
  // latch so the user's own pan/zoom is kept. The builder renders a single
  // FlowGraph, so the container id is unambiguous; the flow store's domNode is
  // not yet set this early in the child's lifecycle.
  const { fitView } = useSvelteFlow();

  onMount(() => {
    const container = document.querySelector("#flow-graph-container");
    if (!(container instanceof HTMLElement)) return;
    let fitted = false;
    const attempt = async () => {
      if (fitted) return;
      const { width, height } = container.getBoundingClientRect();
      if (width === 0 || height === 0) return;
      fitted = await fitView({ padding: 0.2 });
    };
    const observer = new ResizeObserver(() => void attempt());
    observer.observe(container);
    void attempt();
    return () => observer.disconnect();
  });
</script>
