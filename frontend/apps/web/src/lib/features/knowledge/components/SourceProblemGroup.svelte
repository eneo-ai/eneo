<script lang="ts">
  import type { Component, Snippet } from "svelte";
  import ChevronDown from "@lucide/svelte/icons/chevron-down";
  import * as Collapsible from "$lib/components/ui/collapsible/index.js";

  let {
    title,
    advice,
    countLabel,
    icon: Icon,
    tone = "warning",
    open = false,
    children
  }: {
    title: string;
    advice?: string | null;
    countLabel: string;
    icon: Component<{ class?: string; "aria-hidden"?: "true" }>;
    tone?: "warning" | "neutral";
    open?: boolean;
    children: Snippet;
  } = $props();
</script>

<Collapsible.Root {open} class="border-default border-b last:border-b-0">
  <Collapsible.Trigger
    class="hover:bg-hover-dimmer focus-visible:ring-stronger group flex w-full items-center gap-3 px-4 py-3 text-left focus-visible:ring-2 focus-visible:outline-none"
  >
    <span
      class="flex size-8 shrink-0 items-center justify-center rounded-md {tone === 'warning'
        ? 'bg-warning-dimmer text-warning-stronger'
        : 'bg-secondary text-secondary'}"
    >
      <Icon class="size-4" aria-hidden="true" />
    </span>
    <span class="flex min-w-0 flex-1 flex-col">
      <span class="font-medium">{title}</span>
      {#if advice}<span class="text-secondary text-sm">{advice}</span>{/if}
    </span>
    <span class="shrink-0 text-sm font-medium tabular-nums">{countLabel}</span>
    <ChevronDown
      class="text-secondary size-4 shrink-0 motion-safe:transition-transform group-data-[state=open]:rotate-180"
      aria-hidden="true"
    />
  </Collapsible.Trigger>
  <Collapsible.Content>{@render children()}</Collapsible.Content>
</Collapsible.Root>
