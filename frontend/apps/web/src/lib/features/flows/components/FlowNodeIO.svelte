<script lang="ts">
  import { Handle, Position } from "@xyflow/svelte";

  let {
    data
  }: {
    data: {
      label: string;
      nodeType: "input" | "output";
      mode?: "user" | "power_user";
      direction?: "LR" | "TB";
      runStatus?: string;
    };
  } = $props();

  const isInput = $derived(data.nodeType === "input");
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
  <Handle type="source" position={data.direction === "TB" ? Position.Bottom : Position.Right} />
{:else}
  <Handle type="target" position={data.direction === "TB" ? Position.Top : Position.Left} />
{/if}
