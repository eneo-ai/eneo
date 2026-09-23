<script lang="ts">
  import Check from "@lucide/svelte/icons/check";
  import Copy from "@lucide/svelte/icons/copy";
  import { Button, type ButtonSize, type ButtonVariant } from "$lib/components/ui/button/index.js";
  import { createCopyState } from "$lib/core/helpers/clipboard.svelte";
  import { m } from "$lib/paraglide/messages";

  type Props = {
    /** Text to copy; a function is read when the button is clicked. */
    text: string | (() => string);
    /** Accessible name, and the visible label when `showLabel` is set. */
    label?: string;
    showLabel?: boolean;
    variant?: ButtonVariant;
    size?: ButtonSize;
    disabled?: boolean;
    class?: string;
    /** Runs after a successful copy, e.g. to show a toast. */
    onCopied?: () => void;
    /** Other attributes, e.g. the props a Tooltip trigger passes to its child. */
    [attribute: string]: unknown;
  };

  let {
    text,
    label = m.copy_to_clipboard(),
    showLabel = false,
    variant = "ghost",
    size,
    disabled = false,
    class: className,
    onCopied,
    ...restProps
  }: Props = $props();

  const clipboard = createCopyState();
</script>

<Button
  type="button"
  {variant}
  size={size ?? (showLabel ? "default" : "icon")}
  {disabled}
  class={className}
  aria-label={showLabel ? undefined : label}
  {...restProps}
  onclick={async () => {
    if (await clipboard.copy(typeof text === "function" ? text() : text)) onCopied?.();
  }}
>
  {#if clipboard.copied}
    <Check aria-hidden="true" />
  {:else}
    <Copy aria-hidden="true" />
  {/if}
  {#if showLabel}
    {clipboard.copied ? m.copied() : label}
  {/if}
</Button>
<span class="sr-only" aria-live="polite">{clipboard.copied ? m.copied() : ""}</span>
