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
  import { getIntric } from "$lib/core/Intric";
  import { getChatService } from "../../ChatService.svelte";

  type ToolCall = {
    server_name: string;
    tool_name: string;
    title?: string | null;
    arguments?: Record<string, unknown>;
    tool_call_id?: string;
    approved?: boolean;
    result?: string | null;
    result_status?: string | null;
    mcp_tool_name?: string | null;
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

  const intric = getIntric();
  const chat = getChatService();

  const hasArgs = $derived(!!call.arguments && Object.keys(call.arguments).length > 0);
  // Result may be preloaded (historic Message) OR fetched lazily on first
  // expand of the inner "Visa svar" panel. We keep a local override so
  // refetches don't mutate the upstream message object.
  let lazyResult = $state<string | null>(null);
  let lazyLoading = $state(false);
  let lazyError = $state<string | null>(null);
  const effectiveResult = $derived(call.result ?? lazyResult);
  const hasResult = $derived(!!effectiveResult && effectiveResult.trim().length > 0);
  // Only allow lazy-loading after the stream completes — tool results are
  // persisted at stream end, so mid-stream fetches would 404.
  const canLoadResult = $derived(
    !hasResult &&
      !!call.tool_call_id &&
      !!chat.currentConversation?.id &&
      !chat.askQuestion.isLoading
  );

  // Pending rows auto-open so the user sees args + Approve/Deny without
  // hunting for the chevron. We capture the INITIAL pending state only via
  // ``untrack`` — once the user approves/denies, ``isPending`` flips false
  // but we don't want the row to snap shut from under their cursor.
  let open = $state(untrack(() => isPending));
  let responseOpen = $state(false);

  async function loadResult() {
    if (!canLoadResult || lazyLoading) return;
    const sessionId = chat.currentConversation?.id;
    const toolCallId = call.tool_call_id;
    if (!sessionId || !toolCallId) return;
    lazyLoading = true;
    lazyError = null;
    try {
      const res = await intric.conversations.getToolCallResult({
        sessionId,
        toolCallId
      });
      lazyResult = res.result ?? "";
    } catch (e) {
      console.error("Failed to fetch tool call result", e);
      lazyError = e instanceof Error ? e.message : String(e);
    } finally {
      lazyLoading = false;
    }
  }

  function onResponseToggle(next: boolean) {
    responseOpen = next;
    if (next && !hasResult && canLoadResult) {
      loadResult();
    }
  }
</script>

<Collapsible.Root bind:open class={shouldPulse ? "animate-pulse" : ""}>
  <Collapsible.Trigger
    class="group/row hover:bg-hover-dimmer flex w-full items-center gap-2 px-3 py-1 text-left transition-colors disabled:cursor-default disabled:opacity-100"
    disabled={!hasArgs && !isPending && !hasResult && !canLoadResult}
  >
    <Wrench
      class="h-3.5 w-3.5 shrink-0 {isDenied
        ? 'text-negative-default'
        : isApproved
          ? 'text-positive-default'
          : 'text-accent-default'}"
    />

    <span class="text-default min-w-0 truncate text-sm font-medium">
      {call.title ?? call.tool_name}
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
        aria-label={m.tool_approved()}
      >
        <Check class="h-2.5 w-2.5" />
      </span>
    {/if}

    {#if hasArgs || isPending || hasResult || canLoadResult}
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

    {#if hasResult || canLoadResult}
      <Collapsible.Root bind:open={responseOpen} onOpenChange={onResponseToggle}>
        <Collapsible.Trigger
          class="group/result border-dimmer hover:bg-hover-dimmer flex w-full items-center gap-2 border-t px-3 py-1.5 text-left transition-colors"
        >
          <ChevronRight
            class="text-muted h-3.5 w-3.5 shrink-0 transition-transform duration-200 group-data-[state=open]/result:rotate-90"
          />
          <span class="text-muted text-[10px] font-semibold tracking-wider uppercase">
            {m.mcp_tool_response_view()}
          </span>
          {#if lazyLoading}
            <span class="text-muted ml-auto text-[10px]">…</span>
          {/if}
        </Collapsible.Trigger>
        <Collapsible.Content>
          <div class="border-dimmer space-y-1 border-t px-3 py-2">
            {#if lazyLoading && !hasResult}
              <p class="text-muted text-xs italic">…</p>
            {:else if lazyError && !hasResult}
              <p class="text-negative-default text-xs">{lazyError}</p>
            {:else}
              <pre
                class="text-secondary max-h-72 overflow-auto font-mono text-xs leading-snug break-words whitespace-pre-wrap">{effectiveResult}</pre>
            {/if}
          </div>
        </Collapsible.Content>
      </Collapsible.Root>
    {/if}

    {#if isPending && call.tool_call_id}
      <div class="border-dimmer flex items-center gap-2 border-t px-3 py-1.5">
        <span class="text-muted mr-auto text-xs">{m.tool_pending_approval()}</span>
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
