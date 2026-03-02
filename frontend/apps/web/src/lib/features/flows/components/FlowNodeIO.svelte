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
      ? 'bg-blue-50 border-blue-200 text-blue-700 dark:bg-blue-950 dark:border-blue-800 dark:text-blue-300'
      : 'bg-green-50 border-green-200 text-green-700 dark:bg-green-950 dark:border-green-800 dark:text-green-300'}"
  style="min-width: 80px;"
>
  {data.label}
</div>

{#if isInput}
  <Handle type="source" position={Position.Right} />
{:else}
  <Handle type="target" position={Position.Left} />
{/if}
