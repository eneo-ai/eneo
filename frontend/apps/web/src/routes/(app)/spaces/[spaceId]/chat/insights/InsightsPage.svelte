<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Settings } from "$lib/components/layout";
  import { getIntric } from "$lib/core/Intric";
  import { getChatService } from "$lib/features/chat/ChatService.svelte";
  import InsightsExploreConversationsDialog from "$lib/features/insights/components/InsightsExploreConversationsDialog.svelte";
  import { initInsightsService } from "$lib/features/insights/InsightsService.svelte";
  import { IconLoadingSpinner } from "@intric/icons/loading-spinner";
  import { IconSendArrow } from "@intric/icons/send-arrow";
  import { IconSparkles } from "@intric/icons/sparkles";
  import { Button, Input, Markdown } from "@intric/ui";
  import { m } from "$lib/paraglide/messages";

  const intric = getIntric();
  const chat = getChatService();
  const insights = initInsightsService(intric, () => chat.partner);

  let question = $state("");
</script>

<div class="h-full overflow-y-auto pt-4">
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
      <Settings.Row
        title={m.generate_insights()}
        description={m.ask_question_about_how_users_used_assistant()}
      >
        <IconSparkles
          data-dynamic-colour="moss"
          class="text-dynamic-default ml-2 size-6"
          slot="title"
          aria-hidden="true"
        ></IconSparkles>

        <form
          class="placeholder:text-muted focus-within:border-strongest hover:border-strongest border-default flex min-h-14 items-center gap-4 border-b px-2"
          onsubmit={(e) => {
            e.preventDefault();
            if (!question.trim() || insights.askQuestion.isLoading) {
              return;
            }
            insights.askQuestion(question);
            question = "";
          }}
        >
          <label class="sr-only" for="insights-question">{m.ask_a_question()}</label>
          <input
            id="insights-question"
            name="insights-question"
            type="text"
            bind:value={question}
            class="flex-grow appearance-none p-2 text-lg focus:outline-none"
            placeholder={m.ask_a_question()}
            autocomplete="off"
            aria-describedby="insights-question-status-live"
          />
          <Button
            padding="icon"
            aria-label={m.send_the_question()}
            disabled={insights.askQuestion.isLoading || !question.trim()}
            ><IconSendArrow aria-hidden="true"></IconSendArrow></Button
          >
        </form>
        <p id="insights-question-status-live" class="sr-only" aria-live="polite">
          {#if insights.askQuestion.isLoading}
            {m.loading()}
          {:else if insights.analysisJobStatus === "queued" || insights.analysisJobStatus === "processing"}
            {m.loading_ellipsis()}
          {:else if insights.analysisJobError}
            {m.error_connecting_to_server()}
          {/if}
        </p>
      </Settings.Row>

      {#if insights.answer || insights.askQuestion.isLoading || insights.analysisJobStatus}
        <div
          class="bg-primary border-default flex min-h-[14rem] w-full flex-col items-center justify-start rounded-lg border p-8 shadow-md md:p-12"
        >
          <div
            class="insights-answer-scroll prose w-full max-w-[70ch] flex-grow overflow-y-auto pr-6 md:pr-8 max-h-[min(65vh,42rem)]"
            tabindex="-1"
            role="region"
            aria-label={m.generate_insights()}
          >
            <h3 class="m-0 flex gap-2 pb-4 text-lg font-medium">
              <IconSparkles data-dynamic-colour="moss" class="text-dynamic-default size-6"
                aria-hidden="true"
              ></IconSparkles>
              {insights.question}
            </h3>
            <Markdown source={insights.answer}></Markdown>
            {#if !insights.answer && (insights.analysisJobStatus === "queued" || insights.analysisJobStatus === "processing")}
              <p class="text-secondary text-base">{m.loading_ellipsis()}</p>
            {/if}
            {#if insights.askQuestion.isLoading}
              <div
                class="text-secondary flex items-center gap-2 pt-4"
                role="status"
                aria-live="polite"
              >
                <IconLoadingSpinner class="animate-spin" aria-hidden="true"></IconLoadingSpinner>
                <span>{m.loading()}</span>
              </div>
            {/if}
          </div>
          {#if insights.analysisJobStatus === "queued" || insights.analysisJobStatus === "processing"}
            <p
              class="text-secondary self-start pt-4 text-sm"
              role="status"
              aria-live="polite"
            >
              {m.loading_ellipsis()}
            </p>
          {/if}
          {#if insights.analysisJobError}
            <p class="text-red-700 self-start pt-4 text-sm" role="alert">
              {m.error_connecting_to_server()}
            </p>
          {/if}
        </div>
      {/if}
    </Settings.Group>
  </Settings.Page>
</div>

<style lang="postcss">
  .insights-answer-scroll {
    scrollbar-gutter: stable both-edges;
  }
</style>
