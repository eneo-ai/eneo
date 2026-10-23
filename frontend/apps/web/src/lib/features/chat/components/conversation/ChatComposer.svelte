<!--
    Copyright (c) 2026 Sundsvalls Kommun

    Bundles the three pieces of the chat composer — attachments, the context
    (token) usage bar and the input box. Their shared width is also the query
    container for controls, including when a side panel narrows the chat.
-->
<script lang="ts">
  import ConversationAttachments from "./ConversationAttachments.svelte";
  import ContextUsageBar from "./ContextUsageBar.svelte";
  import ConversationInput from "./ConversationInput.svelte";

  type Props = { scrollToBottom: () => void; onNewConversation?: () => void };
  const { scrollToBottom, onNewConversation }: Props = $props();
</script>

<div
  class="mx-auto flex w-full min-w-0 max-w-[74ch] flex-col items-center gap-2 @container/composer md:gap-4"
>
  <ConversationAttachments></ConversationAttachments>
  <div class="w-full min-w-0">
    <ContextUsageBar {onNewConversation}></ContextUsageBar>
  </div>
  <ConversationInput {scrollToBottom} {onNewConversation}></ConversationInput>
</div>
