<script lang="ts">
  import { Pagination as PaginationPrimitive } from "bits-ui";
  import { cn } from "$lib/utils.js";
  import { buttonVariants } from "$lib/components/ui/button/index.js";
  import ChevronRightIcon from "@lucide/svelte/icons/chevron-right";

  let {
    ref = $bindable(null),
    class: className,
    ...restProps
  }: PaginationPrimitive.NextButtonProps = $props();
</script>

<!-- eslint-disable intric/no-hardcoded-text -- shadcn primitive; keep close to upstream -->

<PaginationPrimitive.NextButton
  bind:ref
  aria-label="Go to next page"
  class={cn(buttonVariants({ variant: "ghost", size: "default" }), "pr-1.5!", className)}
  {...restProps}
>
  <span class="cn-pagination-next-text hidden sm:block">Next</span>
  <ChevronRightIcon class="size-4" data-icon="inline-end" />
</PaginationPrimitive.NextButton>
