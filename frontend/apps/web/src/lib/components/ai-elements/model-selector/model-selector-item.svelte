<script lang="ts">
  import type { Snippet } from "svelte";
  import * as Command from "$lib/components/ui/command/index.js";
  import { cn } from "$lib/utils.js";
  import { getModelSelectorContext } from "./context";

  type Props = {
    /** Search/filter string for the command palette — include the model name and vendor. */
    value: string;
    selected?: boolean;
    onSelect?: () => void;
    class?: string;
    children: Snippet;
  };

  let { value, selected = false, onSelect, class: className, children }: Props = $props();

  const modelSelector = getModelSelectorContext();
</script>

<Command.Item
  data-slot="model-selector-item"
  {value}
  data-checked={selected ? "true" : undefined}
  onSelect={() => {
    onSelect?.();
    modelSelector.close();
  }}
  class={cn("gap-2", className)}
>
  {@render children()}
</Command.Item>
