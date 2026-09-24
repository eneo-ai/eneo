<script lang="ts">
  import { Progress as ProgressPrimitive } from "bits-ui";
  import { cn, type WithoutChildrenOrChild } from "$lib/utils.js";

  let {
    ref = $bindable(null),
    class: className,
    max = 100,
    value,
    indicatorClass,
    ...restProps
  }: WithoutChildrenOrChild<ProgressPrimitive.RootProps> & { indicatorClass?: string } = $props();
</script>

<ProgressPrimitive.Root
  bind:ref
  data-slot="progress"
  class={cn(
    "bg-muted h-1 rounded-full relative flex w-full items-center overflow-x-hidden",
    className
  )}
  {value}
  {max}
  {...restProps}
>
  <!-- NOTE: `bg-accent-default` instead of upstream's `bg-primary` — see app.css
    `--color-primary` namespace conflict comment. -->
  <div
    data-slot="progress-indicator"
    class={cn("bg-accent-default size-full flex-1 transition-all", indicatorClass)}
    style="transform: translateX(-{100 - (100 * (value ?? 0)) / (max ?? 1)}%)"
  ></div>
</ProgressPrimitive.Root>
