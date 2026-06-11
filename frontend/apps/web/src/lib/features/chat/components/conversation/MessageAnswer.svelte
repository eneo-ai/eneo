<script lang="ts">
  import { Markdown } from "@intric/ui";
  import MessageIntricInfoBlob from "./MessageIntricInfoBlob.svelte";
  import ReasoningTrace from "./ReasoningTrace.svelte";
  import { dynamicColour } from "$lib/core/colours";
  import { IconSpeechBubble } from "@intric/icons/speech-bubble";
  import { formatEmojiTitle } from "$lib/core/formatting/formatEmojiTitle";
  import { getChatService } from "../../ChatService.svelte";
  import { getAttachmentUrlService } from "$lib/features/attachments/AttachmentUrlService.svelte";
  import { getMessageContext } from "../../MessageContext.svelte";
  import AsyncImage from "$lib/components/AsyncImage.svelte";
  import { m } from "$lib/paraglide/messages";
  import { ChevronRight, Check, X, Wrench } from "lucide-svelte";
  import { SvelteSet } from "svelte/reactivity";

  const chat = getChatService();
  const attachmentUrls = getAttachmentUrlService();

  const { current, isLast } = getMessageContext();
  const message = $derived(current());
  // Tools are still being executed if we're loading and no answer text has arrived yet
  const toolsStillExecuting = $derived(
    isLast() && chat.askQuestion.isLoading && message.answer.trim() === ""
  );
  // Looser gate than toolsStillExecuting: tool calls can interleave with answer
  // text (multi-round MCP), so "pending"/"approved" statuses stay live for the
  // whole streaming turn, not just until the first text chunk.
  const isStreamingTurn = $derived(isLast() && chat.askQuestion.isLoading);

  // Get MCP tool calls from the message
  // - mcp_tool_calls: runtime property added during streaming
  // - tool_calls: persisted field from API response (chat history)
  const mcpToolCalls = $derived(
    ((message as Record<string, unknown>).mcp_tool_calls ?? message.tool_calls) as
      | Array<{
          server_name: string;
          tool_name: string;
          arguments?: Record<string, unknown>;
          tool_call_id?: string;
          approved?: boolean;
          result_status?: string;
        }>
      | undefined
  );

  // Reasoning/thinking text for this message: accumulated by ChatService while
  // streaming, served from the persisted `reasoning` field on reload.
  const reasoningText = $derived(
    ((message as Record<string, unknown>).reasoning as string | null | undefined) ?? ""
  );

  // Check if there's a pending tool approval for this message (only on last message)
  const hasPendingApproval = $derived(isLast() && chat.pendingToolApproval !== null);

  // Get pending tool IDs for matching
  const pendingToolIds = $derived(chat.pendingToolApproval?.tools.map((t) => t.tool_call_id) ?? []);

  // Check if there are multiple pending tools (for showing bulk actions)
  const hasMultiplePendingTools = $derived(pendingToolIds.length > 1);

  // Track which tool calls have expanded arguments
  const expandedToolCalls = new SvelteSet<number>();
  const submittingToolIds = new SvelteSet<string>();
  const deniedToolIds = new SvelteSet<string>();
  let isSubmittingBulk = $state(false);

  // Split tool calls: pending approvals stay as prominent cards below (a
  // blocking decision must never hide); everything else (running, done, denied)
  // folds into the collapsible reasoning trace above them.
  const isPending = (tc: { tool_call_id?: string }) =>
    !!tc.tool_call_id && pendingToolIds.includes(tc.tool_call_id);
  const pendingToolCalls = $derived((mcpToolCalls ?? []).filter(isPending));
  const tracedToolCalls = $derived((mcpToolCalls ?? []).filter((tc) => !isPending(tc)));
  const tracedSteps = $derived(
    tracedToolCalls.map((tc, i) => {
      const denied =
        (!!tc.tool_call_id && deniedToolIds.has(tc.tool_call_id)) ||
        tc.approved === false ||
        tc.result_status === "denied" ||
        tc.result_status === "timeout_denied";
      const isLastTraced = i === tracedToolCalls.length - 1;
      // "pending" = the model is still writing the call's arguments;
      // "approved" = approved/auto-approved but the result hasn't landed yet.
      // A pending call on a turn that is no longer streaming never executed
      // (the stream died), so it is shown as failed rather than spinning forever.
      const status: "preparing" | "running" | "complete" | "failed" | "denied" = denied
        ? "denied"
        : tc.result_status === "failed"
          ? "failed"
          : tc.result_status === "pending"
            ? isStreamingTurn
              ? "preparing"
              : "failed"
            : tc.result_status === "approved" && isStreamingTurn
              ? "running"
              : toolsStillExecuting && isLastTraced
                ? "running"
                : "complete";
      return {
        toolName: tc.tool_name,
        serverName: tc.server_name,
        args: tc.arguments,
        status
      };
    })
  );

  function toggleToolCallExpanded(index: number) {
    if (expandedToolCalls.has(index)) {
      expandedToolCalls.delete(index);
    } else {
      expandedToolCalls.add(index);
    }
  }

  async function handleApproveTool(toolCallId: string) {
    submittingToolIds.add(toolCallId);
    try {
      await chat.approveTool(toolCallId);
    } catch (error) {
      console.error("Failed to approve tool:", error);
    } finally {
      submittingToolIds.delete(toolCallId);
    }
  }

  async function handleDenyTool(toolCallId: string) {
    submittingToolIds.add(toolCallId);
    try {
      await chat.denyTool(toolCallId);
      deniedToolIds.add(toolCallId);
    } catch (error) {
      console.error("Failed to deny tool:", error);
    } finally {
      submittingToolIds.delete(toolCallId);
    }
  }

  async function handleApproveAll() {
    isSubmittingBulk = true;
    try {
      await chat.approveAllTools();
    } catch (error) {
      console.error("Failed to approve all tools:", error);
    } finally {
      isSubmittingBulk = false;
    }
  }

  async function handleDenyAll() {
    isSubmittingBulk = true;
    try {
      // Track all denied tools before clearing
      const toolIds =
        chat.pendingToolApproval?.tools.map((t) => t.tool_call_id).filter(Boolean) ?? [];
      await chat.rejectAllTools();
      toolIds.forEach((id) => deniedToolIds.add(id!));
    } catch (error) {
      console.error("Failed to deny all tools:", error);
    } finally {
      isSubmittingBulk = false;
    }
  }

  const showAnswerLabel = $derived.by(() => {
    let hasInfo = message.tools && message.tools.assistants.length > 0;
    let isSameAssistant = message.tools.assistants.some(({ id }) => id === chat.partner.id);
    let isEnabled =
      chat.partner.type === "default-assistant" ||
      ("show_response_label" in chat.partner && chat.partner.show_response_label);
    return hasInfo && !isSameAssistant && isEnabled;
  });
