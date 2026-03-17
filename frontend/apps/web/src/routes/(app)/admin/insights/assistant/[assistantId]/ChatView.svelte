<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { IconLoadingSpinner } from "@intric/icons/loading-spinner";
  import { IconSparkles } from "@intric/icons/sparkles";
  import { IconSendArrow } from "@intric/icons/send-arrow";
  import { Button, Markdown } from "@intric/ui";
  import { goto } from "$app/navigation";
  import { page } from "$app/stores";
  import { getIntric } from "$lib/core/Intric";
  import type { Assistant } from "@intric/intric-js";
  import type { CalendarDate } from "@internationalized/date";
  import { m } from "$lib/paraglide/messages";

  const intric = getIntric();

  export let assistant: Assistant;
  export let includeFollowups: boolean;
  export let timeframe: { start: CalendarDate; end: CalendarDate };

  let question = "";
  let loadingAnswer = false;
  let copiedAnswer = false;

  const NOT_ANSWERED = "_NO_QUESTION_ASKED_";
  let message = { question: "", answer: NOT_ANSWERED };

  async function askQuestion() {
    const trimmedQuestion = question.trim();
    if (trimmedQuestion === "") {
      return;
    }

    loadingAnswer = true;

    message.question = trimmedQuestion;
    message.answer = "";
    question = "";
    textarea.style.height = "auto";

    try {
      const inclusiveEnd = timeframe.end.add({ days: 1 }).toString();
      const { answer } = await intric.analytics.ask({
        assistant: { id: assistant.id },
        options: {
          includeFollowups,
          start: timeframe.start.toString(),
          end: inclusiveEnd
        },
        question: message.question,
        onAnswer: (token) => {
          message.answer += token;
        }
      });
      message.answer = answer;
    } catch (e) {
      console.error(e);
      message.answer = m.error_connecting_to_server();
    }
    loadingAnswer = false;
  }

  async function copyAnswer() {
    if (!message.answer || message.answer === NOT_ANSWERED) return;
    if (!navigator?.clipboard) return;
    await navigator.clipboard.writeText(message.answer);
    copiedAnswer = true;
    setTimeout(() => {
      copiedAnswer = false;
    }, 1500);
  }

  async function openQuestionHistory() {
    const next = new URL($page.url);
    next.searchParams.set("tab", "questions");
    await goto(next.toString(), {
      replaceState: true,
      noScroll: true,
      keepFocus: true
    });
  }

  let textarea: HTMLTextAreaElement;
</script>

