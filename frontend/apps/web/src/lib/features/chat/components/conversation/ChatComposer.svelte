<!--
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the MIT License.

    Bundles the three pieces of the chat composer — attachments, the context
    (token) usage bar and the input box — so callers mount a single component
    instead of stacking them by hand. Attachments and the usage bar are
    unchanged; only the input box was redesigned.
-->
<script lang="ts">
  import ConversationAttachments from "./ConversationAttachments.svelte";
  import ContextUsageBar from "./ContextUsageBar.svelte";
  import ConversationInput from "./ConversationInput.svelte";

  type Props = { scrollToBottom: () => void; onNewConversation?: () => void };
  const { scrollToBottom, onNewConversation }: Props = $props();
</script>

<div class="flex w-full flex-col items-center gap-2 md:gap-4">
  <ConversationAttachments></ConversationAttachments>
  <div class="w-[100%] max-w-[74ch] md:w-full">
    <ContextUsageBar {onNewConversation}></ContextUsageBar>
  </div>
  <ConversationInput {scrollToBottom} {onNewConversation}></ConversationInput>
</div>
