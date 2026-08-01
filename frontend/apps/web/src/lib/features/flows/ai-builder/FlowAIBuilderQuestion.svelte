<script lang="ts">
  /* eslint-disable eneo/no-raw-color -- the style block derives every colour
     from theme tokens via relative oklch() syntax, which the rule cannot see
     through */
  import { m } from "$lib/paraglide/messages";
  import { slide } from "svelte/transition";
  import { cubicOut } from "svelte/easing";
  import { prefersReducedMotion } from "$lib/core/prefersReducedMotion";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Textarea } from "$lib/components/ui/textarea/index.js";
  import { SvelteSet } from "svelte/reactivity";
  import CheckIcon from "@lucide/svelte/icons/check";
  import PencilIcon from "@lucide/svelte/icons/pencil-line";
  import {
    buildStructuredQuestionCustomAnswer,
    buildStructuredQuestionInputFieldsAnswer,
    buildStructuredQuestionSelection,
    getStructuredQuestionOptionKey,
    toggleStructuredQuestionOption,
    type StructuredQuestion,
    type StructuredQuestionAnswerPayload,
    type StructuredInputFieldType,
    type StructuredQuestionOption
  } from "./structuredQuestionAnswer";

  interface Props {
    question: StructuredQuestion;
    answered?: boolean;
    /** The user's chosen answer, shown in the collapsed answered state. */
    answerLabel?: string | null;
    /** Interaction lock projected from the service (e.g. while a flow is
     *  being created) — controls must LOOK disabled, not silently no-op. */
    disabled?: boolean;
    onanswer?: (payload: StructuredQuestionAnswerPayload) => void;
  }

  let {
    question,
    answered = false,
    answerLabel = null,
    disabled = false,
    onanswer
  }: Props = $props();

  // Generated once per instance so radiogroup + its label can link without colliding.
  const questionLabelId = `ai-builder-q-${Math.random().toString(36).slice(2, 10)}`;

  const reducedMotion = prefersReducedMotion();
  const schemaDirectionVisibleOptionLimit = 24;

  const selectedOptionKeys = new SvelteSet<string>();
  let optionFilter = $state("");
  let customSelected = $state(false);
  let customText = $state("");
  let textareaRef = $state<HTMLTextAreaElement | null>(null);
  let inputFields = $state([
    {
      variableName: "",
      label: "",
      fieldType: "text" as StructuredInputFieldType,
      required: false,
      optionsText: ""
    }
  ]);

  const isSingle = $derived(question.selection_mode === "single");
  const isSchemaDirection = $derived(question.question_id === "schema_direction");
  const requiresConfirm = $derived(question.requires_confirm === true);
  const isInputFieldCollection = $derived(question.input_field_collection === true);
  const matchingOptions = $derived.by(() => {
    if (!isSchemaDirection) return question.options;
    const query = optionFilter.trim().toLocaleLowerCase();
    if (!query) return question.options;
    return question.options.filter((option) =>
      [option.label, option.description, option.id, option.value]
        .filter((value): value is string => typeof value === "string")
        .some((value) => value.toLocaleLowerCase().includes(query))
    );
  });
  const visibleOptions = $derived.by(() => {
    if (!isSchemaDirection) return matchingOptions;

    const matchingKeys = new SvelteSet(matchingOptions.map(getStructuredQuestionOptionKey));
    const visibleKeys = new SvelteSet<string>();
    for (const option of question.options) {
      const optionKey = getStructuredQuestionOptionKey(option);
      if (selectedOptionKeys.has(optionKey) || optionKey === "reference_only") {
        visibleKeys.add(optionKey);
      }
    }
    for (const option of question.options) {
      if (visibleKeys.size >= schemaDirectionVisibleOptionLimit) break;
      const optionKey = getStructuredQuestionOptionKey(option);
      if (matchingKeys.has(optionKey)) visibleKeys.add(optionKey);
    }
    return question.options.filter((option) =>
      visibleKeys.has(getStructuredQuestionOptionKey(option))
    );
  });
  const visibleMatchingOptionCount = $derived(
    visibleOptions.filter((option) => matchingOptions.includes(option)).length
  );

  const canConfirm = $derived.by(() => {
    if (answered) return false;
    if (isInputFieldCollection) {
      return inputFields.every(
        (field) =>
          field.variableName.trim().length > 0 &&
          field.label.trim().length > 0 &&
          (!["select", "multiselect"].includes(field.fieldType) ||
            field.optionsText.trim().length > 0)
      );
    }
    if (customSelected) return customText.trim().length > 0;
    if (!isSingle || requiresConfirm) return selectedOptionKeys.size > 0;
    return false;
  });

  function selectOption(option: StructuredQuestionOption) {
    if (answered || disabled) return;

    // Leaving the custom-answer lane clears any partial text so stale input
    // never submits with a different selection.
    if (customSelected) {
      customSelected = false;
      customText = "";
    }

    const optionKey = getStructuredQuestionOptionKey(option);

    if (isSingle && !requiresConfirm) {
      // Fill the radio before dispatching so the choice is visibly
      // registered even for the frames before the card collapses.
      selectedOptionKeys.clear();
      selectedOptionKeys.add(optionKey);
      onanswer?.(buildStructuredQuestionSelection(question, [option]));
      return;
    }

    if (isSingle) {
      selectedOptionKeys.clear();
      selectedOptionKeys.add(optionKey);
      return;
    }

    const nextSelection = toggleStructuredQuestionOption(question, selectedOptionKeys, option);
    selectedOptionKeys.clear();
    for (const selectedKey of nextSelection) selectedOptionKeys.add(selectedKey);
  }

  function selectCustom() {
    if (answered || disabled) return;
    customSelected = true;
    // Custom answers intentionally replace preset selections instead of mixing
    // both answer types in one payload.
    selectedOptionKeys.clear();
    queueMicrotask(() => textareaRef?.focus());
  }

  function handleConfirm() {
    if (!canConfirm || disabled) return;
    if (isInputFieldCollection) {
      onanswer?.(
        buildStructuredQuestionInputFieldsAnswer(
          question,
          inputFields.map((field) => ({
            name: field.variableName,
            label: field.label,
            type: field.fieldType,
            required: field.required,
            options: field.optionsText.split(",")
          }))
        )
      );
      return;
    }
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

  function addInputField() {
    if (inputFields.length >= 20) return;
    inputFields.push({
      variableName: "",
      label: "",
      fieldType: "text",
      required: false,
      optionsText: ""
    });
  }

  function removeInputField(index: number) {
    if (inputFields.length > 1) inputFields.splice(index, 1);
  }
</script>

<div class="question-panel" class:answered>
  {#if answered}
    <div class="answered-prompt">
      <span class="answered-check" aria-hidden="true">
        <CheckIcon class="size-3" />
      </span>
      <span class="min-w-0">
        {question.question}
        {#if answerLabel}
          <span class="text-primary font-medium">— {answerLabel}</span>
        {/if}
      </span>
    </div>
  {:else}
    <p id={questionLabelId} class="question-title">
      {question.question}
    </p>

    {#if isInputFieldCollection}
      <div class="field-collection" aria-labelledby={questionLabelId}>
        {#each inputFields as field, index (field)}
          <div class="field-row">
            <label>
              <span>{m.ai_builder_question_field_label()}</span>
              <input bind:value={field.label} {disabled} />
            </label>
            <label>
              <span>{m.ai_builder_question_field_name()}</span>
              <input bind:value={field.variableName} {disabled} />
            </label>
            <label>
              <span>{m.ai_builder_question_field_type()}</span>
              <select bind:value={field.fieldType} {disabled}>
                <option value="text">{m.flow_form_field_type_text()}</option>
                <option value="number">{m.flow_form_field_type_number()}</option>
                <option value="date">{m.flow_form_field_type_date()}</option>
                <option value="select">{m.flow_form_field_type_select()}</option>
                <option value="multiselect">{m.flow_form_field_type_multiselect()}</option>
              </select>
            </label>
            {#if field.fieldType === "select" || field.fieldType === "multiselect"}
              <label class="field-options">
                <span>{m.ai_builder_question_field_options()}</span>
                <input bind:value={field.optionsText} {disabled} />
              </label>
            {/if}
            <label class="field-required">
              <input type="checkbox" bind:checked={field.required} {disabled} />
              <span>{m.ai_builder_question_field_required()}</span>
            </label>
            {#if inputFields.length > 1}
              <button
                type="button"
                class="field-remove"
                onclick={() => removeInputField(index)}
                {disabled}
              >
                {m.ai_builder_question_field_remove()}
              </button>
            {/if}
          </div>
        {/each}
        <button
          type="button"
          class="field-add"
          onclick={addInputField}
          disabled={disabled || inputFields.length >= 20}
        >
          {m.ai_builder_question_field_add()}
        </button>
      </div>
    {:else}
      {#if isSchemaDirection && question.options.length > schemaDirectionVisibleOptionLimit}
        <label class="option-filter">
          <span>{m.ai_builder_question_schema_filter()}</span>
          <input
            type="search"
            bind:value={optionFilter}
            placeholder={m.ai_builder_question_schema_filter_placeholder()}
            {disabled}
          />
        </label>
        <p class="option-filter-summary" aria-live="polite">
          {m.ai_builder_question_schema_filter_summary({
            shown: visibleMatchingOptionCount,
            total: matchingOptions.length
          })}
        </p>
      {/if}
      <div
        class="options-stack"
        role={isSingle ? "radiogroup" : "group"}
        aria-labelledby={questionLabelId}
      >
        {#each visibleOptions as option (getStructuredQuestionOptionKey(option))}
          {@const optionKey = getStructuredQuestionOptionKey(option)}
          {@const isSelected = selectedOptionKeys.has(optionKey)}
          <button
            type="button"
            class="option-row"
            class:is-selected={isSelected}
            onclick={() => selectOption(option)}
            role={isSingle ? "radio" : "checkbox"}
            aria-checked={isSelected}
            {disabled}
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
            onclick={selectCustom}
            role={isSingle ? "radio" : "checkbox"}
            aria-checked={customSelected}
            aria-controls="{questionLabelId}-custom"
            {disabled}
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
              transition:slide={{ duration: reducedMotion ? 0 : 180, easing: cubicOut }}
            >
              <Textarea
                bind:ref={textareaRef}
                bind:value={customText}
                rows={2}
                placeholder={m.ai_builder_question_custom_placeholder()}
                onkeydown={handleTextareaKeydown}
                class="resize-none"
                aria-label={m.ai_builder_question_custom()}
                {disabled}
              />
            </div>
          {/if}
        {/if}
      </div>
    {/if}

    {#if isInputFieldCollection || !isSingle || customSelected || requiresConfirm}
      <div class="actions-row">
        <Button
          variant="default"
          size="sm"
          onclick={handleConfirm}
          disabled={!canConfirm || disabled}
        >
          {m.ai_builder_question_confirm()}
        </Button>
      </div>
    {/if}
  {/if}
</div>

<style lang="postcss">
  @reference "@eneo/ui/styles";

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

  /* One surface with hairline dividers; never one border per option. */
  .options-stack {
    @apply flex flex-col;
  }

  .option-filter {
    @apply mb-1 flex flex-col gap-1 text-xs font-medium;
    color: var(--text-secondary);
  }

  .option-filter input {
    @apply h-9 rounded-md border px-3 text-sm font-normal;
    border-color: var(--border-default);
    background: var(--bg-primary);
    color: var(--text-primary);
  }

  .option-filter-summary {
    @apply mb-2 text-xs;
    color: var(--text-secondary);
  }

  .options-stack > .option-row + .option-row {
    border-top: 1px solid var(--border-dimmer);
  }

  .answered-prompt {
    @apply flex min-w-0 items-start gap-2 text-[0.8125rem] leading-relaxed;
    color: var(--text-secondary);
    animation: questionReveal 150ms ease-out;
  }

  .answered-check {
    @apply mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full;
    background: oklch(from var(--accent-default) l c h / 0.11);
    color: var(--accent-stronger);
  }

  .option-row {
    @apply relative flex min-h-11 w-full items-start gap-3 rounded-md px-2 py-3 text-left;
    color: var(--text-primary);
    cursor: pointer;
    transition: background 0.15s ease;
  }

  .option-row:not(:disabled):hover {
    background: oklch(from var(--bg-secondary) l c h / 0.55);
  }

  .option-row:focus-visible {
    outline: 2px solid var(--accent-default);
    outline-offset: -2px;
  }

  .option-row:disabled {
    cursor: default;
  }

  .option-row.is-selected {
    background: oklch(from var(--accent-default) l c h / 0.06);
  }

  .option-row.is-selected:hover {
    background: oklch(from var(--accent-default) l c h / 0.08);
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

  .field-collection {
    @apply flex flex-col gap-3;
  }

  .field-row {
    @apply grid grid-cols-2 gap-3 rounded-lg p-3;
    background: var(--bg-secondary);
  }

  .field-row label:not(.field-required) {
    @apply flex flex-col gap-1 text-xs font-medium;
    color: var(--text-secondary);
  }

  .field-row input:not([type="checkbox"]),
  .field-row select {
    @apply h-9 rounded-md border px-2 text-sm;
    border-color: var(--border-default);
    background: var(--bg-primary);
    color: var(--text-primary);
  }

  .field-options {
    @apply col-span-2;
  }

  .field-required {
    @apply flex items-center gap-2 text-xs;
    color: var(--text-primary);
  }

  .field-add,
  .field-remove {
    @apply w-fit text-xs font-medium underline-offset-2 hover:underline disabled:opacity-50;
    color: var(--accent-stronger);
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

  /* One quiet fade, no slides, no staggered entrances. */
  .question-panel {
    animation: questionReveal 200ms ease-out;
  }

  @keyframes questionReveal {
    from {
      opacity: 0;
    }
    to {
      opacity: 1;
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .question-panel,
    .answered-prompt {
      animation: none;
    }
  }
</style>
