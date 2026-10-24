<!--
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the MIT License.

    Row actions of the previous-analyses table: delete, with the same
    confirmation dialog as the chat history. Legacy component syntax on
    purpose: the table renders its cells as Svelte 4 components.
-->

<script lang="ts">
  import { IconTrash } from "@eneo/icons/trash";
  import ConfirmDialog from "$lib/components/ConfirmDialog.svelte";
  import { Button } from "$lib/components/ui/button/index.js";
  import { m } from "$lib/paraglide/messages";
  import {
    getInsightsChatService,
    type InsightsConversationSummary
  } from "../InsightsChatService.svelte";

  export let conversation: InsightsConversationSummary;

  const chat = getInsightsChatService();
</script>

<div class="flex items-center justify-end gap-2">
  <ConfirmDialog
    title={m.insights_chat_delete_conversation()}
    confirmLabel={m.delete()}
    onConfirm={() => chat.deleteConversation(conversation)}
  >
    {#snippet trigger({ props })}
      <Button
        {...props}
        variant="destructive"
        size="icon"
        aria-label={m.insights_chat_delete_conversation()}
      >
        <IconTrash />
      </Button>
    {/snippet}
    {#snippet description()}
      {m.do_you_really_want_to_delete()}
      <span class="italic">{conversation.name.slice(0, 200)}</span>?
    {/snippet}
  </ConfirmDialog>
</div>
