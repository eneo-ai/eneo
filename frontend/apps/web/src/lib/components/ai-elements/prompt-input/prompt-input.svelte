<script lang="ts">
  import type { Snippet } from "svelte";
  import type { HTMLFormAttributes } from "svelte/elements";
  import { cn } from "$lib/utils.js";
  import { setPromptInputContext, type PromptInputStatus } from "./context";

  type Props = HTMLFormAttributes & {
    status?: PromptInputStatus;
    onSubmit: () => void | Promise<void>;
    onStop?: () => void;
    children: Snippet;
  };

  let {
    status = "ready",
    onSubmit,
    onStop,
    class: className,
    children,
    ...restProps
  }: Props = $props();

  setPromptInputContext({
    get status() {
      return status;
    },
    stop: () => onStop?.()
  });
</script>

<form
  data-slot="prompt-input"
  onsubmit={async (event) => {
    event.preventDefault();
    await onSubmit();
  }}
  class={cn(
    "bg-card border-input focus-within:border-ring focus-within:ring-ring/40 relative flex w-full flex-col rounded-2xl border shadow-sm transition-colors focus-within:ring-[3px]",
    className
  )}
  {...restProps}
>
  {@render children()}
</form>
