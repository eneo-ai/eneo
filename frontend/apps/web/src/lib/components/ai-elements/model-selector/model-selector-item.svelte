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
    onHighlight?: () => void;
    class?: string;
    children: Snippet;
  };

  let {
    value,
    selected = false,
    onSelect,
    onHighlight,
    class: className,
    children
  }: Props = $props();

  const modelSelector = getModelSelectorContext();
  let itemRef = $state<HTMLElement | null>(null);

  $effect(() => {
    if (!itemRef || !onHighlight) return;

    const highlightIfSelected = () => {
      if (itemRef?.hasAttribute("data-selected")) onHighlight();
    };
    const observer = new MutationObserver(highlightIfSelected);
    observer.observe(itemRef, { attributes: true, attributeFilter: ["data-selected"] });
    highlightIfSelected();

    return () => observer.disconnect();
  });
</script>

<Command.Item
  bind:ref={itemRef}
  data-slot="model-selector-item"
  {value}
  data-checked={selected ? "true" : undefined}
  onSelect={() => {
    onSelect?.();
    modelSelector.close();
  }}
  onpointerenter={onHighlight}
  onfocus={onHighlight}
  class={cn("gap-2", className)}
>
  {@render children()}
</Command.Item>
