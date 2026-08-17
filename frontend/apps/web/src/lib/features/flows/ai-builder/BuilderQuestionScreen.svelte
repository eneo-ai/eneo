<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import FlowAIBuilderQuestion from "./FlowAIBuilderQuestion.svelte";
  import type { ChatMessage } from "./protocol";
  import type { StructuredQuestionAnswerPayload } from "./structuredQuestionAnswer";

  interface AnsweredQuestion {
    questionId: string;
    question: string;
    answerLabel: string;
  }

  interface Props {
    /** The message carrying the question to answer now (pending, or one being changed). */
    questionMessage: ChatMessage;
    questionNumber: number;
    answered: AnsweredQuestion[];
    /** The question being re-answered, if any; the card then shows that one. */
    editingQuestionId?: string | null;
    disabled?: boolean;
    onanswer: (payload: StructuredQuestionAnswerPayload) => void;
    onedit: (questionId: string) => void;
    oncanceledit?: () => void;
  }

  let {
    questionMessage,
    questionNumber,
    answered,
    editingQuestionId = null,
    disabled = false,
    onanswer,
    onedit,
    oncanceledit
  }: Props = $props();

  const question = $derived(questionMessage.question!);
  const why = $derived(questionMessage.content.trim() || null);
</script>

<div class="flex justify-center px-7 pt-6 pb-10 max-sm:px-3 max-sm:pt-4 max-sm:pb-0">
  <div class="flex w-full max-w-[41.25rem] flex-col 2xl:max-w-[45.625rem]">
    {#if answered.length > 0}
      <!-- On a phone the answered chips stay on one line and scroll sideways;
           wrapping them would push the question itself below the fold. -->
      <div
        class="mb-4 flex flex-wrap items-center gap-2 max-sm:-mx-3 max-sm:flex-nowrap max-sm:overflow-x-auto max-sm:px-3 max-sm:pb-1"
      >
        <span class="text-secondary shrink-0 text-xs">{m.ai_builder_question_answers_label()}</span>
        {#each answered as item (item.questionId)}
          <button
            type="button"
            class="border-default bg-primary hover:bg-secondary inline-flex h-[1.875rem] max-w-full shrink-0 items-center gap-1.5 rounded-full border px-2.5 text-[0.8125rem] max-sm:h-[44px] max-sm:max-w-[70vw] max-sm:px-3.5"
            class:opacity-60={editingQuestionId === item.questionId}
            title={item.question}
            aria-label={m.ai_builder_question_chip_aria({
              question: item.question,
              answer: item.answerLabel
            })}
            onclick={() => onedit(item.questionId)}
            {disabled}
          >
            <span class="text-primary truncate font-semibold">{item.answerLabel}</span>
            <span class="text-accent-stronger shrink-0 font-semibold"
              >{m.ai_builder_question_change()}</span
            >
          </button>
        {/each}
      </div>
    {/if}

    {#if editingQuestionId}
      <p class="text-secondary mb-2 flex items-center gap-2 text-xs">
        {m.ai_builder_question_editing_note()}
        <button
          type="button"
          class="text-accent-stronger font-semibold hover:underline"
          onclick={() => oncanceledit?.()}
        >
          {m.cancel()}
        </button>
      </p>
    {/if}

    <!-- The card comes last on a phone so its pinned action bar ends flush with
         the bottom of the screen; the reassurance moves above it. -->
    <div class="max-sm:order-last">
      {#key question.question_id}
        <FlowAIBuilderQuestion {question} {questionNumber} {why} {disabled} {onanswer} />
      {/key}
    </div>

    <p class="text-secondary mt-3.5 px-0.5 text-[0.8125rem] text-pretty max-sm:mt-0 max-sm:mb-3.5">
      {m.ai_builder_question_footnote()}
    </p>
  </div>
</div>
