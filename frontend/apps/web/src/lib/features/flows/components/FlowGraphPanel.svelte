<script lang="ts">
  import type { Flow } from "@intric/intric-js";
  import { IconChevronDown } from "@intric/icons/chevron-down";
  import { createEventDispatcher, onMount } from "svelte";
  import { slide } from "svelte/transition";
  import { getFlowUserMode } from "$lib/features/flows/FlowUserMode";
  import { IconLoadingSpinner } from "@intric/icons/loading-spinner";
  import { m } from "$lib/paraglide/messages";
  import { browser } from "$app/environment";

  export let flow: Flow;
  export let activeStepId: string | null;

  const dispatch = createEventDispatcher<{ nodeClick: string }>();
  const mode = getFlowUserMode();

  let isOpen = browser ? ($mode === "power_user" && window.innerWidth >= 1440) : false;
  let prevMode = $mode;
  let FlowGraphComponent: any = null;
  let graphMountKey = 0;
  let slideReady = false;

  // Auto-open graph when user switches to "Avancerad" mode
  $: if ($mode !== prevMode) {
    prevMode = $mode;
    if (browser && $mode === "power_user" && !isOpen) {
      isOpen = true;
    }
  }

  // Reset slideReady when closing
  $: if (!isOpen) slideReady = false;

  onMount(async () => {
    const mod = await import("./FlowGraph.svelte");
    FlowGraphComponent = mod.default;
    // If panel starts already open (no slide transition), mark ready immediately
    if (isOpen) {
      slideReady = true;
      graphMountKey += 1;
    }
  });

  function toggle() {
    isOpen = !isOpen;
  }

  function handleIntroEnd() {
    slideReady = true;
    graphMountKey += 1;
  }
</script>

<div class="border-default border-t">
  <button
    class="hover:bg-hover-dimmer flex w-full items-center justify-between px-4 py-2 text-sm font-medium"
    on:click={toggle}
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
    <div class="border-default h-[200px] border-t lg:h-[320px]" transition:slide={{ duration: 250 }} on:introend={handleIntroEnd}>
      {#if FlowGraphComponent && slideReady}
        {#key graphMountKey}
          <svelte:component
            this={FlowGraphComponent}
            {flow}
            {activeStepId}
            onnodeclick={(id) => dispatch("nodeClick", id)}
          />
        {/key}
      {:else}
        <div class="flex h-full items-center justify-center gap-2 text-secondary">
          <IconLoadingSpinner class="size-4 animate-spin" />
          <p class="text-sm">{m.flow_graph_loading()}</p>
        </div>
      {/if}
    </div>
  {/if}
</div>
