<script lang="ts">
  import type { Snippet } from "svelte";
  import type { HTMLAttributes } from "svelte/elements";
  import { cn } from "$lib/utils.js";

  type Props = HTMLAttributes<HTMLDivElement> & { children: Snippet };

  let { class: className, children, ...restProps }: Props = $props();
</script>

<div
  data-slot="prompt-input-footer"
  class={cn("flex items-center justify-between gap-2 px-2 pt-1 pb-2", className)}
  {...restProps}
>
  {@render children()}
</div>
