<!--
  Copyright (c) 2026 Sundsvalls Kommun

  Collapsible "chain of thought" trace for an assistant turn. Folds the model's
  reasoning/thinking text and tool activity into a single row that auto-expands
  while the assistant works and collapses once the answer starts arriving — the
  user can toggle it. The header shows "Thought for Ns" once the turn is done.

  Pending tool approvals are NOT rendered here; they stay as prominent cards in
  MessageAnswer.svelte so a blocking decision is never hidden inside the trace.
-->
<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import { slide } from "svelte/transition";
  import { Wrench, Brain, ChevronDown, Loader2 } from "lucide-svelte";
  import ReasoningToolStep from "./ReasoningToolStep.svelte";

  type Step = {
    toolName: string;
    serverName: string;
    args?: Record<string, unknown>;
    toolCallId?: string;
    status: "preparing" | "running" | "complete" | "failed" | "denied";
  };

  let {
    steps = [],
    reasoning = "",
    working = false,
    loadToolResult
  }: {
    steps?: Step[];
    reasoning?: string;
    working?: boolean;
    loadToolResult?: (toolCallId: string) => Promise<string | null>;
  } = $props();

  const hasReasoning = $derived(reasoning.trim().length > 0);

  // Label each part as its own section only when both kinds of content are
  // present — a mixed trace reads as distinct "Reasoning" / "Tools" sections,
  // while a single-kind trace stays unlabelled (the collapsed header names it).
  const showSections = $derived(hasReasoning && steps.length > 0);

  // Open while working; collapse once the answer arrives. A manual toggle wins
  // over the auto behaviour for the rest of the turn.
  let manualOpen = $state<boolean | null>(null);
  const open = $derived(manualOpen ?? working);

  // Time spent working, for the "Thought for Ns" summary. Started when work
  // begins and frozen the first time work stops.
  let startMs: number | null = null;
  let elapsedSec = $state<number | null>(null);
  $effect(() => {
    if (working) {
      if (startMs === null) startMs = performance.now();
    } else if (startMs !== null && elapsedSec === null) {
      elapsedSec = Math.max(1, Math.round((performance.now() - startMs) / 1000));
    }
  });
</script>

<div class="border-dimmer bg-secondary/40 rounded-xl border px-3 py-2">
  <button
    type="button"
    class="text-muted hover:text-secondary flex w-full items-center gap-2 py-1 text-sm transition-colors"
    aria-expanded={open}
    onclick={() => (manualOpen = !open)}
  >
    {#if working}
      <Loader2 class="text-accent-default h-4 w-4 shrink-0 animate-spin" />
      <span class="font-medium">{hasReasoning ? m.thinking() : m.chat_reasoning_working()}</span>
    {:else if hasReasoning}
      <Brain class="h-4 w-4 shrink-0" />
      <!-- elapsedSec only exists when this turn streamed live; a reloaded
           conversation has no timing, so fall back to the plain noun label. -->
      <span class="font-medium">
        {elapsedSec ? m.chat_reasoning_thought_for({ seconds: elapsedSec }) : m.reasoning()}
      </span>
    {:else}
      <Wrench class="h-4 w-4 shrink-0" />
      <span class="font-medium">{m.chat_reasoning_tools_label()}</span>
    {/if}

    <!-- Tool-activity count, shown additively alongside the reasoning/working
         summary so tool usage never disappears behind the "Thought for Ns"
         label. The pure-tools branch above already carries the wrench as its
         primary label, so the badge only repeats the icon in the other cases. -->
    {#if steps.length > 0}
      <span
        class="border-default bg-primary text-muted flex items-center gap-1 rounded-full border px-1.5 py-0.5 text-xs leading-none"
      >
        {#if working || hasReasoning}
          <Wrench class="h-3 w-3 shrink-0" />
        {/if}
        {steps.length}
      </span>
    {/if}
    <ChevronDown
      class="ml-auto h-4 w-4 shrink-0 transition-transform duration-200 {open ? 'rotate-180' : ''}"
    />
  </button>

  {#if open}
    <div transition:slide={{ duration: 200 }}>
      <div class="flex flex-col gap-4 pt-2 pl-1">
        {#if hasReasoning}
          <div class="flex flex-col gap-1.5">
            {#if showSections}
              <div class="text-muted flex items-center gap-1.5 text-xs font-semibold">
                <Brain class="h-3.5 w-3.5 shrink-0" />
                <span>{m.reasoning()}</span>
              </div>
            {/if}
            <div
              class="border-dimmer text-muted border-l-2 pl-3 text-sm leading-relaxed whitespace-pre-wrap"
            >
              {reasoning}
            </div>
          </div>
        {/if}

        {#if steps.length > 0}
          <div class="flex flex-col gap-1.5">
            {#if showSections}
              <div class="text-muted flex items-center gap-1.5 text-xs font-semibold">
                <Wrench class="h-3.5 w-3.5 shrink-0" />
                <span>{m.chat_reasoning_tools_label()}</span>
              </div>
            {/if}
            <div class="flex flex-col gap-2">
              {#each steps as step, i (step.toolName + i)}
                <ReasoningToolStep
                  toolName={step.toolName}
                  serverName={step.serverName}
                  args={step.args}
                  toolCallId={step.toolCallId}
                  status={step.status}
                  onLoadResult={loadToolResult && step.toolCallId
                    ? () => loadToolResult(step.toolCallId!)
                    : undefined}
                />
              {/each}
            </div>
          </div>
        {/if}
      </div>
    </div>
  {/if}
</div>
