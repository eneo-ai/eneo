<script lang="ts">
  import type { Snippet } from "svelte";
  import * as Popover from "$lib/components/ui/popover/index.js";
  import * as Command from "$lib/components/ui/command/index.js";
  import { cn } from "$lib/utils.js";

  type Props = {
    class?: string;
    align?: "start" | "center" | "end";
    children: Snippet;
  };

  let { class: className, align = "end", children }: Props = $props();
</script>

<Popover.Content data-slot="model-selector-content" {align} class={cn("w-[320px] p-0", className)}>
  <Command.Root>
    {@render children()}
  </Command.Root>
</Popover.Content>
