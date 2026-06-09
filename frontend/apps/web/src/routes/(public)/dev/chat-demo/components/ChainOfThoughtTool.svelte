<!-- eslint-disable intric/no-hardcoded-text -->
<!--
  PROTOTYPE — a tool call rendered as a step on the Chain of Thought timeline.
  Mirrors the data Eneo already has in MessageAnswer.svelte (tool_name,
  server_name, arguments, approved) but interleaved into the reasoning trace
  instead of stacked above the answer.

  Planning artifact under /dev/chat-demo (see README.md). Not production code.
-->
<script lang="ts">
  import { ChevronRight, ArrowRight } from "lucide-svelte";
  import type { ComponentType } from "svelte";
  import ChainOfThoughtStep from "./ChainOfThoughtStep.svelte";

  type Status = "pending" | "active" | "complete" | "denied";

  let {
    label,
    icon,
    server,
    args,
    result,
    status = "complete",
    last = false
  }: {
    label: string;
    icon?: ComponentType;
    server: string;
    args?: Record<string, unknown>;
    result?: string;
    status?: Status;
    last?: boolean;
  } = $props();

  let argsOpen = $state(false);
  const hasArgs = $derived(args != null && Object.keys(args).length > 0);
</script>

<ChainOfThoughtStep {label} {icon} {status} {last}>
  <div class="flex flex-col gap-1.5">
    <span class="text-muted text-xs">{server}</span>

    {#if hasArgs}
      <button
        type="button"
        class="text-muted hover:text-secondary flex w-fit items-center gap-1 text-xs transition-colors"
        onclick={() => (argsOpen = !argsOpen)}
      >
        <ChevronRight class="h-3 w-3 transition-transform {argsOpen ? 'rotate-90' : ''}" />
        Visa anrop
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

    {#if status === "complete" && result}
      <span class="text-positive-default inline-flex items-center gap-1 text-xs">
        <ArrowRight class="h-3 w-3" />
        {result}
      </span>
    {:else if status === "denied"}
      <span class="text-negative-default text-xs">Nekades av användaren</span>
    {:else if status === "active"}
      <span class="text-muted text-xs">Kör…</span>
    {/if}
  </div>
</ChainOfThoughtStep>
