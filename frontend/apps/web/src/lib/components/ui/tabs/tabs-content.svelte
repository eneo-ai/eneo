<script lang="ts">
  import { Tabs as TabsPrimitive } from "bits-ui";
  import { cn } from "$lib/utils.js";

  let {
    ref = $bindable(null),
    class: className,
    ...restProps
  }: TabsPrimitive.ContentProps = $props();
</script>

<!-- bits-ui gives every panel tabindex="0", so a panel is always a tab stop.
     Upstream then kills the UA outline and puts nothing back, and tabbing out
     of the tab list lands somewhere invisible (WCAG 2.4.7). An inset ring
     stays inside the panel instead of clipping against its edge. -->
<TabsPrimitive.Content
  bind:ref
  data-slot="tabs-content"
  class={cn(
    "focus-visible:inset-ring-ring flex-1 text-sm outline-none focus-visible:inset-ring-2",
    className
  )}
  {...restProps}
/>
