<script lang="ts">
  import type { Snippet } from "svelte";
  import { ChevronDown } from "lucide-svelte";
  import * as Popover from "$lib/components/ui/popover/index.js";
  import { cn } from "$lib/utils.js";

  type Props = {
    class?: string;
    children: Snippet;
    [key: string]: unknown;
  };

  let { class: className, children, ...restProps }: Props = $props();
</script>

<Popover.Trigger
  data-slot="model-selector-trigger"
  class={cn(
    "hover:bg-muted hover:text-foreground aria-expanded:bg-muted aria-expanded:text-foreground flex h-9 max-w-[15rem] items-center gap-1.5 rounded-lg px-2.5 text-sm font-medium transition-colors outline-none focus-visible:ring-2",
    className
  )}
  {...restProps}
>
  {@render children()}
  <ChevronDown class="size-3.5 shrink-0 opacity-50" aria-hidden="true" />
</Popover.Trigger>
