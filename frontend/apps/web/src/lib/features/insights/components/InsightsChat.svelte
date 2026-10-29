<!--
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the MIT License.

    The Insights tab's analysis chat: a tab for the open analysis and one for
    the operator's previous analyses, plus a preview dialog for conversations
    the answer cites.
-->

<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import { IconSparkles } from "@eneo/icons/sparkles";
  import { dialogLayout } from "$lib/components/dialogLayout.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import { Tabs } from "bits-ui";
  import { getInsightsService } from "../InsightsService.svelte";
  import { getInsightsChatService } from "../InsightsChatService.svelte";
  import InsightsChatHistory from "./InsightsChatHistory.svelte";
  import InsightsChatInput from "./InsightsChatInput.svelte";
  import InsightsChatMessages from "./InsightsChatMessages.svelte";
  import InsightsConversationPreview from "./InsightsConversationPreview.svelte";

  const chat = getInsightsChatService();
  const insights = getInsightsService();

  let question = $state("");
  let inputRef = $state<HTMLTextAreaElement | null>(null);
  let showCitedConversation = $state(false);

  // Same tabs as the page-level tab bar (ghost buttons with an active state),
  // scoped to this panel so they never touch the page's ?tab= parameter.
  let activeTab = $state("chat");
  const tabTriggerClass =
    "data-[state=active]:bg-accent-dimmer data-[state=active]:text-accent-stronger tracking-[0.01rem] data-[state=active]:font-medium data-[state=active]:tracking-normal";

  const hasMessages = $derived(chat.messages.length > 0);
  const examples = $derived([
    m.insights_chat_example_yesterday(),
    m.insights_chat_example_top(),
    m.insights_chat_example_trend()
  ]);
  const historyLabel = $derived(
    chat.historyTotal > 0
      ? `${m.insights_chat_tab_history()} (${chat.historyTotal})`
      : m.insights_chat_tab_history()
  );

  async function send(text: string) {
    activeTab = "chat";
    await chat.send(text);
    inputRef?.focus();
  }

  async function openFromHistory(conversation: { id: string }) {
    activeTab = "chat";
    await chat.openConversation(conversation);
  }

  function startNew() {
    chat.reset();
    activeTab = "chat";
    inputRef?.focus();
  }

  function openCitedSession(sessionId: string) {
    showCitedConversation = true;
    insights.loadConversationPreview({ id: sessionId });
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

<Tabs.Root
  bind:value={activeTab}
  activationMode="manual"
  class="bg-primary border-default flex w-full flex-col rounded-lg border shadow-md"
>
  <div class="border-default flex flex-wrap items-center gap-x-6 gap-y-3 border-b px-6 py-4">
    <div class="flex min-w-0 items-center gap-3">
      <IconSparkles
        data-dynamic-colour="moss"
        class="text-dynamic-default size-6 shrink-0"
        aria-hidden="true"
      ></IconSparkles>
      <div class="flex min-w-0 flex-col">
        <span class="text-primary font-medium">{m.insights_chat()}</span>
        <span class="text-secondary text-sm">{m.insights_chat_description()}</span>
      </div>
    </div>
    <div class="ml-auto flex items-center gap-3">
      <Tabs.List class="flex items-center gap-1" aria-label={m.insights_chat()}>
        <Tabs.Trigger value="chat">
          {#snippet child({ props })}
            <Button {...props} variant="ghost" class={tabTriggerClass}
              >{m.insights_chat_tab_chat()}</Button
            >
          {/snippet}
        </Tabs.Trigger>
        <Tabs.Trigger value="history">
          {#snippet child({ props })}
            <Button {...props} variant="ghost" class={tabTriggerClass}>{historyLabel}</Button>
          {/snippet}
        </Tabs.Trigger>
      </Tabs.List>
      {#if hasMessages}
        <Button variant="outline" disabled={chat.isStreaming} onclick={startNew}
          >{m.insights_chat_new_conversation()}</Button
        >
      {/if}
    </div>
  </div>

  <!-- Fixed height from the first render so the panel never grows under the
       operator's hands when the first answer streams in. -->
  {#if activeTab === "chat"}
    <Tabs.Content value="chat">
      {#snippet child({ props })}
        <div
          {...props}
          {@attach followLatestTurn}
          class="insights-chat-scroll h-[min(60vh,40rem)] overflow-y-auto px-6 py-6"
          aria-label={m.insights_chat_tab_chat()}
        >
          {#if hasMessages}
            <InsightsChatMessages
              messages={chat.messages}
              isStreaming={chat.isStreaming}
              loadToolResult={(toolCallId) => chat.getToolCallResult(toolCallId)}
              onOpenSession={openCitedSession}
            />
          {:else if chat.isOpening}
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
            </div>
          {/if}
        </div>
      {/snippet}
    </Tabs.Content>

    <div class="px-4 py-4">
      <InsightsChatInput
        bind:value={question}
        bind:ref={inputRef}
        disabled={chat.isStreaming || chat.isOpening}
        onSubmit={send}
      />
    </div>
  {:else}
    <Tabs.Content value="history">
      {#snippet child({ props })}
        <div {...props} class="insights-chat-scroll h-[min(60vh,40rem)] overflow-y-auto px-6 py-6">
          <InsightsChatHistory onOpen={openFromHistory} />
        </div>
      {/snippet}
    </Tabs.Content>
  {/if}
</Tabs.Root>

<Dialog.Root bind:open={showCitedConversation}>
  <Dialog.Content class={dialogLayout.content("large")} closeLabel={m.close()}>
    <Dialog.Header class={dialogLayout.header}>
      <Dialog.Title>{m.insights_chat_cited_conversation()}</Dialog.Title>
    </Dialog.Header>
    <div class={dialogLayout.body}>
      <InsightsConversationPreview></InsightsConversationPreview>
    </div>
  </Dialog.Content>
</Dialog.Root>

<style lang="postcss">
  .insights-chat-scroll {
    scrollbar-gutter: stable both-edges;
  }
</style>
