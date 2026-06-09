<!-- eslint-disable intric/no-hardcoded-text -->
<!--
  PROTOTYPE — Chain of Thought reasoning block. Svelte port of the AI SDK
  Elements "Chain of Thought" UX (https://elements.ai-sdk.dev/components/chain-of-thought),
  rebuilt on Eneo's design tokens.

  Planning artifact under /dev/chat-demo (see README.md). In production the
  collapsible should be wired to the shared bits-ui primitive in
  lib/components/ui/collapsible for accessibility — here we inline a slide
  transition to keep the prototype self-contained.
-->
<script lang="ts">
  import { slide } from "svelte/transition";
  import { Brain, ChevronDown } from "lucide-svelte";
  import type { Snippet } from "svelte";

  let {
    title = "Reasoning",
    duration,
    streaming = false,
    open = $bindable(false),
    children
  }: {
    title?: string;
    duration?: number;
    streaming?: boolean;
    open?: boolean;
    children: Snippet;
  } = $props();
</script>

<div class="w-full">
  <button
    type="button"
    class="text-muted hover:text-secondary flex w-full items-center gap-2 rounded-md py-1.5 text-sm transition-colors"
    aria-expanded={open}
    onclick={() => (open = !open)}
  >
    <Brain class="h-4 w-4 shrink-0 {streaming ? 'text-accent-default animate-pulse' : ''}" />
    <span class="font-medium">
      {#if streaming}
        {title}…
      {:else if duration != null}
        Thought for {duration}s
      {:else}
        {title}
      {/if}
    </span>
    <ChevronDown
      class="ml-auto h-4 w-4 shrink-0 transition-transform duration-200 {open ? 'rotate-180' : ''}"
    />
  </button>

  {#if open}
    <div transition:slide={{ duration: 200 }}>
      <div class="pt-2 pl-1">
        {@render children()}
      </div>
    </div>
  {/if}
</div>
