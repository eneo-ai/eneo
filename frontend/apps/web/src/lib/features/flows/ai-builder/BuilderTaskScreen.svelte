<script lang="ts">
  import { BUILDER_COLUMN, BUILDER_MEASURE } from "./builderColumns";
  import { m } from "$lib/paraglide/messages";
  import { Button } from "$lib/components/ui/button/index.js";
  import { getLocale } from "$lib/paraglide/runtime";
  import FlowAIBuilderInput from "./FlowAIBuilderInput.svelte";
  import { inSentence } from "./builderStepPhrases";
  import type { AIBuilderEditContext, AIBuilderStepChoice, AIBuilderStepIntent } from "./protocol";

  interface Props {
    targetKind: "create" | "edit";
    /** Other unfinished drafts in this space (the current session excluded). */
    otherDraftCount?: number;
    flowsHref: string;
    editContext?: AIBuilderEditContext | null;
    editContextLabel?: string | null;
    editContextLocked?: boolean;
    oncleareditcontext?: () => void;
    onopenreview?: () => void;
    stepChoices?: AIBuilderStepChoice[] | null;
    onselectstep?: (choice: AIBuilderStepChoice) => void;
    requireStepScope?: boolean;
    onpackage?: (detail: { file: File; text: string }) => void;
    /** The part of the step the editor's menu asked about, and what it is now. */
    stepIntent?: AIBuilderStepIntent | null;
    stepNow?: string | null;
    stepNumber?: number | null;
    /** The flow's steps, for the quick picks of what a step can read. */
    flowSteps?: AIBuilderStepChoice[] | null;
  }

  let {
    targetKind,
    onopenreview,
    otherDraftCount = 0,
    flowsHref,
    editContext = null,
    editContextLabel = null,
    editContextLocked = false,
    oncleareditcontext,
    stepChoices = null,
    onselectstep,
    requireStepScope = false,
    onpackage,
    stepIntent = null,
    stepNow = null,
    stepNumber = null,
    flowSteps = null
  }: Props = $props();

  const locale = $derived(getLocale());
  // The menu asked about one part of the step: the heading asks about that part
  // in the words of the review's strip (Läser, Gör, Svarar med).
  const INTENT_TITLE: Record<AIBuilderStepIntent, (inputs: { step: string }) => string> = {
    underlag: m.ai_builder_task_title_step_reads,
    instruction: m.ai_builder_task_title_step_does,
    format: m.ai_builder_task_title_step_answers
  };
  const intentTitle = $derived(
    stepIntent && stepNumber ? INTENT_TITLE[stepIntent]({ step: String(stepNumber) }) : null
  );
  // What a step can read, one click each: the flow input, the nearest earlier
  // steps and all of them. A long flow offers the four nearest; the reader
  // names an older step in their own words.
  const NEAREST_PICKS = 4;
  const earlierSteps = $derived(
    stepIntent === "underlag" && stepNumber
      ? (flowSteps ?? [])
          .filter((step) => step.order < stepNumber)
          .sort((a, b) => a.order - b.order)
      : []
  );
  const picks = $derived.by(() => {
    if (stepIntent !== "underlag" || !stepNumber) return [];
    const earlier = earlierSteps.slice(-NEAREST_PICKS);
    return [
      {
        key: "flow_input",
        label: m.ai_builder_reads_flow_input(),
        text: inSentence(m.ai_builder_reads_flow_input(), locale)
      },
      ...earlier.map((step) => ({
        key: step.id,
        label: m.ai_builder_step_choice_item({ step: step.order, name: step.name }),
        text: m.ai_builder_task_pick_step({ step: String(step.order), name: step.name })
      })),
      ...(stepNumber > 2
        ? [
            {
              key: "all_previous",
              label: m.ai_builder_step_all_previous(),
              text: inSentence(m.ai_builder_step_all_previous(), locale)
            }
          ]
        : [])
    ];
  });

  let inputRef = $state<FlowAIBuilderInput | undefined>();

  export function focusInput(options?: { placeholder?: string; prefill?: string }) {
    inputRef?.focus(options);
  }

  // Examples write a full description into the field, so a first-time user
  // sees what a good task sounds like instead of guessing.
  const examples: { label: () => string; text: () => string }[] = [
    { label: m.flow_create_example_summarize, text: m.ai_builder_example_summarize_text },
    { label: m.flow_create_example_review, text: m.ai_builder_example_review_text },
    { label: m.ai_builder_example_transcribe, text: m.ai_builder_example_transcribe_text },
    { label: m.flow_create_example_decision, text: m.ai_builder_example_decision_text }
  ];

  const isEdit = $derived(targetKind === "edit");
</script>

<!-- Anchored a little below the rail rather than centred: on a tall screen a
     centred prompt floats half a viewport down, and the composer is the
     first thing the reader should reach. -->
<div
  class="flex flex-1 justify-center px-7 pt-[clamp(2.5rem,14vh,7.5rem)] pb-8 max-sm:px-3 max-sm:pt-6 max-sm:pb-5"
