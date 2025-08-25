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
  <title>Eneo.ai – {data.currentSpace.personal ? "Personal" : data.currentSpace.name}</title>
</svelte:head>

{#snippet defaultAssistantWelcomeMessage()}
  <div class="max-w-[640px]">
    <div class="relative">
      <h3 class="b-1 text-2xl font-extrabold">Hi, {$userInfo.firstName}!</h3>
      <p class="text-secondary max-w-[50ch] pt-2 pr-20">
        Welcome to Eneo. I'm your personal assistant and ready to help. Ask me a question to get
        started.
      </p>
    </div>
  </div>
{/snippet}

<Page.Root tabController={currentTab}>
  <Page.Header>
    {#if chat.partner.type === "default-assistant"}
      <Page.Title truncate={true} title="Personal assistants"></Page.Title>
    {:else}
      <Page.Title truncate={true} parent={{ href: `/spaces/${$currentSpace.routeId}/assistants` }}>
        <AssistantSwitcher></AssistantSwitcher>
      </Page.Title>
    {/if}

    <Page.Tabbar>
      <Page.TabTrigger tab="chat">Chat</Page.TabTrigger>
      <Page.TabTrigger tab="history">History</Page.TabTrigger>
      {#if chat.partner.permissions?.includes("insight_view")}
        <Page.TabTrigger tab="insights">Insights</Page.TabTrigger>
      {/if}
    </Page.Tabbar>

    <Page.Flex>
      {#if chat.partner.type === "default-assistant"}
        <DefaultAssistantModelSwitcher></DefaultAssistantModelSwitcher>
      {:else if chat.partner.permissions?.includes("edit")}
        <Button href="/spaces/{$currentSpace.routeId}/{chat.partner.type}s/{chat.partner.id}/edit"
          >Edit</Button
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
        >New conversation
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
              aria-label="Load more conversations"
            >
              Load more conversations</Button
            >
            <p role="status" aria-live="polite">
              Loaded {chat.loadedConversations.length}/{chat.totalConversations} conversations
            </p>
          {:else if chat.totalConversations > 0}
            <p role="status" aria-live="polite">
              Loaded all {chat.totalConversations} conversations.
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
          No insights available for this chat.
        </div>
      {/if}
    </Page.Tab>
  </Page.Main>
</Page.Root>
