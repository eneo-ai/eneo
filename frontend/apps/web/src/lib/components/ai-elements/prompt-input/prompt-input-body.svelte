<script lang="ts">
  import type { Snippet } from "svelte";
  import type { HTMLAttributes } from "svelte/elements";
  import { cn } from "$lib/utils.js";

  type Props = HTMLAttributes<HTMLDivElement> & { children: Snippet };

  let { class: className, children, ...restProps }: Props = $props();
</script>

<div data-slot="prompt-input-body" class={cn("relative px-1.5 pt-1", className)} {...restProps}>
  {@render children()}
</div>
