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
    // bits-ui makes every panel a Tab stop, so it needs a focus indicator of 3:1;
    // `ring-ring/50` is about 1.3:1 in both themes.
    "focus-visible:outline-muted-foreground flex-1 rounded-md text-sm outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-solid",
    className
  )}
  {...restProps}
/>
