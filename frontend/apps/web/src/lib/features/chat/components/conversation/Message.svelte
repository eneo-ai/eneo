<script lang="ts">
  import type { ConversationMessage } from "@intric/intric-js";
  import { IconLoadingSpinner } from "@intric/icons/loading-spinner";
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
    return isLast && isLoading && !isGeneratingImage;
  });

  const isReasoning = $derived.by(() => {
    // Check if chat partner has a reasoning-capable model
    if (!("completion_model" in chat.partner) || !chat.partner.completion_model?.reasoning) {
      return false;
    }

    const noAnswerReceived = message.answer.trim() === "";
    if (!noAnswerReceived) {
      return false; // Already received answer, no longer reasoning
    }

    const modelName = chat.partner.completion_model.name;
    
    // Gemini 2.5 Flash models: Check if user has enabled reasoning
    if (modelName === "gemini-2.5-flash" || modelName === "gemini-2.5-flash-preview-05-20") {
      if ("completion_model_kwargs" in chat.partner) {
        const kwargs = chat.partner.completion_model_kwargs;
        
        // Check reasoning_level first (new system)
        if (kwargs?.reasoning_level !== undefined && kwargs?.reasoning_level !== null) {
          return kwargs.reasoning_level !== "disabled";
        }
        
        // Fallback to thinking_budget (legacy system)
        const thinkingBudget = kwargs?.thinking_budget ?? 0;
        return thinkingBudget > 0;
      }
      return false;
    }
    
    // Always-on reasoning models (Claude, Gemini 2.5 Pro, etc.): Show if model supports reasoning
    return true;
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
    <div class="flex items-center gap-2">
      <IconLoadingSpinner class="animate-spin" />
      {#if isReasoning}
        <span
          class="bg-accent-dimmer text-accent-stronger w-fit animate-pulse rounded-full px-4 py-2"
          >Thinking...</span
        >
      {/if}
    </div>
  {:else}
    <MessageTools></MessageTools>
  {/if}
</div>
