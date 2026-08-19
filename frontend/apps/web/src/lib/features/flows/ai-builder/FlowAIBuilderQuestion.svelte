<script lang="ts">
  /* eslint-disable eneo/no-raw-color -- the style block derives every colour
     from theme tokens via relative oklch() syntax, which the rule cannot see
     through */
  import { untrack } from "svelte";
  import IconX from "@lucide/svelte/icons/x";
  import { m } from "$lib/paraglide/messages";
  import {
    getFlowFormFieldNameIssue,
    getFlowFormFieldVariableToken,
    getSuggestedFlowFormFieldRuntimeKey
  } from "$lib/features/flows/flowFormSchema";
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
    isStructuredInputFieldPurpose,
    toggleStructuredQuestionOption,
    type StructuredQuestion,
    type StructuredQuestionAnswerPayload,
    type StructuredInputFieldAnswer,
    type StructuredInputFieldPurpose,
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
    /** Ordinal of this question in the interview, shown as "Fråga n". */
    questionNumber?: number | null;
    /** The assistant's sentence that came with the question: "Därför frågar jag". */
    why?: string | null;
    onanswer?: (payload: StructuredQuestionAnswerPayload) => void;
    /** The user hands this question back; only offered with a recommendation. */
    ondelegate?: () => void;
    /** Changing a published flow: the option the flow runs on today is the one
     *  preselected and marked "Används i dag", so confirming without reading
     *  cannot move a live flow off its current value. */
    isEdit?: boolean;
    /** Further questions the server plans after this one — a snapshot that can
     *  grow, so it is said in words and never drawn as a progress bar. */
    plannedRemaining?: number | null;
    /** The fields this question was already answered with. Editing starts from
     *  them: an empty form would let one blank row replace the whole set. */
    answeredFields?: StructuredInputFieldAnswer[] | null;
  }

  let {
    question,
    answered = false,
    answerLabel = null,
    disabled = false,
    questionNumber = null,
    why = null,
    onanswer,
    ondelegate,
    isEdit = false,
    plannedRemaining = null,
    answeredFields = null
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
  // The technical name follows the label the way the flow's own field editor
  // suggests it — same helper, so a field named here and a field named there
  // end up with the same key — until the user types one themselves.
  function suggestFieldName(index: number, label: string) {
    const field = inputFields[index];
    if (!field || field.nameEdited) return;
    field.variableName = getSuggestedFlowFormFieldRuntimeKey(
      label,
      inputFields.filter((_, i) => i !== index).map((other) => other.variableName)
    );
  }

  // The same rules the flow's field editor enforces: a name that breaks them
  // is refused by the server, so the editor should not let it be sent.
  function fieldNameIssue(index: number): string | null {
    const field = inputFields[index];
    const name = field?.variableName.trim() ?? "";
    if (!field || name.length === 0) return null;
    const issue = getFlowFormFieldNameIssue(name);
    if (issue === "namespace_head") return m.flow_form_field_name_namespace_head();
    if (issue === "primary_input_key") return m.flow_form_field_name_primary_input_key();
    if (issue === "step_alias") return m.flow_form_field_name_step_alias();
    if (issue === "dot") return m.flow_form_field_name_dot();
    const lowered = name.toLowerCase();
    const first = inputFields.findIndex(
      (other) => other.variableName.trim().toLowerCase() === lowered
    );
    return first !== index ? m.flow_form_field_name_duplicate() : null;
  }

  let showTechnicalNames = $state(false);
  function pasteFieldList(text: string) {
    const labels = text
      .split(/[\n\t;]+/)
      .map((line) => line.trim())
      .filter(Boolean);
    if (labels.length === 0) return;
    // A pasted list is labels; everything else keeps its default and the
    // runtime name follows the label the way a typed one does.
    const startedEmpty = inputFields.length === 1 && !inputFields[0]?.label.trim();
    if (startedEmpty) inputFields.length = 0;
    for (const label of labels.slice(0, 20 - inputFields.length)) {
      const row = blankField();
      row.label = label;
      row.variableName = getSuggestedFlowFormFieldRuntimeKey(
        label,
        inputFields.map((other) => other.variableName)
      );
      inputFields.push(row);
    }
    expandedFieldIndex = -1;
  }
  let copiedFieldIndex = $state<number | null>(null);
  let copiedTimer: ReturnType<typeof setTimeout> | null = null;

  function fieldToken(name: string): string {
    return getFlowFormFieldVariableToken(name.trim());
  }

  async function copyFieldToken(index: number) {
    const token = fieldToken(inputFields[index]?.variableName ?? "");
    if (!token) return;
    try {
      await navigator.clipboard.writeText(token);
    } catch {
      return;
    }
    copiedFieldIndex = index;
    if (copiedTimer) clearTimeout(copiedTimer);
    copiedTimer = setTimeout(() => (copiedFieldIndex = null), 1500);
  }

  interface EditableField {
    variableName: string;
    nameEdited: boolean;
    label: string;
    fieldType: StructuredInputFieldType;
    required: boolean;
    options: string[];
    purpose: StructuredInputFieldPurpose | "";
  }

  function blankField(): EditableField {
    return {
      variableName: "",
      nameEdited: false,
      label: "",
      fieldType: "text" as StructuredInputFieldType,
      required: false,
      options: [],
      purpose: "" as StructuredInputFieldPurpose | ""
    };
  }

  // Seeded once, on purpose: the editor is re-keyed per question, and after
  // that the rows belong to the user, not to the answer they started from.
  let inputFields = $state<EditableField[]>(
    untrack(() =>
      (answeredFields ?? []).length > 0
        ? (answeredFields ?? []).map((field) => ({
            variableName: field.value.name,
            nameEdited: true,
            label: field.value.label,
            fieldType: field.value.type,
            required: field.value.required === true,
            options: [...(field.value.options ?? [])],
            purpose: field.purpose as StructuredInputFieldPurpose | ""
          }))
        : [blankField()]
    )
  );

  let expandedFieldIndex = $state(0);
  let fieldSearch = $state("");
  let pasteOpen = $state(false);
  let pasteText = $state("");
  const pasteId = `builder-paste-${Math.random().toString(36).slice(2, 8)}`;
  const FIELD_LIST_SCROLLS_FROM = 12;
  const visibleFieldIndexes = $derived.by(() => {
    const needle = fieldSearch.trim().toLowerCase();
    const all = inputFields.map((_, index) => index);
    if (!needle) return all;
    return all.filter((index) => {
      const field = inputFields[index];
      return (
        field.label.toLowerCase().includes(needle) ||
        field.variableName.toLowerCase().includes(needle)
      );
    });
  });
  const requiredFieldCount = $derived(inputFields.filter((field) => field.required).length);
  const fieldSummaryLine = $derived(
    requiredFieldCount > 0
      ? `${inputFields.length === 1 ? m.ai_builder_requirements_runtime_fields_count_one() : m.ai_builder_requirements_runtime_fields_count({ count: String(inputFields.length) })} · ${requiredFieldCount === 1 ? m.ai_builder_requirements_field_required_count_one() : m.ai_builder_requirements_field_required_count({ required: String(requiredFieldCount) })}`
      : inputFields.length === 1
        ? m.ai_builder_requirements_runtime_fields_count_one()
        : m.ai_builder_requirements_runtime_fields_count({ count: String(inputFields.length) })
  );

  let preselectedQuestionId: string | null = null;
  $effect(() => {
    const key = recommendedKey;
    if (preselectedQuestionId === question.question_id) return;
    preselectedQuestionId = question.question_id;
    const preselect = currentKey ?? key;
    if (preselect && question.selection_mode === "single" && selectedOptionKeys.size === 0) {
      selectedOptionKeys.add(preselect);
    }
  });

  // The custom-answer row is the last radio in a single-choice group; this
  // sentinel keeps it addressable next to the real option keys.
  const CUSTOM_RADIO_KEY = "__ai_builder_custom__";

  // Eneo names the option it would settle on. It is preselected, so confirming
  // is one click, and it is the only thing a delegation can produce — without
  // one there is nothing to hand back.
  // Editing: the value in use is the one that starts selected, and it wears
  // "Används i dag" rather than a recommendation — the server guarantees a
  // recommendation here equals it or is absent.
  const currentKey = $derived.by(() => {
    const id = isEdit ? question.current_option_id : null;
    if (!id) return null;
    const option = question.options.find(
      (candidate) => getStructuredQuestionOptionKey(candidate) === id
    );
    return option ? getStructuredQuestionOptionKey(option) : null;
  });
  const recommendedKey = $derived.by(() => {
    const id = isEdit ? null : question.recommended_option_id;
    if (!id) return null;
    const option = question.options.find(
      (candidate) => getStructuredQuestionOptionKey(candidate) === id
    );
    return option ? getStructuredQuestionOptionKey(option) : null;
  });
  const canDelegate = $derived(
    recommendedKey !== null && ondelegate !== undefined && !answered && !disabled
  );

  const isSingle = $derived(question.selection_mode === "single");
  const isSchemaDirection = $derived(question.question_id === "schema_direction");
  const isInputFieldCollection = $derived(question.input_field_collection === true);
  const purposeOptions = $derived(
    question.options.filter((option) => isStructuredInputFieldPurpose(option.value))
  );
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

  // A single-choice group is one tab stop: the chosen option carries it, and
  // the arrow keys move both selection and focus inside the group.
  const radioKeys = $derived(
    isSingle
      ? [
          ...visibleOptions.map(getStructuredQuestionOptionKey),
          ...(question.allow_custom ? [CUSTOM_RADIO_KEY] : [])
        ]
      : []
  );
  const activeRadioKey = $derived.by(() => {
    if (!isSingle) return null;
    if (customSelected) return CUSTOM_RADIO_KEY;
    return radioKeys.find((key) => selectedOptionKeys.has(key)) ?? radioKeys[0] ?? null;
  });
  function radioTabIndex(key: string): number | undefined {
    if (!isSingle) return undefined;
    return key === activeRadioKey ? 0 : -1;
  }

  let optionsStackEl = $state<HTMLDivElement | null>(null);

  function moveRadioSelection(fromKey: string, event: KeyboardEvent) {
    if (!isSingle || answered || disabled) return;
    const keys = radioKeys;
    const index = keys.indexOf(fromKey);
    if (index === -1 || keys.length === 0) return;
    let next: number;
    switch (event.key) {
      case "ArrowDown":
      case "ArrowRight":
        next = (index + 1) % keys.length;
        break;
      case "ArrowUp":
      case "ArrowLeft":
        next = (index - 1 + keys.length) % keys.length;
        break;
      case "Home":
        next = 0;
        break;
      case "End":
        next = keys.length - 1;
        break;
      default:
        return;
    }
    event.preventDefault();
    const nextKey = keys[next]!;
    if (nextKey === CUSTOM_RADIO_KEY) {
      // Arrowing onto the custom row selects it but keeps focus on the radio,
      // so the next arrow press still moves inside the group.
      selectCustom({ focusTextarea: false });
    } else {
      const option = visibleOptions.find(
        (candidate) => getStructuredQuestionOptionKey(candidate) === nextKey
      );
      if (!option) return;
      selectOption(option);
    }
    queueMicrotask(() =>
      optionsStackEl?.querySelector<HTMLElement>(`[data-radio-index="${next}"]`)?.focus()
    );
  }

  const confirmLabel = $derived.by(() => {
    if (!isInputFieldCollection) return m.ai_builder_question_confirm();
    if (inputFields.length < 4) return m.ai_builder_question_confirm();
    // The same words the list uses, so the button confirms what was counted.
    return m.ai_builder_question_confirm_fields({ summary: fieldSummaryLine });
  });

  const canConfirm = $derived.by(() => {
    if (answered) return false;
    if (isInputFieldCollection) {
      return inputFields.every(
        (field, index) =>
          field.variableName.trim().length > 0 &&
          fieldNameIssue(index) === null &&
          field.label.trim().length > 0 &&
          isStructuredInputFieldPurpose(field.purpose) &&
          (!["select", "multiselect"].includes(field.fieldType) ||
            field.options.some((option) => option.trim().length > 0))
      );
    }
    if (customSelected) return customText.trim().length > 0;
    return selectedOptionKeys.size > 0;
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

    // Every shape selects first and sends on "Bekräfta svaret": the choice is
    // visible and changeable before it becomes an answer.
    if (isSingle) {
      selectedOptionKeys.clear();
      selectedOptionKeys.add(optionKey);
      return;
    }

    const nextSelection = toggleStructuredQuestionOption(question, selectedOptionKeys, option);
    selectedOptionKeys.clear();
    for (const selectedKey of nextSelection) selectedOptionKeys.add(selectedKey);
  }

  function selectCustom(options: { focusTextarea?: boolean } = {}) {
    if (answered || disabled) return;
    customSelected = true;
    // Custom answers intentionally replace preset selections instead of mixing
    // both answer types in one payload.
    selectedOptionKeys.clear();
    if (options.focusTextarea !== false) queueMicrotask(() => textareaRef?.focus());
  }

  function handleConfirm() {
    if (!canConfirm || disabled) return;
    if (!canConfirm || disabled) return;
    if (isInputFieldCollection) {
      const completedFields: StructuredInputFieldAnswer[] = [];
      for (const field of inputFields) {
        if (!isStructuredInputFieldPurpose(field.purpose)) return;
        completedFields.push({
          value: {
            name: field.variableName,
            label: field.label,
            type: field.fieldType,
            required: field.required,
            options: field.options
          },
          purpose: field.purpose
        });
      }
      onanswer?.(buildStructuredQuestionInputFieldsAnswer(question, completedFields));
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

  function typeLabel(type: StructuredInputFieldType): string {
    if (type === "number") return m.flow_form_field_type_number();
    if (type === "date") return m.flow_form_field_type_date();
    if (type === "select") return m.flow_form_field_type_select();
    if (type === "multiselect") return m.flow_form_field_type_multiselect();
    return m.flow_form_field_type_text();
  }

  function addInputField() {
    if (inputFields.length >= 20) return;
    inputFields.push(blankField());
    expandedFieldIndex = inputFields.length - 1;
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
    <div class="question-head">
      {#if questionNumber !== null}
        <p class="question-kicker">
          {m.ai_builder_question_number({ number: String(questionNumber) })}
          {#if plannedRemaining !== null && plannedRemaining > 0}
            <span class="question-kicker-rest">
              {m.ai_builder_question_planned_remaining({ count: String(plannedRemaining) })}
            </span>
          {/if}
        </p>
      {/if}
      <h2 id={questionLabelId} class="question-title" tabindex="-1" data-builder-screen-heading>
        {question.question}
      </h2>

      {#if why}
        <p class="question-why">
          <span class="question-why-lead">{m.ai_builder_question_why_lead()}</span>
          {why}
        </p>
      {/if}
    </div>

    {#if isInputFieldCollection}
      <div class="field-collection" aria-labelledby={questionLabelId}>
        {#if inputFields.length > 3}
          <div class="field-list-head">
            <span class="field-list-count">{fieldSummaryLine}</span>
            {#if inputFields.length >= FIELD_LIST_SCROLLS_FROM}
              <input
                class="field-search"
                type="search"
                bind:value={fieldSearch}
                placeholder={m.ai_builder_question_field_search()}
                aria-label={m.ai_builder_question_field_search()}
                {disabled}
              />
              {#if fieldSearch.trim()}
                <span class="field-list-count">
                  {m.ai_builder_question_field_search_count({
                    shown: String(visibleFieldIndexes.length),
                    total: String(inputFields.length)
                  })}
                </span>
              {/if}
            {/if}
          </div>
        {/if}
        <div class="field-list" class:is-scrolling={inputFields.length >= FIELD_LIST_SCROLLS_FROM}>
          {#each visibleFieldIndexes as index (index)}
            {@const field = inputFields[index]}
            {#if expandedFieldIndex !== index}
              <button
                type="button"
                class="field-summary-row"
                onclick={() => (expandedFieldIndex = index)}
                {disabled}
              >
                <span class="field-summary-label"
                  >{field.label.trim() || m.ai_builder_question_field_label()}</span
                >
                {#if showTechnicalNames && field.variableName.trim()}
                  <span class="field-summary-name">{field.variableName.trim()}</span>
                {/if}
                <span class="field-summary-type">{typeLabel(field.fieldType)}</span>
                {#if field.required}
                  <span class="field-summary-required"
                    >{m.ai_builder_requirements_field_required()}</span
                  >
                {/if}
                {#if fieldNameIssue(index)}
                  <span class="field-name-issue">{fieldNameIssue(index)}</span>
                {/if}
              </button>
            {:else}
              <div class="field-row">
                <label>
                  <span>{m.ai_builder_question_field_label()}</span>
                  <input
                    bind:value={field.label}
                    oninput={(event) => suggestFieldName(index, event.currentTarget.value)}
                    {disabled}
                  />
                </label>
                <div class="field-name">
                  <span class="field-name-label">{m.ai_builder_question_field_name()}</span>
                  {#if fieldToken(field.variableName)}
                    <button
                      type="button"
                      class="field-name-token"
                      aria-label={m.ai_builder_question_field_copy({
                        token: fieldToken(field.variableName)
                      })}
                      onclick={() => copyFieldToken(index)}
                      {disabled}
                    >
                      {copiedFieldIndex === index
                        ? m.ai_builder_question_field_copied()
                        : fieldToken(field.variableName)}
                    </button>
                  {/if}
                  {#if showTechnicalNames}
                    <input
                      bind:value={field.variableName}
                      oninput={() => (field.nameEdited = true)}
                      aria-label={m.ai_builder_question_field_name()}
                      aria-invalid={fieldNameIssue(index) !== null}
                      {disabled}
                    />
                  {:else if !field.nameEdited}
                    <span class="field-name-auto">{m.ai_builder_question_field_name_auto()}</span>
                  {/if}
                  {#if fieldNameIssue(index)}
                    <span class="field-name-issue">{fieldNameIssue(index)}</span>
                  {/if}
                </div>
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
                <label class="field-purpose">
                  <span>{m.ai_builder_question_field_purpose()}</span>
                  <select
                    bind:value={field.purpose}
                    aria-label={`${field.label.trim() || field.variableName.trim() || m.ai_builder_question_field_label()}: ${question.question}`}
                    {disabled}
                  >
                    <option value="" disabled>—</option>
                    {#each purposeOptions as option (getStructuredQuestionOptionKey(option))}
                      <option value={option.value}>{option.label}</option>
                    {/each}
                  </select>
                </label>
                {#if field.fieldType === "select" || field.fieldType === "multiselect"}
                  <div class="field-options">
                    <span class="field-options-label">{m.ai_builder_question_field_options()}</span>
                    {#each field.options as _option, optionIndex (optionIndex)}
                      <div class="field-option-row">
                        <input
                          bind:value={field.options[optionIndex]}
                          aria-label={m.ai_builder_question_field_option_n({
                            number: String(optionIndex + 1)
                          })}
                          {disabled}
                        />
                        <button
                          type="button"
                          class="field-option-remove"
                          aria-label={m.ai_builder_question_field_option_remove({
                            number: String(optionIndex + 1)
                          })}
                          onclick={() => field.options.splice(optionIndex, 1)}
                          {disabled}
                        >
                          <IconX class="size-3.5" aria-hidden="true" />
                        </button>
                      </div>
                    {/each}
                    <button
                      type="button"
                      class="field-option-add"
                      onclick={() => field.options.push("")}
                      {disabled}
                    >
                      {m.ai_builder_question_field_option_add()}
                    </button>
                  </div>
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
            {/if}
          {/each}
        </div>
        <div class="field-actions">
          <button
            type="button"
            class="field-add"
            onclick={addInputField}
            disabled={disabled || inputFields.length >= 20}
          >
            {m.ai_builder_question_field_add()}
          </button>
          <button
            type="button"
            class="field-add"
            onclick={() => (pasteOpen = !pasteOpen)}
            aria-expanded={pasteOpen}
            disabled={disabled || inputFields.length >= 20}
          >
            {m.ai_builder_question_field_paste()}
          </button>
        </div>
        {#if pasteOpen}
          <div class="field-paste">
            <label class="field-paste-label" for={pasteId}>
              {m.ai_builder_question_field_paste_hint()}
            </label>
            <textarea id={pasteId} bind:value={pasteText} rows="3" {disabled}></textarea>
            <button
              type="button"
              class="field-add"
              disabled={disabled || !pasteText.trim()}
              onclick={() => {
                pasteFieldList(pasteText);
                pasteText = "";
                pasteOpen = false;
              }}
            >
              {m.ai_builder_question_field_paste_apply()}
            </button>
          </div>
        {/if}
        <!-- The runtime name is a developer's concern; it is derived, and only
             someone who asks to see it needs the field. -->
        <label class="field-technical-toggle">
          <input type="checkbox" bind:checked={showTechnicalNames} {disabled} />
          {m.ai_builder_question_show_technical()}
        </label>
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
      <p id="{questionLabelId}-keys" class="sr-only">
        {isSingle ? m.ai_builder_question_keys_single() : m.ai_builder_question_keys_multi()}
      </p>
      <div
        bind:this={optionsStackEl}
        class="options-stack"
        role={isSingle ? "radiogroup" : "group"}
        aria-labelledby={questionLabelId}
        aria-describedby="{questionLabelId}-keys"
      >
        {#each visibleOptions as option, optionIndex (getStructuredQuestionOptionKey(option))}
          {@const optionKey = getStructuredQuestionOptionKey(option)}
          {@const isSelected = selectedOptionKeys.has(optionKey)}
          <button
            type="button"
            class="option-row"
            class:is-selected={isSelected}
            onclick={() => selectOption(option)}
            onkeydown={(event) => moveRadioSelection(optionKey, event)}
            role={isSingle ? "radio" : "checkbox"}
            aria-checked={isSelected}
            tabindex={radioTabIndex(optionKey)}
            data-radio-index={isSingle ? optionIndex : undefined}
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
              <span class="option-label-row">
                <span class="option-label">{option.label}</span>
                {#if optionKey === currentKey}
                  <span class="option-current">{m.ai_builder_question_in_use_today()}</span>
                {:else if optionKey === recommendedKey}
                  <span class="option-recommendation">{m.ai_builder_question_recommended()}</span>
                {/if}
              </span>
              {#if option.description}
                <span class="option-description">{option.description}</span>
              {/if}
              {#if option.example}
                <span class="option-example">{option.example}</span>
              {/if}
              {#if optionKey === recommendedKey && question.recommended_option_evidence}
                <!-- The user's own words, so the recommendation is traceable
                     rather than asserted. -->
                <span class="option-evidence">
                  {m.ai_builder_question_evidence({
                    quote: question.recommended_option_evidence
                  })}
                </span>
              {/if}
            </span>
          </button>
        {/each}

        {#if question.allow_custom}
          <button
            type="button"
            class="option-row option-row-custom"
            class:is-selected={customSelected}
            onclick={() => selectCustom()}
            onkeydown={(event) => moveRadioSelection(CUSTOM_RADIO_KEY, event)}
            role={isSingle ? "radio" : "checkbox"}
            aria-checked={customSelected}
            aria-expanded={customSelected}
            aria-controls={customSelected ? `${questionLabelId}-custom` : undefined}
            tabindex={radioTabIndex(CUSTOM_RADIO_KEY)}
            data-radio-index={isSingle ? visibleOptions.length : undefined}
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

    <div class="actions-row">
      {#if canDelegate}
        <span class="delegate-block">
          <button type="button" class="delegate-action" onclick={() => ondelegate?.()}>
            {m.ai_builder_question_delegate()}
          </button>
          <span class="delegate-note">{m.ai_builder_question_delegate_note()}</span>
        </span>
      {/if}
      <!-- Kept in the tab order while it is unavailable: a keyboard user has to
           be able to reach it and hear why it does not fire yet. -->
      <Button
        variant="default"
        class="ml-auto max-sm:ml-0 max-sm:h-[44px] max-sm:w-full max-sm:text-sm"
        onclick={handleConfirm}
        aria-disabled={!canConfirm || disabled}
        aria-describedby={!canConfirm && !disabled ? `${questionLabelId}-confirm-hint` : undefined}
      >
        {confirmLabel}
      </Button>
      {#if !canConfirm && !disabled}
        <span id="{questionLabelId}-confirm-hint" class="sr-only">
          {m.ai_builder_question_confirm_hint()}
        </span>
      {/if}
    </div>
  {/if}
</div>

<style lang="postcss">
  @reference "@eneo/ui/styles";

  .question-panel {
    @apply flex flex-col overflow-hidden rounded-xl border;
    border-color: var(--border-default);
    background: var(--background-primary);
    animation: builder-screen-in 0.22s cubic-bezier(0.16, 1, 0.3, 1);
  }

  .question-panel.answered {
    @apply mt-3 px-3.5 py-3;
    border-color: oklch(from var(--border-default) l c h / 0.55);
    background: oklch(from var(--background-secondary) l c h / 0.28);
  }

  .question-head {
    padding: 1rem 1.125rem 0.875rem;
  }

  .question-kicker {
    @apply text-[0.72rem] font-semibold;
    color: var(--text-secondary);
  }

  .question-title {
    @apply mt-2 text-[1.1875rem] leading-snug font-bold tracking-[-0.02em] text-pretty;
    color: var(--text-primary);
  }

  .question-kicker-rest {
    color: var(--text-secondary);
    font-weight: 500;
  }

  .question-why {
    @apply mt-2 max-w-[62ch] text-[0.8125rem] leading-relaxed text-pretty;
    color: var(--text-secondary);
  }

  .question-why-lead {
    @apply font-semibold;
    color: var(--text-primary);
  }

  .options-stack {
    @apply flex flex-col gap-1.5 border-t px-2.5 pt-1.5 pb-2.5;
    border-color: var(--border-dimmer);
  }

  .option-filter {
    @apply mx-4 mb-1 flex flex-col gap-1 text-xs font-medium;
    color: var(--text-secondary);
  }

  .option-filter input {
    @apply h-9 rounded-md border px-3 text-sm font-normal;
    border-color: var(--border-default);
    background: var(--background-primary);
    color: var(--text-primary);
  }

  .option-filter-summary {
    @apply mx-4 mb-2 text-xs;
    color: var(--text-secondary);
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
    @apply relative flex min-h-11 w-full items-start gap-3 rounded-[10px] border px-3 py-3 text-left;
    border-color: var(--border-default);
    background: var(--background-primary);
    color: var(--text-primary);
    cursor: pointer;
    transition:
      background 0.15s ease,
      border-color 0.15s ease;
  }

  .option-row:not(:disabled):hover {
    border-color: var(--border-stronger);
    background: var(--background-secondary);
  }

  .option-row.is-selected:not(:disabled):hover {
    border-color: var(--accent-default);
    background: oklch(from var(--accent-default) l c h / 0.1);
  }

  .option-label-row {
    @apply flex flex-wrap items-center gap-1.5;
  }

  .option-example {
    @apply text-[0.78125rem];
    color: var(--text-secondary);
    opacity: 0.85;
  }

  .option-evidence {
    @apply mt-1.5 self-start border-l-2 pl-2.5 text-xs italic;
    border-color: oklch(from var(--accent-default) l c h / 0.35);
    color: var(--text-secondary);
  }

  .option-current {
    @apply inline-flex h-5 shrink-0 items-center rounded-full px-2 text-[0.65625rem] font-bold;
    letter-spacing: 0.03em;
    color: var(--positive-stronger);
    background: var(--positive-dimmer);
  }

  .option-recommendation {
    @apply inline-flex h-5 shrink-0 items-center rounded-full px-2 text-[0.65625rem] font-bold;
    letter-spacing: 0.03em;
    color: var(--accent-stronger);
    background: var(--accent-dimmer);
  }

  .delegate-block {
    @apply flex min-w-0 flex-col gap-0.5;
  }

  .delegate-note {
    @apply text-xs;
    color: var(--text-secondary);
  }

  .delegate-action {
    @apply rounded text-[0.8125rem] font-semibold;
    color: var(--accent-stronger);
  }

  .delegate-action:hover {
    @apply underline;
  }

  .delegate-action:focus-visible {
    outline: 2px solid var(--accent-stronger);
    outline-offset: 2px;
  }

  .option-row:focus-visible {
    outline: 2px solid var(--accent-stronger);
    outline-offset: 1px;
  }

  .option-row:disabled {
    cursor: default;
  }

  .option-row.is-selected {
    border-color: var(--accent-default);
    box-shadow: inset 0 0 0 1px var(--accent-default);
    background: oklch(from var(--accent-default) l c h / 0.07);
  }

  .option-indicator {
    @apply relative mt-0.5 flex size-[1.1875rem] shrink-0 items-center justify-center rounded-md;
    border: 1.5px solid var(--border-stronger);
    background: var(--background-primary);
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
    border-color: var(--border-stronger);
  }

  .option-indicator.is-selected {
    border-color: var(--accent-default);
    background: var(--accent-default);
    color: var(--text-on-fill);
  }

  .option-indicator-dot {
    @apply size-[0.4375rem] rounded-full;
    background: var(--text-on-fill);
  }

  .option-body {
    @apply flex min-w-0 flex-col gap-0.5;
  }

  .option-label {
    @apply text-sm leading-snug font-semibold tracking-[-0.01em];
    color: var(--text-primary);
  }

  .option-description {
    @apply text-[0.8125rem] leading-relaxed text-pretty;
    color: var(--text-secondary);
  }

  .field-collection {
    @apply flex flex-col gap-3 border-t px-4 py-3;
    border-color: var(--border-dimmer);
  }

  .field-list {
    @apply flex flex-col gap-1.5;
  }

  .field-list.is-scrolling {
    @apply overflow-y-auto pr-1;
    max-height: 26.25rem;
  }

  .field-list-head {
    @apply flex flex-wrap items-center gap-2;
  }

  .field-list-count {
    @apply text-xs;
    color: var(--text-secondary);
  }

  .field-search {
    @apply ml-auto h-8 w-[11.875rem] rounded-md border px-2 text-xs;
    border-color: var(--border-default);
    background: var(--background-primary);
  }

  .field-summary-row {
    @apply flex min-h-11 w-full flex-wrap items-center gap-x-3 gap-y-0.5 rounded-lg px-3 py-2 text-left text-xs;
    background: var(--background-secondary);
    color: var(--text-secondary);
  }

  .field-summary-row:hover:not(:disabled) {
    background: oklch(from var(--background-secondary) l c h / 0.7);
  }

  .field-summary-label {
    @apply flex-1 truncate text-[0.8125rem] font-semibold;
    color: var(--text-primary);
  }

  .field-summary-name {
    @apply truncate text-[0.6875rem];
    font-family: var(--font-mono, ui-monospace, monospace);
  }

  .field-summary-required {
    @apply rounded px-1.5 py-0.5 text-[0.6875rem] font-semibold;
    background: var(--accent-dimmer);
    color: var(--accent-stronger);
  }

  .field-actions {
    @apply flex flex-wrap items-center gap-3;
  }

  .field-paste {
    @apply flex flex-col gap-1.5 rounded-lg p-3;
    background: var(--background-secondary);
  }

  .field-paste-label {
    @apply text-xs;
    color: var(--text-secondary);
  }

  .field-row {
    @apply grid grid-cols-2 gap-3 rounded-lg p-3;
    background: var(--background-secondary);
  }

  .field-name {
    @apply flex flex-col gap-1 text-xs font-medium;
  }

  .field-name-label {
    color: var(--text-secondary);
  }

  .field-name-token {
    @apply inline-flex h-[1.375rem] w-fit items-center rounded-md border px-2 text-[0.6875rem];
    font-family: var(--font-mono, ui-monospace, monospace);
    border-color: var(--border-default);
    background: var(--background-primary);
    color: var(--text-secondary);
  }

  .field-name-token:hover:not(:disabled) {
    color: var(--text-primary);
  }

  .field-name-auto {
    @apply text-[0.6875rem] font-normal;
    color: var(--text-secondary);
  }

  .field-technical-toggle {
    @apply inline-flex items-center gap-2 text-xs;
    color: var(--text-secondary);
  }

  .field-name-issue {
    @apply text-[0.6875rem] font-semibold;
    color: var(--text-warning-stronger, var(--text-secondary));
  }

  .field-row label:not(.field-required) {
    @apply flex flex-col gap-1 text-xs font-medium;
    color: var(--text-secondary);
  }

  .field-row input:not([type="checkbox"]),
  .field-row select {
    @apply h-9 rounded-md border px-2 text-sm;
    border-color: var(--border-default);
    background: var(--background-primary);
    color: var(--text-primary);
  }

  .field-options {
    @apply col-span-2 flex flex-col gap-1.5 text-xs font-medium;
  }

  .field-options-label {
    color: var(--text-secondary);
  }

  .field-option-row {
    @apply flex items-center gap-2;
  }

  .field-option-row input {
    @apply flex-1;
  }

  .field-option-remove {
    @apply inline-flex size-8 shrink-0 items-center justify-center rounded-md;
    color: var(--text-secondary);
  }

  .field-option-remove:hover:not(:disabled) {
    background: var(--background-secondary);
    color: var(--text-primary);
  }

  .field-option-add {
    @apply w-fit text-xs font-semibold;
    color: var(--accent-stronger);
  }

  .field-purpose {
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
    @apply rounded-lg;
    padding: 0.125rem 0.25rem 0;
  }

  .custom-input-wrap :global([data-slot="textarea"]) {
    @apply text-[0.8125rem];
    min-height: 4rem;
  }

  .actions-row {
    @apply flex flex-wrap items-center gap-2.5 border-t px-[1.125rem] py-3;
    border-color: var(--border-dimmer);
  }

  /* Phone width: the option list is longer than the screen, so the confirm
     action leaves the card and becomes a bar pinned to the bottom of the
     builder. Confirming must never require scrolling past every option. */
  @media (max-width: 39.9375rem) {
    .question-panel:not(.answered) {
      overflow: visible;
    }

    .actions-row {
      position: sticky;
      bottom: 0;
      z-index: 5;
      flex-direction: column-reverse;
      flex-wrap: nowrap;
      align-items: stretch;
      gap: 0.5rem;
      padding: 0.6875rem 0.875rem calc(0.6875rem + env(safe-area-inset-bottom));
      border-bottom-right-radius: 0.75rem;
      border-bottom-left-radius: 0.75rem;
      border-color: var(--border-default);
      background: var(--background-primary);
      box-shadow: 0 -0.5rem 1rem -0.75rem var(--shadow-stronger);
    }

    /* Below the primary, and still a touch target of its own. */
    .delegate-block {
      @apply flex min-w-0 flex-col gap-0.5;
    }

    .delegate-note {
      @apply text-xs;
      color: var(--text-secondary);
    }

    .delegate-action {
      @apply h-10 w-full;
    }

    /* One field per line: two columns leave no room for a label at 375 px. */
    .field-list {
      @apply flex flex-col gap-1.5;
    }

    .field-list.is-scrolling {
      @apply overflow-y-auto pr-1;
      max-height: 26.25rem;
    }

    .field-list-head {
      @apply flex flex-wrap items-center gap-2;
    }

    .field-list-count {
      @apply text-xs;
      color: var(--text-secondary);
    }

    .field-search {
      @apply ml-auto h-8 w-[11.875rem] rounded-md border px-2 text-xs;
      border-color: var(--border-default);
      background: var(--background-primary);
    }

    .field-summary-row {
      @apply flex min-h-11 w-full flex-wrap items-center gap-x-3 gap-y-0.5 rounded-lg px-3 py-2 text-left text-xs;
      background: var(--background-secondary);
      color: var(--text-secondary);
    }

    .field-summary-row:hover:not(:disabled) {
      background: oklch(from var(--background-secondary) l c h / 0.7);
    }

    .field-summary-label {
      @apply flex-1 truncate text-[0.8125rem] font-semibold;
      color: var(--text-primary);
    }

    .field-summary-name {
      @apply truncate text-[0.6875rem];
      font-family: var(--font-mono, ui-monospace, monospace);
    }

    .field-summary-required {
      @apply rounded px-1.5 py-0.5 text-[0.6875rem] font-semibold;
      background: var(--accent-dimmer);
      color: var(--accent-stronger);
    }

    .field-actions {
      @apply flex flex-wrap items-center gap-3;
    }

    .field-paste {
      @apply flex flex-col gap-1.5 rounded-lg p-3;
      background: var(--background-secondary);
    }

    .field-paste-label {
      @apply text-xs;
      color: var(--text-secondary);
    }

    .field-row {
      grid-template-columns: minmax(0, 1fr);
    }

    .field-options,
    .field-purpose {
      grid-column: auto;
    }
  }

  @keyframes builder-screen-in {
    from {
      opacity: 0.4;
      transform: translateY(6px);
    }
    to {
      opacity: 1;
      transform: none;
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .question-panel {
      animation: none;
    }
  }
</style>
