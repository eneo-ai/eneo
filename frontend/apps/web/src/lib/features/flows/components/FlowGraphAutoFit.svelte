<script lang="ts">
  import { useSvelteFlow, type FitViewOptions } from "@xyflow/svelte";

  /**
   * Keeps the graph framed inside whatever room it is given.
   *
   * SvelteFlow reads its `fitView` prop once, while the store is built. The
   * panel that hosts the graph is a collapsible, so at that moment it is
   * still animating out of zero height and there is nothing to fit to --
   * which left the graph permanently at 1:1 in the top-left corner, with a
   * long flow running off the edge and no sign that it did. Fitting from a
   * size observer instead covers the first real layout, the window resizing,
   * and the enlarged dialog, all through the same path.
   *
   * Must be rendered inside `<SvelteFlow>`: the hook reads its context.
   */
  let {
    container,
    options,
    revision,
    fit = $bindable()
  }: {
    container: HTMLElement | undefined;
    options?: FitViewOptions;
    /**
     * Advances once per laid-out graph. A counter rather than a signature of
     * the layout: two different graphs must never share a value, or the frame
     * silently stays on the previous one.
     */
    revision?: number;
    fit?: (() => void) | undefined;
  } = $props();

  const flow = useSvelteFlow();

  $effect(() => {
    fit = () => void flow.fitView(options);
  });

  // A new layout can be a different size in the same box -- switching to
  // Avancerad swaps 160x48 nodes for 300x150 ones without the panel moving a
  // pixel, so a size observer alone never hears about it and the old frame
  // stays on a graph that has outgrown it. The two frames are grace, not a
  // guarantee: xyflow queues its own fit behind node measurement, and this
  // only has to land after the new nodes are in the DOM.
  $effect(() => refitAfterLayout(revision));

  // The revision arrives as an argument so the effect tracks it by reading it.
  function refitAfterLayout(_revision: number | undefined): () => void {
    let frame = requestAnimationFrame(() => {
      frame = requestAnimationFrame(() => void flow.fitView(options));
    });
    return () => cancelAnimationFrame(frame);
  }

  $effect(() => {
    if (!container) return;
    let lastSize = "";
    let frame = 0;
    const observer = new ResizeObserver((entries) => {
      const box = entries[0]?.contentRect;
      if (!box || box.width < 1 || box.height < 1) return;
      const size = `${Math.round(box.width)}x${Math.round(box.height)}`;
      // Re-fit on a size change only. Panning and zooming are the reader's,
      // and a fit on every frame would take them back.
      if (size === lastSize) return;
      lastSize = size;
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => void flow.fitView(options));
    });
    observer.observe(container);
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
    };
  });
</script>
