<!--
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the MIT License.

    The operator's previous analyses for the current chat partner: open one
    to resume it, or delete it.
-->

<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import { Button } from "@eneo/ui";
  import { IconLoadingSpinner } from "@eneo/icons/loading-spinner";
  import { Trash2 } from "lucide-svelte";
  import { getInsightsChatService } from "../InsightsChatService.svelte";

  type Props = {
    /** Called when the operator picks an analysis to resume. */
    onOpen: (conversation: { id: string }) => void;
  };

  let { onOpen }: Props = $props();

  const chat = getInsightsChatService();

  const dateFormatter = new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short"
  });

  function formatDate(value: string | null | undefined): string {
    if (!value) return "";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? "" : dateFormatter.format(date);
  }
</script>

<section
  class="flex w-full max-w-[60ch] flex-col gap-2 text-left"
  aria-label={m.insights_chat_history()}
>
  <h3 class="text-secondary text-xs font-medium tracking-wide uppercase">
    {m.insights_chat_history()}
  </h3>

  {#if chat.historyError}
    <p class="text-negative-default text-sm" role="alert">{m.insights_chat_history_error()}</p>
  {:else if chat.loadHistory.isLoading && chat.history.length === 0}
    <div class="text-secondary flex items-center gap-2 text-sm">
      <IconLoadingSpinner class="size-4 animate-spin" aria-hidden="true"></IconLoadingSpinner>
      <span>{m.loading()}</span>
    </div>
  {:else if chat.history.length === 0}
    <p class="text-secondary text-sm">{m.insights_chat_empty_history()}</p>
  {:else}
    <ul class="border-default divide-default divide-y rounded-lg border">
      {#each chat.history as conversation (conversation.id)}
        <li class="group flex items-center gap-2 pr-2">
          <button
            type="button"
            class="hover:bg-secondary flex min-w-0 flex-1 flex-col items-start gap-0.5 rounded-lg px-3 py-2 text-left transition-colors"
            onclick={() => onOpen(conversation)}
          >
            <span class="text-primary w-full truncate text-sm">{conversation.name}</span>
            <span class="text-muted text-xs">{formatDate(conversation.created_at)}</span>
          </button>
          <Button
            padding="icon"
            variant="simple"
            class="opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100"
            aria-label={m.insights_chat_delete_conversation()}
            disabled={chat.deleteConversation.isLoading}
            onclick={() => chat.deleteConversation(conversation)}
          >
            <Trash2 class="size-4" aria-hidden="true" />
          </Button>
        </li>
      {/each}
    </ul>
    {#if chat.hasMoreHistory}
      <Button
        variant="simple"
        class="self-start"
        disabled={chat.loadHistory.isLoading}
        onclick={() => chat.loadHistory(true)}>{m.insights_chat_load_more()}</Button
      >
    {/if}
  {/if}
</section>
