<script lang="ts">
  import { Markdown } from "@intric/ui";
  import MessageIntricInfoBlob from "./MessageIntricInfoBlob.svelte";
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

  // Get MCP tool calls from the message
  // - mcp_tool_calls: runtime property added during streaming
  // - tool_calls: persisted field from API response (chat history)
  const mcpToolCalls = $derived(
    ((message as any).mcp_tool_calls ?? message.tool_calls) as Array<{ server_name: string; tool_name: string; arguments?: Record<string, unknown>; tool_call_id?: string; approved?: boolean }> | undefined
  );

  // Check if there's a pending tool approval for this message (only on last message)
  const hasPendingApproval = $derived(
    isLast() && chat.pendingToolApproval !== null
  );

  // Get pending tool IDs for matching
  const pendingToolIds = $derived(
    chat.pendingToolApproval?.tools.map(t => t.tool_call_id) ?? []
  );

  // Check if there are multiple pending tools (for showing bulk actions)
  const hasMultiplePendingTools = $derived(pendingToolIds.length > 1);

  // Track which tool calls have expanded arguments
  const expandedToolCalls = new SvelteSet<number>();
  const submittingToolIds = new SvelteSet<string>();
  const deniedToolIds = new SvelteSet<string>();
  let isSubmittingBulk = $state(false);

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
      console.error('Failed to approve tool:', error);
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
      console.error('Failed to deny tool:', error);
    } finally {
      submittingToolIds.delete(toolCallId);
    }
  }

  async function handleApproveAll() {
    isSubmittingBulk = true;
    try {
      await chat.approveAllTools();
    } catch (error) {
      console.error('Failed to approve all tools:', error);
    } finally {
      isSubmittingBulk = false;
    }
  }

  async function handleDenyAll() {
    isSubmittingBulk = true;
    try {
      // Track all denied tools before clearing
      const toolIds = chat.pendingToolApproval?.tools.map(t => t.tool_call_id).filter(Boolean) ?? [];
      await chat.rejectAllTools();
      toolIds.forEach(id => deniedToolIds.add(id!));
    } catch (error) {
      console.error('Failed to deny all tools:', error);
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

  {#if mcpToolCalls && mcpToolCalls.length > 0}
    <div class="mb-4 flex flex-col gap-1">
      {#each mcpToolCalls as toolCall, idx (toolCall.tool_call_id ?? idx)}
        {@const isLastToolCall = idx === mcpToolCalls.length - 1}
        {@const isPendingTool = toolCall.tool_call_id && pendingToolIds.includes(toolCall.tool_call_id)}
        {@const isDeniedLocally = toolCall.tool_call_id && deniedToolIds.has(toolCall.tool_call_id)}
        {@const isDeniedFromBackend = toolCall.approved === false}
        {@const isDenied = isDeniedLocally || isDeniedFromBackend}
        {@const isApproved = toolCall.approved === true}
        {@const shouldPulse = isLastToolCall && toolsStillExecuting && !hasPendingApproval}
        {@const hasArgs = toolCall.arguments && Object.keys(toolCall.arguments).length > 0}
        {@const isExpanded = expandedToolCalls.has(idx)}
        {@const isSubmitting = toolCall.tool_call_id ? submittingToolIds.has(toolCall.tool_call_id) : false}
        {@const pillColor = isDenied ? 'bg-negative-dimmer text-negative-stronger' : isApproved ? 'bg-positive-dimmer text-positive-stronger' : 'bg-accent-dimmer text-accent-stronger'}
        <div class="flex flex-col">
          <div class="flex items-center gap-2">
            <button
              type="button"
              class="inline-flex w-fit items-center gap-1.5 rounded-full px-3 py-1.5 text-sm font-medium {pillColor} {shouldPulse ? 'animate-pulse' : ''} {hasArgs ? 'cursor-pointer hover:opacity-80' : 'cursor-default'}"
              onclick={() => hasArgs && toggleToolCallExpanded(idx)}
              disabled={!hasArgs}
            >
              {#if hasArgs}
                <ChevronRight class="h-3 w-3 transition-transform {isExpanded ? 'rotate-90' : ''}" />
              {/if}
              <Wrench class="h-3.5 w-3.5" />
              {isPendingTool ? m.tool_waiting_approval?.({ tool: toolCall.tool_name, server: toolCall.server_name }) ?? `${toolCall.server_name}: ${toolCall.tool_name}` : m.executing_tool({ tool: toolCall.tool_name, server: toolCall.server_name })}
            </button>
            {#if isDenied}
              <span class="text-xs text-tertiary italic">{m.tool_rejected_by_user()}</span>
            {/if}
            {#if isPendingTool && toolCall.tool_call_id}
              <button
                type="button"
                class="inline-flex items-center gap-1 rounded border border-positive-default bg-positive-default px-1.5 py-0.5 text-xs font-medium text-on-fill hover:bg-positive-stronger disabled:opacity-50"
                onclick={() => handleApproveTool(toolCall.tool_call_id!)}
                disabled={isSubmitting}
              >
                <Check class="h-3 w-3" />
                {m.tool_accept()}
              </button>
              <button
                type="button"
                class="inline-flex items-center gap-1 rounded border border-dimmer bg-secondary px-1.5 py-0.5 text-xs font-medium text-secondary hover:bg-hover-default disabled:opacity-50"
                onclick={() => handleDenyTool(toolCall.tool_call_id!)}
                disabled={isSubmitting}
              >
                <X class="h-3 w-3" />
                {m.tool_deny()}
              </button>
            {/if}
          </div>
          {#if hasArgs && isExpanded}
            <div class="ml-4 mt-1 rounded-md border border-dimmer bg-secondary p-3 text-xs">
              <pre class="overflow-x-auto whitespace-pre-wrap break-words text-secondary">{JSON.stringify(toolCall.arguments, null, 2)}</pre>
            </div>
          {/if}
        </div>
      {/each}
      {#if hasPendingApproval && hasMultiplePendingTools}
        <div class="mt-2 flex items-center gap-2">
          <button
            type="button"
            class="inline-flex items-center gap-1 rounded border border-positive-default bg-positive-default px-2 py-1 text-xs font-medium text-on-fill hover:bg-positive-stronger disabled:opacity-50"
            onclick={handleApproveAll}
            disabled={isSubmittingBulk}
          >
            <Check class="h-3 w-3" />
            {m.tool_accept_all({ count: pendingToolIds.length })}
          </button>
          <button
            type="button"
            class="inline-flex items-center gap-1 rounded border border-dimmer bg-secondary px-2 py-1 text-xs font-medium text-secondary hover:bg-hover-default disabled:opacity-50"
            onclick={handleDenyAll}
            disabled={isSubmittingBulk}
          >
            <X class="h-3 w-3" />
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
