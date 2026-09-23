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
  import * as RadioGroup from "$lib/components/ui/radio-group/index.js";
  import { Checkbox } from "$lib/components/ui/checkbox/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { Label } from "$lib/components/ui/label/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import * as NativeSelect from "$lib/components/ui/native-select/index.js";
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
  import { fieldTypeLabel } from "./aiBuilderSummaryText";

  // An option key can be its label ("One PDF") when the planner gave no id; a
  // space would split aria-labelledby into references that do not exist. The
  // encoding is one-to-one, so two keys never share an id.
  function optionIdPart(key: string): string {
    return key.replace(/[^A-Za-z0-9-]/g, (char) => `_${char.codePointAt(0)?.toString(16)}_`);
  }

  interface Props {
    question: StructuredQuestion;
    answered?: boolean;
    /** The user's chosen answer, shown in the collapsed answered state. */
    answerLabel?: string | null;
    /** Interaction lock projected from the service (e.g. while a flow is
     *  being created) — controls must LOOK disabled, not silently no-op. */
    disabled?: boolean;
    sendBlockedReason?: string | null;
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
    /** Editing an earlier answer: what that answer settled starts selected,
     *  so the reader sees their current answer instead of an empty form. */
    answeredOptionIds?: string[] | null;
    /** The text typed instead of an option, when that is what was answered. */
    answeredCustomValue?: string | null;
  }

  let {
    question,
    answered = false,
    answerLabel = null,
    disabled = false,
    sendBlockedReason = null,
    questionNumber = null,
    why = null,
    onanswer,
    ondelegate,
    isEdit = false,
    plannedRemaining = null,
    answeredFields = null,
    answeredOptionIds = null,
    answeredCustomValue = null
  }: Props = $props();

  // Generated once per instance so radiogroup + its label can link without colliding.
  const questionLabelId = `ai-builder-q-${Math.random().toString(36).slice(2, 10)}`;

  const submissionDisabled = $derived(disabled || sendBlockedReason !== null);
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

  const answeredKeys = $derived(
    (answeredOptionIds ?? []).flatMap((id) => {
      const option = question.options.find(
        (candidate) => getStructuredQuestionOptionKey(candidate) === id
      );
      return option ? [getStructuredQuestionOptionKey(option)] : [];
    })
  );
  let preselectedQuestionId: string | null = null;
  $effect(() => {
    const key = recommendedKey;
    if (preselectedQuestionId === question.question_id) return;
    preselectedQuestionId = question.question_id;
    if (selectedOptionKeys.size !== 0) return;
    if (answeredCustomValue) {
      customSelected = true;
      customText = answeredCustomValue;
      return;
    }
    if (answeredKeys.length > 0) {
      for (const answered of question.selection_mode === "single"
        ? answeredKeys.slice(0, 1)
        : answeredKeys) {
        selectedOptionKeys.add(answered);
      }
      return;
    }
    const preselect = currentKey ?? key;
    if (preselect && question.selection_mode === "single") {
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

  // DESIGN.md option row: 10px corners, hairline, 0.75rem padding; hover turns
  // the rule strong over linen, a checked control turns it civic blue with an
  // inset ring over a 7% wash.
  const optionRowClass =
    "w-full cursor-pointer items-start gap-3 rounded-[10px] border border-default bg-primary p-3 text-left font-normal text-primary transition-colors duration-(--duration-quick) ease-(--ease-smooth-out) hover:border-stronger hover:bg-secondary has-data-[state=checked]:border-accent-default has-data-[state=checked]:bg-accent-default/7 has-data-[state=checked]:shadow-[inset_0_0_0_1px_var(--accent-default)] has-data-[state=checked]:hover:bg-accent-default/10 dark:has-data-[state=checked]:border-accent-default dark:has-data-[state=checked]:bg-accent-default/10 has-[:disabled]:cursor-default has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-1 has-[:focus-visible]:outline-accent-stronger motion-reduce:transition-none";

  // The radio group owns one-tab-stop and arrow-key selection; this only maps
  // its single value onto the selection the answer is built from.
  const singleValue = $derived(
    customSelected ? CUSTOM_RADIO_KEY : ([...selectedOptionKeys][0] ?? "")
  );
  // A click on the custom row puts the caret in its text box; arrowing onto it
  // only selects it, so the next arrow press still moves inside the group.
  let customPointerSelect = false;

  function selectSingle(key: string) {
    if (key === CUSTOM_RADIO_KEY) {
      selectCustom({ focusTextarea: customPointerSelect });
    } else {
      const option = visibleOptions.find(
        (candidate) => getStructuredQuestionOptionKey(candidate) === key
      );
      if (option) selectOption(option);
    }
    customPointerSelect = false;
  }

  function toggleCustom(on: boolean) {
    if (on) {
      selectCustom();
    } else if (!answered && !disabled) {
      customSelected = false;
      customText = "";
    }
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
    if (!canConfirm || submissionDisabled) return;
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
          <span class="text-primary font-semibold">{answerLabel}</span>
        {/if}
      </span>
    </div>
  {:else}
    {#if question.understanding}
      <div class="understanding" data-testid="question-understanding">
        <p class="understanding-title">{m.ai_builder_understanding_title()}</p>
        {#each question.understanding.sentences as sentence (sentence)}
          <p class="understanding-sentence">{sentence}</p>
        {/each}
        {#if (question.understanding.open_topics ?? []).length > 0}
          <p class="understanding-open">
            {m.ai_builder_understanding_open({
              topics: (question.understanding.open_topics ?? []).join(", ")
            })}
          </p>
        {/if}
      </div>
    {/if}
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
      <div
        class="border-dimmer flex flex-col gap-3 border-t px-4 py-3"
        aria-labelledby={questionLabelId}
      >
        {#if inputFields.length > 3}
          <div class="flex flex-wrap items-center gap-2">
            <span class="text-secondary text-xs">{fieldSummaryLine}</span>
            {#if inputFields.length >= FIELD_LIST_SCROLLS_FROM}
              <Input
                type="search"
                class="ml-auto h-8 w-48 text-xs"
                bind:value={fieldSearch}
                placeholder={m.ai_builder_question_field_search()}
                aria-label={m.ai_builder_question_field_search()}
                {disabled}
              />
              {#if fieldSearch.trim()}
                <span class="text-secondary text-xs">
                  {m.ai_builder_question_field_search_count({
                    shown: String(visibleFieldIndexes.length),
                    total: String(inputFields.length)
                  })}
                </span>
              {/if}
            {/if}
          </div>
        {/if}
        <div
          class="flex flex-col gap-1.5 {inputFields.length >= FIELD_LIST_SCROLLS_FROM
            ? 'max-h-[26.25rem] overflow-y-auto pr-1'
            : ''}"
        >
          {#each visibleFieldIndexes as index (index)}
            {@const field = inputFields[index]}
            {#if expandedFieldIndex !== index}
              <button
                type="button"
                class="bg-secondary text-secondary hover:bg-hover-dimmer focus-visible:ring-ring flex min-h-11 w-full flex-wrap items-center gap-x-3 gap-y-0.5 rounded-lg px-3 py-2 text-left text-xs focus-visible:ring-2 focus-visible:outline-none disabled:cursor-not-allowed motion-safe:transition-colors motion-safe:duration-(--duration-quick)"
                onclick={() => (expandedFieldIndex = index)}
                {disabled}
              >
                <span class="text-primary flex-1 truncate text-[0.8125rem] font-semibold"
                  >{field.label.trim() || m.ai_builder_question_field_label()}</span
                >
                {#if showTechnicalNames && field.variableName.trim()}
                  <span class="truncate font-mono text-xs">{field.variableName.trim()}</span>
                {/if}
                <span>{fieldTypeLabel(field.fieldType)}</span>
                {#if field.required}
                  <Badge
                    variant="secondary"
                    class="bg-accent-dimmer text-accent-stronger h-5 px-1.5"
                  >
                    {m.ai_builder_requirements_field_required()}
                  </Badge>
                {/if}
                {#if fieldNameIssue(index)}
                  <span class="text-warning-stronger font-semibold">{fieldNameIssue(index)}</span>
                {/if}
              </button>
            {:else}
              {@const labelId = `${questionLabelId}-field-${index}-label`}
              {@const typeId = `${questionLabelId}-field-${index}-type`}
              {@const purposeId = `${questionLabelId}-field-${index}-purpose`}
              {@const requiredId = `${questionLabelId}-field-${index}-required`}
              <div class="bg-secondary grid gap-3 rounded-lg p-3 sm:grid-cols-2">
                <div class="flex flex-col gap-1">
                  <Label for={labelId} class="text-secondary text-xs font-medium">
                    {m.ai_builder_question_field_label()}
                  </Label>
                  <Input
                    id={labelId}
                    class="bg-primary"
                    bind:value={field.label}
                    oninput={(event) => suggestFieldName(index, event.currentTarget.value)}
                    {disabled}
                  />
                </div>
                <div class="flex flex-col gap-1 text-xs font-medium">
                  <span class="text-secondary">{m.ai_builder_question_field_name()}</span>
                  {#if fieldToken(field.variableName)}
                    <Button
                      variant="outline"
                      size="xs"
                      class="text-secondary w-fit font-mono"
                      aria-label={m.ai_builder_question_field_copy({
                        token: fieldToken(field.variableName)
                      })}
                      onclick={() => copyFieldToken(index)}
                      {disabled}
                    >
                      {copiedFieldIndex === index
                        ? m.ai_builder_question_field_copied()
                        : fieldToken(field.variableName)}
                    </Button>
                  {/if}
                  {#if showTechnicalNames}
                    <Input
                      class="bg-primary"
                      bind:value={field.variableName}
                      oninput={() => (field.nameEdited = true)}
                      aria-label={m.ai_builder_question_field_name()}
                      aria-invalid={fieldNameIssue(index) !== null}
                      {disabled}
                    />
                  {:else if !field.nameEdited}
                    <span class="text-secondary font-normal"
                      >{m.ai_builder_question_field_name_auto()}</span
                    >
                  {/if}
                  {#if fieldNameIssue(index)}
                    <span class="text-warning-stronger font-semibold">{fieldNameIssue(index)}</span>
                  {/if}
                </div>
                <div class="flex flex-col gap-1">
                  <Label for={typeId} class="text-secondary text-xs font-medium">
                    {m.ai_builder_question_field_type()}
                  </Label>
                  <NativeSelect.Root
                    id={typeId}
                    class="bg-primary w-full"
                    bind:value={field.fieldType}
                    {disabled}
                  >
                    <NativeSelect.Option value="text"
                      >{m.flow_form_field_type_text()}</NativeSelect.Option
                    >
                    <NativeSelect.Option value="number"
                      >{m.flow_form_field_type_number()}</NativeSelect.Option
                    >
                    <NativeSelect.Option value="date"
                      >{m.flow_form_field_type_date()}</NativeSelect.Option
                    >
                    <NativeSelect.Option value="select"
                      >{m.flow_form_field_type_select()}</NativeSelect.Option
                    >
                    <NativeSelect.Option value="multiselect"
                      >{m.flow_form_field_type_multiselect()}</NativeSelect.Option
                    >
                    <NativeSelect.Option value="list"
                      >{m.flow_form_field_type_list()}</NativeSelect.Option
                    >
                  </NativeSelect.Root>
                </div>
                <div class="flex flex-col gap-1 sm:col-span-2">
                  <Label for={purposeId} class="text-secondary text-xs font-medium">
                    {m.ai_builder_question_field_purpose()}
                  </Label>
                  <NativeSelect.Root
                    id={purposeId}
                    class="bg-primary w-full"
                    bind:value={field.purpose}
                    aria-label={`${field.label.trim() || field.variableName.trim() || m.ai_builder_question_field_label()}: ${question.question}`}
                    {disabled}
                  >
                    <NativeSelect.Option value="" disabled>—</NativeSelect.Option>
                    {#each purposeOptions as option (getStructuredQuestionOptionKey(option))}
                      <NativeSelect.Option value={option.value}>{option.label}</NativeSelect.Option>
                    {/each}
                  </NativeSelect.Root>
                </div>
                {#if field.fieldType === "select" || field.fieldType === "multiselect"}
                  <div class="flex flex-col gap-1.5 text-xs font-medium sm:col-span-2">
                    <span class="text-secondary">{m.ai_builder_question_field_options()}</span>
                    {#each field.options as _option, optionIndex (optionIndex)}
                      <div class="flex items-center gap-2">
                        <Input
                          class="bg-primary flex-1"
                          bind:value={field.options[optionIndex]}
                          aria-label={m.ai_builder_question_field_option_n({
                            number: String(optionIndex + 1)
                          })}
                          {disabled}
                        />
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          class="text-secondary"
                          aria-label={m.ai_builder_question_field_option_remove({
                            number: String(optionIndex + 1)
                          })}
                          onclick={() => field.options.splice(optionIndex, 1)}
                          {disabled}
                        >
                          <IconX aria-hidden="true" />
                        </Button>
                      </div>
                    {/each}
                    <Button
                      variant="link"
                      size="xs"
                      class="w-fit px-0"
                      onclick={() => field.options.push("")}
                      {disabled}
                    >
                      {m.ai_builder_question_field_option_add()}
                    </Button>
                  </div>
                {/if}
                <div class="flex min-h-6 items-center gap-2">
                  <Checkbox id={requiredId} bind:checked={field.required} {disabled} />
                  <Label for={requiredId} class="text-primary text-xs font-normal">
                    {m.ai_builder_question_field_required()}
                  </Label>
                </div>
                {#if inputFields.length > 1}
                  <Button
                    variant="link"
                    size="xs"
                    class="w-fit justify-self-start px-0"
                    onclick={() => removeInputField(index)}
                    {disabled}
                  >
                    {m.ai_builder_question_field_remove()}
                  </Button>
                {/if}
              </div>
            {/if}
          {/each}
        </div>
        <div class="flex flex-wrap items-center gap-3">
          <Button
            variant="outline"
            size="sm"
            onclick={addInputField}
            disabled={disabled || inputFields.length >= 20}
          >
            {m.ai_builder_question_field_add()}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onclick={() => (pasteOpen = !pasteOpen)}
            aria-expanded={pasteOpen}
            disabled={disabled || inputFields.length >= 20}
          >
            {m.ai_builder_question_field_paste()}
          </Button>
        </div>
        {#if pasteOpen}
          <div class="bg-secondary flex flex-col gap-1.5 rounded-lg p-3">
            <Label for={pasteId} class="text-secondary text-xs font-normal">
              {m.ai_builder_question_field_paste_hint()}
            </Label>
            <Textarea id={pasteId} bind:value={pasteText} rows={3} {disabled} />
            <Button
              variant="outline"
              size="sm"
              class="w-fit"
              disabled={disabled || !pasteText.trim()}
              onclick={() => {
                pasteFieldList(pasteText);
                pasteText = "";
                pasteOpen = false;
              }}
            >
              {m.ai_builder_question_field_paste_apply()}
            </Button>
          </div>
        {/if}
        <!-- The runtime name is a developer's concern; it is derived, and only
             someone who asks to see it needs the field. -->
        <div class="flex min-h-6 items-center gap-2">
          <Checkbox
            id="{questionLabelId}-show-technical"
            bind:checked={showTechnicalNames}
            {disabled}
          />
          <Label for="{questionLabelId}-show-technical" class="text-secondary text-xs font-normal">
            {m.ai_builder_question_show_technical()}
          </Label>
        </div>
      </div>
    {:else}
      {#if isSchemaDirection && question.options.length > schemaDirectionVisibleOptionLimit}
        <label class="option-filter">
          <span>{m.ai_builder_question_schema_filter()}</span>
          <Input
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
      <!-- Each row is a label for its radio or checkbox, so the whole row is
           the hit target; the name is the option's own words and the rest of
           the row describes it. -->
      {#snippet optionRow(
        key: string,
        control: import("svelte").Snippet<
          [{ id: string; labelledby: string; describedby: string }]
        >,
        body: import("svelte").Snippet<[{ labelId: string; detailId: string }]>,
        onpointerdown?: () => void
      )}
        {@const id = `${questionLabelId}-option-${optionIdPart(key)}`}
        <Field.Label for={id} class={optionRowClass} data-option-key={key} {onpointerdown}>
          <!-- The name is the option's words plus its tag ("Eneo föreslår"). -->
          {@render control({
            id,
            // The tag ("Eneo föreslår", "Används i dag") exists only on those rows.
            labelledby:
              key === currentKey || key === recommendedKey
                ? `${id}-label ${id}-label-tag`
                : `${id}-label`,
            describedby: `${id}-detail`
          })}
          <span class="option-body">
            {@render body({ labelId: `${id}-label`, detailId: `${id}-detail` })}
          </span>
        </Field.Label>
      {/snippet}

      {#snippet presetBody(
        option: StructuredQuestionOption,
        optionKey: string,
        ids: { labelId: string; detailId: string }
      )}
        <span class="option-label-row">
          <span class="option-label" id={ids.labelId}>{option.label}</span>
          {#if optionKey === currentKey}
            <span class="option-current" id="{ids.labelId}-tag"
              >{m.ai_builder_question_in_use_today()}</span
            >
          {:else if optionKey === recommendedKey}
            <span class="option-recommendation" id="{ids.labelId}-tag"
              >{m.ai_builder_question_recommended()}</span
            >
          {/if}
        </span>
        <span class="contents" id={ids.detailId}>
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
      {/snippet}

      {#snippet customBody(ids: { labelId: string; detailId: string })}
        <span class="option-label" id={ids.labelId}>{m.ai_builder_question_custom()}</span>
        <span class="option-description" id={ids.detailId}>
          {m.ai_builder_question_custom_helper()}
        </span>
      {/snippet}

      {#snippet customInput()}
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
      {/snippet}

      {#if isSingle}
        <RadioGroup.Root
          class="border-dimmer flex flex-col gap-1.5 border-t px-2.5 pt-1.5 pb-2.5"
          bind:value={() => singleValue, selectSingle}
          {disabled}
          aria-labelledby={questionLabelId}
          aria-describedby="{questionLabelId}-keys"
        >
          {#each visibleOptions as option (getStructuredQuestionOptionKey(option))}
            {@const optionKey = getStructuredQuestionOptionKey(option)}
            {#snippet radio(ids: { id: string; labelledby: string; describedby: string })}
              <RadioGroup.Item
                value={optionKey}
                id={ids.id}
                class="mt-0.5"
                aria-labelledby={ids.labelledby}
                aria-describedby={ids.describedby}
              />
            {/snippet}
            {#snippet body(ids: { labelId: string; detailId: string })}
              {@render presetBody(option, optionKey, ids)}
            {/snippet}
            {@render optionRow(optionKey, radio, body)}
          {/each}
          {#if question.allow_custom}
            {#snippet customRadio(ids: { id: string; labelledby: string; describedby: string })}
              <RadioGroup.Item
                value={CUSTOM_RADIO_KEY}
                id={ids.id}
                class="mt-0.5"
                aria-labelledby={ids.labelledby}
                aria-describedby={ids.describedby}
                aria-expanded={customSelected}
                aria-controls={customSelected ? `${questionLabelId}-custom` : undefined}
              />
            {/snippet}
            {@render optionRow(
              CUSTOM_RADIO_KEY,
              customRadio,
              customBody,
              () => (customPointerSelect = true)
            )}
            {@render customInput()}
          {/if}
        </RadioGroup.Root>
      {:else}
        <div
          class="border-dimmer flex flex-col gap-1.5 border-t px-2.5 pt-1.5 pb-2.5"
          role="group"
          aria-labelledby={questionLabelId}
          aria-describedby="{questionLabelId}-keys"
        >
          {#each visibleOptions as option (getStructuredQuestionOptionKey(option))}
            {@const optionKey = getStructuredQuestionOptionKey(option)}
            {#snippet box(ids: { id: string; labelledby: string; describedby: string })}
              <Checkbox
                id={ids.id}
                class="mt-0.5"
                bind:checked={() => selectedOptionKeys.has(optionKey), () => selectOption(option)}
                {disabled}
                aria-labelledby={ids.labelledby}
                aria-describedby={ids.describedby}
              />
            {/snippet}
            {#snippet body(ids: { labelId: string; detailId: string })}
              {@render presetBody(option, optionKey, ids)}
            {/snippet}
            {@render optionRow(optionKey, box, body)}
          {/each}
          {#if question.allow_custom}
            {#snippet customBox(ids: { id: string; labelledby: string; describedby: string })}
              <Checkbox
                id={ids.id}
                class="mt-0.5"
                bind:checked={() => customSelected, toggleCustom}
                {disabled}
                aria-labelledby={ids.labelledby}
                aria-describedby={ids.describedby}
                aria-expanded={customSelected}
                aria-controls={customSelected ? `${questionLabelId}-custom` : undefined}
              />
            {/snippet}
            {@render optionRow(CUSTOM_RADIO_KEY, customBox, customBody)}
            {@render customInput()}
          {/if}
        </div>
      {/if}
    {/if}

    {#if sendBlockedReason !== null}
      <p id="{questionLabelId}-send-block" class="text-secondary px-4 text-sm" role="status">
        {sendBlockedReason}
      </p>
    {/if}

    <div class="actions-row">
      {#if canDelegate}
        <span class="delegate-block">
          <button
            type="button"
            class="delegate-action"
            disabled={submissionDisabled}
            onclick={() => {
              if (!submissionDisabled) ondelegate?.();
            }}
          >
            {m.ai_builder_question_delegate()}
          </button>
          <span class="delegate-note">{m.ai_builder_question_delegate_note()}</span>
        </span>
      {/if}
      <!-- Kept in the tab order while it is unavailable: a keyboard user has to
           be able to reach it and hear why it does not fire yet. -->
      <Button
        variant="default"
        class="ml-auto aria-disabled:cursor-default aria-disabled:opacity-50 max-sm:ml-0 max-sm:h-[44px] max-sm:w-full max-sm:text-sm"
        onclick={handleConfirm}
        aria-disabled={!canConfirm || submissionDisabled}
        aria-describedby={sendBlockedReason !== null
          ? `${questionLabelId}-send-block`
          : !canConfirm && !disabled
            ? `${questionLabelId}-confirm-hint`
            : undefined}
      >
        {confirmLabel}
      </Button>
      {#if !canConfirm && !submissionDisabled}
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
    animation: builder-screen-in var(--duration-fast) var(--ease-smooth-out);
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
    @apply font-semibold;
    font-size: var(--text-xs);
    line-height: var(--text-xs--line-height);
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

  .option-filter {
    @apply mx-4 mb-1 flex flex-col gap-1 font-medium;
    font-size: var(--text-xs);
    line-height: var(--text-xs--line-height);
    color: var(--text-secondary);
  }

  .option-filter-summary {
    @apply mx-4 mb-2;
    font-size: var(--text-xs);
    line-height: var(--text-xs--line-height);
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

  .option-label-row {
    @apply flex flex-wrap items-center gap-1.5;
  }

  .option-example {
    font-size: var(--text-xs);
    line-height: var(--text-xs--line-height);
    color: var(--text-secondary);
    opacity: 0.85;
  }

  .option-evidence {
    @apply mt-1.5 self-start border-l-2 pl-2.5 italic;
    font-size: var(--text-xs);
    line-height: var(--text-xs--line-height);
    border-color: oklch(from var(--accent-default) l c h / 0.35);
    color: var(--text-secondary);
  }

  .option-current {
    @apply inline-flex h-5 shrink-0 items-center rounded-full px-2 font-bold;
    font-size: var(--text-xs);
    line-height: var(--text-xs--line-height);
    letter-spacing: 0.03em;
    color: var(--positive-stronger);
    background: var(--positive-dimmer);
  }

  .option-recommendation {
    @apply inline-flex h-5 shrink-0 items-center rounded-full px-2 font-bold;
    font-size: var(--text-xs);
    line-height: var(--text-xs--line-height);
    letter-spacing: 0.03em;
    color: var(--accent-stronger);
    background: var(--accent-dimmer);
  }

  .delegate-block {
    @apply flex min-w-0 flex-col items-start gap-0.5;
  }

  .delegate-note {
    font-size: var(--text-xs);
    line-height: var(--text-xs--line-height);
    color: var(--text-secondary);
  }

  .delegate-action {
    @apply rounded text-left text-[0.8125rem] font-semibold;
    color: var(--accent-stronger);
  }

  .delegate-action:hover {
    @apply underline;
  }

  .delegate-action:focus-visible {
    outline: 2px solid var(--accent-stronger);
    outline-offset: 2px;
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
      font-size: var(--text-xs);
      line-height: var(--text-xs--line-height);
      color: var(--text-secondary);
    }

    .delegate-action {
      @apply h-10 w-full text-center;
    }

    /* One field per line: two columns leave no room for a label at 375 px. */
  }

  @media (prefers-reduced-motion: reduce) {
    .question-panel {
      animation: none;
    }
  }

  .understanding {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
    margin-bottom: 1rem;
    padding: 0.75rem 0.875rem;
    border: 1px solid var(--border-dimmer);
    border-radius: 0.5rem;
  }
  .understanding-title {
    font-size: 0.8125rem;
    font-weight: 600;
    color: var(--text-secondary);
  }
  .understanding-sentence {
    font-size: 0.9375rem;
    color: var(--text-primary);
  }
  .understanding-open {
    font-size: 0.8125rem;
    color: var(--text-secondary);
  }
</style>
