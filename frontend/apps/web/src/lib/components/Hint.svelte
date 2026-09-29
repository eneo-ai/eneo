<script lang="ts">
  import type { Snippet } from "svelte";
  import { cn } from "$lib/utils.js";
  import { m } from "$lib/paraglide/messages";

  type Props = {
    tone?: "warning" | "info";
    class?: string;
    children: Snippet;
  };

  let { tone = "warning", class: className, children }: Props = $props();
</script>

<p
  class={cn(
    tone === "warning" ? "label-warning" : "label-info",
    "border-label-default bg-label-dimmer text-label-stronger rounded-md border px-2 py-1 text-sm",
    className
  )}
>
  <span class="font-bold">{m.hint()}:</span>
  {@render children()}
</p>
