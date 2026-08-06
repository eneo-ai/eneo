<!--
  Copyright (c) 2026 Sundsvalls Kommun

  A call to one of Eneo's built-in loopback tools, rendered with a thinking-
  like footprint instead of a tool card: a shimmer line while running
  ("Söker kunskap…"), collapsing to a muted past-tense line when done
  ("Sökte i kunskap") that expands to parameters and result on click.
  External MCP tools keep their ReasoningToolStep cards.
-->
<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import { ChevronRight, X } from "lucide-svelte";
  import ShimmerText from "./ShimmerText.svelte";
  import ToolCallDetailsPanel from "./ToolCallDetailsPanel.svelte";

  type Status = "preparing" | "running" | "complete" | "failed" | "denied";

  let {
    runningLabel,
    doneLabel,
    serverName,
    detail = null,
    args,
    toolCallId,
    onLoadResult,
    status
  }: {
    /** Present-tense label without ellipsis, e.g. "Söker kunskap". */
    runningLabel: string;
    /** Past-tense label, e.g. "Sökte i kunskap". */
    doneLabel: string;
    /** Localized server label ("Kunskap"), used in the result heading. */
    serverName: string;
    /** Extra context for the call, e.g. a filename or search query. */
    detail?: string | null;
    args?: Record<string, unknown>;
    toolCallId?: string;
    onLoadResult?: () => Promise<string | null>;
    status: Status;
  } = $props();

  let open = $state(false);
  const isActive = $derived(status === "preparing" || status === "running");
  const isNegative = $derived(status === "failed" || status === "denied");
  const hasArgs = $derived(args != null && Object.keys(args).length > 0);
  const canViewResult = $derived(
    !!toolCallId && !!onLoadResult && (status === "complete" || status === "failed")
  );
  const canExpand = $derived(!isActive && (hasArgs || canViewResult));
</script>

{#if isActive}
  <div
    class="flex w-fit min-w-0 max-w-full items-center gap-2 text-sm leading-tight"
    role="status"
    aria-label={runningLabel}
  >
    <ShimmerText text={`${runningLabel}…`} />
    {#if detail}
      <span class="text-muted min-w-0 truncate text-xs">{detail}</span>
    {/if}
  </div>
{:else}
  <div>
    <button
      type="button"
      class="text-muted hover:text-secondary group flex w-fit max-w-full items-center gap-1.5 text-sm leading-tight transition-colors {canExpand
        ? 'cursor-pointer'
        : 'cursor-default'}"
      onclick={() => {
        if (canExpand) open = !open;
      }}
      disabled={!canExpand}
      aria-expanded={open}
    >
      {#if isNegative}
        <X class="text-negative-default h-3.5 w-3.5 shrink-0" />
      {/if}
      <span class="truncate">{doneLabel}</span>
      {#if detail}
        <span class="min-w-0 truncate text-xs opacity-70">{detail}</span>
      {/if}
      {#if isNegative}
        <span class="text-negative-default shrink-0 text-xs">
          {status === "denied" ? m.tool_rejected_by_user() : m.chat_tool_status_failed()}
        </span>
      {/if}
      {#if canExpand}
        <ChevronRight
          class="h-3.5 w-3.5 shrink-0 transition-transform {open
            ? 'rotate-90 opacity-100'
            : 'opacity-0 group-hover:opacity-100'}"
        />
      {/if}
    </button>

    <ToolCallDetailsPanel
      {open}
      toolName={serverName}
      {args}
      {toolCallId}
      {onLoadResult}
      {status}
      containerClass="border-dimmer bg-secondary/40 mt-1 mb-1 rounded-lg border px-3 py-2.5"
    />
  </div>
{/if}
