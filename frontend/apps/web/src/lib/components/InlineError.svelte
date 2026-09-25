<!--
  A failure shown where it happened, e.g. inside a dialog that stays open,
  and read out once when it appears. Not the destructive Alert: its text
  falls below 4.5:1 in dark mode.
-->
<script lang="ts">
  import type { Snippet } from "svelte";
  import CircleAlert from "@lucide/svelte/icons/circle-alert";
  import { cn } from "$lib/utils.js";

  type Props = {
    message?: string;
    /** Replaces `message` when the failure offers a way out, such as a button. */
    children?: Snippet;
    ref?: HTMLElement | null;
    class?: string;
  };

  let { message, children, ref = $bindable(null), class: className }: Props = $props();
</script>

<div
  bind:this={ref}
  role="alert"
  class={cn(
    "bg-negative-dimmer text-negative-stronger flex items-start gap-2 rounded-lg p-3 text-sm",
    className
  )}
>
  <CircleAlert class="mt-0.5 size-4 shrink-0" aria-hidden="true" />
  {#if children}
    <div class="flex min-w-0 flex-col items-start gap-2">{@render children()}</div>
  {:else}
    <p class="min-w-0">{message}</p>
  {/if}
</div>
