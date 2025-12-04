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
  import { ChevronRight } from "lucide-svelte";

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
    ((message as any).mcp_tool_calls ?? message.tool_calls) as Array<{ server_name: string; tool_name: string; arguments?: Record<string, unknown> }> | undefined
  );

  // Track which tool calls have expanded arguments
  let expandedToolCalls = $state(new Set<number>());

  function toggleToolCallExpanded(index: number) {
    const newExpanded = new Set(expandedToolCalls);
    if (newExpanded.has(index)) {
      newExpanded.delete(index);
    } else {
      newExpanded.add(index);
    }
    expandedToolCalls = newExpanded;
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
      {#each mcpToolCalls as toolCall, idx}
        {@const isLastToolCall = idx === mcpToolCalls.length - 1}
        {@const shouldPulse = isLastToolCall && toolsStillExecuting}
        {@const hasArgs = toolCall.arguments && Object.keys(toolCall.arguments).length > 0}
        {@const isExpanded = expandedToolCalls.has(idx)}
        <div class="flex flex-col">
          <button
            type="button"
            class="bg-accent-dimmer text-accent-stronger inline-flex w-fit items-center gap-1.5 rounded-full px-4 py-2 text-sm font-medium {shouldPulse ? 'animate-pulse' : ''} {hasArgs ? 'cursor-pointer hover:bg-accent-default/20' : 'cursor-default'}"
            onclick={() => hasArgs && toggleToolCallExpanded(idx)}
            disabled={!hasArgs}
          >
            {#if hasArgs}
              <ChevronRight class="h-3 w-3 transition-transform {isExpanded ? 'rotate-90' : ''}" />
            {/if}
            <span class="text-base">🔧</span>
            {m.executing_tool({ tool: toolCall.tool_name, server: toolCall.server_name })}
          </button>
          {#if hasArgs && isExpanded}
            <div class="ml-4 mt-1 rounded-md border border-dimmer bg-secondary p-3 text-xs">
              <pre class="overflow-x-auto whitespace-pre-wrap break-words text-secondary">{JSON.stringify(toolCall.arguments, null, 2)}</pre>
            </div>
          {/if}
        </div>
      {/each}
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
