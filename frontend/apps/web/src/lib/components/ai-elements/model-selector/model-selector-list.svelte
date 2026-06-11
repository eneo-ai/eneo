<script lang="ts">
  import type { Snippet } from "svelte";
  import * as Command from "$lib/components/ui/command/index.js";
  import { cn } from "$lib/utils.js";

  type Props = { class?: string; children: Snippet };

  let { class: className, children }: Props = $props();
</script>

<Command.List data-slot="model-selector-list" class={cn("max-h-[320px]", className)}>
  {@render children()}
</Command.List>
