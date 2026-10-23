<!--
  Copyright (c) 2026 Sundsvalls Kommun

  The glyph of a function step: the function's icon on a small tinted chip,
  the same icon the admin and settings surfaces show for that function. The
  chip turns negative for a call that failed or was refused. Context steps
  (knowledge, files) carry no chip, so a function step reads as work done
  rather than as a lookup.
-->
<script lang="ts">
  import type { CapabilityDescriptor } from "$lib/features/mcp/capabilities";
  import { X } from "@lucide/svelte";

  let {
    icon,
    tone = "default",
    class: className = ""
  }: {
    icon: CapabilityDescriptor["icon"];
    tone?: "default" | "negative";
    class?: string;
  } = $props();

  const Icon = $derived(icon);
</script>

<span
  class="flex size-5 shrink-0 items-center justify-center rounded-md {tone === 'negative'
    ? 'bg-negative-dimmer text-negative-default'
    : 'bg-accent-dimmer text-accent-default'} {className}"
  aria-hidden="true"
>
  {#if tone === "negative"}
    <X class="size-3" />
  {:else}
    <Icon class="size-3" />
  {/if}
</span>
