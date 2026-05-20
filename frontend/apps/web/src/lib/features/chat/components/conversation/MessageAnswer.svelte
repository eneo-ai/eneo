<script lang="ts">
  import { Markdown } from "@intric/ui";
  import MessageIntricInfoBlob from "./MessageIntricInfoBlob.svelte";
  import ToolCallRow from "./ToolCallRow.svelte";
  import * as Separator from "$lib/components/ui/separator/index.js";
  import { dynamicColour } from "$lib/core/colours";
  import { IconSpeechBubble } from "@intric/icons/speech-bubble";
  import { formatEmojiTitle } from "$lib/core/formatting/formatEmojiTitle";
  import { getChatService } from "../../ChatService.svelte";
  import { getAttachmentUrlService } from "$lib/features/attachments/AttachmentUrlService.svelte";
  import { getMessageContext } from "../../MessageContext.svelte";
  import AsyncImage from "$lib/components/AsyncImage.svelte";
  import { m } from "$lib/paraglide/messages";
  import { Check, X } from "lucide-svelte";
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
    ((message as Record<string, unknown>).mcp_tool_calls ?? message.tool_calls) as
      | Array<{
          server_name: string;
          tool_name: string;
          arguments?: Record<string, unknown>;
          tool_call_id?: string;
          approved?: boolean;
        }>
      | undefined
  );

  // Check if there's a pending tool approval for this message (only on last message)
  const hasPendingApproval = $derived(isLast() && chat.pendingToolApproval !== null);

  // Get pending tool IDs for matching
  const pendingToolIds = $derived(chat.pendingToolApproval?.tools.map((t) => t.tool_call_id) ?? []);

  // Check if there are multiple pending tools (for showing bulk actions)
  const hasMultiplePendingTools = $derived(pendingToolIds.length > 1);

  const submittingToolIds = new SvelteSet<string>();
  const deniedToolIds = new SvelteSet<string>();
  let isSubmittingBulk = $state(false);

  // Group consecutive same-server tool calls so a chain of `query_table`
  // hits the same MCP server reads as one operation rather than 4 separate
  // bordered cards. A different server name starts a new group.
  type ToolCall = NonNullable<typeof mcpToolCalls>[number];
  type ToolCallGroup = { serverName: string; calls: ToolCall[] };
  const toolCallGroups = $derived.by<ToolCallGroup[]>(() => {
    const groups: ToolCallGroup[] = [];
    for (const call of mcpToolCalls ?? []) {
      const last = groups.at(-1);
      if (last && last.serverName === call.server_name) {
        last.calls.push(call);
      } else {
        groups.push({ serverName: call.server_name, calls: [call] });
      }
    }
    return groups;
  });

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

  {#if mcpToolCalls && mcpToolCalls.length > 0}
    <div class="mb-3 flex flex-col gap-1.5">
      {#each toolCallGroups as group, groupIdx (groupIdx)}
        <div class="border-default overflow-hidden rounded-md border">
          {#each group.calls as call, callIdx (call.tool_call_id ?? `${groupIdx}-${callIdx}`)}
            {@const isLastInMessage =
              groupIdx === toolCallGroups.length - 1 && callIdx === group.calls.length - 1}
            {@const isPending = !!call.tool_call_id && pendingToolIds.includes(call.tool_call_id)}
            {@const isDeniedLocally = !!call.tool_call_id && deniedToolIds.has(call.tool_call_id)}
            {@const isDenied = isDeniedLocally || call.approved === false}
            {@const isApproved = call.approved === true}
            {@const isSubmitting = call.tool_call_id
              ? submittingToolIds.has(call.tool_call_id)
              : false}
            {@const shouldPulse = isLastInMessage && toolsStillExecuting && !hasPendingApproval}
            {#if callIdx > 0}
              <Separator.Root />
            {/if}
            <ToolCallRow
              {call}
              {isPending}
              {isDenied}
              {isApproved}
              {isSubmitting}
              {shouldPulse}
              onApprove={handleApproveTool}
              onDeny={handleDenyTool}
            />
          {/each}
        </div>
      {/each}

      <!-- Bulk approval actions -->
      {#if hasPendingApproval && hasMultiplePendingTools}
        <div
          class="border-default bg-secondary/50 mt-1 flex items-center justify-end gap-2 rounded-lg border border-dashed px-3 py-2.5"
        >
          <span class="text-muted mr-auto text-xs">{pendingToolIds.length} verktyg väntar</span>
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
