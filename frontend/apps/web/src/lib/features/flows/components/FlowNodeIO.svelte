<script lang="ts">
  import { Handle, Position } from "@xyflow/svelte";
  import { cn } from "$lib/utils.js";

  let {
    data
  }: {
    data: {
      label: string;
      nodeType: "input" | "output" | "http_source" | "http_target";
      mode?: "user" | "power_user";
      dimmed?: boolean;
      lifted?: boolean;
    };
  } = $props();

  const isExternal = $derived(data.nodeType === "http_source" || data.nodeType === "http_target");
  // Sources sit above the step they feed and hand down to it; receivers sit
  // in line after the steps.
  const isSource = $derived(data.nodeType === "input" || data.nodeType === "http_source");
</script>

<!-- Where the flow starts and ends is a place, not an action or an outcome, so
     it stays neutral; the word says which end it is and a dashed rule marks an
     external system. -->
<div
  class={cn(
    "flow-node bg-secondary border-strongest text-primary flex size-full items-center justify-center rounded-[10px] border px-4 text-center text-sm leading-tight font-medium",
    isExternal && "border-dashed",
    data.dimmed && "is-dimmed",
    data.lifted && "is-lifted"
  )}
>
  {data.label}
</div>

{#if isSource}
  <Handle type="source" position={Position.Bottom} />
{:else}
  <Handle type="target" id="left" position={Position.Left} />
  {#if data.nodeType === "output"}
    <!-- An empty flow hands what is sent in straight down to the result. -->
    <Handle type="target" id="top" position={Position.Top} />
  {/if}
{/if}
