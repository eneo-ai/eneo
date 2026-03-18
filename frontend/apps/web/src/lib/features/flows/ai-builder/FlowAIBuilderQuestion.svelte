<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import { Button } from "@intric/ui";
  import { SvelteSet } from "svelte/reactivity";
  import {
    buildStructuredQuestionCustomAnswer,
    buildStructuredQuestionSelection,
    getStructuredQuestionOptionKey,
    type StructuredQuestion
  } from "./structuredQuestionAnswer";

  interface Props {
    question: StructuredQuestion;
    answered?: boolean;
    onanswer?: (payload: { text: string; questionAnswer: Record<string, unknown> }) => void;
  }

  let { question, answered = false, onanswer }: Props = $props();

  const selectedOptionKeys = new SvelteSet<string>();
  let showCustomInput = $state(false);
  let customText = $state("");

  function handleOptionClick(option: StructuredQuestion["options"][number]) {
    if (answered) return;

    if (question.selection_mode === "single") {
      // Single select: immediately send
      onanswer?.(buildStructuredQuestionSelection(question, [option]));
    } else {
      const optionKey = getStructuredQuestionOptionKey(option);
      if (selectedOptionKeys.has(optionKey)) {
        selectedOptionKeys.delete(optionKey);
      } else {
        selectedOptionKeys.add(optionKey);
      }
    }
  }

  function handleConfirmMulti() {
    if (selectedOptionKeys.size === 0) return;
    const selectedOptions = question.options.filter((option) =>
      selectedOptionKeys.has(getStructuredQuestionOptionKey(option))
    );
    onanswer?.(buildStructuredQuestionSelection(question, selectedOptions));
  }

  function handleCustomSubmit() {
    const trimmed = customText.trim();
    if (!trimmed) return;
    onanswer?.(buildStructuredQuestionCustomAnswer(question, trimmed));
  }
</script>

