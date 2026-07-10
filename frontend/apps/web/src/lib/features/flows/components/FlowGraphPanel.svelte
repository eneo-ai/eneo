<script lang="ts">
  import { onMount } from "svelte";
  import type { Flow } from "@eneo/eneo-js";
  import { IconChevronDown } from "@eneo/icons/chevron-down";
  import { IconRefresh } from "@eneo/icons/refresh";
  import { IconLoadingSpinner } from "@eneo/icons/loading-spinner";
  import { m } from "$lib/paraglide/messages";
  import * as Collapsible from "$lib/components/ui/collapsible/index.js";

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
  // Dynamically imported Svelte component; concrete shape is unknown at this call site.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let FlowGraphComponent: any = $state(null);
  let loadState: "idle" | "loading" | "ready" | "error" = $state("idle");

  onMount(() => {
    loadState = "loading";
    loadGraph();
  });

  async function loadGraph() {
    loadState = "loading";
    try {
      const mod = await Promise.race([
        import("./FlowGraph.svelte"),
        new Promise<never>((_, reject) => setTimeout(() => reject(new Error("timeout")), 5000))
      ]);
      FlowGraphComponent = mod.default;
      loadState = "ready";
    } catch {
      loadState = "error";
    }
  }

  const hasSteps = $derived((flow?.steps ?? []).length > 0);
  const stepCount = $derived((flow?.steps ?? []).length);
</script>

<div class="border-default bg-secondary/15 border-t">
  <Collapsible.Root bind:open={isOpen}>
    <Collapsible.Trigger
      class="hover:bg-hover-dimmer/60 group focus-visible:ring-accent-default/30 flex min-h-[44px] w-full items-center justify-between gap-3 px-4 py-2.5 text-left transition-colors focus-visible:ring-2 focus-visible:outline-none focus-visible:ring-inset sm:px-5"
    >
      <span class="flex min-w-0 items-center gap-2">
        <span class="bg-hover-dimmer/80 size-1.5 shrink-0 rounded-full" aria-hidden="true"></span>
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
        class="text-muted flex size-5 shrink-0 items-center justify-center transition-transform duration-200 ease-out"
        class:rotate-180={isOpen}
        aria-hidden="true"
      >
        <IconChevronDown class="size-4" />
      </span>
    </Collapsible.Trigger>

    <Collapsible.Content>
      <div
        id="flow-graph-panel"
        class="border-default bg-primary/40 h-[200px] border-t lg:h-[320px]"
      >
        {#if loadState === "ready" && FlowGraphComponent && hasSteps}
          <FlowGraphComponent
            {flow}
            {activeStepId}
            onnodeclick={(id: string) => onNodeClick?.(id)}
          />
        {:else if loadState === "error"}
          <div class="text-secondary flex h-full flex-col items-center justify-center gap-3">
            <p class="text-sm">{m.flow_graph_error()}</p>
            <button
              type="button"
              class="bg-hover-dimmer hover:bg-hover-default focus-visible:ring-accent-default/30 flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors focus-visible:ring-2 focus-visible:outline-none"
              onclick={loadGraph}
            >
              <IconRefresh class="size-3.5" aria-hidden="true" />
              {m.flow_graph_retry()}
            </button>
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
      </div>
    </Collapsible.Content>
  </Collapsible.Root>
</div>
