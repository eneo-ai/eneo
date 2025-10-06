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
  import { fly } from "svelte/transition";
  import { m } from "$lib/paraglide/messages";

  const intric = getIntric();
  const chat = getChatService();
  const insights = initInsightsService(intric, () => chat.partner);

  let question = $state("");
  let scrollContainer = $state<HTMLDivElement>();
  let questionForm = $state<HTMLFormElement>();
  let answerContainer = $state<HTMLDivElement>();
</script>

<div class="h-full overflow-y-auto" bind:this={scrollContainer}>
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
          {#await insights.statistics}
            <IconLoadingSpinner class="animate-spin"></IconLoadingSpinner>
          {:then stats}
            <span class="text-2xl font-extrabold">
              {stats?.total_conversations}
            </span>
          {/await}
        </div>
      </Settings.Row>

      <Settings.Row
        title={m.total_questions()}
        description={m.amount_of_questions_assistant_received()}
      >
        <div class="border-default flex h-14 items-center justify-end border-b px-4 py-2">
          {#await insights?.statistics}
            <IconLoadingSpinner class="animate-spin"></IconLoadingSpinner>
          {:then stats}
            <span class="text-2xl font-extrabold">
              {stats?.total_questions}
            </span>
          {/await}
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
        ></IconSparkles>

        <form
          class="placeholder:text-muted focus-within:border-strongest hover:border-strongest border-default flex h-14 items-center gap-4 border-b px-2"
          onsubmit={(e) => {
            e.preventDefault();
            insights.askQuestion(question);
            question = "";
            setTimeout(() => {
              if (scrollContainer && questionForm) {
                const inputRowRect =
                  questionForm.parentElement?.parentElement?.getBoundingClientRect() ??
                  new DOMRect(0, 0, 0, 0);
                const containerRect = scrollContainer.getBoundingClientRect();
                const answerHeight = containerRect.height - inputRowRect.height - 160;

                if (answerContainer) answerContainer.style.minHeight = answerHeight + "px";
                const elementPosition =
                  inputRowRect.top - containerRect.top + scrollContainer.scrollTop; // Get the position relative to the container

                scrollContainer.scrollTo({
                  // We want some space on top
                  top: elementPosition - 75,
                  behavior: "smooth"
                });
              }
            }, 1);
          }}
          bind:this={questionForm}
        >
          <input
            type="text"
            bind:value={question}
            class="flex-grow appearance-none p-2 text-lg focus:outline-none"
            placeholder={m.ask_a_question()}
          />
          <Button padding="icon" aria-label={m.send_the_question()}
            ><IconSendArrow></IconSendArrow></Button
          >
        </form>
      </Settings.Row>

      {#if insights.answer || insights.askQuestion.isLoading}
        <div
          class="bg-primary flex w-full flex-col items-center justify-start rounded-lg border p-12 shadow-md"
          bind:this={answerContainer}
          in:fly={{ y: 40, duration: 500, opacity: 0, delay: 300 }}
        >
          <div class="prose w-full max-w-[70ch] flex-grow">
            <h3 class="m-0 flex gap-2 pb-4 text-lg font-medium">
              <IconSparkles data-dynamic-colour="moss" class="text-dynamic-default size-6"
              ></IconSparkles>
              {insights.question}
            </h3>
            <Markdown source={insights.answer}></Markdown>
            {#if insights.askQuestion.isLoading}
              <IconLoadingSpinner class="animate-spin self-start"></IconLoadingSpinner>
            {/if}
          </div>
        </div>
      {/if}
    </Settings.Group>
  </Settings.Page>
</div>
