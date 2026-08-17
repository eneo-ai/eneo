<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import { SvelteMap, SvelteSet } from "svelte/reactivity";
  import { slide } from "svelte/transition";
  import { cubicOut } from "svelte/easing";
  import { prefersReducedMotion } from "$lib/core/prefersReducedMotion";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Skeleton } from "$lib/components/ui/skeleton/index.js";
  import * as Tooltip from "$lib/components/ui/tooltip/index.js";
  import IconInfo from "@lucide/svelte/icons/info";
  import BuilderChangeRequest from "./BuilderChangeRequest.svelte";
  import { summaryTerm } from "./aiBuilderSummaryText";
  import FlowAIBuilderQuestion from "./FlowAIBuilderQuestion.svelte";
  import IconCheck from "@lucide/svelte/icons/check";
  import IconChevronDown from "@lucide/svelte/icons/chevron-down";
  import type {
    StructuredInputFieldAnswer,
    StructuredQuestionAnswerPayload
  } from "./structuredQuestionAnswer";
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
    /** What the answer settled, e.g. "Indata vid körning" — from the decision
     *  the server links to this question. */
    topic?: string | null;
    /** Eneo settled this one after the user handed it back. */
    delegated?: boolean;
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
    /** What the person running the flow fills in before each run. Not what
     *  Eneo produces — that is the content list — and not something the card
     *  can read off a decision row, which only names the option chosen. */
    runtimeFields?: { label: string; type: string; required: boolean }[];
    runtimeFieldsQuestionId?: string | null;
    /** No structured question was asked before this summary. */
    noQuestions: boolean;
    confirmed: boolean;
    /** An earlier version was confirmed; this one replaced it and needs a fresh confirmation. */
    stale: boolean;
    /** A turn is running: the card is waiting for Eneo to answer, and the user
     *  needs to see that their correction went somewhere. */
    pending?: boolean;
    /** The build phase (or later) already started from this confirmation. */
    readOnly?: boolean;
    /** Changing a published flow, so a reopened question must not propose
     *  moving away from what the flow runs on today. */
    isEdit?: boolean;
    disabled?: boolean;
    /** The answer being changed, edited here instead of walking back through
     *  the questions; the card below it stays visible the whole time. */
    editingQuestion?: ChatMessage | null;
    editingQuestionNumber?: number | null;
    /** What the user already answered with, so reopening edits those fields
     *  instead of replacing them with an empty form. */
    editingFields?: StructuredInputFieldAnswer[] | null;
    onanswer?: (payload: StructuredQuestionAnswerPayload) => void;
    oncanceledit?: () => void;
    onconfirm: () => void;
    /** A change request in the user's own words, optionally about one row; the
     *  server answers with a new requirements version, which re-arms this card. */
    onchange: (text: string, topic?: string | null) => void;
    oneditanswer: (questionId: string) => void;
  }

  let {
    summary,
    userRequest,
    savedFlowStepScope,
    attachments,
    answered,
    runtimeFields = [],
    runtimeFieldsQuestionId = null,
    noQuestions,
    confirmed,
    stale,
    pending = false,
    readOnly = false,
    isEdit = false,
    disabled = false,
    editingQuestion = null,
    editingQuestionNumber = null,
    editingFields = null,
    onanswer,
    oncanceledit,
    onconfirm,
    onchange,
    oneditanswer
  }: Props = $props();

  // Naming what Eneo derived only means something beside rows the user settled
  // themselves; on a run with no questions every row would carry it.
  const hasAnsweredDecision = $derived(
    summary.key_decisions.some((decision) => decision.question_id != null)
  );
  const namedContentFields = $derived(summary.named_content_fields ?? []);
  const decisionQuestionIds = $derived(
    new SvelteSet(
      summary.key_decisions
        .map((decision) => decision.question_id)
        .filter((id): id is string => id != null)
    )
  );
  const unlistedAnswers = $derived(
    answered.filter((item) => !decisionQuestionIds.has(item.questionId))
  );
  const delegatedQuestionIds = $derived(
    new SvelteSet(answered.filter((item) => item.delegated).map((item) => item.questionId))
  );
  // What the decisions already say, so the input and result rows do not repeat
  // a value the user has just read one line above.
  const inputTerm = $derived(summaryTerm(summary.input_description));
  const outputTerm = $derived(summaryTerm(summary.output_description));
  const decisionsState = $derived(
    new SvelteSet(summary.key_decisions.map((decision) => decision.decision.trim()))
  );
  const contractRows = $derived(
    [
      { label: m.ai_builder_requirements_input(), value: inputTerm },
      { label: m.ai_builder_requirements_output(), value: outputTerm }
    ].filter((row) => !decisionsState.has(row.value))
  );

  // One owner for the whole correction: which row it is about, whether the box
  // is open, and the words in it. A draft belongs to the scope it was written
  // under, so moving to another row (or to the card as a whole) never carries
  // it along relabelled as something the user did not say.
  function openChange(topic: string | null) {
    const next = topic?.trim() ?? null;
    if (next !== changeTopic) {
      changeDrafts.set(changeTopic, changeDraft);
      changeDraft = changeDrafts.get(next) ?? "";
    }
    // Two open editors would leave the user correcting one thing while looking
    // at another.
    oncanceledit?.();
    changeTopic = next;
    changeOpen = true;
    void changeRequestRef?.focusInput();
  }

  let editorRef = $state<HTMLElement | null>(null);
  // The editor opens above the card, which on a long card is off-screen: from
  // where the user clicked, nothing appeared to happen at all.
  $effect(() => {
    if (editingQuestion?.question && editorRef) {
      editorRef.scrollIntoView({
        block: "center",
        behavior: reducedMotion ? "auto" : "smooth"
      });
    }
  });

  function reopenQuestion(questionId: string) {
    changeDrafts.set(changeTopic, changeDraft);
    changeOpen = false;
    changeTopic = null;
    changeDraft = "";
    oneditanswer(questionId);
  }

  // Swedish and English both break on "1 obligatoriska" / "1 fields", and the
  // required half says nothing when none are.
  let allContentFieldsShown = $state(false);
  const RUNTIME_FIELD_CHIP_CAP = 6;
  const CONTENT_FIELD_CHIP_CAP = 10;
  let allRuntimeFieldsShown = $state(false);
  const shownRuntimeFields = $derived(
    allRuntimeFieldsShown ? runtimeFields : runtimeFields.slice(0, RUNTIME_FIELD_CHIP_CAP)
  );
  const shownContentFields = $derived(
    allContentFieldsShown ? namedContentFields : namedContentFields.slice(0, CONTENT_FIELD_CHIP_CAP)
  );
  const runtimeFieldsCount = $derived.by(() => {
    const total =
      runtimeFields.length === 1
        ? m.ai_builder_requirements_runtime_fields_count_one()
        : m.ai_builder_requirements_runtime_fields_count({ count: String(runtimeFields.length) });
    const required = runtimeFields.filter((field) => field.required).length;
    if (required === 0) return total;
    const requiredText =
      required === 1
        ? m.ai_builder_requirements_field_required_count_one()
        : m.ai_builder_requirements_field_required_count({ required: String(required) });
    return `${total} · ${requiredText}`;
  });

  function fieldTypeLabel(type: string): string {
    if (type === "number") return m.flow_form_field_type_number();
    if (type === "date") return m.flow_form_field_type_date();
    if (type === "select") return m.flow_form_field_type_select();
    if (type === "multiselect") return m.flow_form_field_type_multiselect();
    return m.flow_form_field_type_text();
  }

  const reducedMotion = prefersReducedMotion();
  // The change box lives under the card it rewrites, never in a side panel:
  // the user is reading the summary while describing the change.
  let changeOpen = $state(false);
  /** Which row the open change box is correcting; cleared with its chip. */
  let changeTopic = $state<string | null>(null);
  let changeDraft = $state("");
  /** What the user has typed under each row, so moving between rows loses
   *  nothing and never relabels one row's words as another's. */
  const changeDrafts = new SvelteMap<string | null, string>();
  let changeRequestRef = $state<BuilderChangeRequest | undefined>();
  let assumptionsOpen = $state(false);
  const assumptions = $derived(summary.assumptions ?? []);
  const manualNotes = $derived(summary.manual_setup_notes ?? []);
