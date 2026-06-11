<script lang="ts">
  import type { Snippet } from "svelte";
  import * as Popover from "$lib/components/ui/popover/index.js";
  import { setModelSelectorContext } from "./context";

  type Props = { open?: boolean; children: Snippet };

  let { open = $bindable(false), children }: Props = $props();

  setModelSelectorContext({
    close: () => (open = false)
  });
</script>

<Popover.Root bind:open>
  {@render children()}
</Popover.Root>
