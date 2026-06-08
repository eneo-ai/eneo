<script lang="ts">
  import { Pagination as PaginationPrimitive } from "bits-ui";
  import { cn } from "$lib/utils.js";
  import { buttonVariants } from "$lib/components/ui/button/index.js";
  import ChevronLeftIcon from "@lucide/svelte/icons/chevron-left";
  import { m } from "$lib/paraglide/messages";

  let {
    ref = $bindable(null),
    class: className,
    ...restProps
  }: PaginationPrimitive.PrevButtonProps = $props();
</script>

<PaginationPrimitive.PrevButton
  bind:ref
  aria-label={m.aria_go_to_previous_page()}
  class={cn(buttonVariants({ variant: "ghost", size: "default" }), "pl-1.5!", className)}
  {...restProps}
>
  <ChevronLeftIcon class="size-4" data-icon="inline-start" />
  <span class="cn-pagination-previous-text hidden sm:block">{m.previous()}</span>
</PaginationPrimitive.PrevButton>