</script>

<div
  class="flex min-h-full shrink-0 justify-center px-7 pt-6 pb-16 max-lg:px-5 max-md:px-4 max-sm:pt-4 max-sm:pb-12"
>
  <div class="confirm-screen my-auto w-full max-w-[43.75rem] 2xl:max-w-[48.125rem]">
    {#if unlistedAnswers.length > 0 && !readOnly}
      <div class="mb-4 flex flex-wrap items-center gap-2">
        <span class="text-secondary text-xs">{m.ai_builder_question_answers_label()}</span>
        {#each unlistedAnswers as item (item.questionId)}
          <button
            type="button"
            class="border-default bg-primary hover:bg-secondary inline-flex h-[1.875rem] max-w-full items-center gap-1.5 rounded-full border px-[0.6875rem] text-[0.78125rem]"
            title={item.question}
            aria-label={m.ai_builder_question_chip_aria({
              question: item.question,
              answer: item.answerLabel
            })}
            class:opacity-60={editingQuestion?.question?.question_id === item.questionId}
            onclick={() => reopenQuestion(item.questionId)}
            {disabled}
          >
            {#if item.topic}
              <span class="text-secondary shrink-0">{item.topic}</span>
            {/if}
            <span class="text-primary truncate font-semibold">{item.answerLabel}</span>
            {#if item.delegated}
              <span class="text-secondary shrink-0 text-[0.6875rem]">
                {m.ai_builder_question_delegated_badge()}
              </span>
            {/if}
            <span class="text-accent-stronger shrink-0 font-semibold">
              {m.ai_builder_question_change()}
            </span>
          </button>
        {/each}
      </div>
    {/if}

    {#if editingQuestion?.question}
      <div class="mb-4" bind:this={editorRef}>
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
            answeredFields={editingFields}
            {isEdit}
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
              {hasAnsweredDecision
                ? m.ai_builder_requirements_decisions()
                : m.ai_builder_requirements_decisions_derived()}
            </h3>
            <dl class="mt-1.5 flex flex-col">
              {#each summary.key_decisions as decision (decision.topic)}
                {@const settledBy = decision.question_id ?? null}
                <div
                  class="border-dimmer grid items-baseline gap-x-4 gap-y-0.5 border-t py-2.5 sm:grid-cols-[12.5rem_1fr_auto]"
                >
                  <dt class="text-secondary text-[0.8125rem]">{decision.topic}</dt>
                  <dd class="text-primary text-[0.85rem] font-medium">
                    {decision.decision}
                    <!-- Says where the value came from, so it sits with the
                         value. Only worth saying beside rows the user did
                         settle themselves: with no questions asked, every row
                         follows from the description and the note says nothing. -->
                    {#if !settledBy && hasAnsweredDecision}
                      <Tooltip.Provider delayDuration={250}>
                        <Tooltip.Root>
                          <Tooltip.Trigger>
                            {#snippet child({ props })}
                              <button
                                {...props}
                                type="button"
                                class="text-secondary focus-visible:ring-accent-stronger/40 mt-0.5 flex items-center gap-1 rounded-full text-xs font-normal focus-visible:ring-2 focus-visible:outline-none"
                                aria-label={m.ai_builder_requirements_derived_explained()}
                              >
                                {m.ai_builder_requirements_derived()}
                                <IconInfo class="size-3.5 shrink-0" aria-hidden="true" />
                              </button>
                            {/snippet}
                          </Tooltip.Trigger>
                          <Tooltip.Content class="max-w-64 text-xs">
                            {m.ai_builder_requirements_derived_explained()}
                          </Tooltip.Content>
                        </Tooltip.Root>
                      </Tooltip.Provider>
                    {:else if settledBy && delegatedQuestionIds.has(settledBy)}
                      <span class="text-secondary mt-0.5 block text-xs font-normal">
                        {m.ai_builder_question_delegated_badge()}
                      </span>
                    {/if}
                  </dd>
                  {#if !readOnly && !confirmed}
                    <Button
                      variant="outline"
                      size="sm"
                      class="justify-self-start sm:justify-self-end"
                      aria-label={m.ai_builder_confirm_change_row_aria({ topic: decision.topic })}
                      {disabled}
                      onclick={() =>
                        settledBy ? reopenQuestion(settledBy) : openChange(decision.topic)}
                    >
                      {m.ai_builder_question_change()}
                    </Button>
                  {/if}
                </div>
              {/each}
              <!-- The contract keeps the input and the result in their own
                   fields, and a key decision is not guaranteed to repeat them.
                   Shown only when nothing above already said it, so the card
                   never states the same thing twice. -->
              {#each contractRows as row (row.label)}
                <div
                  class="border-dimmer grid items-baseline gap-x-4 gap-y-0.5 border-t py-2.5 sm:grid-cols-[12.5rem_1fr_auto]"
                >
                  <dt class="text-secondary text-[0.8125rem]">{row.label}</dt>
                  <dd class="text-primary text-[0.85rem] font-medium">{row.value}</dd>
                  {#if !readOnly && !confirmed}
                    <Button
                      variant="outline"
                      size="sm"
                      class="justify-self-start sm:justify-self-end"
                      aria-label={m.ai_builder_confirm_change_row_aria({ topic: row.label })}
                      {disabled}
                      onclick={() => openChange(row.label)}
                    >
                      {m.ai_builder_question_change()}
                    </Button>
                  {/if}
                </div>
              {/each}
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

        {#if runtimeFields.length > 0 && !savedFlowStepScope}
          <section class="mt-[1.125rem]">
            <div class="flex flex-wrap items-baseline gap-x-2.5 gap-y-1">
              <h3 class="text-primary text-[0.8125rem] font-bold">
                {m.ai_builder_requirements_runtime_fields()}
              </h3>
              <span class="text-secondary text-xs">{runtimeFieldsCount}</span>
              {#if runtimeFieldsQuestionId && !readOnly && !confirmed}
                <Button
                  variant="outline"
                  size="sm"
                  class="ml-auto"
                  {disabled}
                  onclick={() => reopenQuestion(runtimeFieldsQuestionId)}
                >
                  {m.ai_builder_requirements_runtime_fields_change()}
                </Button>
              {/if}
            </div>
            <p class="text-secondary mt-0.5 text-xs text-pretty">
              {m.ai_builder_requirements_runtime_fields_lead()}
            </p>
            <ul class="mt-2 flex list-none flex-wrap gap-1.5 p-0">
              {#each shownRuntimeFields as field, fieldIndex (fieldIndex)}
                <li
                  class="border-default inline-flex h-[1.625rem] items-center gap-1.5 rounded-full border px-2.5 text-[0.78125rem]"
                  class:bg-secondary={!field.required}
                  class:text-primary={!field.required}
                  class:bg-accent-dimmer={field.required}
                  class:text-accent-stronger={field.required}
                >
                  <span class="font-medium">{field.label}</span>
                  <span class="opacity-45" aria-hidden="true">·</span>
                  <span class="opacity-70">{fieldTypeLabel(field.type)}</span>
                  {#if field.required}
                    <span class="opacity-45" aria-hidden="true">·</span>
                    <span class="opacity-70">{m.ai_builder_requirements_field_required()}</span>
                  {/if}
                </li>
              {/each}
              {#if runtimeFields.length > shownRuntimeFields.length}
                <li>
                  <button
                    type="button"
                    class="text-accent-stronger inline-flex h-[1.625rem] items-center text-[0.78125rem] font-semibold"
                    onclick={() => (allRuntimeFieldsShown = true)}
                  >
                    {m.ai_builder_requirements_show_all_fields({
                      count: String(runtimeFields.length)
                    })}
                  </button>
                </li>
              {/if}
            </ul>
          </section>
        {/if}

        {#if namedContentFields.length > 0}
          <section class="mt-[1.125rem]">
            <h3 class="text-primary text-[0.8125rem] font-bold">
              {m.ai_builder_requirements_named_content({
                count: String(namedContentFields.length)
              })}
            </h3>
            <p class="text-secondary mt-0.5 text-xs text-pretty">
              {m.ai_builder_requirements_named_content_lead()}
            </p>
            <ul class="mt-2 flex list-none flex-wrap gap-1.5 p-0">
              {#each shownContentFields as field (field.id)}
                <li
                  class="border-default bg-secondary text-primary inline-flex h-[1.625rem] items-center rounded-full border px-2.5 text-[0.78125rem]"
                >
                  {field.label}
                </li>
              {/each}
              {#if namedContentFields.length > shownContentFields.length}
                <li>
                  <button
                    type="button"
                    class="text-accent-stronger inline-flex h-[1.625rem] items-center text-[0.78125rem] font-semibold"
                    onclick={() => (allContentFieldsShown = true)}
                  >
                    {m.ai_builder_requirements_show_all_fields({
                      count: String(namedContentFields.length)
                    })}
                  </button>
                </li>
              {/if}
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
              <Button variant="outline" onclick={() => openChange(null)} {disabled}>
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

    {#if pending && !readOnly && !confirmed}
      <div class="border-default bg-primary mt-3 rounded-xl border p-[1.125rem] max-sm:p-4">
        <p class="text-secondary text-[0.8125rem]" role="status" aria-live="polite">
          {m.ai_builder_confirm_change_pending()}
        </p>
        <div class="mt-3 flex flex-col gap-[0.4375rem]" aria-hidden="true">
          <Skeleton class="bg-tertiary h-[0.6875rem] w-[74%] rounded" />
          <Skeleton class="bg-tertiary h-[0.5625rem] w-[44%] rounded" />
        </div>
      </div>
    {:else if !readOnly && !confirmed}
      <div class="mt-3">
        <BuilderChangeRequest
          bind:this={changeRequestRef}
          bind:open={changeOpen}
          bind:text={changeDraft}
          onopen={() => openChange(null)}
          scopeLabel={changeTopic}
          onclearscope={() => (changeTopic = null)}
          {disabled}
          title={m.ai_builder_confirm_change_answers()}
          example={m.ai_builder_confirm_change_example()}
          placeholder={m.ai_builder_confirm_change_hint()}
          hint={m.ai_builder_confirm_change_request_hint()}
          onsend={(text) => {
            changeOpen = false;
            const topic = changeTopic;
            changeTopic = null;
            changeDraft = "";
            changeDrafts.delete(topic);
            onchange(text, topic);
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
