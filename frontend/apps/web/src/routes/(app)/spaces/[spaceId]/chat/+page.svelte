<script lang="ts">
  import { pushState } from "$app/navigation";
  import { Page } from "$lib/components/layout/index.js";
  import { getAppContext } from "$lib/core/AppContext.js";
  import { initChatService } from "$lib/features/chat/ChatService.svelte";
  import ConversationView from "$lib/features/chat/components/conversation/ConversationView.svelte";
  import HistoryTable from "$lib/features/chat/components/history/HistoryTable.svelte";
  import AssistantSwitcher from "$lib/features/chat/components/switcher/AssistantSwitcher.svelte";
  import DefaultAssistantModelSwitcher from "$lib/features/chat/components/switcher/DefaultAssistantModelSwitcher.svelte";
  import { getChatQueryParams } from "$lib/features/chat/getChatQueryParams.js";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { IconLoadingSpinner } from "@intric/icons/loading-spinner";
  import { Button } from "@intric/ui";
  import { fade } from "svelte/transition";
  import InsightsPage from "./insights/InsightsPage.svelte";
  import { page } from "$app/state";
  import { writable } from "svelte/store";
  import { untrack } from "svelte";
  import { m } from "$lib/paraglide/messages";

  const { data } = $props();

  const {
    state: { userInfo }
  } = getAppContext();

  const {
    state: { currentSpace }
  } = getSpacesManager();

  const chat = initChatService(data);

  let currentTab = writable("chat");

  $effect(() => {
    chat.init(data);

    untrack(() => {
      // If on insights page go to chat page
      if ($currentTab === "insights" && !data.chatPartner.insight_enabled) {
        $currentTab = "chat";
        page.url.searchParams.set("tab", "chat");
        return;
      }

      // If opening default assistant always open chat
      if (data.chatPartner.type === "default-assistant") {
        $currentTab = "chat";
      }
    });
  });
</script>

<svelte:head>
  <title>Eneo.ai – {data.currentSpace.personal ? m.personal() : data.currentSpace.name}</title>
</svelte:head>

{#snippet defaultAssistantWelcomeMessage()}
  <div class="max-w-[640px]">
    <div class="relative">
      <h3 class="b-1 text-2xl font-extrabold">
        {m.hi_firstname({ firstName: $userInfo.firstName })}
      </h3>
      <p class="text-secondary max-w-[50ch] pt-2 pr-20">
        {m.personal_assistant_welcome()}
      </p>
    </div>
  </div>
{/snippet}

<Page.Root tabController={currentTab}>
  <Page.Header>
    {#if chat.partner.type === "default-assistant"}
      <Page.Title truncate={true} title={m.personal_assistant()}></Page.Title>
    {:else}
      <Page.Title truncate={true} parent={{ href: `/spaces/${$currentSpace.routeId}/assistants` }}>
        <AssistantSwitcher></AssistantSwitcher>
      </Page.Title>
    {/if}

    <Page.Tabbar>
      <Page.TabTrigger tab="chat">{m.chat()}</Page.TabTrigger>
      <Page.TabTrigger tab="history">{m.history()}</Page.TabTrigger>
      {#if chat.partner.permissions?.includes("insight_view")}
        <Page.TabTrigger tab="insights">{m.insights()}</Page.TabTrigger>
      {/if}
    </Page.Tabbar>

    <Page.Flex>
      {#if chat.partner.type === "default-assistant"}
        <DefaultAssistantModelSwitcher></DefaultAssistantModelSwitcher>
      {:else if chat.partner.permissions?.includes("edit")}
        <Button href="/spaces/{$currentSpace.routeId}/{chat.partner.type}s/{chat.partner.id}/edit"
          >{m.edit()}</Button
        >
      {/if}
      <Button
        variant="primary"
        on:click={() => {
          chat.newConversation();
          const tab = "chat";
          pushState(
            `/spaces/${$currentSpace.routeId}/chat/?${getChatQueryParams({ chatPartner: chat.partner, tab })}`,
            {
              conversation: undefined,
              tab
            }
          );
        }}
        class="!line-clamp-1"
        >{m.new_conversation()}
      </Button>
    </Page.Flex>
  </Page.Header>

  <Page.Main>
    <Page.Tab id="chat">
      <ConversationView
        children={chat.partner.type === "default-assistant"
          ? defaultAssistantWelcomeMessage
          : undefined}
      ></ConversationView>
    </Page.Tab>
    <Page.Tab id="history">
      {#await data.initialHistory}
        <!-- TODO: This has some delay on it as the underlying table is delayed in updating its rows, so we cover it up during that time. -->
        <div
          class="bg-primary absolute inset-0 z-[100] flex items-center justify-center"
          out:fade={{ delay: 250, duration: 100 }}
        >
          <IconLoadingSpinner class="animate-spin"></IconLoadingSpinner>
        </div>
      {/await}
      <HistoryTable
        onConversationLoaded={(conversation) => {
          const tab = "chat";
          pushState(
            `/spaces/${$currentSpace.routeId}/chat/?${getChatQueryParams({ chatPartner: chat.partner, conversation, tab })}`,
            {
              conversation,
              tab
            }
          );
        }}
        onConversationDeleted={() => {
          const tab = "history";
          pushState(
            `/spaces/${$currentSpace.routeId}/chat/?${getChatQueryParams({ chatPartner: chat.partner, tab })}`,
            {
              conversation: undefined,
              tab
            }
          );
        }}
      />

      <div class="text-secondary flex-col pt-8 pb-12">
        <div class="flex flex-col items-center justify-center gap-2">
          {#if chat.hasMoreConversations}
            <Button
              variant="primary-outlined"
              on:click={() => chat.loadMoreConversations()}
              aria-label={m.load_more_conversations()}
            >
              {m.load_more_conversations()}</Button
            >
            <p role="status" aria-live="polite">
              {m.loaded_conversations_count({
                loaded: chat.loadedConversations.length,
                total: chat.totalConversations
              })}
            </p>
          {:else if chat.totalConversations > 0}
            <p role="status" aria-live="polite">
              {m.loaded_all_conversations({ total: chat.totalConversations })}
            </p>
          {/if}
        </div>
      </div>
    </Page.Tab>

    <Page.Tab id="insights">
      {#if chat.partner.permissions?.includes("insight_view")}
        {#if page.state.tab === "insights" || page.url.searchParams.get("tab") === "insights"}
          <InsightsPage></InsightsPage>
        {/if}
      {:else}
        <div class="absolute inset-0 flex items-center justify-center">
          {m.no_insights_available_for_this_chat()}
        </div>
      {/if}
    </Page.Tab>
  </Page.Main>
</Page.Root>
