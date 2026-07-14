<!--
  Copyright (c) 2026 Sundsvalls Kommun

  Licensed under the MIT License.

  One collapsible section of the chat debug panel.
-->

<script lang="ts">
  import type { Snippet } from "svelte";
  import { ChevronRight } from "lucide-svelte";

  let {
    title,
    count = null,
    defaultOpen = false,
    children
  }: {
    title: string;
    /** Optional badge, e.g. number of tool calls in the section. */
    count?: number | null;
    defaultOpen?: boolean;
    children: Snippet;
  } = $props();

  // Initial value only by design: the section owns its open state after mount.
  // svelte-ignore state_referenced_locally
  let open = $state(defaultOpen);
</script>

<div class="border-dimmer border-b last:border-b-0">
  <button
    type="button"
    class="text-default hover:bg-hover-dimmer flex w-full items-center gap-1.5 px-3 py-2.5 text-sm font-medium transition-colors"
    onclick={() => (open = !open)}
    aria-expanded={open}
  >
    <ChevronRight
      class="text-muted h-3.5 w-3.5 shrink-0 transition-transform {open ? 'rotate-90' : ''}"
    />
    <span class="truncate">{title}</span>
    {#if count !== null}
      <span
        class="border-default bg-primary text-muted rounded-full border px-1.5 py-0.5 text-xs leading-none"
      >
        {count}
      </span>
    {/if}
  </button>
  {#if open}
    <div class="flex flex-col gap-2 px-3 pb-3">
      {@render children()}
    </div>
  {/if}
</div>
