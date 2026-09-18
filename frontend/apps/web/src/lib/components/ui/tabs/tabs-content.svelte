<script lang="ts">
  import { Tabs as TabsPrimitive } from "bits-ui";
  import { cn } from "$lib/utils.js";

  let {
    ref = $bindable(null),
    class: className,
    ...restProps
  }: TabsPrimitive.ContentProps = $props();
</script>

<!-- The ARIA tabs pattern makes a panel with no focusable content a tab stop
     of its own, and bits-ui sets tabindex="0" for exactly that case. Upstream
     then kills the UA outline and puts nothing back, so tabbing out of the tab
     list lands somewhere invisible (WCAG 2.4.7). An inset ring stays inside the
     panel instead of clipping against its edge. -->
<TabsPrimitive.Content
  bind:ref
  data-slot="tabs-content"
  class={cn(
    "focus-visible:inset-ring-ring flex-1 text-sm outline-none focus-visible:inset-ring-2",
    className
  )}
  {...restProps}
/>
