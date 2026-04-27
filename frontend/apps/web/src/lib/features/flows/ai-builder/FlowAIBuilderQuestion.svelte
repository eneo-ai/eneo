<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import { slide } from "svelte/transition";
  import { cubicOut } from "svelte/easing";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Textarea } from "$lib/components/ui/textarea/index.js";
  import { SvelteSet } from "svelte/reactivity";
  import CheckIcon from "@lucide/svelte/icons/check";
  import PencilIcon from "@lucide/svelte/icons/pencil-line";
  import {
    buildStructuredQuestionCustomAnswer,
    buildStructuredQuestionSelection,
    getStructuredQuestionOptionKey,
    type StructuredQuestion,
    type StructuredQuestionAnswerPayload,
    type StructuredQuestionOption
  } from "./structuredQuestionAnswer";

  interface Props {
    question: StructuredQuestion;
    answered?: boolean;
    onanswer?: (payload: StructuredQuestionAnswerPayload) => void;
  }

  let { question, answered = false, onanswer }: Props = $props();

  // Generated once per instance so radiogroup + its label can link without colliding.
  const questionLabelId = `ai-builder-q-${Math.random().toString(36).slice(2, 10)}`;

  const selectedOptionKeys = new SvelteSet<string>();
  let customSelected = $state(false);
  let customText = $state("");
  let textareaRef = $state<HTMLTextAreaElement | null>(null);

  const isSingle = $derived(question.selection_mode === "single");
  const requiresConfirm = $derived(question.requires_confirm === true);

  const canConfirm = $derived.by(() => {
    if (answered) return false;
    if (customSelected) return customText.trim().length > 0;
    if (!isSingle || requiresConfirm) return selectedOptionKeys.size > 0;
    return false;
  });

  function selectOption(option: StructuredQuestionOption) {
    if (answered) return;

    // Leaving the custom-answer lane clears any partial text so stale input
    // never submits with a different selection.
    if (customSelected) {
      customSelected = false;
      customText = "";
    }

    const optionKey = getStructuredQuestionOptionKey(option);

    if (isSingle && !requiresConfirm) {
      onanswer?.(buildStructuredQuestionSelection(question, [option]));
      return;
    }

    if (isSingle) {
      selectedOptionKeys.clear();
      selectedOptionKeys.add(optionKey);
      return;
    }

    if (selectedOptionKeys.has(optionKey)) {
      selectedOptionKeys.delete(optionKey);
    } else {
      selectedOptionKeys.add(optionKey);
    }
  }

  function selectCustom() {
    if (answered) return;
    customSelected = true;
    // Custom answers intentionally replace preset selections instead of mixing
    // both answer types in one payload.
    selectedOptionKeys.clear();
    queueMicrotask(() => textareaRef?.focus());
  }

  function handleConfirm() {
    if (!canConfirm) return;
    if (customSelected) {
      const trimmed = customText.trim();
      if (!trimmed) return;
      onanswer?.(buildStructuredQuestionCustomAnswer(question, trimmed));
      return;
    }
    const selectedOptions = question.options.filter((option) =>
      selectedOptionKeys.has(getStructuredQuestionOptionKey(option))
    );
    if (selectedOptions.length === 0) return;
    onanswer?.(buildStructuredQuestionSelection(question, selectedOptions));
  }

  function handleTextareaKeydown(event: KeyboardEvent) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      handleConfirm();
    }
  }
</script>

