<script lang="ts">
  import { onMount } from "svelte";
  import type { Flow } from "@intric/intric-js";
  import { IconChevronDown } from "@intric/icons/chevron-down";
  import { IconRefresh } from "@intric/icons/refresh";
  import { IconLoadingSpinner } from "@intric/icons/loading-spinner";
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
</script>

<div class="border-default border-t">
  <Collapsible.Root bind:open={isOpen}>
    <Collapsible.Trigger
      class="hover:bg-hover-dimmer flex w-full items-center justify-between px-4 py-2 text-sm font-medium"
    >
      <span>{m.flow_graph_preview()}</span>
      <span class="transition-transform" class:rotate-180={isOpen}>
        <IconChevronDown class="size-4" />
      </span>
    </Collapsible.Trigger>

    <Collapsible.Content>
      <div id="flow-graph-panel" class="border-default h-[200px] border-t lg:h-[320px]">
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
              class="bg-hover-dimmer hover:bg-hover-default flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors"
              onclick={loadGraph}
            >
              <IconRefresh class="size-3.5" />
              {m.flow_graph_retry()}
            </button>
          </div>
        {:else if loadState === "ready" && !hasSteps}
          <div class="text-secondary flex h-full items-center justify-center">
            <p class="text-sm">{m.flow_graph_empty()}</p>
          </div>
        {:else}
          <div class="text-secondary flex h-full items-center justify-center gap-2">
            <IconLoadingSpinner class="size-4 animate-spin" />
            <p class="text-sm">{m.flow_graph_loading()}</p>
          </div>
        {/if}
      </div>
    </Collapsible.Content>
  </Collapsible.Root>
</div>
