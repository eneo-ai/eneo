<script lang="ts">
  import { Handle, Position } from "@xyflow/svelte";

  export let data: {
    label: string;
    nodeType: "input" | "output";
    mode?: "user" | "power_user";
    runStatus?: string;
  };

  $: isInput = data.nodeType === "input";
</script>

<div
  class="flex items-center justify-center rounded-full border-2 px-4 py-2 text-sm font-medium shadow-sm
    {isInput
      ? 'bg-accent-dimmer border-accent-default/40 text-accent-stronger'
      : 'bg-positive-dimmer border-positive-default/40 text-positive-stronger'}"
  style="min-width: 80px;"
>
  {data.label}
</div>

{#if isInput}
  <Handle type="source" position={Position.Right} />
{:else}
  <Handle type="target" position={Position.Left} />
{/if}
