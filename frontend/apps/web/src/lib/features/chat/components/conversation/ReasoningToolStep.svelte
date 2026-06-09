<!--
  Copyright (c) 2026 Sundsvalls Kommun

  A single tool call rendered as a step on the reasoning trace timeline.
  Presentational only — approval handling stays in MessageAnswer.svelte.
-->
<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import { Check, X, Loader2, ChevronRight } from "lucide-svelte";

  type Status = "running" | "complete" | "denied";

  let {
    toolName,
    serverName,
    args,
    status = "complete",
    last = false
  }: {
    toolName: string;
    serverName: string;
    args?: Record<string, unknown>;
    status?: Status;
    last?: boolean;
  } = $props();

  let argsOpen = $state(false);
  const hasArgs = $derived(args != null && Object.keys(args).length > 0);
</script>

<div class="relative flex gap-3 pb-3 last:pb-0">
  {#if !last}
    <div class="border-dimmer absolute top-6 left-[11px] h-full border-l" aria-hidden="true"></div>
  {/if}

  <div
    class="relative z-10 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border {status ===
    'denied'
      ? 'border-negative-default/30 bg-negative-dimmer text-negative-default'
      : status === 'running'
        ? 'border-accent-default/40 bg-accent-dimmer text-accent-default'
        : 'border-positive-default/30 bg-positive-dimmer text-positive-default'}"
  >
    {#if status === "running"}
      <Loader2 class="h-3.5 w-3.5 animate-spin" />
    {:else if status === "denied"}
      <X class="h-3.5 w-3.5" />
    {:else}
      <Check class="h-3.5 w-3.5" />
    {/if}
  </div>

  <div class="flex min-w-0 flex-1 flex-col gap-1 pt-0.5">
    <div class="flex items-center gap-2">
      <span class="text-secondary truncate text-sm font-medium">{toolName}</span>
      {#if status === "denied"}
        <span
          class="bg-negative-dimmer text-negative-default rounded px-1.5 py-0.5 text-[10px] font-medium tracking-wide uppercase"
        >
          {m.tool_rejected_by_user()}
        </span>
      {/if}
    </div>
    <span class="text-muted text-xs">{serverName}</span>

    {#if hasArgs}
      <button
        type="button"
        class="text-muted hover:text-secondary flex w-fit items-center gap-1 text-xs transition-colors"
        onclick={() => (argsOpen = !argsOpen)}
      >
        <ChevronRight class="h-3 w-3 transition-transform {argsOpen ? 'rotate-90' : ''}" />
        {m.chat_reasoning_show_call()}
      </button>
      {#if argsOpen}
        <pre
          class="bg-secondary text-secondary overflow-x-auto rounded-md p-2 font-mono text-xs whitespace-pre-wrap">{JSON.stringify(
            args,
            null,
            2
          )}</pre>
      {/if}
    {/if}

    {#if status === "running"}
      <span class="text-muted text-xs">{m.chat_reasoning_running()}</span>
    {/if}
  </div>
</div>
