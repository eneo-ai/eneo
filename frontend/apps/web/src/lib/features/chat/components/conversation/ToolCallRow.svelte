<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import * as Collapsible from "$lib/components/ui/collapsible/index.js";
  import { m } from "$lib/paraglide/messages";
  import { Check, ChevronRight, Wrench, X } from "lucide-svelte";
  import { untrack } from "svelte";
  import { formatToolArgValue } from "./toolCallFormatting";

  type ToolCall = {
    server_name: string;
    tool_name: string;
    arguments?: Record<string, unknown>;
    tool_call_id?: string;
    approved?: boolean;
  };

  type Props = {
    call: ToolCall;
    isPending: boolean;
    isDenied: boolean;
    isApproved: boolean;
    isSubmitting: boolean;
    shouldPulse: boolean;
    onApprove: (toolCallId: string) => void;
    onDeny: (toolCallId: string) => void;
  };

  const {
    call,
    isPending,
    isDenied,
    isApproved,
    isSubmitting,
    shouldPulse,
    onApprove,
    onDeny
  }: Props = $props();

  const hasArgs = $derived(!!call.arguments && Object.keys(call.arguments).length > 0);
  // Pending rows auto-open so the user sees args + Approve/Deny without
  // hunting for the chevron. We capture the INITIAL pending state only via
  // ``untrack`` — once the user approves/denies, ``isPending`` flips false
  // but we don't want the row to snap shut from under their cursor.
  let open = $state(untrack(() => isPending));
</script>

<Collapsible.Root bind:open class={shouldPulse ? "animate-pulse" : ""}>
  <Collapsible.Trigger
    class="group/row hover:bg-hover-dimmer flex w-full items-center gap-2 px-3 py-1 text-left transition-colors disabled:cursor-default disabled:opacity-100"
    disabled={!hasArgs && !isPending}
  >
    <Wrench
      class="h-3.5 w-3.5 shrink-0 {isDenied
        ? 'text-negative-default'
        : isApproved
          ? 'text-positive-default'
          : 'text-accent-default'}"
    />

    <span class="text-default min-w-0 truncate text-sm font-medium">
      {call.tool_name}
    </span>
    <span class="text-muted truncate text-xs">· {call.server_name}</span>

    <span class="flex-1"></span>

    {#if isDenied}
      <span
        class="bg-negative-dimmer text-negative-default inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium tracking-wide uppercase"
      >
        {m.tool_rejected_by_user()}
      </span>
    {:else if isApproved}
      <span
        class="bg-positive-dimmer text-positive-default inline-flex h-3.5 w-3.5 items-center justify-center rounded"
        aria-label="Godkänt"
      >
        <Check class="h-2.5 w-2.5" />
      </span>
    {/if}

    {#if hasArgs || isPending}
      <ChevronRight
        class="text-muted h-3.5 w-3.5 shrink-0 transition-transform duration-200 {open
          ? 'rotate-90'
          : ''}"
      />
    {/if}
  </Collapsible.Trigger>

  <Collapsible.Content>
    {#if hasArgs}
      <div class="border-dimmer space-y-2 border-t px-3 py-2">
        {#each Object.entries(call.arguments ?? {}) as [argKey, argValue] (argKey)}
          <div class="space-y-0.5">
            <span class="text-muted block text-[10px] font-semibold tracking-wider uppercase">
              {argKey}:
            </span>
            <pre
              class="text-secondary overflow-x-auto font-mono text-xs leading-snug break-words whitespace-pre-wrap">{formatToolArgValue(
                argValue
              )}</pre>
          </div>
        {/each}
      </div>
    {/if}

    {#if isPending && call.tool_call_id}
      <div class="border-dimmer flex items-center gap-2 border-t px-3 py-1.5">
        <span class="text-muted mr-auto text-xs">Väntar på godkännande</span>
        <button
          type="button"
          class="bg-positive-default text-on-fill hover:bg-positive-stronger inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium shadow-sm transition-colors disabled:opacity-50"
          onclick={() => onApprove(call.tool_call_id!)}
          disabled={isSubmitting}
        >
          <Check class="h-3.5 w-3.5" />
          {m.tool_accept()}
        </button>
        <button
          type="button"
          class="border-default bg-primary text-secondary hover:bg-hover-default inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs font-medium shadow-sm transition-colors disabled:opacity-50"
          onclick={() => onDeny(call.tool_call_id!)}
          disabled={isSubmitting}
        >
          <X class="h-3.5 w-3.5" />
          {m.tool_deny()}
        </button>
      </div>
    {/if}
  </Collapsible.Content>
</Collapsible.Root>
