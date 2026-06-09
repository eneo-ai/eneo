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
    status: "running" | "complete" | "denied";
  };

  let {
    steps = [],
    reasoning = "",
    working = false
  }: {
    steps?: Step[];
    reasoning?: string;
    working?: boolean;
  } = $props();

  const hasReasoning = $derived(reasoning.trim().length > 0);

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
      <span class="font-medium">
        {elapsedSec ? m.chat_reasoning_thought_for({ seconds: elapsedSec }) : m.thinking()}
      </span>
    {:else}
      <Wrench class="h-4 w-4 shrink-0" />
      <span class="font-medium">{m.chat_reasoning_tools_label()}</span>
      <span
        class="border-default bg-primary text-muted rounded-full border px-1.5 py-0.5 text-xs leading-none"
      >
        {steps.length}
      </span>
    {/if}
    <ChevronDown
      class="ml-auto h-4 w-4 shrink-0 transition-transform duration-200 {open ? 'rotate-180' : ''}"
    />
  </button>

  {#if open}
    <div transition:slide={{ duration: 200 }}>
      <div class="flex flex-col gap-3 pt-2 pl-1">
        {#if hasReasoning}
          <div
            class="border-dimmer text-muted border-l-2 pl-3 text-sm leading-relaxed whitespace-pre-wrap"
          >
            {reasoning}
          </div>
        {/if}

        {#if steps.length > 0}
          <div>
            {#each steps as step, i (step.toolName + i)}
              <ReasoningToolStep
                toolName={step.toolName}
                serverName={step.serverName}
                args={step.args}
                status={step.status}
                last={i === steps.length - 1}
              />
            {/each}
          </div>
        {/if}
      </div>
    </div>
  {/if}
</div>
