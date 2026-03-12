<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import Message from "$lib/features/chat/components/conversation/Message.svelte";
  import { IconLoadingSpinner } from "@intric/icons/loading-spinner";
  import { getInsightsService } from "../InsightsService.svelte";
  import { m } from "$lib/paraglide/messages";

  const insights = getInsightsService();
  const conversation = $derived(insights.previewedConversation);
</script>

<div class="flex flex-col gap-3.5">
  {#if insights.loadConversationPreview.isLoading}
    <div
      class="text-secondary flex h-full w-full items-center justify-center gap-2"
      role="status"
      aria-live="polite"
    >
      <IconLoadingSpinner class="animate-spin" aria-hidden="true"></IconLoadingSpinner>
      <span>{m.loading_ellipsis()}</span>
    </div>
  {:else if insights.previewLoadError}
    <div class="text-secondary flex h-full w-full items-center justify-center" role="alert">
      {m.error_connecting_to_server()}
    </div>
  {:else if conversation && conversation.messages.length > 0}
    <section class="flex-grow">
      <div class="flex flex-grow flex-col gap-2 p-4 md:p-8">
        {#each conversation.messages as message, idx (idx)}
          <Message {message} isLoading={false} isLast={idx === conversation.messages.length - 1}
          ></Message>
        {/each}
      </div>
    </section>
  {:else if conversation}
    <div class="text-secondary flex h-full w-full items-center justify-center">
      {m.insights_conversation_no_messages()}
    </div>
  {:else}
    <div class="text-secondary flex h-full w-full items-center justify-center">
      {m.insights_select_conversation()}
    </div>
  {/if}
</div>

<style lang="postcss">
  @reference "@intric/ui/styles";
  section {
    @apply border-stronger bg-primary overflow-auto rounded-md border border-b shadow-md;
  }
</style>
