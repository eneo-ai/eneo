<!--
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the MIT License.

    Row actions of the previous-analyses table: delete, with the same
    confirmation dialog as the chat history. Legacy component syntax on
    purpose: svelte-headless-table's createRender needs a class component.
-->

<script lang="ts">
  import { IconTrash } from "@eneo/icons/trash";
  import { Button, Dialog } from "@eneo/ui";
  import { m } from "$lib/paraglide/messages";
  import {
    getInsightsChatService,
    type InsightsConversationSummary
  } from "../InsightsChatService.svelte";

  export let conversation: InsightsConversationSummary;

  const chat = getInsightsChatService();
</script>

<div class="flex items-center justify-end gap-2">
  <Dialog.Root alert>
    <Dialog.Trigger asFragment let:trigger>
      <Button
        variant="destructive"
        is={trigger}
        label={m.insights_chat_delete_conversation()}
        padding="icon"
      >
        <IconTrash />
      </Button>
    </Dialog.Trigger>

    <Dialog.Content width="small">
      <Dialog.Title>{m.insights_chat_delete_conversation()}</Dialog.Title>
      <Dialog.Description>
        {m.do_you_really_want_to_delete()}
        <span class="italic">{conversation.name.slice(0, 200)}</span>?
      </Dialog.Description>

      <Dialog.Controls let:close>
        <Button is={close}>{m.cancel()}</Button>
        <Button
          is={close}
          variant="destructive"
          on:click={() => chat.deleteConversation(conversation)}
        >
          {m.delete()}
        </Button>
      </Dialog.Controls>
    </Dialog.Content>
  </Dialog.Root>
</div>
