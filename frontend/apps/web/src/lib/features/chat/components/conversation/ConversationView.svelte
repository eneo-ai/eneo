<script lang="ts">
  import { getIntric } from "$lib/core/Intric";
  import { initAttachmentManager } from "$lib/features/attachments/AttachmentManager";
  import AttachmentDropArea from "$lib/features/attachments/components/AttachmentDropArea.svelte";
  import { IconArrowDownToLine } from "@intric/icons/arrow-down-to-line";
  import { Markdown } from "@intric/ui";
  import Message from "./Message.svelte";
  import ConversationAttachments from "./ConversationAttachments.svelte";
  import ConversationInput from "./ConversationInput.svelte";
  import { fade } from "svelte/transition";
  import { browser } from "$app/environment";
  import { Tooltip } from "@intric/ui";
  import { getChatService } from "../../ChatService.svelte";
  import type { Snippet } from "svelte";
  import { m } from "$lib/paraglide/messages";

  type Props = {
    children?: Snippet;
  };

  let { children }: Props = $props();

  const chat = getChatService();

  const attachmentRules = undefined; // getAttachmentRulesStore(toStore(() => chat.partner));
  initAttachmentManager({ intric: getIntric(), options: { rules: attachmentRules } });

  let scrollContainer = $state() as HTMLDivElement;
  let showScrollToBottom = $state(false);

  const scrollToBottom = () => {
    if (scrollContainer) {
      setTimeout(() => {
        scrollContainer.scrollTo({ top: scrollContainer.scrollHeight, behavior: "smooth" });
      }, 10);
    }
  };

  const handleScroll = () => {
    if (!browser) return;
    const bottomThreshold = 150; // px from bottom to still consider it "at bottom"
    const distanceFromBottom =
      scrollContainer.scrollHeight - scrollContainer.clientHeight - scrollContainer.scrollTop;
    showScrollToBottom = distanceFromBottom > bottomThreshold;
  };

  const updateScroll = (session: { id: string | null }) => {
    if (session.id || !session.id) {
      setTimeout(() => {
        handleScroll();
      }, 10);
    }
  };

  $effect(() => {
    updateScroll(chat.currentConversation);
  });

  let isDragging = $state(false);
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
  class="md:stable-gutter relative flex h-full flex-col overflow-y-auto"
  id="session-view-container"
  bind:this={scrollContainer}
  onscroll={handleScroll}
  ondragenter={(event) => {
    event.preventDefault();
    isDragging = true;
  }}
>
  {#if chat.currentConversation.messages && chat.currentConversation.messages.length > 0}
    <div
      class="flex flex-grow flex-col gap-2 p-4 md:p-8"
      aria-live="polite"
      id="session-message-container"
    >
      {#each chat.currentConversation.messages as message, idx (idx)}
        <Message
          {message}
          isLast={idx === chat.currentConversation.messages.length - 1}
          isLoading={chat.askQuestion.isLoading}
        ></Message>
      {/each}
    </div>
  {:else if children}
    <div class="flex flex-grow flex-col items-center justify-center">
      {@render children?.()}
    </div>
  {:else}
    <div class="flex flex-grow items-center justify-center">
      <div class="text-primary max-h-[80%] max-w-[50ch] overflow-x-auto">
        <Markdown
          class="flex flex-col items-center justify-center gap-4 *:m-0 [&_p]:text-center"
          source={"description" in chat.partner && chat.partner.description
            ? chat.partner.description
            : ` Hi, I'm _${chat.partner.name}_!\nAsk me anything to get started.`}
        ></Markdown>
      </div>
    </div>
  {/if}
  <div
    id="session-input-container"
    class="sticky inset-x-0 bottom-0 flex flex-col items-center justify-end gap-2 bg-gradient-to-b from-transparent to-[var(--background-primary)] p-0 backdrop-blur-sm md:gap-4 md:p-6 md:pt-0"
  >
    {#if showScrollToBottom}
      <div transition:fade={{ duration: 150 }} class="absolute -top-12">
        <Tooltip text={m.scroll_to_bottom()}>
          <button
            class="border-stronger bg-primary ring-default hover:bg-secondary flex gap-1 rounded-full border px-1.5 py-1.5 shadow-lg ring-offset-0 hover:ring-2"
            onclick={scrollToBottom}><IconArrowDownToLine></IconArrowDownToLine></button
          >
        </Tooltip>
      </div>
    {/if}
    <ConversationAttachments></ConversationAttachments>
    <ConversationInput {scrollToBottom}></ConversationInput>
  </div>
</div>
{#if isDragging}
  <AttachmentDropArea bind:isDragging label={m.drop_files_here_conversation()} />
{/if}

<style></style>
