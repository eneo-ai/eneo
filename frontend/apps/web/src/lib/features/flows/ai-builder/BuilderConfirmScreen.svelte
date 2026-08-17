<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import { slide } from "svelte/transition";
  import { cubicOut } from "svelte/easing";
  import { prefersReducedMotion } from "$lib/core/prefersReducedMotion";
  import { Button } from "$lib/components/ui/button/index.js";
  import BuilderChangeRequest from "./BuilderChangeRequest.svelte";
  import FlowAIBuilderQuestion from "./FlowAIBuilderQuestion.svelte";
  import IconCheck from "@lucide/svelte/icons/check";
  import IconChevronDown from "@lucide/svelte/icons/chevron-down";
  import type { StructuredQuestionAnswerPayload } from "./structuredQuestionAnswer";
  import type { ChatMessage } from "./protocol";
  import type {
    AIBuilderAttachmentFile,
    AIBuilderStepScopePresentation,
    RequirementsSummary
  } from "./protocol";

  interface AnsweredQuestion {
    questionId: string;
    question: string;
    answerLabel: string;
  }

  /**
   * The confirmation card is the contract: what the user confirms here is
   * exactly what the plan is built from. Any change re-arms it — a new
   * requirements version is a new contract, never a stale confirmation.
   */
  interface Props {
    summary: RequirementsSummary;
    userRequest: string | null;
    savedFlowStepScope: AIBuilderStepScopePresentation | null;
    attachments: AIBuilderAttachmentFile[];
    answered: AnsweredQuestion[];
    /** No structured question was asked before this summary. */
    noQuestions: boolean;
    confirmed: boolean;
    /** An earlier version was confirmed; this one replaced it and needs a fresh confirmation. */
    stale: boolean;
    /** The build phase (or later) already started from this confirmation. */
    readOnly?: boolean;
    disabled?: boolean;
    /** The answer being changed, edited here instead of walking back through
     *  the questions; the card below it stays visible the whole time. */
    editingQuestion?: ChatMessage | null;
    editingQuestionNumber?: number;
    onanswer?: (payload: StructuredQuestionAnswerPayload) => void;
    oncanceledit?: () => void;
    onconfirm: () => void;
    /** A change request in the user's own words; the server answers with a
     *  new requirements version, which re-arms this card. */
    onchange: (text: string) => void;
    oneditanswer: (questionId: string) => void;
  }

  let {
    summary,
    userRequest,
    savedFlowStepScope,
    attachments,
    answered,
    noQuestions,
    confirmed,
    stale,
    readOnly = false,
    disabled = false,
    editingQuestion = null,
    editingQuestionNumber = 1,
    onanswer,
    oncanceledit,
    onconfirm,
    onchange,
    oneditanswer
  }: Props = $props();

  const reducedMotion = prefersReducedMotion();
  // The change box lives under the card it rewrites, never in a side panel:
  // the user is reading the summary while describing the change.
  let changeOpen = $state(false);
  let changeRequestRef = $state<BuilderChangeRequest | undefined>();
  let assumptionsOpen = $state(false);
  const assumptions = $derived(summary.assumptions ?? []);
  const manualNotes = $derived(summary.manual_setup_notes ?? []);
</script>

