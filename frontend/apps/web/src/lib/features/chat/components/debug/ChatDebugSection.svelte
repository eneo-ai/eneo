<script lang="ts">
  import { Badge } from "$lib/components/ui/badge/index.js";
  import * as Collapsible from "$lib/components/ui/collapsible/index.js";
  import ChevronDown from "@lucide/svelte/icons/chevron-down";
  import type { Snippet } from "svelte";

  let {
    id,
    title,
    count = null,
    defaultOpen = true,
    children
  }: {
    id: string;
    title: string;
    count?: number | null;
    defaultOpen?: boolean;
    children: Snippet;
  } = $props();

  // defaultOpen intentionally seeds the disclosure state once; later toggling
  // belongs to the user.
  // svelte-ignore state_referenced_locally
  let open = $state(defaultOpen);
</script>

<Collapsible.Root bind:open class="border-border border-b">
  <h2 class="m-0">
    <Collapsible.Trigger
      class="hover:bg-muted/60 focus-visible:ring-ring flex w-full items-center gap-2 px-5 py-3 text-left focus-visible:ring-1 focus-visible:outline-none [&[data-state=closed]>svg]:-rotate-90"
      aria-controls={id}
    >
      <span class="min-w-0 flex-1 truncate text-sm font-semibold">{title}</span>
      {#if count !== null}
        <Badge variant={count > 0 ? "secondary" : "outline"} class="tabular-nums">{count}</Badge>
      {/if}
      <ChevronDown
        aria-hidden="true"
        class="text-muted-foreground size-4 shrink-0 transition-transform motion-reduce:transition-none"
      />
    </Collapsible.Trigger>
  </h2>
  <Collapsible.Content {id} class="flex flex-col gap-3 px-5 pt-1 pb-5">
    {@render children()}
  </Collapsible.Content>
</Collapsible.Root>
