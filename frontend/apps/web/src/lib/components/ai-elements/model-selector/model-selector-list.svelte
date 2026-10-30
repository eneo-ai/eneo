<script lang="ts">
  import type { Snippet } from "svelte";
  import * as Command from "$lib/components/ui/command/index.js";
  import { m } from "$lib/paraglide/messages";
  import { cn } from "$lib/utils.js";

  type Props = { class?: string; children: Snippet };

  let { class: className, children }: Props = $props();
</script>

<!-- Without a name the list is announced by bits-ui's own English fallback,
     "Suggestions...", in every model picker of the app. -->
<Command.List
  data-slot="model-selector-list"
  aria-label={m.models()}
  class={cn("max-h-[320px]", className)}
>
  {@render children()}
</Command.List>