<div class="question-container" class:answered>
  <p class="question-text">{question.question}</p>

  <div class="options-grid" role={question.selection_mode === "single" ? "radiogroup" : "group"} aria-label={question.question}>
    {#each question.options as option, i (getStructuredQuestionOptionKey(option))}
      {@const optionKey = getStructuredQuestionOptionKey(option)}
      {@const isSelected = selectedOptionKeys.has(optionKey)}
      <button
        class="option-card"
        class:selected={isSelected}
        class:answered
        disabled={answered}
        onclick={() => handleOptionClick(option)}
        role={question.selection_mode === "single" ? "radio" : "checkbox"}
        aria-checked={isSelected}
        aria-label={option.label}
      >
        <span class="select-indicator" class:checked={isSelected} class:is-radio={question.selection_mode === "single"}>
          {#if isSelected}
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="size-3">
              <path fill-rule="evenodd" d="M16.704 4.153a.75.75 0 0 1 .143 1.052l-8 10.5a.75.75 0 0 1-1.127.075l-4.5-4.5a.75.75 0 0 1 1.06-1.06l3.894 3.893 7.48-9.817a.75.75 0 0 1 1.05-.143Z" clip-rule="evenodd" />
            </svg>
          {/if}
        </span>
        <span class="option-content">
          <span class="option-label">{option.label}</span>
          {#if option.description}
            <span class="option-desc">{option.description}</span>
          {/if}
        </span>
      </button>
    {/each}
  </div>

  {#if question.selection_mode === "multi" && selectedOptionKeys.size > 0 && !answered}
    <div class="mt-2">
      <Button variant="primary" size="small" onclick={handleConfirmMulti}>
        {m.ai_builder_question_confirm()}
      </Button>
    </div>
  {/if}

  {#if question.allow_custom && !answered}
    {#if showCustomInput}
      <div class="custom-input-row">
        <input
          type="text"
          class="custom-input"
          placeholder={m.ai_builder_question_custom_placeholder()}
          bind:value={customText}
          onkeydown={(e) => {
            if (e.key === "Enter") handleCustomSubmit();
          }}
        />
        <Button
          variant="outlined"
          size="small"
          onclick={handleCustomSubmit}
          disabled={!customText.trim()}
        >
          {m.ai_builder_question_confirm()}
        </Button>
      </div>
    {:else}
      <button class="custom-card" onclick={() => (showCustomInput = true)}>
        {m.ai_builder_question_custom()}
      </button>
    {/if}
  {/if}
</div>

<style lang="postcss">
  @reference "@intric/ui/styles";

  .question-text {
    font-size: 0.875rem;
    font-weight: 600;
    color: var(--text-primary);
    margin-bottom: 0.5rem;
    line-height: 1.4;
  }

  .question-container {
    margin-top: 0.625rem;
    max-width: 36rem;
  }

  .question-container.answered {
    opacity: 0.55;
    pointer-events: none;
  }

  .options-grid {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }

  .option-card {
    display: flex;
    align-items: flex-start;
    gap: 0.625rem;
    padding: 0.875rem 1rem;
    border-radius: 0.625rem;
    border: 1px solid var(--border-default);
    background: var(--bg-primary);
    cursor: pointer;
    transition: border-color 0.15s ease, background 0.15s ease, box-shadow 0.15s ease;
    text-align: left;
    min-height: 2.75rem;
  }

  .option-card:not(.answered):hover {
    border-color: var(--border-accent-default);
    background: oklch(from var(--accent-default) l c h / 0.03);
    box-shadow: 0 1px 4px oklch(0 0 0 / 0.04);
  }

  .option-card:not(.answered):active {
    transform: scale(0.995);
  }

  .option-card:focus-visible {
    outline: 2px solid var(--accent-default);
    outline-offset: 2px;
  }

  .option-card.selected {
    border-color: var(--border-accent-default);
    background: oklch(from var(--accent-default) l c h / 0.05);
  }

  .option-card.answered {
    cursor: default;
  }

  /* --- Selection indicator (radio circle / checkbox) --- */

  .select-indicator {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 1.125rem;
    height: 1.125rem;
    margin-top: 0.0625rem;
    border-radius: 0.25rem;
    border: 1.5px solid var(--border-stronger);
    flex-shrink: 0;
    transition: border-color 0.15s ease, background 0.15s ease;
  }

  .select-indicator.is-radio {
    border-radius: 9999px;
  }

  .option-card:not(.answered):hover .select-indicator {
    border-color: var(--accent-default);
  }

  .select-indicator.checked {
    border-color: var(--accent-default);
    background: var(--accent-default);
    color: var(--text-on-fill);
  }

  .option-content {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }

  .option-label {
    font-size: 0.8125rem;
    font-weight: 550;
    color: var(--text-primary);
    line-height: 1.3;
  }

  .option-desc {
    font-size: 0.75rem;
    color: var(--text-secondary);
    line-height: 1.4;
    margin-top: 0.125rem;
  }

  .custom-card {
    display: flex;
    align-items: center;
    width: 100%;
    padding: 0.75rem 1rem;
    border-radius: 0.625rem;
    border: 1px dashed var(--border-default);
    background: transparent;
    cursor: pointer;
    font-size: 0.8125rem;
    font-weight: 500;
    color: var(--text-secondary);
    transition: border-color 0.15s ease, color 0.15s ease, background 0.15s ease;
    text-align: left;
  }

  .custom-card:hover {
    border-color: var(--border-accent-default);
    color: var(--accent-default);
    background: oklch(from var(--accent-default) l c h / 0.02);
  }

  .custom-card:focus-visible {
    outline: 2px solid var(--accent-default);
    outline-offset: 2px;
  }

  .custom-input-row {
    display: flex;
    gap: 0.375rem;
    margin-top: 0.375rem;
    align-items: center;
  }

  .custom-input {
    flex: 1;
    padding: 0.375rem 0.625rem;
    font-size: 0.8125rem;
    border: 1px solid var(--border-default);
    border-radius: 0.375rem;
    background: var(--bg-primary);
    color: var(--text-primary);
    outline: none;
  }

  .custom-input:focus {
    border-color: var(--border-accent-default);
    box-shadow: 0 0 0 2px oklch(from var(--accent-default) l c h / 0.08);
  }

  /* --- Entrance animations --- */

  .question-container {
    animation: questionReveal 300ms ease-out;
  }

  .option-card {
    animation: optionSlideIn 200ms ease-out both;
  }

  .option-card:nth-child(1) { animation-delay: 80ms; }
  .option-card:nth-child(2) { animation-delay: 140ms; }
  .option-card:nth-child(3) { animation-delay: 200ms; }
  .option-card:nth-child(4) { animation-delay: 260ms; }

  @keyframes questionReveal {
    from { opacity: 0; transform: translateY(8px); }
    to { opacity: 1; transform: translateY(0); }
  }

  @keyframes optionSlideIn {
    from { opacity: 0; transform: translateY(4px); }
    to { opacity: 1; transform: translateY(0); }
  }

  @media (prefers-reduced-motion: reduce) {
    .question-container,
    .option-card {
      animation: none;
    }

    .option-card:not(.answered):active {
      transform: none;
    }
  }
</style>
