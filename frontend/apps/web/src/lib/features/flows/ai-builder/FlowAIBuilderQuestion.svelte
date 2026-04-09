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

<div class="question-container mt-2.5 max-w-xl" class:answered>
  <p class="text-primary mb-2 text-sm font-semibold leading-snug">{question.question}</p>

  <div class="flex flex-col gap-2" role={question.selection_mode === "single" ? "radiogroup" : "group"} aria-label={question.question}>
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
        <span class="flex min-w-0 flex-col">
          <span class="text-primary text-[0.8125rem] font-semibold leading-snug">{option.label}</span>
          {#if option.description}
            <span class="text-secondary mt-0.5 text-xs leading-snug">{option.description}</span>
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
      <div class="mt-1.5 flex items-center gap-1.5">
        <input
          type="text"
          class="bg-primary text-primary border-border-default focus:border-accent-default flex-1 rounded-md border px-2.5 py-1.5 text-[0.8125rem] outline-none transition-shadow focus:ring-2 focus:ring-[oklch(from_var(--accent-default)_l_c_h_/_0.08)]"
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
      <button
        class="border-border-stronger text-secondary hover:border-accent-default hover:text-accent-default mt-2 flex w-full items-center rounded-[0.625rem] border border-dashed px-4 py-3 text-left text-[0.8125rem] font-medium transition-all duration-150 hover:bg-[oklch(from_var(--accent-default)_l_c_h_/_0.02)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent-default)]"
        onclick={() => (showCustomInput = true)}
      >
        {m.ai_builder_question_custom()}
      </button>
    {/if}
  {/if}
</div>

<style lang="postcss">
  @reference "@intric/ui/styles";

  /* --- Answered state --- */

  .answered {
    opacity: 0.55;
    pointer-events: none;
  }

  /* --- Option card --- */

  .option-card {
    @apply flex items-start gap-2.5 rounded-[0.625rem] border px-4 py-3.5 text-left;
    border-color: var(--border-stronger);
    background: var(--bg-primary);
    cursor: pointer;
    min-height: 2.75rem;
    transition: border-color 0.15s ease, background 0.15s ease, box-shadow 0.15s ease;
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
    @apply flex shrink-0 items-center justify-center rounded;
    width: 1.125rem;
    height: 1.125rem;
    margin-top: 0.0625rem;
    border: 1.5px solid var(--border-strongest);
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
