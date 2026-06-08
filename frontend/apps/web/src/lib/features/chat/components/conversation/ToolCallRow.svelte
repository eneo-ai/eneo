<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import * as Collapsible from "$lib/components/ui/collapsible/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { m } from "$lib/paraglide/messages";
  import {
    Check,
    ChevronDown,
    ChevronRight,
    ChevronUp,
    CircleCheck,
    CircleX,
    Clock,
    Wrench,
    X
  } from "lucide-svelte";
  import { untrack } from "svelte";
  import { formatToolArgs, formatToolChangePreview, formatToolResult } from "./toolCallFormatting";
  import { getIntric } from "$lib/core/Intric";
  import { getChatService, type ElicitationState } from "../../ChatService.svelte";
  import MessageElicitation from "./MessageElicitation.svelte";

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
    elicitation?: ElicitationState | null;
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

  // shadcn's `default` button maps to eneo's accent (blue); confirmations use a
  // soft tonal positive (green) treatment instead — matching the elicitation
  // confirm button.
  const confirmClass =
    "bg-positive-dimmer text-positive-stronger hover:bg-positive-dimmer/60 border-positive-stronger/25";

  const hasArgs = $derived(!!call.arguments && Object.keys(call.arguments).length > 0);
  // Result may be preloaded (historic Message) OR fetched lazily on first
  // expand of the inner response panel. We keep a local override so refetches
  // don't mutate the upstream message object.
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
  // While confirming a change we show a clamped preview of the args (see below);
  // this lets the user expand it to the full value.
  let argsExpanded = $state(false);

  // A tool paused mid-execution to ask the user to confirm a change being made
  // (the new system prompt, say). The change lives in the args panel.
  const isElicitationPending = $derived(call.elicitation?.status === "pending");

  // Auto-open the row while the elicitation is pending so the user sees what they
  // are approving instead of a collapsed card. The args render as a short clamped
  // preview (with a fade + "show full change" toggle) so a long value can't bury
  // the confirm buttons below. Once they answer, collapse the row back so the
  // resolved change tucks away.
  let sawPendingElicitation = false;
  $effect(() => {
    if (isElicitationPending) {
      open = true;
      sawPendingElicitation = true;
    } else if (sawPendingElicitation) {
      open = false;
      sawPendingElicitation = false;
    }
  });

  // A single status reflected as a shadcn Badge in the header (ai-elements style).
  const badgeState = $derived(
    isDenied
      ? "denied"
      : isApproved
        ? "approved"
        : isPending
          ? "pending-approval"
          : isElicitationPending
            ? "awaiting-confirmation"
            : shouldPulse
              ? "running"
              : hasResult
                ? "completed"
                : null
  );

  // An ask-the-user elicitation (free-text/choice question) renders the question
  // and options in its own card, so the args panel would just echo them — hide it.
  // A pure-confirm elicitation has no answer field, and its args ARE the change
  // being confirmed, so those stay visible.
  const hideArgs = $derived(isElicitationPending && !!call.elicitation?.answerField);
  const showArgs = $derived(hasArgs && !hideArgs);

  // While confirming a change, preview just the new content (the prompt/name);
  // for plain inspection show the full structured arguments.
  const argsText = $derived(
    isElicitationPending
      ? formatToolChangePreview(call.arguments ?? {})
      : formatToolArgs(call.arguments ?? {})
  );

  const hasContent = $derived(
    showArgs || isPending || hasResult || canLoadResult || !!call.elicitation
  );

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

