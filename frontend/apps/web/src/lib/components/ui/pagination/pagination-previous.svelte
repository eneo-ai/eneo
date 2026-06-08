<script lang="ts">
  import { Pagination as PaginationPrimitive } from "bits-ui";
  import { cn } from "$lib/utils.js";
  import { buttonVariants } from "$lib/components/ui/button/index.js";
  import ChevronLeftIcon from "@lucide/svelte/icons/chevron-left";

  let {
    ref = $bindable(null),
    class: className,
    ...restProps
  }: PaginationPrimitive.PrevButtonProps = $props();
</script>

<!-- eslint-disable intric/no-hardcoded-text -- shadcn primitive; keep close to upstream -->

<PaginationPrimitive.PrevButton
  bind:ref
  aria-label="Go to previous page"
  class={cn(buttonVariants({ variant: "ghost", size: "default" }), "pl-1.5!", className)}
  {...restProps}
>
  <ChevronLeftIcon class="size-4" data-icon="inline-start" />
  <span class="cn-pagination-previous-text hidden sm:block">Previous</span>
</PaginationPrimitive.PrevButton>
