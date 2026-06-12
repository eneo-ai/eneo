<!--
  Copyright (c) 2026 Sundsvalls Kommun

  A single tool call rendered as a self-contained card on the reasoning trace:
  header (icon + name + server + status badge) over a collapsible "Parameters"
  section. Presentational only — approval handling stays in MessageAnswer.svelte.
-->
<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import { Check, X, Loader2, ChevronRight, Wrench } from "lucide-svelte";

  type Status = "preparing" | "running" | "complete" | "failed" | "denied";

  let {
    toolName,
    serverName,
    args,
    status = "complete"
  }: {
    toolName: string;
    serverName: string;
    args?: Record<string, unknown>;
    status?: Status;
  } = $props();

  let argsOpen = $state(false);
  const hasArgs = $derived(args != null && Object.keys(args).length > 0);

  // Visuals per status: icon colour, badge label, and badge tone. Kept in one
  // map so the header and badge never drift out of sync.
  const ui = $derived(
    {
      preparing: {
        ring: "border-accent-default/40 bg-accent-dimmer text-accent-default",
        badge: "bg-accent-dimmer text-accent-default",
        label: m.chat_tool_status_preparing()
      },
      running: {
        ring: "border-accent-default/40 bg-accent-dimmer text-accent-default",
        badge: "bg-accent-dimmer text-accent-default",
        label: m.chat_reasoning_running()
      },
      complete: {
        ring: "border-positive-default/30 bg-positive-dimmer text-positive-default",
        badge: "bg-positive-dimmer text-positive-default",
        label: m.chat_tool_status_done()
      },
      failed: {
        ring: "border-negative-default/30 bg-negative-dimmer text-negative-default",
        badge: "bg-negative-dimmer text-negative-default",
        label: m.chat_tool_status_failed()
      },
      denied: {
        ring: "border-negative-default/30 bg-negative-dimmer text-negative-default",
        badge: "bg-negative-dimmer text-negative-default",
        label: m.tool_rejected_by_user()
      }
    }[status]
  );
</script>

<div class="border-dimmer bg-secondary/40 overflow-hidden rounded-lg border">
  <button
    type="button"
    class="flex w-full items-center gap-2.5 px-3 py-2 text-left {hasArgs
      ? 'cursor-pointer'
      : 'cursor-default'}"
    onclick={() => hasArgs && (argsOpen = !argsOpen)}
    disabled={!hasArgs}
  >
    <div class="flex h-6 w-6 shrink-0 items-center justify-center rounded-full border {ui.ring}">
      {#if status === "running" || status === "preparing"}
        <Loader2 class="h-3.5 w-3.5 animate-spin" />
      {:else if status === "complete"}
        <Check class="h-3.5 w-3.5" />
      {:else}
        <X class="h-3.5 w-3.5" />
      {/if}
    </div>

    <div class="flex min-w-0 flex-1 flex-col gap-0.5">
      <div class="flex items-center gap-2">
        <span class="text-secondary truncate text-sm font-medium">{toolName}</span>
        <span
          class="shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium tracking-wide uppercase {ui.badge}"
        >
          {ui.label}
        </span>
      </div>
      <span class="text-muted truncate text-xs">{serverName}</span>
    </div>

    {#if hasArgs}
      <ChevronRight
        class="text-muted h-4 w-4 shrink-0 transition-transform {argsOpen ? 'rotate-90' : ''}"
      />
    {/if}
  </button>

  {#if hasArgs && argsOpen}
    <div class="border-dimmer border-t px-3 py-2.5">
      <div class="text-muted mb-1.5 flex items-center gap-1.5 text-xs font-semibold">
        <Wrench class="h-3 w-3 shrink-0" />
        <span>{m.chat_reasoning_parameters()}</span>
      </div>
      <pre
        class="bg-primary/60 text-secondary overflow-x-auto rounded-md p-2.5 font-mono text-xs whitespace-pre-wrap">{JSON.stringify(
          args,
          null,
          2
        )}</pre>
    </div>
  {/if}
</div>