<div class="flex justify-center px-7 pt-6 pb-10 max-sm:px-3 max-sm:pt-4">
  <div class="confirm-screen w-full max-w-[43.75rem] 2xl:max-w-[48.125rem]">
    {#if answered.length > 0 && !readOnly}
      <div class="mb-4 flex flex-wrap items-center gap-2">
        <span class="text-secondary text-xs">{m.ai_builder_question_answers_label()}</span>
        {#each answered as item (item.questionId)}
          <button
            type="button"
            class="border-default bg-primary hover:bg-secondary inline-flex h-[1.875rem] max-w-full items-center gap-1.5 rounded-full border px-2.5 text-[0.8125rem]"
            title={item.question}
            aria-label={m.ai_builder_question_chip_aria({
              question: item.question,
              answer: item.answerLabel
            })}
            class:opacity-60={editingQuestion?.question?.question_id === item.questionId}
            onclick={() => oneditanswer(item.questionId)}
            {disabled}
          >
            <span class="text-primary truncate font-semibold">{item.answerLabel}</span>
            <span class="text-accent-stronger shrink-0 font-semibold">
              {m.ai_builder_question_change()}
            </span>
          </button>
        {/each}
      </div>
    {/if}

    {#if editingQuestion?.question}
      <div class="mb-4">
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
        {#key editingQuestion.question.question_id}
          <FlowAIBuilderQuestion
            question={editingQuestion.question}
            questionNumber={editingQuestionNumber}
            why={editingQuestion.content.trim() || null}
            {disabled}
            onanswer={(payload) => onanswer?.(payload)}
          />
        {/key}
      </div>
    {/if}

    <section
      class="border-stronger bg-primary overflow-hidden rounded-xl border shadow-xs"
      aria-label={m.ai_builder_requirements_title()}
    >
      <header class="bg-accent-dimmer border-accent-default/25 border-b px-5 py-3.5">
        <h2
          class="text-primary text-[1.0625rem] font-bold tracking-[-0.015em]"
          tabindex="-1"
          data-builder-screen-heading
        >
          {savedFlowStepScope
            ? m.ai_builder_saved_step_review_heading({ step: savedFlowStepScope.stepNumber })
            : m.ai_builder_requirements_title()}
        </h2>
        <p class="text-accent-stronger mt-1 text-[0.8125rem] text-pretty">
          {confirmed ? m.ai_builder_confirm_lead_confirmed() : m.ai_builder_confirm_lead()}
        </p>
      </header>

      <div class="px-5 pt-[1.125rem] pb-5">
        {#if stale && !confirmed}
          <div
            class="bg-warning-dimmer border-warning-default/45 text-warning-stronger mb-3.5 flex flex-wrap items-baseline gap-x-2 gap-y-1 rounded-[9px] border px-3 py-2.5 text-[0.8125rem]"
            role="status"
          >
            <span class="font-semibold">{m.ai_builder_confirm_stale_title()}</span>
            <span>{m.ai_builder_confirm_stale_body()}</span>
          </div>
        {/if}
        {#if noQuestions && !savedFlowStepScope}
          <p class="text-secondary mb-3 text-[0.8125rem]">{m.ai_builder_confirm_no_questions()}</p>
        {/if}

        {#if savedFlowStepScope}
          <div class="border-accent-default/25 bg-accent-default/6 rounded-lg border px-3 py-2.5">
            <p class="text-primary text-sm font-medium">{savedFlowStepScope.stepName}</p>
            <p class="text-secondary mt-0.5 text-xs leading-relaxed">
              {m.ai_builder_saved_step_review_scope()}
            </p>
          </div>
        {:else}
          <p class="text-primary max-w-[64ch] text-[0.9375rem] leading-[1.6] text-pretty">
            {summary.summary}
          </p>
        {/if}

        {#if userRequest}
          <section class="border-stronger mt-4 border-l-2 py-0.5 pl-3">
            <h3 class="text-secondary text-[0.8125rem]">
              {m.ai_builder_requirements_user_request()}
            </h3>
            <p class="text-primary mt-0.5 text-[0.8125rem] leading-relaxed whitespace-pre-wrap">
              {userRequest}
            </p>
          </section>
        {/if}

        {#if !savedFlowStepScope}
          <section class="mt-[1.125rem]">
            <h3 class="text-primary text-[0.8125rem] font-bold">
              {m.ai_builder_requirements_decisions()}
            </h3>
            <dl class="mt-1.5 flex flex-col">
              {#each summary.key_decisions as decision (decision.topic)}
                <div
                  class="border-dimmer grid gap-x-4 gap-y-0.5 border-t py-2.5 sm:grid-cols-[12.5rem_1fr]"
                >
                  <dt class="text-secondary text-[0.8125rem]">{decision.topic}</dt>
                  <dd class="text-primary text-[0.85rem] font-medium">{decision.decision}</dd>
                </div>
              {/each}
              <div
                class="border-dimmer grid gap-x-4 gap-y-0.5 border-t py-2.5 sm:grid-cols-[12.5rem_1fr]"
              >
                <dt class="text-secondary text-[0.8125rem]">{m.ai_builder_requirements_input()}</dt>
                <dd class="text-primary text-[0.85rem] font-medium">{summary.input_description}</dd>
              </div>
              <div
                class="border-dimmer grid gap-x-4 gap-y-0.5 border-t py-2.5 sm:grid-cols-[12.5rem_1fr]"
              >
                <dt class="text-secondary text-[0.8125rem]">
                  {m.ai_builder_requirements_output()}
                </dt>
                <dd class="text-primary text-[0.85rem] font-medium">
                  {summary.output_description}
                </dd>
              </div>
              {#if attachments.length > 0}
                <div
                  class="border-dimmer grid gap-x-4 gap-y-0.5 border-t py-2.5 sm:grid-cols-[12.5rem_1fr]"
                >
                  <dt class="text-secondary text-[0.8125rem]">
                    {m.ai_builder_confirm_attachments()}
                  </dt>
                  <dd class="text-primary flex flex-wrap gap-1.5 text-[0.85rem] font-medium">
                    {#each attachments as file (file.id)}
                      <span
                        class="border-default inline-flex h-7 items-center rounded-full border px-2.5 text-[0.8rem]"
                        title={file.name}
                      >
                        {file.name}
                      </span>
                    {/each}
                  </dd>
                </div>
              {/if}
            </dl>
          </section>
        {/if}

        {#if manualNotes.length > 0}
          <section class="border-default mt-4 border-t pt-3.5">
            <h3 class="text-primary text-[0.8125rem] font-bold">
              {m.ai_builder_requirements_manual_notes()}
            </h3>
            <ul class="divide-dimmer mt-1 flex flex-col divide-y">
              {#each manualNotes as note (note)}
                <li class="text-secondary py-2 text-[0.8125rem] leading-relaxed">{note}</li>
              {/each}
            </ul>
          </section>
        {/if}

        {#if assumptions.length > 0}
          <section class="border-default mt-4 border-t pt-3.5">
            <button
              type="button"
              class="text-primary flex min-h-[2.75rem] w-full items-center gap-1.5 text-left text-[0.8125rem] font-bold"
              aria-expanded={assumptionsOpen}
              onclick={() => (assumptionsOpen = !assumptionsOpen)}
            >
              {m.ai_builder_assumptions()} ({assumptions.length})
              <IconChevronDown
                class="text-secondary size-3.5 transition-transform {assumptionsOpen
                  ? 'rotate-180'
                  : ''}"
              />
            </button>
            {#if !assumptionsOpen}
              <p class="text-secondary mt-1 truncate text-[0.8125rem]">{assumptions[0]}</p>
            {:else}
              <ul
                class="mt-2 flex flex-col"
                transition:slide={{ duration: reducedMotion ? 0 : 180, easing: cubicOut }}
              >
                {#each assumptions as assumption (assumption)}
                  <li
                    class="border-dimmer text-secondary border-t py-2 text-[0.8125rem] leading-relaxed text-pretty"
                  >
                    {assumption}
                  </li>
                {/each}
              </ul>
            {/if}
          </section>
        {/if}
      </div>

      <footer
        class="border-default bg-secondary flex flex-wrap items-center gap-2.5 border-t px-5 py-3.5"
      >
        {#if confirmed}
          <span
            class="text-positive-stronger inline-flex items-center gap-1.5 text-[0.8125rem] font-semibold"
          >
            <IconCheck class="size-3.5" strokeWidth={3} />
            {m.ai_builder_confirm_done()}
          </span>
        {:else}
          <span class="flex flex-col">
            <span class="text-secondary text-[0.8125rem]">{m.ai_builder_confirm_note()}</span>
            <span class="text-secondary text-xs">{m.ai_builder_confirm_note_after()}</span>
          </span>
          {#if !readOnly}
            <div class="ml-auto flex flex-wrap gap-2">
              <Button
                variant="outline"
                onclick={() => {
                  changeOpen = true;
                  changeRequestRef?.focusInput();
                }}
                {disabled}
              >
                {m.ai_builder_confirm_change_answers()}
              </Button>
              <Button variant="default" onclick={onconfirm} {disabled}>
                {m.ai_builder_confirm_action()}
              </Button>
            </div>
          {/if}
        {/if}
      </footer>
    </section>

    {#if !readOnly && !confirmed}
      <div class="mt-3">
        <BuilderChangeRequest
          bind:this={changeRequestRef}
          bind:open={changeOpen}
          {disabled}
          title={m.ai_builder_confirm_change_answers()}
          example={m.ai_builder_confirm_change_example()}
          placeholder={m.ai_builder_confirm_change_hint()}
          hint={m.ai_builder_confirm_change_request_hint()}
          onsend={(text) => {
            changeOpen = false;
            onchange(text);
          }}
        />
      </div>
    {/if}
  </div>
</div>

<style lang="postcss">
  .confirm-screen {
    animation: confirm-fade-up 0.2s ease-out;
  }
  @keyframes confirm-fade-up {
    from {
      opacity: 0;
      transform: translateY(6px);
    }
    to {
      opacity: 1;
      transform: none;
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .confirm-screen {
      animation: none;
    }
  }
</style>
