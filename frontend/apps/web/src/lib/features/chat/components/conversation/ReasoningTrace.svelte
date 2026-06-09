<!--
  Copyright (c) 2026 Sundsvalls Kommun

  Collapsible "chain of thought" trace for an assistant turn. Folds the tool
  activity into a single row that auto-expands while the assistant is working
  and collapses once the answer starts arriving — the user can toggle it.

  Pending tool approvals are NOT rendered here; they stay as prominent cards in
  MessageAnswer.svelte so a blocking decision is never hidden inside the trace.
-->
<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import { slide } from "svelte/transition";
  import { Wrench, ChevronDown, Loader2 } from "lucide-svelte";
  import ReasoningToolStep from "./ReasoningToolStep.svelte";

  type Step = {
    toolName: string;
    serverName: string;
    args?: Record<string, unknown>;
    status: "running" | "complete" | "denied";
  };

  let {
    steps,
    working = false
  }: {
    steps: Step[];
    working?: boolean;
  } = $props();

  // Open while working; collapse once the answer arrives. A manual toggle wins
  // over the auto behaviour for the rest of the turn.
  let manualOpen = $state<boolean | null>(null);
  const open = $derived(manualOpen ?? working);
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
      <span class="font-medium">{m.chat_reasoning_working()}</span>
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
      <div class="pt-2 pl-1">
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
    </div>
  {/if}
</div>
