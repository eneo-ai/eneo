<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import { tick } from "svelte";
  import { SvelteMap, SvelteSet } from "svelte/reactivity";
  import { slide } from "svelte/transition";
  import { cubicOut } from "svelte/easing";
  import { prefersReducedMotion } from "$lib/core/prefersReducedMotion";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Skeleton } from "$lib/components/ui/skeleton/index.js";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu/index.js";
  import IconX from "@lucide/svelte/icons/x";
  import IconCornerDownRight from "@lucide/svelte/icons/corner-down-right";
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
    runtimeFields?: {
      label: string;
      type: string;
      required: boolean;
      purpose?: string | null;
      options?: string[];
    }[];
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
    editingAnsweredOptionIds?: string[] | null;
    editingAnsweredCustomValue?: string | null;
    /** What the user already answered with, so reopening edits those fields
     *  instead of replacing them with an empty form. */
    editingFields?: StructuredInputFieldAnswer[] | null;
    onanswer?: (payload: StructuredQuestionAnswerPayload) => void;
    oncanceledit?: () => void;
    onconfirm: () => void;
    /** A change request in the user's own words, optionally about one row; the
     *  server answers with a new requirements version, which re-arms this card. */
    onchange: (text: string, topic?: string | null) => void;
    /** The resulting full set of content-field ids (plus raw names for
     *  additions, optionally placed under a kept parent id); the server
     *  answers with a new requirements version, which re-arms this card
     *  like any change. */
    oneditcontentfields?: (
      fieldNames: string[],
      addedFieldPlacements?: Record<string, string>
    ) => void;
    oneditanswer: (questionId: string) => void;
    /** Reopen an assumption Eneo made: the server answers with its question. */
    onreopenassumption?: (questionId: string) => void;
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
    editingAnsweredOptionIds = null,
    editingAnsweredCustomValue = null,
    editingFields = null,
    onanswer,
    oncanceledit,
    onconfirm,
    onchange,
    oneditcontentfields,
    oneditanswer,
    onreopenassumption
  }: Props = $props();

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
  const USER_REQUEST_CLAMP_CHARS = 180;
  const USER_REQUEST_CLAMP_LINES = 5;
  const userRequestId = $derived(`builder-user-request-${summary.requirements_version}`);
  let userRequestExpanded = $state(false);
  const userRequestNeedsClamp = $derived(
    userRequest != null &&
      (userRequest.length > USER_REQUEST_CLAMP_CHARS ||
        userRequest.split(/\r?\n/).length > USER_REQUEST_CLAMP_LINES)
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
  // Simple by default, complete on demand: the chips answer "which fields",
  // this answers "and exactly what will they do", without a wall of detail on
  // a card whose job is to be readable.
  let runtimeFieldDetails = $state(false);
  let addingContentField = $state(false);
  let newContentField = $state("");
  /** Where a newly typed name is placed; null = the top level (design default). */
  let addTargetParentId = $state<string | null>(null);
  const addTargetLabel = $derived.by(() => {
    if (addTargetParentId === null) return m.ai_builder_requirements_place_top_level();
    const target = placementTargets.find((t) => t.parentId === addTargetParentId);
    return target ? target.path.join(" › ") : m.ai_builder_requirements_place_top_level();
  });
  let addContentFieldButton = $state<HTMLButtonElement | null>(null);

  async function cancelAddingContentField() {
    newContentField = "";
    addingContentField = false;
    await tick();
    addContentFieldButton?.focus();
  }
  const hasRuntimeFieldDetail = $derived(
    runtimeFields.some((field) => field.purpose || (field.options?.length ?? 0) > 0)
  );
  const shownRuntimeFields = $derived(
    allRuntimeFieldsShown ? runtimeFields : runtimeFields.slice(0, RUNTIME_FIELD_CHIP_CAP)
  );
  // Placement groups: what the user confirms IS the structure verification
  // later enforces, so children render under their parent, never mixed into
  // the flat list. Groups keep first-appearance order; unplaced names close
  // the section with their own honest label.
  type ContentFieldGroup = {
    key: string;
    /** Original-spelling parent path; empty means the top level. */
    path: string[];
    unplaced: boolean;
    fields: typeof namedContentFields;
  };
  // A payload from an older backend has no placement fields; those names
  // degrade to the flat top level instead of crashing the card.
  function placementOf(field: (typeof namedContentFields)[number]) {
    return { segments: field.segments ?? [], unplaced: field.unplaced ?? false };
  }

  const contentFieldGroups = $derived.by(() => {
    const groups = new SvelteMap<string, ContentFieldGroup>();
    for (const field of namedContentFields) {
      const { segments, unplaced } = placementOf(field);
      const key = unplaced ? "::unplaced" : segments.join("\u0000");
      let group = groups.get(key);
      if (!group) {
        group = { key, path: segments, unplaced, fields: [] };
        groups.set(key, group);
      }
      group.fields.push(field);
    }
    // Top level first, then nested groups in first-appearance order, unplaced last.
    return [...groups.values()].sort((a, b) => {
      const rank = (g: ContentFieldGroup) => (g.unplaced ? 2 : g.path.length === 0 ? 0 : 1);
      return rank(a) - rank(b);
    });
  });

  /** The field's own full path: its parent segments plus its raw name. */
  function fullPathOf(field: (typeof namedContentFields)[number]): string[] | null {
    const { segments, unplaced } = placementOf(field);
    // Without a raw name (older payload) the field cannot act as a parent.
    if (unplaced || !field.name) return null;
    return [...segments, field.name];
  }

  /** Attested descendants at any depth, keyed on raw identities. */
  function descendantsOf(field: (typeof namedContentFields)[number]) {
    const prefix = fullPathOf(field);
    if (prefix === null) return [];
    return namedContentFields.filter((other) => {
      const placement = placementOf(other);
      return (
        !placement.unplaced &&
        placement.segments.length >= prefix.length &&
        prefix.every((segment, index) => placement.segments[index] === segment)
      );
    });
  }

  /**
   * Grouped truncation: a collapsed card caps each group's chips, but a
   * container whose children render is never hidden — children must not
   * appear without their parent.
   */
  function visibleGroupFields(group: ContentFieldGroup) {
    if (allContentFieldsShown) return group.fields;
    // A container whose children render elsewhere is never truncated out,
    // at any depth — children must not float without their parent.
    const containers = group.fields.filter((field) => descendantsOf(field).length > 0);
    const rest = group.fields.filter((field) => descendantsOf(field).length === 0);
    return [
      ...containers,
      ...rest.slice(0, Math.max(CONTENT_FIELD_CHIP_CAP - containers.length, 0))
    ];
  }

  function removeContentField(field: (typeof namedContentFields)[number]) {
    if (!oneditcontentfields) return;
    // Removing a container removes its attested descendants with it —
    // explicitly, so the request states exactly what remains.
    const removedIds = new Set([field.id, ...descendantsOf(field).map((d) => d.id)]);
    oneditcontentfields(
      namedContentFields.filter((other) => !removedIds.has(other.id)).map((other) => other.id)
    );
    // The removed chip held focus; hand it to the group's successor.
    addContentFieldButton?.focus();
  }

  /** Every exact container a name can be placed under — childless ones
   *  included (an empty events[] is the central case), scalars never. */
  const placementTargets = $derived.by(() => {
    const targets: { parentId: string; path: string[] }[] = [];
    for (const field of namedContentFields) {
      const path = fullPathOf(field);
      if (path === null) continue;
      if (field.can_contain_fields || descendantsOf(field).length > 0) {
        targets.push({ parentId: field.id, path });
      }
    }
    return targets;
  });

  /** Resolve an unplaced name into a group: re-add the raw name at that path. */
  function placeUnplacedField(field: (typeof namedContentFields)[number], parentId: string) {
    if (!oneditcontentfields || !field.name) return;
    const kept = namedContentFields
      .filter((other) => other.id !== field.id)
      .map((other) => other.id);
    oneditcontentfields([...kept, field.name], { [field.name]: parentId });
  }
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
    if (type === "list") return m.flow_form_field_type_list();
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
  /** Defaults Eneo chose, each reopenable to its own question. */
  const assumptionRows = $derived(summary.assumption_rows ?? []);
  const assumptionCount = $derived(assumptionRows.length + assumptions.length);
  const firstAssumption = $derived(
    assumptionRows.length > 0
      ? `${assumptionRows[0].topic}: ${assumptionRows[0].label}`
      : (assumptions[0] ?? "")
  );
  const manualNotes = $derived(summary.manual_setup_notes ?? []);
  /** Every attachment as the server typed it; the role label is the client's. */
  const attachmentRows = $derived(summary.attachment_rows ?? []);
  const weakRoleIds = $derived(new Set(summary.weak_role_file_ids ?? []));
  const runPreview = $derived(summary.run_preview ?? null);
  const attachmentRoleLabel = (role: string): string => {
    switch (role) {
      case "runtime_input_sample":
        return m.ai_builder_attachment_role_runtime_input_sample();
      case "template":
        return m.ai_builder_attachment_role_template();
      case "reference_material":
        return m.ai_builder_attachment_role_reference_material();
      case "example_output":
        return m.ai_builder_attachment_role_example_output();
      default:
        return m.ai_builder_attachment_role_context_only();
    }
  };
</script>

<div
  class="flex min-h-full shrink-0 justify-center px-7 pt-6 pb-16 max-lg:px-5 max-md:px-4 max-sm:pt-4 max-sm:pb-12"
>
  <div class="confirm-screen my-auto w-full max-w-[43.75rem] 2xl:max-w-[48.125rem]">
    {#if unlistedAnswers.length > 0 && !readOnly}
      <div class="mb-4 flex flex-wrap items-center gap-2">
        <span class="text-secondary text-xs">{m.ai_builder_question_answers_label()}</span>
        {#each unlistedAnswers as item (item.questionId)}
          <Button
            variant="outline"
            size="sm"
            class="h-[1.875rem] max-w-full gap-1.5 rounded-full px-[0.6875rem] text-[0.78125rem] font-normal {editingQuestion
              ?.question?.question_id === item.questionId
              ? 'opacity-60'
              : ''}"
            title={item.question}
            aria-label={m.ai_builder_question_chip_aria({
              question: item.question,
              answer: item.answerLabel
            })}
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
          </Button>
        {/each}
      </div>
    {/if}

    {#if editingQuestion?.question}
      <div class="mb-4" bind:this={editorRef}>
        <p class="text-secondary mb-2 flex items-center gap-2 text-xs">
          {m.ai_builder_question_editing_note()}
          <Button
            variant="link"
            size="xs"
            class="text-accent-stronger h-auto p-0 font-semibold"
            onclick={() => oncanceledit?.()}
          >
            {m.cancel()}
          </Button>
        </p>
        {#key editingQuestion.question.question_id}
          <FlowAIBuilderQuestion
            question={editingQuestion.question}
            questionNumber={editingQuestionNumber}
            answeredFields={editingFields}
            answeredOptionIds={editingAnsweredOptionIds}
            answeredCustomValue={editingAnsweredCustomValue}
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
            <p
              id={userRequestId}
              class="text-primary mt-0.5 max-w-[72ch] text-[0.8125rem] leading-relaxed break-words whitespace-pre-wrap"
              class:line-clamp-5={userRequestNeedsClamp && !userRequestExpanded}
            >
              {userRequest}
            </p>
            {#if userRequestNeedsClamp}
              <button
                type="button"
                class="text-accent-stronger focus-visible:ring-accent-stronger/40 mt-1 -ml-2 inline-flex min-h-8 items-center gap-1 rounded-md px-2 text-xs font-semibold transition-colors hover:underline focus-visible:ring-2 focus-visible:outline-none max-sm:min-h-[44px]"
                aria-expanded={userRequestExpanded}
                aria-controls={userRequestId}
                onclick={() => (userRequestExpanded = !userRequestExpanded)}
              >
                {userRequestExpanded
                  ? m.ai_builder_requirements_hide_full_request()
                  : m.ai_builder_requirements_show_full_request()}
                <IconChevronDown
                  class="size-3.5 transition-transform duration-200 ease-out motion-reduce:duration-0 {userRequestExpanded
                    ? 'rotate-180'
                    : ''}"
                  aria-hidden="true"
                />
              </button>
            {/if}
          </section>
        {/if}

        {#if !savedFlowStepScope}
          <section class="mt-[1.125rem]">
            <h3 class="text-primary text-[0.8125rem] font-bold">
              {m.ai_builder_requirements_decisions_derived()}
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
                    <!-- The heading already says these are Eneo's reading of
                         the task, so only the rows the user settled themselves
                         say where they came from. -->
                    {#if settledBy && delegatedQuestionIds.has(settledBy)}
                      <span class="text-secondary mt-0.5 block text-xs font-normal">
                        {m.ai_builder_question_delegated_badge()}
                      </span>
                    {:else if settledBy}
                      <span class="text-secondary mt-0.5 block text-xs font-normal">
                        {m.ai_builder_requirements_answered()}
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
              {#if attachmentRows.length > 0}
                <div
                  class="border-dimmer grid gap-x-4 gap-y-0.5 border-t py-2.5 sm:grid-cols-[12.5rem_1fr]"
                >
                  <dt class="text-secondary text-[0.8125rem]">
                    {m.ai_builder_attachment_rows_title()}
                  </dt>
                  <dd class="text-primary text-[0.85rem]">
                    <ul class="flex flex-col gap-1.5" data-testid="attachment-rows">
                      {#each attachmentRows as row (row.file_id)}
                        <li class="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                          <span class="font-medium" title={row.filename}>{row.filename}</span>
                          <span class="text-secondary">{attachmentRoleLabel(row.role)}</span>
                          <span class="text-secondary">
                            · {row.travels
                              ? m.ai_builder_attachment_travels()
                              : m.ai_builder_attachment_not_carried()}
                          </span>
                          {#if row.placeholders && row.placeholders.length > 0}
                            <span class="text-secondary">
                              · {m.ai_builder_attachment_placeholders({
                                count: String(row.placeholders.length)
                              })}
                            </span>
                          {/if}
                          {#if !row.readable}
                            <span class="text-secondary"
                              >· {m.ai_builder_attachment_unreadable()}</span
                            >
                          {/if}
                          {#if weakRoleIds.has(row.file_id)}
                            <span class="text-warning-default text-[0.8rem] font-medium">
                              {m.ai_builder_attachment_role_unsure()}
                            </span>
                          {/if}
                        </li>
                      {/each}
                    </ul>
                  </dd>
                </div>
              {:else if attachments.length > 0}
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

        {#if runPreview}
          <section class="border-default mt-4 border-t pt-3.5" data-testid="run-preview">
            <h3 class="text-primary text-[0.8125rem] font-bold">
              {m.ai_builder_run_preview_title()}
            </h3>
            <p class="text-secondary mt-0.5 text-[0.8rem]">{m.ai_builder_run_preview_note()}</p>
            <dl class="mt-1.5 flex flex-col">
              {#if runPreview.runtime_input_label}
                <div class="grid gap-x-4 gap-y-0.5 py-1.5 sm:grid-cols-[12.5rem_1fr]">
                  <dt class="text-secondary text-[0.8125rem]">
                    {m.ai_builder_run_preview_input()}
                  </dt>
                  <dd class="text-primary text-[0.85rem] font-medium">
                    {runPreview.runtime_input_label}{#if runPreview.max_files}, {m.ai_builder_run_preview_max_files(
                        { count: String(runPreview.max_files) }
                      )}{/if}
                  </dd>
                </div>
              {/if}
              {#if runPreview.result_type_label}
                <div class="grid gap-x-4 gap-y-0.5 py-1.5 sm:grid-cols-[12.5rem_1fr]">
                  <dt class="text-secondary text-[0.8125rem]">
                    {m.ai_builder_run_preview_result()}
                  </dt>
                  <dd class="text-primary text-[0.85rem] font-medium">
                    {runPreview.result_type_label}{#if runPreview.report_layout_label}, {runPreview.report_layout_label}{/if}
                  </dd>
                </div>
              {/if}
              {#if (runPreview.required_sections ?? []).length > 0}
                <div class="grid gap-x-4 gap-y-0.5 py-1.5 sm:grid-cols-[12.5rem_1fr]">
                  <dt class="text-secondary text-[0.8125rem]">
                    {m.ai_builder_run_preview_sections()}
                  </dt>
                  <dd class="text-primary text-[0.85rem]">
                    {(runPreview.required_sections ?? []).join(", ")}
                  </dd>
                </div>
              {/if}
              {#if runPreview.template}
                <div class="grid gap-x-4 gap-y-0.5 py-1.5 sm:grid-cols-[12.5rem_1fr]">
                  <dt class="text-secondary text-[0.8125rem]">
                    {m.ai_builder_run_preview_template()}
                  </dt>
                  <dd class="text-primary text-[0.85rem] font-medium">
                    {runPreview.template.filename}, {m.ai_builder_attachment_placeholders({
                      count: String(runPreview.template.placeholder_count)
                    })}
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
              {#if hasRuntimeFieldDetail}
                <Button
                  variant="link"
                  size="xs"
                  class="text-accent-stronger ml-1 h-auto p-0 font-semibold"
                  aria-expanded={runtimeFieldDetails}
                  onclick={() => (runtimeFieldDetails = !runtimeFieldDetails)}
                >
                  {runtimeFieldDetails
                    ? m.ai_builder_requirements_fields_hide_detail()
                    : m.ai_builder_requirements_fields_show_detail()}
                </Button>
              {/if}
            </p>
            {#if runtimeFieldDetails}
              <dl
                class="border-dimmer mt-2 flex flex-col divide-y divide-[var(--border-dimmer)] border-t border-b"
                transition:slide={{ duration: reducedMotion ? 0 : 180, easing: cubicOut }}
              >
                {#each runtimeFields as field, detailIndex (detailIndex)}
                  <div class="grid gap-x-4 gap-y-0.5 py-2 sm:grid-cols-[12.5rem_1fr]">
                    <dt class="text-primary text-[0.8125rem] font-medium">{field.label}</dt>
                    <dd class="text-secondary text-[0.8125rem]">
                      {fieldTypeLabel(field.type)}{field.required
                        ? ` · ${m.ai_builder_requirements_field_required()}`
                        : ""}{field.purpose ? ` · ${field.purpose}` : ""}
                      {#if field.options?.length}
                        <span class="mt-0.5 block text-xs">
                          {m.ai_builder_requirements_field_options()}
                        </span>
                        <ul class="mt-1 flex list-none flex-wrap gap-1.5 p-0">
                          {#each field.options as option, optionIndex (optionIndex)}
                            <li
                              class="border-default text-secondary inline-flex h-[1.375rem] items-center rounded border px-1.5 text-[0.6875rem]"
                            >
                              {option}
                            </li>
                          {/each}
                        </ul>
                      {/if}
                    </dd>
                  </div>
                {/each}
              </dl>
            {:else}
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
                    <Button
                      variant="link"
                      size="xs"
                      class="text-accent-stronger h-[1.625rem] p-0 text-[0.78125rem] font-semibold"
                      onclick={() => (allRuntimeFieldsShown = true)}
                    >
                      {m.ai_builder_requirements_show_all_fields({
                        count: String(runtimeFields.length)
                      })}
                    </Button>
                  </li>
                {/if}
              </ul>
            {/if}
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
            {#snippet contentFieldChip(field: (typeof namedContentFields)[number])}
              {@const cascade = descendantsOf(field).length}
              <li
                class="border-default bg-secondary text-primary inline-flex h-[1.625rem] items-center gap-1 rounded-full border py-0 pr-1 pl-2.5 text-[0.78125rem]"
              >
                {field.label}
                {#if field.origin === "card_edit"}
                  <span class="text-secondary text-[0.6875rem]">
                    {m.ai_builder_requirements_field_added_by_you()}
                  </span>
                {/if}
                {#if !readOnly && !confirmed && oneditcontentfields && placementOf(field).unplaced && field.name && placementTargets.length > 0}
                  <DropdownMenu.Root>
                    <DropdownMenu.Trigger
                      class="hover:bg-hover-default text-secondary hover:text-primary inline-flex size-5 items-center justify-center rounded-full transition-colors"
                      aria-label={m.ai_builder_requirements_field_place({ field: field.label })}
                      title={m.ai_builder_requirements_field_place({ field: field.label })}
                      {disabled}
                    >
                      <IconCornerDownRight class="size-3" aria-hidden="true" />
                    </DropdownMenu.Trigger>
                    <DropdownMenu.Content align="start">
                      {#each placementTargets as target (target.parentId)}
                        <DropdownMenu.Item
                          onclick={() => placeUnplacedField(field, target.parentId)}
                        >
                          {target.path.join(" › ")}
                        </DropdownMenu.Item>
                      {/each}
                    </DropdownMenu.Content>
                  </DropdownMenu.Root>
                {/if}
                {#if !readOnly && !confirmed && oneditcontentfields}
                  <Button
                    variant="ghost"
                    size="icon-xs"
                    class="hover:bg-negative-dimmer/40 hover:text-negative-stronger text-secondary size-5 rounded-full"
                    aria-label={cascade > 0
                      ? m.ai_builder_requirements_field_remove_with_children({
                          field: field.label,
                          count: String(cascade)
                        })
                      : m.ai_builder_requirements_field_remove({ field: field.label })}
                    title={cascade > 0
                      ? m.ai_builder_requirements_field_remove_with_children({
                          field: field.label,
                          count: String(cascade)
                        })
                      : undefined}
                    {disabled}
                    onclick={() => removeContentField(field)}
                  >
                    <IconX class="size-3" aria-hidden="true" />
                  </Button>
                {/if}
              </li>
            {/snippet}

            {#each contentFieldGroups as group (group.key)}
              {#if group.path.length > 0 || group.unplaced}
                <p class="text-secondary mt-2 mb-1 text-[0.6875rem] font-medium">
                  {#if group.unplaced}
                    {m.ai_builder_requirements_group_unplaced()}
                  {:else}
                    {m.ai_builder_requirements_group_inside({
                      parent: group.path.join(" › ")
                    })}
                  {/if}
                </p>
              {/if}
              <ul
                class={group.path.length > 0 || group.unplaced
                  ? "border-default mt-0 ml-2 flex list-none flex-wrap gap-1.5 border-l pt-0.5 pb-0.5 pl-3"
                  : "mt-2 flex list-none flex-wrap gap-1.5 p-0"}
              >
                {#each visibleGroupFields(group) as field (field.id)}
                  {@render contentFieldChip(field)}
                {/each}
                {#if !allContentFieldsShown && visibleGroupFields(group).length < group.fields.length}
                  <li>
                    <Button
                      variant="link"
                      size="xs"
                      class="text-accent-stronger h-[1.625rem] p-0 text-[0.78125rem] font-semibold"
                      onclick={() => (allContentFieldsShown = true)}
                    >
                      {m.ai_builder_requirements_group_show_more({
                        count: String(group.fields.length - visibleGroupFields(group).length)
                      })}
                    </Button>
                  </li>
                {/if}
              </ul>
            {/each}
            <ul class="mt-1 flex list-none flex-wrap gap-1.5 p-0">
              {#if !readOnly && !confirmed && oneditcontentfields}
                <li>
                  {#if addingContentField}
                    <form
                      class="flex items-center gap-1.5"
                      onsubmit={(event) => {
                        event.preventDefault();
                        const name = newContentField.trim();
                        if (!name) return;
                        oneditcontentfields(
                          [...namedContentFields.map((f) => f.id), name],
                          addTargetParentId !== null ? { [name]: addTargetParentId } : undefined
                        );
                        newContentField = "";
                        addTargetParentId = null;
                        addingContentField = false;
                      }}
                    >
                      <!-- svelte-ignore a11y_autofocus -->
                      <input
                        class="border-default bg-primary h-[1.625rem] w-40 rounded-full border px-2.5 text-[0.78125rem]"
                        bind:value={newContentField}
                        aria-label={m.ai_builder_requirements_field_add()}
                        placeholder={m.ai_builder_requirements_field_add_placeholder()}
                        autofocus
                        {disabled}
                        onkeydown={(event) => {
                          if (event.key !== "Escape") return;
                          event.preventDefault();
                          void cancelAddingContentField();
                        }}
                      />
                      {#if placementTargets.length > 0}
                        <DropdownMenu.Root>
                          <DropdownMenu.Trigger
                            class="border-default text-secondary hover:text-primary inline-flex h-[1.625rem] max-w-40 items-center gap-1 truncate rounded-full border px-2.5 text-[0.78125rem]"
                            aria-label={m.ai_builder_requirements_place_label()}
                            title={m.ai_builder_requirements_place_label()}
                            {disabled}
                          >
                            <IconCornerDownRight class="size-3 shrink-0" aria-hidden="true" />
                            <span class="truncate">{addTargetLabel}</span>
                          </DropdownMenu.Trigger>
                          <DropdownMenu.Content align="start">
                            <DropdownMenu.Item onclick={() => (addTargetParentId = null)}>
                              {m.ai_builder_requirements_place_top_level()}
                            </DropdownMenu.Item>
                            {#each placementTargets as target (target.parentId)}
                              <DropdownMenu.Item
                                onclick={() => (addTargetParentId = target.parentId)}
                              >
                                {target.path.join(" › ")}
                              </DropdownMenu.Item>
                            {/each}
                          </DropdownMenu.Content>
                        </DropdownMenu.Root>
                      {/if}
                      <Button
                        type="submit"
                        size="sm"
                        disabled={disabled || !newContentField.trim()}
                      >
                        {m.ai_builder_requirements_field_add_confirm()}
                      </Button>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon-xs"
                        aria-label={m.cancel()}
                        title={m.cancel()}
                        {disabled}
                        onclick={() => void cancelAddingContentField()}
                      >
                        <IconX aria-hidden="true" />
                      </Button>
                    </form>
                  {:else}
                    <Button
                      variant="outline"
                      size="sm"
                      class="h-[1.625rem] rounded-full border-dashed px-2.5 text-[0.78125rem] font-normal"
                      bind:ref={addContentFieldButton}
                      {disabled}
                      onclick={() => (addingContentField = true)}
                    >
                      {m.ai_builder_requirements_field_add()}
                    </Button>
                  {/if}
                </li>
              {/if}
            </ul>
          </section>
        {/if}

        {#if assumptionCount > 0}
          <section class="border-default mt-4 border-t pt-3.5">
            <button
              type="button"
              class="text-primary flex min-h-[2.75rem] w-full items-center gap-1.5 text-left text-[0.8125rem] font-bold"
              aria-expanded={assumptionsOpen}
              onclick={() => (assumptionsOpen = !assumptionsOpen)}
            >
              {m.ai_builder_assumptions()} ({assumptionCount})
              <IconChevronDown
                class="text-secondary size-3.5 transition-transform {assumptionsOpen
                  ? 'rotate-180'
                  : ''}"
              />
            </button>
            {#if !assumptionsOpen}
              <p class="text-secondary mt-1 truncate text-[0.8125rem]">{firstAssumption}</p>
            {:else}
              <div
                class="mt-1.5"
                transition:slide={{ duration: reducedMotion ? 0 : 180, easing: cubicOut }}
              >
                <dl class="flex flex-col">
                  {#each assumptionRows as row (row.question_id)}
                    <div
                      class="border-dimmer grid items-baseline gap-x-4 gap-y-0.5 border-t py-2.5 sm:grid-cols-[12.5rem_1fr_auto]"
                    >
                      <dt class="text-secondary text-[0.8125rem]">{row.topic}</dt>
                      <dd class="text-primary text-[0.85rem] font-medium">{row.label}</dd>
                      {#if !readOnly && !confirmed && onreopenassumption}
                        <Button
                          variant="outline"
                          size="sm"
                          class="justify-self-start sm:justify-self-end"
                          aria-label={m.ai_builder_assumption_change_aria({
                            topic: row.topic,
                            label: row.label
                          })}
                          {disabled}
                          onclick={() => onreopenassumption(row.question_id)}
                        >
                          {m.ai_builder_question_change()}
                        </Button>
                      {/if}
                    </div>
                  {/each}
                </dl>
                {#if assumptions.length > 0}
                  <ul class="flex list-none flex-col p-0">
                    {#each assumptions as assumption (assumption)}
                      <li
                        class="border-dimmer text-secondary border-t py-2.5 text-[0.8125rem] leading-relaxed text-pretty"
                      >
                        {assumption}
                      </li>
                    {/each}
                  </ul>
                {/if}
              </div>
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
            <!-- Describing a change has one home: the composer bar right
                 below the card. A second button for it here read as two
                 different actions. -->
            <div class="ml-auto flex flex-wrap gap-2">
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
    animation: builder-screen-in 0.22s cubic-bezier(0.16, 1, 0.3, 1);
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
    .confirm-screen {
      animation: none;
    }
  }
</style>