<div class="mx-auto flex w-full max-w-6xl flex-col gap-4 px-6 py-4">
  <form
    class="bg-frosted-glass-primary border-default sticky top-0 z-10 flex w-full flex-col gap-3 rounded-lg border px-4 py-4 shadow-md"
    aria-labelledby="insights_description"
    on:submit|preventDefault={askQuestion}
  >
    <div class="flex items-baseline justify-between gap-3">
      <label for="question" class="text-sm font-semibold tracking-tight"
        >{m.ask_about_insights()}</label
      >
      <span class="text-muted text-[11px]">Enter / Shift+Enter</span>
    </div>

    <div
      class="border-default bg-primary flex w-full items-end justify-center gap-1 overflow-clip rounded-lg border p-1"
    >
      <textarea
        aria-label={m.ask_question_about_assistant()}
        placeholder={m.ask_about_insights()}
        bind:this={textarea}
        bind:value={question}
        on:input={() => {
          textarea.style.height = "";
          const scrollHeight = Math.min(textarea.scrollHeight, 200);
          textarea.style.height = scrollHeight > 45 ? scrollHeight + "px" : "auto";
          textarea.style.overflowY = scrollHeight === 200 ? "auto" : "hidden";
        }}
        on:keydown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            if (!loadingAnswer) {
              void askQuestion();
            }
          }
        }}
        required
        name="question"
        id="question"
        rows="1"
        class="bg-primary ring-default placeholder:text-secondary hover:border-strongest relative min-h-10 flex-grow resize-none overflow-y-auto rounded-md px-4 py-2 text-lg hover:ring-2"
      ></textarea>
      <button
        disabled={loadingAnswer || question.trim() === ""}
        type="submit"
        aria-label={m.submit_your_question()}
        class="bg-accent-default hover:bg-accent-stronger text-on-fill flex h-11 w-11 items-center justify-center rounded-lg p-2 text-lg transition-colors disabled:opacity-50"
      >
        {#if loadingAnswer}
          <IconLoadingSpinner class="animate-spin" />
        {:else}
          <IconSendArrow />
        {/if}
      </button>
    </div>
  </form>

  {#if message.answer === NOT_ANSWERED}
    <div
      class="empty-state border-dimmer flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed px-8 py-16 text-center"
      id="insights_description"
      role="status"
      aria-live="polite"
      style="--delay: 100ms"
    >
      <IconSparkles class="text-accent-default mb-1 size-7 opacity-50" aria-hidden="true" />
      <p class="text-primary text-base font-medium">
        {m.discover_what_users_wanted({ assistant: assistant.name })}
      </p>
      <p class="text-secondary max-w-md text-sm">
        {m.ask_question_about_conversation_history()}
      </p>
    </div>
  {:else}
    <div
      class="answer-card border-default bg-primary rounded-lg border shadow-sm"
      style="--delay: 50ms"
    >
      <div
        class="border-default bg-secondary flex flex-wrap items-center justify-between gap-3 rounded-t-lg border-b px-4 py-3"
      >
        <div class="flex min-w-0 flex-1 items-center gap-2 text-sm font-medium">
          <IconSparkles
            class="text-accent-default size-4 shrink-0 opacity-60"
            aria-hidden="true"
          />
          <span class="truncate">{message.question}</span>
        </div>
        <div class="flex shrink-0 items-center gap-2">
          <Button variant="outlined" on:click={copyAnswer}>
            {copiedAnswer ? m.copied() : m.copy()}
          </Button>
          <div class="border-dimmer h-5 w-px border-l" aria-hidden="true"></div>
          <Button variant="outlined" on:click={openQuestionHistory}>
            {m.question_history()}
          </Button>
          <Button
            variant="outlined"
            on:click={() => {
              message.answer = NOT_ANSWERED;
              copiedAnswer = false;
            }}>{m.new_questions()}</Button
          >
        </div>
      </div>

      <div
        class="prose prose-neutral max-h-[min(65vh,42rem)] overflow-y-auto px-6 pt-4 pb-6 pr-10 text-base [scrollbar-gutter:stable_both-edges]"
        aria-live="polite"
      >
        {#if loadingAnswer && message.answer.length === 0}
          <div class="flex flex-col gap-3 py-2" role="status" aria-live="polite">
            <div class="h-4 w-3/4 animate-pulse rounded bg-secondary"></div>
            <div
              class="h-4 w-full animate-pulse rounded bg-secondary"
              style="animation-delay: 75ms"
            ></div>
            <div
              class="h-4 w-5/6 animate-pulse rounded bg-secondary"
              style="animation-delay: 150ms"
            ></div>
            <div
              class="h-4 w-2/3 animate-pulse rounded bg-secondary"
              style="animation-delay: 225ms"
            ></div>
            <span class="sr-only">{m.loading()}</span>
          </div>
        {/if}
        <Markdown source={message.answer} />
      </div>
    </div>
  {/if}
</div>

<style>
  @keyframes nordic-fade-in {
    from {
      opacity: 0;
      transform: translateY(4px);
    }
    to {
      opacity: 1;
      transform: translateY(0);
    }
  }
  .empty-state,
  .answer-card {
    animation: nordic-fade-in 0.5s cubic-bezier(0.25, 0.46, 0.45, 0.94) both;
    animation-delay: var(--delay, 50ms);
  }
</style>
