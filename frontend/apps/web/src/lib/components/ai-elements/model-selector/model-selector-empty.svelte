<script lang="ts">
  import type { Snippet } from "svelte";
  import * as Command from "$lib/components/ui/command/index.js";

  type Props = { children: Snippet };

  let { children }: Props = $props();
</script>

<Command.Empty data-slot="model-selector-empty">
  {@render children()}
</Command.Empty>
