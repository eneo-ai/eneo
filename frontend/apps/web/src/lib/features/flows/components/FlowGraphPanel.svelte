<script lang="ts">
  import type { Flow } from "@eneo/eneo-js";
  import { IconChevronDown } from "@eneo/icons/chevron-down";
  import { IconRefresh } from "@eneo/icons/refresh";
  import { IconLoadingSpinner } from "@eneo/icons/loading-spinner";
  import Maximize2 from "@lucide/svelte/icons/maximize-2";
  import { m } from "$lib/paraglide/messages";
  import * as Collapsible from "$lib/components/ui/collapsible/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import { Button } from "$lib/components/ui/button/index.js";

  let {
    flow,
    activeStepId,
    onNodeClick
  }: {
    flow: Flow;
    activeStepId: string | null;
    onNodeClick?: (stepId: string) => void;
  } = $props();

  let isOpen = $state(false);
  let isEnlarged = $state(false);
  // Dynamically imported Svelte component; concrete shape is unknown at this call site.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let FlowGraphComponent: any = $state(null);
  let loadState: "idle" | "loading" | "ready" | "error" = $state("idle");

  // The graph chunk carries @xyflow/svelte and dagre, so it is fetched the
  // first time someone actually asks to see the graph -- not on mount, where
  // every flow page would pay for a panel that starts collapsed.
  $effect(() => {
    if ((isOpen || isEnlarged) && loadState === "idle") {
      void loadGraph();
    }
  });

  async function loadGraph() {
    loadState = "loading";
    try {
      const mod = await import("./FlowGraph.svelte");
      FlowGraphComponent = mod.default;
      loadState = "ready";
    } catch (error) {
      // A download this size is slow on a cold cache and on a throttled
      // connection, so it is never abandoned on a timer: reaching here means
      // the module genuinely failed. Name the reason in the console -- the
      // retry button is all the reader can do about it.
      console.error("[FlowGraphPanel] flow graph module failed to load", error);
      loadState = "error";
    }
  }

  const hasSteps = $derived((flow?.steps ?? []).length > 0);
  const stepCount = $derived((flow?.steps ?? []).length);

  // A fixed strip height suits exactly one flow shape. Taking the graph's own
  // proportions instead lets CSS derive the height from whatever width the
  // screen gives -- a straight chain stops reserving room it never uses, and
  // a branching one gets its share -- with the clamps keeping the strip from
  // crowding the step editor above it. aspectRatio is unitless, so this holds
  // from a narrow window to an ultrawide one without a breakpoint.
  let contentSize = $state<{ width: number; height: number } | null>(null);
  const aspectRatio = $derived(
    contentSize && contentSize.width > 0 && contentSize.height > 0
      ? `${contentSize.width} / ${contentSize.height}`
      : null
  );
</script>

{#snippet graphBody()}
  {#if loadState === "ready" && FlowGraphComponent && hasSteps}
    <FlowGraphComponent
      {flow}
      {activeStepId}
      onnodeclick={(id: string) => onNodeClick?.(id)}
      oncontentsize={(size: { width: number; height: number }) => (contentSize = size)}
    />
  {:else if loadState === "error"}
    <div class="text-secondary flex h-full flex-col items-center justify-center gap-3">
      <p class="text-sm">{m.flow_graph_error()}</p>
      <Button variant="secondary" size="sm" onclick={loadGraph}>
        <IconRefresh class="size-3.5" aria-hidden="true" />
        {m.flow_graph_retry()}
      </Button>
    </div>
  {:else if loadState === "ready" && !hasSteps}
    <div class="text-secondary flex h-full items-center justify-center">
      <p class="text-sm">{m.flow_graph_empty()}</p>
    </div>
  {:else}
    <div class="text-secondary flex h-full items-center justify-center gap-2">
      <IconLoadingSpinner class="size-4 animate-spin" aria-hidden="true" />
      <p class="text-sm">{m.flow_graph_loading()}</p>
    </div>
  {/if}
{/snippet}

<div class="border-default bg-secondary/15 border-t">
  <Collapsible.Root bind:open={isOpen}>
    <div class="flex items-stretch">
      <Collapsible.Trigger
        class="hover:bg-hover-dimmer/60 group focus-visible:ring-ring flex min-h-[44px] flex-1 items-center justify-between gap-3 px-4 py-2.5 text-left transition-colors focus-visible:ring-2 focus-visible:outline-none focus-visible:ring-inset sm:px-5"
      >
        <span class="flex min-w-0 items-center gap-2">
          <span class="text-primary truncate text-sm font-medium">{m.flow_graph_preview()}</span>
          {#if hasSteps}
            <span
              class="text-secondary bg-hover-dimmer/70 shrink-0 rounded-full px-1.5 py-0.5 text-xs font-semibold tabular-nums"
            >
              {stepCount}
            </span>
          {/if}
        </span>
        <span
          class="text-muted flex size-5 shrink-0 items-center justify-center ease-out motion-safe:transition-transform motion-safe:duration-(--duration-quick) motion-safe:ease-(--ease-smooth-out)"
          class:rotate-180={isOpen}
          aria-hidden="true"
        >
          <IconChevronDown class="size-4" />
        </span>
      </Collapsible.Trigger>

      {#if isOpen && hasSteps}
        <div class="flex shrink-0 items-center pr-3 sm:pr-4">
          <Button variant="ghost" size="sm" onclick={() => (isEnlarged = true)}>
            <Maximize2 class="size-4" aria-hidden="true" />
            {m.flow_graph_enlarge()}
          </Button>
        </div>
      {/if}
    </div>

    <Collapsible.Content class="collapsible-animate">
      <div
        id="flow-graph-panel"
        class="border-default bg-primary/40 max-h-[40vh] min-h-[13rem] w-full border-t"
        style={aspectRatio ? `aspect-ratio: ${aspectRatio}` : "height: 22rem"}
      >
        {@render graphBody()}
      </div>
    </Collapsible.Content>
  </Collapsible.Root>
</div>

<Dialog.Root bind:open={isEnlarged}>
  <!-- sm:max-w-none is load-bearing: the dialog primitive sets sm:max-w-sm,
       and a bare max-w-none loses to it from the breakpoint up. -->
  <Dialog.Content
    class="flex max-h-[94vh] w-[98vw] max-w-none flex-col gap-3 overflow-y-auto p-4 sm:max-w-none sm:p-5"
    closeLabel={m.close()}
  >
    <Dialog.Header class="gap-1 text-left">
      <Dialog.Title>{m.flow_graph_preview()}</Dialog.Title>
      <Dialog.Description>{flow?.name ?? ""}</Dialog.Description>
    </Dialog.Header>
    <!-- The floor is what the canvas needs to hold its own overlays, measured
         in Avancerad: the export panel ends 51px down and the minimap starts
         121px from the bottom, so anything under ~172px overlaps them. The
         dialog scrolls instead of squeezing the canvas below that. -->
    <div
      class="border-default bg-primary/40 max-h-[80vh] min-h-[13rem] w-full min-w-0 shrink-0 overflow-hidden rounded-lg border"
      style={aspectRatio ? `aspect-ratio: ${aspectRatio}` : "height: 70vh"}
    >
      {#if loadState === "ready" && FlowGraphComponent && hasSteps}
        <FlowGraphComponent
          {flow}
          {activeStepId}
          onnodeclick={(id: string) => {
            onNodeClick?.(id);
            isEnlarged = false;
          }}
        />
      {:else}
        {@render graphBody()}
      {/if}
    </div>
  </Dialog.Content>
</Dialog.Root>
