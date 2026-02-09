<script lang="ts">
  import type { ConversationMessage } from "@intric/intric-js";
  import TypingIndicator from "./TypingIndicator.svelte";
  import ThinkingIndicator from "./ThinkingIndicator.svelte";
  import MessageQuestion from "./MessageQuestion.svelte";
  import MessageAnswer from "./MessageAnswer.svelte";
  import MessageFiles from "./MessageFiles.svelte";
  import MessageTools from "./MessageTools.svelte";
  import { browser } from "$app/environment";
  import { getChatService } from "../../ChatService.svelte";
  import { setMessageContext } from "../../MessageContext.svelte";

  interface Props {
    message: ConversationMessage;
    isLast: boolean;
    isLoading: boolean;
  }

  let { message, isLast, isLoading }: Props = $props();

  setMessageContext({
    current: () => message,
    isLast: () => isLast,
    isLoading: () => isLoading
  });

  const chat = getChatService();

  let messageHeight: number = $state(0);

  const updateHeight = (isLast: boolean) => {
    if (!isLast || !browser) {
      messageHeight = 0;
      return;
    }

    setTimeout(() => {
      const viewContainer = document.getElementById("session-view-container");
      const inputContainer = document.getElementById("session-input-container");
      const messageContainer = document.getElementById("session-message-container");
      const question = [...document.querySelectorAll(".question")].pop();

      if (viewContainer && inputContainer && messageContainer && question) {
        const containerHeight = viewContainer.clientHeight;
        const inputFieldHeight = inputContainer.clientHeight;
        const parentPadding = parseInt(getComputedStyle(messageContainer).paddingBottom);
        // If the questoin is longer than 0.5 of the screen, we jump directly to the answer
        const extraSpace =
          question.clientHeight > containerHeight * 0.5 ? question.clientHeight + parentPadding : 0;

        messageHeight = containerHeight - inputFieldHeight - 2 * parentPadding + extraSpace;
      }
    }, 1);
  };

  $effect(() => {
    updateHeight(isLast);
  });

  const showSpinner = $derived.by(() => {
    const isGeneratingImage = message.generated_files.length > 0;
    const hasStartedStreaming = message.answer.trim().length > 0;
    // Show typing indicator only while waiting for text to start, not during streaming
    return isLast && isLoading && !isGeneratingImage && !hasStartedStreaming;
  });

  const isReasoning = $derived.by(() => {
    const modelCanReason =
      "completion_model" in chat.partner && chat.partner.completion_model?.reasoning;
    const noAnswerReceived = message.answer.trim() === "";
    return modelCanReason && noAnswerReceived;
  });
</script>

<svelte:window onresize={() => updateHeight(isLast)} />

<div
  class="group/message mx-auto flex w-full max-w-[71ch] flex-col gap-4"
  data-is-last-message={isLast}
  style="min-height: {messageHeight}px"
>
  <MessageFiles></MessageFiles>
  <MessageQuestion></MessageQuestion>
  <MessageAnswer></MessageAnswer>
  {#if showSpinner}
    {#if isReasoning}
      <ThinkingIndicator />
    {:else}
      <TypingIndicator />
    {/if}
  {:else}
    <MessageTools></MessageTools>
  {/if}
</div>

