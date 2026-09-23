<script lang="ts" module>
  const colorClasses = {
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

  export type StatusBadgeColor = keyof typeof colorClasses;
  export type StatusBadgeItem = {
    label: string | number;
    color: StatusBadgeColor;
    tooltip?: string;
  };
</script>

<script lang="ts">
  import { Badge, badgeVariants } from "$lib/components/ui/badge/index.js";
  import * as Tooltip from "$lib/components/ui/tooltip/index.js";
  import { cn } from "$lib/utils.js";

  let {
    item,
    capitalize = true,
    monospaced = false
  }: { item: StatusBadgeItem; capitalize?: boolean; monospaced?: boolean } = $props();

  const classes = $derived(
    cn(
      colorClasses[item.color],
      "border-label-default bg-label-dimmer text-label-stronger cursor-default",
      capitalize && "capitalize",
      monospaced && "font-mono"
    )
  );
</script>

{#if item.tooltip}
  <Tooltip.Root>
    <Tooltip.Trigger class={cn(badgeVariants({ variant: "outline" }), classes)}>
      {item.label}
    </Tooltip.Trigger>
    <Tooltip.Content>{item.tooltip}</Tooltip.Content>
  </Tooltip.Root>
{:else}
  <Badge variant="outline" class={classes}>{item.label}</Badge>
{/if}