</script>

<div class="relative pt-4 text-lg">
  <span class="sr-only">{m.answer()}</span>
  {#if showAnswerLabel}
    {#each message.tools?.assistants ?? [] as mention (mention.id)}
      <div
        {...dynamicColour({ basedOn: mention.id })}
        class="bg-dynamic-dimmer text-dynamic-stronger mb-4 -ml-2 flex w-fit items-center gap-2 rounded-full px-4 py-2 text-base font-medium"
      >
        <IconSpeechBubble class="stroke-2"></IconSpeechBubble>
        <span>
          {formatEmojiTitle(mention.handle ?? m.unknown_assistant())}
        </span>
      </div>
    {/each}
  {/if}

  {#if tracedSteps.length > 0 || reasoningText.trim().length > 0}
    <div class="mb-4">
      <ReasoningTrace steps={tracedSteps} reasoning={reasoningText} working={toolsStillExecuting} />
    </div>
  {/if}

  {#if pendingToolCalls.length > 0}
    <div class="mb-5 flex flex-col gap-2">
      {#each pendingToolCalls as toolCall, idx (toolCall.tool_call_id ?? idx)}
        {@const isLastToolCall = idx === pendingToolCalls.length - 1}
        {@const isPendingTool =
          toolCall.tool_call_id && pendingToolIds.includes(toolCall.tool_call_id)}
        {@const isDeniedLocally = toolCall.tool_call_id && deniedToolIds.has(toolCall.tool_call_id)}
        {@const isDeniedFromBackend = toolCall.approved === false}
        {@const isDenied = isDeniedLocally || isDeniedFromBackend}
        {@const isApproved = toolCall.approved === true}
        {@const shouldPulse = isLastToolCall && toolsStillExecuting && !hasPendingApproval}
        {@const hasArgs = toolCall.arguments && Object.keys(toolCall.arguments).length > 0}
        {@const isExpanded = expandedToolCalls.has(idx)}
        {@const isSubmitting = toolCall.tool_call_id
          ? submittingToolIds.has(toolCall.tool_call_id)
          : false}
        {@const statusStyle = isDenied
          ? "border-negative-default/20 bg-negative-dimmer/50"
          : isApproved
            ? "border-positive-default/20 bg-positive-dimmer/50"
            : "border-default bg-secondary/80"}
        <div
          class="group rounded-lg border {statusStyle} transition-all duration-200 {shouldPulse
            ? 'animate-pulse'
            : ''}"
        >
          <!-- Tool header -->
          <button
            type="button"
            class="flex w-full items-center gap-3 px-3 py-2.5 text-left {hasArgs
              ? 'cursor-pointer'
              : 'cursor-default'}"
            onclick={() => hasArgs && toggleToolCallExpanded(idx)}
            disabled={!hasArgs}
          >
            <!-- Status indicator -->
            <div
              class="flex h-8 w-8 shrink-0 items-center justify-center rounded-md {isDenied
                ? 'bg-negative-default/10 text-negative-default'
                : isApproved
                  ? 'bg-positive-default/10 text-positive-default'
                  : 'bg-accent-default/10 text-accent-default'}"
            >
              <Wrench class="h-4 w-4" />
            </div>

            <!-- Tool info -->
            <div class="flex min-w-0 flex-1 flex-col gap-0.5">
              <div class="flex items-center gap-2">
                <span class="text-default truncate text-sm font-medium">{toolCall.tool_name}</span>
                {#if isDenied}
                  <span
                    class="bg-negative-dimmer text-negative-default inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium tracking-wide uppercase"
                  >
                    {m.tool_rejected_by_user()}
                  </span>
                {:else if isApproved}
                  <span
                    class="bg-positive-dimmer text-positive-default inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium tracking-wide uppercase"
                  >
                    <Check class="h-2.5 w-2.5" />
                  </span>
                {/if}
              </div>
              <span class="text-muted text-xs">{toolCall.server_name}</span>
            </div>

            <!-- Expand indicator -->
            {#if hasArgs}
              <ChevronRight
                class="text-muted h-4 w-4 shrink-0 transition-transform duration-200 {isExpanded
                  ? 'rotate-90'
                  : ''}"
              />
            {/if}
          </button>

          <!-- Expanded arguments -->
          {#if hasArgs && isExpanded}
            <div class="border-dimmer border-t px-3 py-2.5">
              <div class="bg-primary/60 rounded-md p-3">
                <pre
                  class="text-secondary overflow-x-auto font-mono text-xs leading-relaxed break-words whitespace-pre-wrap">{JSON.stringify(
                    toolCall.arguments,
                    null,
                    2
                  )}</pre>
              </div>
            </div>
          {/if}

          <!-- Approval actions -->
          {#if isPendingTool && toolCall.tool_call_id}
            <div class="border-dimmer flex items-center gap-2 border-t px-3 py-2.5">
              <span class="text-muted mr-auto text-xs">{m.chat_tool_awaiting_approval()}</span>
              <button
                type="button"
                class="bg-positive-default text-on-fill hover:bg-positive-stronger inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium shadow-sm transition-colors disabled:opacity-50"
                onclick={() => handleApproveTool(toolCall.tool_call_id!)}
                disabled={isSubmitting}
              >
                <Check class="h-3.5 w-3.5" />
                {m.tool_accept()}
              </button>
              <button
                type="button"
                class="border-default bg-primary text-secondary hover:bg-hover-default inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs font-medium shadow-sm transition-colors disabled:opacity-50"
                onclick={() => handleDenyTool(toolCall.tool_call_id!)}
                disabled={isSubmitting}
              >
                <X class="h-3.5 w-3.5" />
                {m.tool_deny()}
              </button>
            </div>
          {/if}
        </div>
      {/each}

      <!-- Bulk approval actions -->
      {#if hasPendingApproval && hasMultiplePendingTools}
        <div
          class="border-default bg-secondary/50 mt-1 flex items-center justify-end gap-2 rounded-lg border border-dashed px-3 py-2.5"
        >
          <span class="text-muted mr-auto text-xs"
            >{m.chat_tools_pending({ count: pendingToolIds.length })}</span
          >
          <button
            type="button"
            class="bg-positive-default text-on-fill hover:bg-positive-stronger inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium shadow-sm transition-colors disabled:opacity-50"
            onclick={handleApproveAll}
            disabled={isSubmittingBulk}
          >
            <Check class="h-3.5 w-3.5" />
            {m.tool_accept_all({ count: pendingToolIds.length })}
          </button>
          <button
            type="button"
            class="border-default bg-primary text-secondary hover:bg-hover-default inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs font-medium shadow-sm transition-colors disabled:opacity-50"
            onclick={handleDenyAll}
            disabled={isSubmittingBulk}
          >
            <X class="h-3.5 w-3.5" />
            {m.tool_deny_all()}
          </button>
        </div>
      {/if}
    </div>
  {/if}

  <Markdown
    source={message.answer}
    customRenderers={{
      inref: MessageIntricInfoBlob
    }}
  />
</div>

{#each message.generated_files as file (file.id)}
  {@const url = attachmentUrls.getUrl(file) ?? null}
  <AsyncImage {url}></AsyncImage>
{/each}