<Collapsible.Root bind:open class={shouldPulse && !isElicitationPending ? "animate-pulse" : ""}>
  <Collapsible.Trigger
    class="group/row hover:bg-hover-dimmer flex w-full items-center gap-2 p-3 text-left transition-colors disabled:cursor-default disabled:opacity-100"
    disabled={!hasContent}
  >
    <Wrench class="text-muted-foreground size-4 shrink-0" />

    <span class="text-foreground min-w-0 truncate text-sm font-medium">
      {call.title ?? call.tool_name}
    </span>
    <span class="text-muted-foreground truncate text-xs">· {call.server_name}</span>

    {#if badgeState}
      <Badge variant="secondary" class="gap-1.5 rounded-full font-normal">
        {#if badgeState === "denied"}
          <CircleX class="text-negative-default" />
          {m.tool_rejected_by_user()}
        {:else if badgeState === "approved"}
          <CircleCheck class="text-positive-default" />
          {m.tool_approved()}
        {:else if badgeState === "pending-approval"}
          <Clock class="text-caution" />
          {m.tool_pending_approval()}
        {:else if badgeState === "awaiting-confirmation"}
          <Clock class="text-caution" />
          {m.tool_awaiting_confirmation()}
        {:else if badgeState === "running"}
          <Clock class="text-caution animate-pulse" />
          {m.tool_running()}
        {:else if badgeState === "completed"}
          <CircleCheck class="text-positive-default" />
          {m.tool_completed()}
        {/if}
      </Badge>
    {/if}

    <span class="flex-1"></span>

    {#if hasContent}
      <ChevronDown
        class="text-muted-foreground size-4 shrink-0 transition-transform duration-200 {open
          ? 'rotate-180'
          : ''}"
      />
    {/if}
  </Collapsible.Trigger>

  <Collapsible.Content>
    <div class="space-y-3 px-3 pt-1 pb-3">
      {#if showArgs}
        {@const clampArgs = isElicitationPending && !argsExpanded}
        <div class="space-y-1.5">
          <div class="bg-muted/50 rounded-md p-3">
            <div
              class={clampArgs
                ? "max-h-32 overflow-hidden [mask-image:linear-gradient(to_bottom,black_55%,transparent)] [-webkit-mask-image:linear-gradient(to_bottom,black_55%,transparent)]"
                : isElicitationPending && argsExpanded
                  ? "max-h-72 overflow-auto"
                  : ""}
            >
              <pre
                class="text-foreground overflow-x-auto font-mono text-xs leading-snug break-words whitespace-pre-wrap">{argsText}</pre>
            </div>
          </div>
          {#if isElicitationPending}
            <button
              type="button"
              class="text-muted-foreground hover:text-foreground flex w-full items-center justify-center gap-1 text-[11px] font-medium transition-colors"
              onclick={() => (argsExpanded = !argsExpanded)}
            >
              {#if argsExpanded}
                <ChevronUp class="h-3 w-3" />
                {m.elicitation_show_less()}
              {:else}
                <ChevronDown class="h-3 w-3" />
                {m.elicitation_show_full_change()}
              {/if}
            </button>
          {/if}
        </div>
      {/if}

      {#if hasResult || canLoadResult}
        <Collapsible.Root bind:open={responseOpen} onOpenChange={onResponseToggle}>
          <Collapsible.Trigger
            class="group/result text-muted-foreground hover:text-foreground flex w-full items-center gap-1.5 text-[10px] font-semibold tracking-wider uppercase transition-colors"
          >
            <ChevronRight
              class="size-3 shrink-0 transition-transform duration-200 group-data-[state=open]/result:rotate-90"
            />
            {m.mcp_tool_response_view()}
            {#if lazyLoading}
              <span class="ml-auto">…</span>
            {/if}
          </Collapsible.Trigger>
          <Collapsible.Content>
            <div class="bg-muted/50 mt-1.5 rounded-md p-3">
              {#if lazyLoading && !hasResult}
                <p class="text-muted-foreground text-xs italic">…</p>
              {:else if lazyError && !hasResult}
                <p class="text-muted-foreground text-xs italic">{m.tool_no_response()}</p>
              {:else}
                <pre
                  class="text-foreground max-h-72 overflow-auto font-mono text-xs leading-snug break-words whitespace-pre-wrap">{formatToolResult(
                    effectiveResult ?? ""
                  )}</pre>
              {/if}
            </div>
          </Collapsible.Content>
        </Collapsible.Root>
      {/if}

      {#if call.elicitation}
        <MessageElicitation elicitation={call.elicitation} />
      {/if}

      {#if isPending && call.tool_call_id}
        <div class="flex items-center gap-2">
          <span class="text-muted-foreground mr-auto text-xs">{m.tool_pending_approval()}</span>
          <Button
            variant="outline"
            size="sm"
            disabled={isSubmitting}
            onclick={() => onDeny(call.tool_call_id!)}
          >
            <X />
            {m.tool_deny()}
          </Button>
          <Button
            size="sm"
            class={confirmClass}
            disabled={isSubmitting}
            onclick={() => onApprove(call.tool_call_id!)}
          >
            <Check />
            {m.tool_accept()}
          </Button>
        </div>
      {/if}
    </div>
  </Collapsible.Content>
</Collapsible.Root>
