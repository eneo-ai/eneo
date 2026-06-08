<script lang="ts">
  import { Pagination as PaginationPrimitive } from "bits-ui";
  import ChevronLeftIcon from "@lucide/svelte/icons/chevron-left";
  import { cn } from "$lib/utils.js";
  import { buttonVariants } from "../button/index.js";
  import { m } from "$lib/paraglide/messages";

  let {
    ref = $bindable(null),
    class: className,
    children,
    ...restProps
  }: PaginationPrimitive.PrevButtonProps = $props();
</script>

{#snippet Fallback()}
  <ChevronLeftIcon class={cn("size-4", className)} />
  <span>{m.previous()}</span>
{/snippet}

<PaginationPrimitive.PrevButton
  bind:ref
  aria-label={m.aria_go_to_previous_page()}
  class={cn(buttonVariants({ variant: "ghost" }), "pl-1.5!", className)}
  {...restProps}
>
  {#if children}
    {@render children?.()}
  {:else}
    {@render Fallback()}
  {/if}
</PaginationPrimitive.PrevButton>
