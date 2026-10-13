<script lang="ts">
  import { Command as CommandPrimitive } from "bits-ui";
  import { cn } from "$lib/utils.js";
  import * as InputGroup from "$lib/components/ui/input-group/index.js";
  import SearchIcon from "@lucide/svelte/icons/search";

  let {
    ref = $bindable(null),
    class: className,
    value = $bindable(""),
    variant = "muted",
    ...restProps
  }: CommandPrimitive.InputProps & {
    /**
     * `muted` is the command palette look. `field` renders as an ordinary text
     * field (white background, visible border) for dialogs where a tinted
     * search box reads as disabled.
     */
    variant?: "muted" | "field";
  } = $props();
</script>

<div data-slot="command-input-wrapper" class={variant === "field" ? "p-2 pb-0" : "p-1 pb-0"}>
  <InputGroup.Root
    class={cn(
      "h-8! rounded-lg! shadow-none! *:data-[slot=input-group-addon]:pl-2!",
      variant === "field"
        ? "bg-background border-input h-10! focus-within:ring-ring/50 focus-within:ring-[3px]"
        : "bg-input/30 border-input/30"
    )}
  >
    <CommandPrimitive.Input
      data-slot="command-input"
      class={cn(
        "w-full text-sm outline-hidden disabled:cursor-not-allowed disabled:opacity-50",
        className
      )}
      bind:ref
      {...restProps}
      bind:value
    />
    <InputGroup.Addon>
      <SearchIcon class="size-4 shrink-0 opacity-50" />
    </InputGroup.Addon>
  </InputGroup.Root>
</div>
