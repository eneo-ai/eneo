<script lang="ts">
  import type { Snippet } from "svelte";
  import * as Command from "$lib/components/ui/command/index.js";

  type Props = { heading?: string; children: Snippet };

  let { heading, children }: Props = $props();
</script>

<Command.Group data-slot="model-selector-group" {heading}>
  {@render children()}
</Command.Group>
