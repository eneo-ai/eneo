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

  const chat = getChatService();
  const attachmentUrls = getAttachmentUrlService();

  const { current, isLast } = getMessageContext();
  const message = $derived(current());
  // Tools are still being executed if we're loading and no answer text has arrived yet
  const toolsStillExecuting = $derived(
    isLast() && chat.askQuestion.isLoading && message.answer.trim() === ""
  );

  // Get MCP tool calls from the message (runtime property added during streaming)
  const mcpToolCalls = $derived(
    (message as any).mcp_tool_calls as Array<{ server_name: string; tool_name: string }> | undefined
  );

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
        <span class="bg-accent-dimmer text-accent-stronger inline-flex w-fit items-center gap-1.5 rounded-full px-4 py-2 text-sm font-medium {shouldPulse ? 'animate-pulse' : ''}">
          <span class="text-base">🔧</span>
          {m.executing_tool({ tool: toolCall.tool_name, server: toolCall.server_name })}
        </span>
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
