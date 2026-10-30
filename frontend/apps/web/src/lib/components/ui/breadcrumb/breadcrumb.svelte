<script lang="ts">
  import type { WithElementRef } from "$lib/utils.js";
  import type { HTMLAttributes } from "svelte/elements";
  import { cn } from "$lib/utils.js";
  import { m } from "$lib/paraglide/messages";

  let {
    ref = $bindable(null),
    class: className,
    children,
    ...restProps
  }: WithElementRef<HTMLAttributes<HTMLElement>> = $props();
</script>

<nav
  bind:this={ref}
  data-slot="breadcrumb"
  aria-label={m.breadcrumb()}
  class={cn("cn-breadcrumb", className)}
  {...restProps}
>
  {@render children?.()}
</nav>
