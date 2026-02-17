<script context="module" lang="ts">
  const colorMap = {
    blue: "label-blue",
    green: "label-green",
    yellow: "label-yellow",
    red: "label-red",
    orange: "label-yellow",
    gray: "label-grey",
    moss: "label-moss",
    pine: "label-pine",
    amethyst: "label-amethyst"
  } as const;
  export type LabelColor = keyof typeof colorMap;
  export type LabelItem = { label: string | number; color: LabelColor; tooltip?: string };
</script>

<script lang="ts">
  import Tooltip from "$lib/Tooltip/Root.svelte";
  export let item: LabelItem;
  export let capitalize = true;
  export let monospaced = false;

  // Temporary fix for the color mapping to new classnames
</script>

{#if item.tooltip}
  <Tooltip text={item.tooltip} asFragment let:trigger>
    {@const tooltipTrigger = trigger[0]}
    <div
      {...tooltipTrigger}
      use:tooltipTrigger.action
      class:capitalize
      class:font-mono={monospaced}
      class="{colorMap[
        item.color
      ]} border-label-default bg-label-dimmer text-label-stronger inline-block cursor-default rounded-md border px-2 py-1 text-sm"
    >
      {item.label}
    </div>
  </Tooltip>
{:else}
  <div
    class:capitalize
    class:font-mono={monospaced}
    class="{colorMap[
      item.color
    ]} border-label-default bg-label-dimmer text-label-stronger inline-block cursor-default rounded-md border px-2 py-1 text-sm"
  >
    {item.label}
  </div>
{/if}
