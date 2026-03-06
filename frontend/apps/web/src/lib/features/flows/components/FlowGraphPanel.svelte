<script lang="ts">
  import type { Flow } from "@intric/intric-js";
  import { IconChevronDown } from "@intric/icons/chevron-down";
  import { IconRefresh } from "@intric/icons/refresh";
  import { createEventDispatcher, onMount } from "svelte";
  import { slide } from "svelte/transition";
  import { IconLoadingSpinner } from "@intric/icons/loading-spinner";
  import { m } from "$lib/paraglide/messages";

  export let flow: Flow;
  export let activeStepId: string | null;

  const dispatch = createEventDispatcher<{ nodeClick: string }>();

  let isOpen = false;
  let FlowGraphComponent: any = null;
  let loadState: "idle" | "loading" | "ready" | "error" = "idle";

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

  function toggle() {
    isOpen = !isOpen;
  }

  $: hasSteps = (flow?.steps ?? []).length > 0;
</script>

<div class="border-default border-t">
  <button
    class="hover:bg-hover-dimmer flex w-full items-center justify-between px-4 py-2 text-sm font-medium"
    on:click={toggle}
    aria-expanded={isOpen}
    aria-controls="flow-graph-panel"
  >
    <span>{m.flow_graph_preview()}</span>
    <span
      class="transition-transform"
      class:rotate-180={isOpen}
    >
      <IconChevronDown class="size-4" />
    </span>
  </button>

  {#if isOpen}
    <div
      id="flow-graph-panel"
      class="border-default h-[200px] border-t lg:h-[320px]"
      transition:slide={{ duration: 200 }}
    >
      {#if loadState === "ready" && FlowGraphComponent && hasSteps}
        <svelte:component
          this={FlowGraphComponent}
          {flow}
          {activeStepId}
          onnodeclick={(id) => dispatch("nodeClick", id)}
        />
      {:else if loadState === "error"}
        <div class="flex h-full flex-col items-center justify-center gap-3 text-secondary">
          <p class="text-sm">{m.flow_graph_error()}</p>
          <button
            class="bg-hover-dimmer hover:bg-hover-default flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors"
            on:click={loadGraph}
          >
            <IconRefresh class="size-3.5" />
            {m.flow_graph_retry()}
          </button>
        </div>
      {:else if loadState === "ready" && !hasSteps}
        <div class="flex h-full items-center justify-center text-secondary">
          <p class="text-sm">{m.flow_graph_empty()}</p>
        </div>
      {:else}
        <div class="flex h-full items-center justify-center gap-2 text-secondary">
          <IconLoadingSpinner class="size-4 animate-spin" />
          <p class="text-sm">{m.flow_graph_loading()}</p>
        </div>
      {/if}
    </div>
  {/if}
</div>
