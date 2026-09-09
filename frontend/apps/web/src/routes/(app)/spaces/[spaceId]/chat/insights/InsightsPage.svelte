<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Settings } from "$lib/components/layout";
  import { getEneo } from "$lib/core/Eneo";
  import { getChatService } from "$lib/features/chat/ChatService.svelte";
  import InsightsChat from "$lib/features/insights/components/InsightsChat.svelte";
  import InsightsExploreConversationsDialog from "$lib/features/insights/components/InsightsExploreConversationsDialog.svelte";
  import { initInsightsChatService } from "$lib/features/insights/InsightsChatService.svelte";
  import { initInsightsService } from "$lib/features/insights/InsightsService.svelte";
  import { IconLoadingSpinner } from "@eneo/icons/loading-spinner";
  import { Input } from "@eneo/ui";
  import { m } from "$lib/paraglide/messages";

  const eneo = getEneo();
  const chat = getChatService();
  const insights = initInsightsService(eneo, () => chat.partner);
  initInsightsChatService(
    eneo,
    () => chat.partner,
    () => insights.dateRange
  );
</script>

<div class="h-full overflow-y-auto">
  <div
    class="bg-primary border-default sticky top-0 z-[11] mx-auto mb-4 w-full max-w-[74rem] rounded-xl rounded-t-none border border-t-0 py-2 pr-2.5 pl-4 shadow-lg"
  >
    <Input.DateRange bind:value={insights.dateRange}
      >{m.choose_timeframe_for_insights()}</Input.DateRange
    >
  </div>
  <Settings.Page>
    <Settings.Group title={m.statistics()}>
      <Settings.Row
        title={m.total_conversations()}
        description={m.number_of_times_new_conversation_started()}
      >
        <div class="border-default flex h-14 items-center justify-end border-b px-4 py-2">
          {#if insights.statisticsLoading && !insights.statistics}
            <IconLoadingSpinner class="animate-spin"></IconLoadingSpinner>
          {:else if insights.statisticsError && !insights.statistics}
            <span class="text-secondary text-sm">{m.error_connecting_to_server()}</span>
          {:else}
            <div class="flex items-center gap-2">
              <span class="text-2xl font-extrabold">
                {insights.statistics?.total_conversations ?? "—"}
              </span>
              {#if insights.statisticsLoading}
                <IconLoadingSpinner
                  class="text-secondary size-4 animate-spin"
                  aria-label={m.loading()}
                ></IconLoadingSpinner>
              {/if}
            </div>
          {/if}
        </div>
      </Settings.Row>

      <Settings.Row
        title={m.total_questions()}
        description={m.amount_of_questions_assistant_received()}
      >
        <div class="border-default flex h-14 items-center justify-end border-b px-4 py-2">
          {#if insights.statisticsLoading && !insights.statistics}
            <IconLoadingSpinner class="animate-spin"></IconLoadingSpinner>
          {:else if insights.statisticsError && !insights.statistics}
            <span class="text-secondary text-sm">{m.error_connecting_to_server()}</span>
          {:else}
            <div class="flex items-center gap-2">
              <span class="text-2xl font-extrabold">
                {insights.statistics?.total_questions ?? "—"}
              </span>
              {#if insights.statisticsLoading}
                <IconLoadingSpinner
                  class="text-secondary size-4 animate-spin"
                  aria-label={m.loading()}
                ></IconLoadingSpinner>
              {/if}
            </div>
          {/if}
        </div>
      </Settings.Row>
    </Settings.Group>
    <Settings.Group title={m.explore()}>
      <Settings.Row
        title={m.explore_conversations()}
        description={m.view_all_conversations_users_had()}
      >
        <InsightsExploreConversationsDialog></InsightsExploreConversationsDialog>
      </Settings.Row>
    </Settings.Group>
    <Settings.Group title={m.insights_chat()}>
      <InsightsChat />
    </Settings.Group>
  </Settings.Page>
</div>
