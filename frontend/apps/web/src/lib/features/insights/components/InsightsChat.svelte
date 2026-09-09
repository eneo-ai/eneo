<!--
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import { IconSparkles } from "@eneo/icons/sparkles";
  import { Button } from "@eneo/ui";
  import { getInsightsChatService } from "../InsightsChatService.svelte";
  import InsightsChatHistory from "./InsightsChatHistory.svelte";
  import InsightsChatInput from "./InsightsChatInput.svelte";
  import InsightsChatMessages from "./InsightsChatMessages.svelte";

  const chat = getInsightsChatService();

  let question = $state("");
  let inputRef = $state<HTMLTextAreaElement | null>(null);

  const hasMessages = $derived(chat.messages.length > 0);
  const examples = $derived([
    m.insights_chat_example_yesterday(),
    m.insights_chat_example_top(),
    m.insights_chat_example_trend()
  ]);

  async function send(text: string) {
    await chat.send(text);
    inputRef?.focus();
  }

  // Keep the newest turn in view while it streams in: the attachment re-runs
  // whenever the last turn's answer or tool steps change.
  function followLatestTurn(node: HTMLDivElement) {
    const last = chat.messages[chat.messages.length - 1];
    void last?.answer;
    void last?.toolCalls.length;
    node.scrollTop = node.scrollHeight;
  }
</script>

<div class="bg-primary border-default flex w-full flex-col rounded-lg border shadow-md">
  <div class="border-default flex items-center gap-3 border-b px-6 py-4">
    <IconSparkles data-dynamic-colour="moss" class="text-dynamic-default size-6" aria-hidden="true"
    ></IconSparkles>
    <div class="flex flex-col">
      <span class="text-primary font-medium">{m.insights_chat()}</span>
      <span class="text-secondary text-sm">{m.insights_chat_description()}</span>
    </div>
    {#if hasMessages}
      <Button
        variant="outlined"
        class="ml-auto"
        disabled={chat.isStreaming}
        onclick={() => {
          chat.reset();
          chat.loadHistory();
          inputRef?.focus();
        }}>{m.insights_chat_new_conversation()}</Button
      >
    {/if}
  </div>

  <!-- Fixed height from the first render so the panel never grows under the
       operator's hands when the first answer streams in. -->
  <div
    {@attach followLatestTurn}
    class="insights-chat-scroll h-[min(60vh,40rem)] overflow-y-auto px-6 py-6"
    role="log"
    aria-label={m.insights_chat()}
  >
    {#if hasMessages}
      <InsightsChatMessages messages={chat.messages} isStreaming={chat.isStreaming} />
    {:else if chat.openConversation.isLoading}
      <div class="text-secondary flex h-full items-center justify-center text-sm">
        {m.loading()}
      </div>
    {:else}
      <div class="flex min-h-full flex-col items-center justify-center gap-6 text-center">
        <p class="text-secondary max-w-[40ch] text-sm">{m.insights_chat_empty()}</p>
        <ul class="flex flex-wrap justify-center gap-2">
          {#each examples as example (example)}
            <li>
              <button
                type="button"
                class="border-default text-primary hover:bg-secondary hover:border-strongest rounded-full border px-3.5 py-1.5 text-sm transition-colors"
                onclick={() => send(example)}
              >
                {example}
              </button>
            </li>
          {/each}
        </ul>
        {#if chat.error}
          <p class="text-negative-default text-sm" role="alert">{m.insights_chat_error()}</p>
        {/if}
        <InsightsChatHistory />
      </div>
    {/if}
  </div>

  <div class="px-4 py-4">
    <InsightsChatInput
      bind:value={question}
      bind:ref={inputRef}
      disabled={chat.isStreaming}
      onSubmit={send}
    />
  </div>
</div>

<style lang="postcss">
  .insights-chat-scroll {
    scrollbar-gutter: stable both-edges;
  }
</style>
