<script lang="ts">
  import { Handle, Position } from "@xyflow/svelte";

  let {
    data
  }: {
    data: {
      label: string;
      nodeType: "input" | "output" | "http_source" | "http_target";
      mode?: "user" | "power_user";
      direction?: "LR" | "TB";
    };
  } = $props();

  const isSource = $derived(data.nodeType === "input" || data.nodeType === "http_source");
  const isExternal = $derived(data.nodeType === "http_source" || data.nodeType === "http_target");
</script>

<!-- Where the flow starts and ends is a place, not an action or an outcome, so
     it stays neutral; the word says which end it is and a dashed rule marks an
     external system. -->
<div
  class="bg-secondary border-strongest text-primary flex items-center justify-center rounded-[10px] border px-4 py-2 text-sm font-medium
    {isExternal ? 'border-dashed' : ''}"
  style="min-width: 80px;"
>
  {data.label}
</div>

{#if isSource}
  <Handle type="source" position={data.direction === "TB" ? Position.Bottom : Position.Right} />
{:else}
  <Handle type="target" position={data.direction === "TB" ? Position.Top : Position.Left} />
{/if}
