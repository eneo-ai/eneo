<script lang="ts">
  import { Tabs as TabsPrimitive } from "bits-ui";
  import { cn } from "$lib/utils.js";

  let {
    ref = $bindable(null),
    class: className,
    ...restProps
  }: TabsPrimitive.ContentProps = $props();
</script>

<TabsPrimitive.Content
  bind:ref
  data-slot="tabs-content"
  class={cn(
    // bits-ui makes every panel a Tab stop, so it needs a visible focus indicator.
    "focus-visible:ring-ring/50 flex-1 rounded-md text-sm outline-none focus-visible:ring-3",
    className
  )}
  {...restProps}
/>
