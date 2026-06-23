<script lang="ts">
  import type { Snippet } from "svelte";
  import { cn } from "$lib/utils.js";

  type Props = { class?: string; children: Snippet };

  let { class: className, children }: Props = $props();
</script>

<span data-slot="model-selector-name" class={cn("truncate", className)}>
  {@render children()}
</span>