<div class="question-panel" class:answered>
  {#if answered}
    <div class="answered-prompt">
      <span class="answered-check" aria-hidden="true">
        <CheckIcon class="size-3" />
      </span>
      <span>{question.question}</span>
    </div>
  {:else}
    <p id={questionLabelId} class="question-title">
      <span class="question-dot" aria-hidden="true"></span>
      {question.question}
    </p>

    <div
      class="options-stack"
      role={isSingle ? "radiogroup" : "group"}
      aria-labelledby={questionLabelId}
    >
      {#each question.options as option, i (getStructuredQuestionOptionKey(option))}
        {@const optionKey = getStructuredQuestionOptionKey(option)}
        {@const isSelected = selectedOptionKeys.has(optionKey)}
        <button
          type="button"
          class="option-row"
          class:is-selected={isSelected}
          style="--i: {i}"
          onclick={() => selectOption(option)}
          role={isSingle ? "radio" : "checkbox"}
          aria-checked={isSelected}
        >
          <span
            class="option-indicator"
            class:is-selected={isSelected}
            class:is-radio={isSingle}
            aria-hidden="true"
          >
            {#if isSelected}
              {#if isSingle}
                <span class="option-indicator-dot"></span>
              {:else}
                <CheckIcon class="size-3" />
              {/if}
            {/if}
          </span>
          <span class="option-body">
            <span class="option-label">{option.label}</span>
            {#if option.description}
              <span class="option-description">{option.description}</span>
            {/if}
          </span>
        </button>
      {/each}

      {#if question.allow_custom}
        <button
          type="button"
          class="option-row option-row-custom"
          class:is-selected={customSelected}
          style="--i: {question.options.length}"
          onclick={selectCustom}
          role={isSingle ? "radio" : "checkbox"}
          aria-checked={customSelected}
          aria-controls="{questionLabelId}-custom"
        >
          <span
            class="option-indicator"
            class:is-selected={customSelected}
            class:is-radio={isSingle}
            aria-hidden="true"
          >
            {#if customSelected}
              {#if isSingle}
                <span class="option-indicator-dot"></span>
              {:else}
                <CheckIcon class="size-3" />
              {/if}
            {:else}
              <PencilIcon class="text-secondary size-3" />
            {/if}
          </span>
          <span class="option-body">
            <span class="option-label">{m.ai_builder_question_custom()}</span>
            <span class="option-description">{m.ai_builder_question_custom_helper()}</span>
          </span>
        </button>

        {#if customSelected}
          <div
            class="custom-input-wrap"
            id="{questionLabelId}-custom"
            transition:slide={{ duration: 180, easing: cubicOut }}
          >
            <Textarea
              bind:ref={textareaRef}
              bind:value={customText}
              rows={2}
              placeholder={m.ai_builder_question_custom_placeholder()}
              onkeydown={handleTextareaKeydown}
              class="resize-none"
              aria-label={m.ai_builder_question_custom()}
            />
          </div>
        {/if}
      {/if}
    </div>

    {#if !isSingle || customSelected || requiresConfirm}
      <div class="actions-row">
        <Button variant="default" size="sm" onclick={handleConfirm} disabled={!canConfirm}>
          {m.ai_builder_question_confirm()}
        </Button>
      </div>
    {/if}
  {/if}
</div>

<style lang="postcss">
  @reference "@intric/ui/styles";

  .question-panel {
    @apply mt-3 flex flex-col rounded-xl border;
    border-color: var(--border-default);
    background: var(--bg-card, var(--bg-primary));
    padding: 0.875rem 0.875rem 0.75rem;
    transition:
      opacity 0.2s ease,
      filter 0.2s ease;
  }

  .question-panel.answered {
    border-color: oklch(from var(--border-default) l c h / 0.55);
    background: oklch(from var(--bg-secondary) l c h / 0.28);
  }

  .question-title {
    @apply mb-3 flex items-start gap-2 text-sm leading-snug font-medium;
    color: var(--text-primary);
  }

  .question-dot {
    @apply mt-[0.5em] size-1.5 shrink-0 rounded-full;
    background: var(--accent-default);
    opacity: 0.7;
  }

  .options-stack {
    @apply flex flex-col gap-1.5;
  }

  .answered-prompt {
    @apply flex min-w-0 items-start gap-2 text-[0.8125rem] leading-relaxed;
    color: var(--text-secondary);
  }

  .answered-check {
    @apply mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full;
    background: oklch(from var(--accent-default) l c h / 0.11);
    color: var(--accent-stronger);
  }

  .option-row {
    @apply relative flex w-full items-start gap-3 rounded-lg border px-3 py-2.5 text-left;
    border-color: var(--border-default);
    background: var(--bg-primary);
    color: var(--text-primary);
    cursor: pointer;
    transition:
      border-color 0.15s ease,
      background 0.15s ease,
      box-shadow 0.15s ease;
  }

  .option-row:not(:disabled):hover {
    border-color: var(--border-stronger);
    background: oklch(from var(--bg-secondary) l c h / 0.55);
  }

  .option-row:focus-visible {
    outline: none;
    border-color: var(--accent-default);
    box-shadow: 0 0 0 3px oklch(from var(--accent-default) l c h / 0.18);
  }

  .option-row:disabled {
    cursor: default;
  }

  .option-row.is-selected {
    border-color: oklch(from var(--accent-default) l c h / 0.45);
    background: oklch(from var(--accent-default) l c h / 0.06);
  }

  .option-row.is-selected:hover {
    background: oklch(from var(--accent-default) l c h / 0.08);
  }

  .option-row-custom {
    border-style: dashed;
  }

  .option-row-custom.is-selected {
    border-style: solid;
  }

  .option-indicator {
    @apply relative mt-[0.1875rem] flex size-[1.125rem] shrink-0 items-center justify-center rounded-md;
    border: 1.5px solid var(--border-stronger);
    background: var(--bg-primary);
    color: var(--text-primary);
    transition:
      border-color 0.15s ease,
      background 0.15s ease,
      color 0.15s ease;
  }

  .option-indicator.is-radio {
    border-radius: 9999px;
  }

  .option-row:not(:disabled):hover .option-indicator {
    border-color: var(--accent-default);
  }

  .option-indicator.is-selected {
    border-color: var(--accent-default);
    background: var(--accent-default);
    color: var(--text-on-fill);
  }

  .option-indicator-dot {
    @apply size-1.5 rounded-full;
    background: var(--text-on-fill);
  }

  .option-body {
    @apply flex min-w-0 flex-col gap-0.5;
  }

  .option-label {
    @apply text-[0.8125rem] leading-snug font-medium;
    color: var(--text-primary);
  }

  .option-description {
    @apply text-xs leading-relaxed;
    color: var(--text-secondary);
  }

  .custom-input-wrap {
    @apply mt-1 rounded-lg;
    padding: 0.25rem 0.25rem 0;
  }

  .custom-input-wrap :global([data-slot="textarea"]) {
    @apply text-[0.8125rem];
    min-height: 4rem;
  }

  .actions-row {
    @apply mt-3 flex items-center justify-end gap-2;
  }

  .question-panel {
    animation: questionReveal 260ms cubic-bezier(0.16, 1, 0.3, 1);
  }

  .option-row {
    animation: optionSlideIn 220ms cubic-bezier(0.16, 1, 0.3, 1) both;
    animation-delay: calc(70ms + var(--i, 0) * 55ms);
  }

  @keyframes questionReveal {
    from {
      opacity: 0;
      transform: translateY(4px);
    }
    to {
      opacity: 1;
      transform: translateY(0);
    }
  }

  @keyframes optionSlideIn {
    from {
      opacity: 0;
      transform: translateY(3px);
    }
    to {
      opacity: 1;
      transform: translateY(0);
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .question-panel,
    .option-row {
      animation: none;
    }
  }
</style>
