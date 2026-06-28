<script lang="ts">
  import type { HTMLAttributes } from "svelte/elements";
  import { cn, type WithElementRef, type WithoutChildren } from "$lib/utils.js";
  import EllipsisIcon from "@lucide/svelte/icons/ellipsis";

  let {
    ref = $bindable(null),
    class: className,
    ...restProps
  }: WithoutChildren<WithElementRef<HTMLAttributes<HTMLSpanElement>>> = $props();
</script>

<!-- eslint-disable eneo/no-hardcoded-text -- shadcn primitive; keep close to upstream -->

<span
  bind:this={ref}
  aria-hidden="true"
  data-slot="pagination-ellipsis"
  class={cn(
    "flex size-8 items-center items-center justify-center justify-center [&_svg:not([class*='size-'])]:size-4",
    className
  )}
  {...restProps}
>
  <EllipsisIcon class="size-4" />
  <span class="sr-only">More pages</span>
</span>