>
  <div class="task-screen w-full {BUILDER_COLUMN.sheet}">
    <!-- One thing is asked here, so the writing stays at a comfortable
         measure while the sheet keeps every screen the same width. -->
    <div class="mx-auto w-full {BUILDER_MEASURE}">
      <h2
        class="text-primary text-[1.6875rem] leading-tight font-extrabold tracking-[-0.03em] text-pretty"
      >
        {#if !isEdit}
          {m.ai_builder_task_title()}
        {:else if intentTitle}
          {intentTitle}
        {:else if editContextLabel}
          {m.ai_builder_task_title_edit_step()}
        {:else}
          {m.ai_builder_task_title_edit()}
        {/if}
      </h2>
      {#if intentTitle && stepNow}
        <p class="text-primary mt-2 text-[0.9375rem] font-medium">
          {m.ai_builder_task_now({ what: inSentence(stepNow, locale) })}
        </p>
      {/if}
      <p class="text-secondary mt-2 max-w-[54ch] text-[0.9375rem] leading-relaxed text-pretty">
        {isEdit ? m.ai_builder_task_intro_edit() : m.ai_builder_task_intro()}
      </p>

      <div class="mt-5">
        <FlowAIBuilderInput
          bind:this={inputRef}
          {editContext}
          {editContextLabel}
          {editContextLocked}
          {oncleareditcontext}
          {stepChoices}
          {onselectstep}
          {requireStepScope}
          {onpackage}
          placeholder={!isEdit
            ? m.ai_builder_task_placeholder()
            : editContextLabel
              ? m.ai_builder_saved_step_prompt_placeholder()
              : m.ai_builder_task_placeholder_edit()}
        />
      </div>
      <p class="text-secondary mt-2 px-0.5 text-xs">{m.ai_builder_task_model_note()}</p>

      {#if picks.length > 0}
        <div class="mt-5">
          <h3 class="text-primary text-[0.8125rem] font-bold">{m.ai_builder_task_picks_label()}</h3>
          <div class="mt-2 flex flex-wrap gap-2">
            {#each picks as pick (pick.key)}
              <Button
                variant="outline"
                size="sm"
                class="h-auto min-h-8 max-w-full rounded-2xl py-1.5 text-left font-normal whitespace-normal max-sm:min-h-[44px]"
                onclick={() => inputRef?.append(pick.text)}
              >
                <span class="line-clamp-2">{pick.label}</span>
              </Button>
            {/each}
          </div>
          <p class="text-secondary mt-2 text-xs">
            {m.ai_builder_task_picks_hint()}
            {#if earlierSteps.length > NEAREST_PICKS}
              {m.ai_builder_task_picks_hint_older()}
            {/if}
          </p>
        </div>
      {/if}

      {#if isEdit && onopenreview}
        <div
          class="border-default mt-6 flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-t pt-4"
        >
          <span class="text-secondary max-w-[44ch] text-xs text-pretty">
            {m.ai_builder_review_entry_hint()}
          </span>
          <Button
            variant="outline"
            size="sm"
            class="rounded-full font-normal max-sm:h-[44px]"
            data-testid="open-review"
            onclick={() => onopenreview?.()}
          >
            {m.ai_builder_review_entry()}
          </Button>
        </div>
      {/if}

      {#if !isEdit}
        <div class="mt-4 flex flex-wrap items-center gap-2">
          <span class="text-secondary text-xs">{m.ai_builder_task_examples_label()}</span>
          {#each examples as example (example.label())}
            <Button
              variant="outline"
              size="sm"
              class="rounded-full font-normal max-sm:h-[44px]"
              onclick={() => inputRef?.focus({ prefill: example.text() })}
            >
              {example.label()}
            </Button>
          {/each}
        </div>

        <div
          class="border-default mt-6 flex flex-wrap items-center gap-x-4 gap-y-2 border-t pt-4 text-xs"
        >
          {#if otherDraftCount > 0}
            <span class="text-secondary">{m.ai_builder_task_drafts_question()}</span>
            <Button
              variant="link"
              class="text-accent-stronger h-auto p-0 text-xs font-semibold"
              href={flowsHref}
            >
              {otherDraftCount === 1
                ? m.ai_builder_task_drafts_link_one()
                : m.ai_builder_task_drafts_link({ count: String(otherDraftCount) })}
            </Button>
          {/if}
          <span class="text-secondary ml-auto max-sm:ml-0">
            {m.ai_builder_task_manual_question()}
            <Button
              variant="link"
              class="text-accent-stronger h-auto p-0 text-xs font-semibold"
              href={flowsHref}
            >
              {m.ai_builder_task_manual_link()}
            </Button>
          </span>
        </div>
      {/if}
    </div>
  </div>
</div>

<style lang="postcss">
  .task-screen {
    animation: builder-screen-in var(--duration-fast) var(--ease-smooth-out);
  }
  @media (prefers-reduced-motion: reduce) {
    .task-screen {
      animation: none;
    }
  }
</style>
