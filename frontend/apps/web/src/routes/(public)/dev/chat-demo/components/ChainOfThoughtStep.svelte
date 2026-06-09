<!-- eslint-disable intric/no-hardcoded-text -->
<!--
  PROTOTYPE — single reasoning step on the Chain of Thought timeline.
  Planning artifact under /dev/chat-demo (see README.md). Not production code.
-->
<script lang="ts">
  import { Check, Loader2, X } from "lucide-svelte";
  import type { ComponentType, Snippet } from "svelte";

  type Status = "pending" | "active" | "complete" | "denied";

  let {
    label,
    status = "complete",
    icon,
    last = false,
    children
  }: {
    label: string;
    status?: Status;
    icon?: ComponentType;
    last?: boolean;
    children?: Snippet;
  } = $props();

  const Icon = $derived(icon);
</script>

<div class="relative flex gap-3 pb-4">
  {#if !last}
    <!-- connector rail between nodes -->
    <div class="border-dimmer absolute top-6 left-[11px] h-full border-l" aria-hidden="true"></div>
  {/if}

  <!-- status node -->
  <div
    class="relative z-10 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border transition-colors duration-200 {status ===
    'complete'
      ? 'border-positive-default/30 bg-positive-dimmer text-positive-default'
      : status === 'denied'
        ? 'border-negative-default/30 bg-negative-dimmer text-negative-default'
        : status === 'active'
          ? 'border-accent-default/40 bg-accent-dimmer text-accent-default'
          : 'border-default bg-secondary text-muted'}"
  >
    {#if status === "active"}
      <Loader2 class="h-3.5 w-3.5 animate-spin" />
    {:else if status === "complete"}
      <Check class="h-3.5 w-3.5" />
    {:else if status === "denied"}
      <X class="h-3.5 w-3.5" />
    {:else if Icon}
      <Icon class="h-3.5 w-3.5" />
    {/if}
  </div>

  <!-- label + optional content -->
  <div class="flex min-w-0 flex-1 flex-col gap-1.5 pt-0.5">
    <span
      class="text-sm transition-colors duration-200 {status === 'pending'
        ? 'text-muted'
        : 'text-secondary'} {status === 'active' ? 'font-medium' : ''}"
    >
      {label}
    </span>
    {#if children}
      <div class="text-muted text-sm">
        {@render children()}
      </div>
    {/if}
  </div>
</div>
