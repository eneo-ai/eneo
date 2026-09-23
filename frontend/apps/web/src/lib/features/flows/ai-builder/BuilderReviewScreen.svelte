<script lang="ts">
  import { BUILDER_COLUMN } from "./builderColumns";
  import type { Snippet } from "svelte";
  import { SvelteSet } from "svelte/reactivity";
  import { onDestroy, tick, untrack } from "svelte";
  import { m } from "$lib/paraglide/messages";
  import IconLoaderCircle from "@lucide/svelte/icons/loader-circle";
  import { getLocale } from "$lib/paraglide/runtime";
  import TokenUsageBadge from "$lib/features/flows/components/TokenUsageBadge.svelte";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Tabs from "$lib/components/ui/tabs/index.js";
  import IconChevronDown from "@lucide/svelte/icons/chevron-down";
  import IconAlertTriangle from "@lucide/svelte/icons/triangle-alert";
  import IconInfo from "@lucide/svelte/icons/info";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import BuilderApproveDialog, { type ApprovePhase } from "./BuilderApproveDialog.svelte";
  import BuilderChangeRequest from "./BuilderChangeRequest.svelte";
  import BuilderStepDetails, { type StepFieldChangeDisplay } from "./BuilderStepDetails.svelte";
  import BuilderStepNode from "./BuilderStepNode.svelte";
  import { Checkbox } from "$lib/components/ui/checkbox/index.js";
  import FlowAIBuilderDiagnosticCopyButton from "./FlowAIBuilderDiagnosticCopyButton.svelte";
  import { getAIBuilderService } from "./FlowAIBuilderService.svelte.ts";
  import { describeFailure, type FailureAction } from "./aiBuilderFailurePresentation";
  import { fieldTypeLabel } from "./aiBuilderSummaryText";
  import type {
    AIBuilderPlanEditContext,
    AIBuilderStatus,
    EditAdvisory,
    FlowDraftSpecCore,
    StepFieldChange,
    StepSpec
  } from "./protocol";
  import {
    AIBuilderIssueKind,
    buildAIBuilderDiagnosticReport,
    buildAIBuilderDiagnosticReportPlan,
    buildAIBuilderDiagnosticReportSession
  } from "./aiBuilderDiagnosticReport";
  import {
    getRemovedStepChanges,
    getReviewFocusStepIndex,
    getStepChangeKind,
    getStepFieldChanges
  } from "./flowAIBuilderPlanDiff";
  import { getRevisedStepRefs } from "./flowAIBuilderPlanRevisionDiff";
  import {
    getAIBuilderApplyPrerequisites,
    hasAIBuilderApplyBlocker
  } from "./flowAIBuilderApplyPrerequisites";
  import {
    buildAIBuilderTokenUsageView,
    formatAIBuilderTokenCount
  } from "./flowAIBuilderTokenUsage";
  import { outputModeUsesCompletionModel } from "$lib/features/flows/flowStepTypes";

  interface Props {
    onapplied?: (detail: { flow_id: string; focusStepIndex: number | null }) => void;
    /** The shell's composer route for a change request. This screen asks for
     *  changes in place, so the prop stays part of the contract but unused. */
    /** A generation attempt failed before a plan became available. */
    showGenerationFailure?: boolean;
    /** Open the composer, answers kept, so the user can reword the task. */
    onclarify?: () => void;
    /** The named fix is attaching a file; the conversation opens on that control. */
    onattachtemplate?: () => void;
    /** Narrow layouts: bring the conversation back into view. */
    onshowconversation?: () => void;
  }

  let {
    onapplied,
    showGenerationFailure = false,
    onshowconversation,
    onclarify,
    onattachtemplate
  }: Props = $props();

  const service = getAIBuilderService();
  const {
    state: { currentSpace }
  } = getSpacesManager();

  const isCreateMode = $derived(service.session?.target_kind === "create");
  // The server accepts a change request by leaving approval (status "chatting")
  // and only returns to it when a new plan lands. If that turn failed, the last
  // plan is still shown but cannot be approved until a change request succeeds.
  const planNotApprovable = $derived(
    service.currentPlan !== null &&
      !service.applyResult &&
      !service.canApprove &&
      !service.canApply &&
      // Eneo answering in prose is a reply, not a failure.
      service.latestReviewNote === null &&
      !service.isBusy &&
      !service.isRevisingPlan &&
      service.session?.status === "chatting"
  );
  const plan = $derived(service.currentPlan);
  const spec = $derived<FlowDraftSpecCore | null>(plan?.proposal.spec ?? null);
  const steps = $derived<StepSpec[]>(spec?.steps ?? []);
  const stepCount = $derived(steps.length);

  // ---- Plan identity: what changed since the plan the user was looking at ---

  let seenPlan: { sessionId: string; planKey: string; spec: FlowDraftSpecCore } | null = null;
  let previousSpec = $state<FlowDraftSpecCore | null>(null);
  let justUpdated = $state(false);

  $effect(() => {
    const currentPlan = service.currentPlan;
    const sessionId = service.session?.session_id ?? null;
    if (!sessionId) {
      seenPlan = null;
      previousSpec = null;
      justUpdated = false;
      return;
    }
    if (!currentPlan) return;
    const planKey = `${currentPlan.plan_id}:${currentPlan.updated_at ?? ""}:${currentPlan.spec_hash ?? ""}`;
    if (seenPlan === null || seenPlan.sessionId !== sessionId) {
      // A resumed draft's first plan is not an update the user just caused.
      justUpdated = false;
      previousSpec = null;
    } else if (seenPlan.planKey !== planKey) {
      justUpdated = true;
      previousSpec = seenPlan.spec;
    } else {
      return;
    }
    seenPlan = { sessionId, planKey, spec: currentPlan.proposal.spec };
  });

  // Create-mode plans carry no server diff, so the markers come from comparing
  // the replaced plan with the new one. Edit mode keeps the authored diff.
  const revisedStepRefs = $derived.by(() => {
    if (!isCreateMode || !justUpdated || !spec) return new Set<string>();
    return getRevisedStepRefs(previousSpec, spec);
  });

  function changeBadge(step: StepSpec): "new" | "updated" | null {
    if (isCreateMode) {
      return revisedStepRefs.has(step.plan_step_ref) ? "updated" : null;
    }
    const kind = getStepChangeKind(step, plan?.proposal.edit?.diff ?? null);
    if (kind === "added") return "new";
    if (kind === "modified") return "updated";
    return null;
  }

  const revisedStepCount = $derived(steps.filter((step) => changeBadge(step) !== null).length);

  // ---- Scoped step review (edit mode) --------------------------------------

  const scopedTargetExistingStepRef = $derived(
    plan?.proposal.edit?.scoped_target_existing_step_ref ?? null
  );
  const scopedTargetPlanStepRef = $derived(
    plan?.proposal.edit?.scoped_target_plan_step_ref ?? null
  );
  const isScopedStepReview = $derived(
    scopedTargetExistingStepRef !== null || scopedTargetPlanStepRef !== null
  );
  function isScopedTargetStep(step: StepSpec): boolean {
    return scopedTargetPlanStepRef
      ? step.plan_step_ref === scopedTargetPlanStepRef
      : step.existing_step_ref === scopedTargetExistingStepRef;
  }
  const activeStepScope = $derived(service.activeStepScope);

  const indexedSteps = $derived(steps.map((step, index) => ({ step, index })));

  const stepChangeCounts = $derived.by(() => {
    if (isCreateMode) return null;
    const counts = { added: 0, modified: 0, unchanged: 0, removed: removedStepChanges.length };
    for (const step of steps) {
      const kind = getStepChangeKind(step, plan?.proposal.edit?.diff ?? null);
      if (kind === "added") counts.added += 1;
      else if (kind === "modified") counts.modified += 1;
      else counts.unchanged += 1;
    }
    return counts;
  });
  let onlyChanges = $state(false);
  const visibleSteps = $derived(
    onlyChanges && !isCreateMode
      ? indexedSteps.filter(({ step }) => changeBadge(step) !== null)
      : indexedSteps
  );
  const detailSteps = $derived(
    isScopedStepReview
      ? [
          ...indexedSteps.filter(({ step }) => isScopedTargetStep(step)),
          ...indexedSteps.filter(({ step }) => !isScopedTargetStep(step))
        ]
      : indexedSteps
  );

  // ---- Steps view and per-step disclosure ----------------------------------

  type StepsView = "diagram" | "details";
  let stepsViewPreference = $state<{ planId: string; view: StepsView } | null>(null);
  const stepsView = $derived.by<StepsView>(() => {
    const planId = plan?.plan_id ?? null;
    if (planId && stepsViewPreference?.planId === planId) return stepsViewPreference.view;
    return isScopedStepReview ? "details" : "diagram";
  });
  function handleStepsViewChange(view: string): void {
    const planId = plan?.plan_id;
    if (!planId || (view !== "diagram" && view !== "details")) return;
    stepsViewPreference = { planId, view };
  }

  // Disclosure state belongs to a plan; a replacement plan starts closed, with
  // the server-scoped target step already open.
  const openStepRefs = new SvelteSet<string>();
  let openStepsPlanId: string | null = null;
  $effect(() => {
    const planId = plan?.plan_id ?? null;
    if (planId === openStepsPlanId) return;
    openStepsPlanId = planId;
    openStepRefs.clear();
    if (isScopedStepReview) {
      for (const step of steps) {
        if (isScopedTargetStep(step)) openStepRefs.add(step.plan_step_ref);
      }
      return;
    }
    // An edit's changed steps open on their own so the details view lands on
    // what the proposal does; unchanged steps stay folded for context.
    if (isCreateMode) return;
    for (const step of steps) {
      if (changeBadge(step) !== null) openStepRefs.add(step.plan_step_ref);
    }
  });

  function setStepOpen(step: StepSpec, open: boolean): void {
    if (open) openStepRefs.add(step.plan_step_ref);
    else openStepRefs.delete(step.plan_step_ref);
  }
  // Revealing a step is a handoff: the details view opens with that step
  // expanded, and focus and the reading position move to its heading.
  let detailsListEl = $state<HTMLOListElement | undefined>();
  async function revealStep(step: StepSpec): Promise<void> {
    const planId = plan?.plan_id;
    if (planId) stepsViewPreference = { planId, view: "details" };
    openStepRefs.add(step.plan_step_ref);
    await tick();
    const trigger = detailsListEl?.querySelector<HTMLElement>(
      `[data-plan-step-ref="${step.plan_step_ref}"] button`
    );
    trigger?.focus({ preventScroll: true });
    // Steps above it may still be animating open; scroll once the layout has settled.
    await Promise.all(
      (detailsListEl?.getAnimations?.({ subtree: true }) ?? []).map((animation) =>
        animation.finished.catch(() => undefined)
      )
    );
    trigger?.scrollIntoView?.({ block: "start" });
  }

  // ---- Step presentation ---------------------------------------------------

  function simpleTypeLabel(value: string): string {
    switch (value) {
      case "json":
        return m.flow_output_type_simple_structured();
      case "document":
        return m.flow_type_document();
      case "text":
        return m.flow_type_text();
      case "audio":
        return m.flow_type_audio();
      case "file":
        return m.flow_type_file();
      case "any":
        return m.flow_type_any();
      case "pdf":
        return m.flow_output_type_pdf();
      case "docx":
        return m.flow_output_type_docx();
      default:
        return value;
    }
  }

  function ioLabel(step: StepSpec): string {
    return m.ai_builder_node_io({
      input: simpleTypeLabel(step.input_type ?? "text"),
      output: simpleTypeLabel(step.output_type ?? "text")
    });
  }

  function modelLabel(step: StepSpec): string {
    if (step.output_mode === "transcribe_only") return m.ai_builder_step_transcription_model();
    if (!outputModeUsesCompletionModel(step.output_mode ?? "pass_through")) {
      return m.ai_builder_node_model_none();
    }
    return modelRefLabel(step.assistant_spec.model_ref);
  }

  function modelRefLabel(ref: string | null | undefined): string {
    if (!ref) return m.ai_builder_node_model_space_default();
    const known = service.availableModels.find((model) => model.id === ref);
    if (known) return known.name;
    // An unresolved plan-local reference still names the model; "model." is
    // protocol bookkeeping and reads as noise on the step chip.
    return ref.startsWith("model.") ? ref.slice("model.".length) : ref;
  }

  // What the proposal changes in a published step, in the words the rest of
  // the plan uses for the same values. Instructions keep their full text: the
  // details panel shows the previous wording behind a fold.
  const FIELD_CHANGE_LABELS: Record<StepFieldChange["field"], () => string> = {
    name: m.ai_builder_step_change_field_name,
    input_source: m.ai_builder_step_change_field_input_source,
    input_type: m.ai_builder_step_change_field_input_type,
    output_mode: m.ai_builder_step_change_field_output_mode,
    output_type: m.ai_builder_step_change_field_output_type,
    instructions: m.ai_builder_step_instructions,
    model_ref: m.ai_builder_step_change_field_model_ref,
    knowledge_refs: m.ai_builder_step_change_field_knowledge_refs,
    input_bindings: m.ai_builder_step_change_field_input_bindings,
    input_contract: m.ai_builder_step_change_field_input_contract,
    input_config: m.ai_builder_step_change_field_input_config,
    output_contract: m.ai_builder_step_change_field_output_contract,
    output_config: m.ai_builder_step_change_field_output_config,
    review_policy: m.flow_step_review_policy
  };
  const REVIEW_POLICY_LABELS: Record<string, () => string> = {
    view: m.flow_step_review_policy_view,
    edit: m.flow_step_review_policy_edit
  };
  const OUTPUT_MODE_LABELS: Record<string, () => string> = {
    pass_through: m.flow_output_mode_pass_through,
    compose_text: m.flow_output_mode_compose_text,
    render_verbatim: m.flow_output_mode_render_verbatim,
    template_fill: m.flow_output_mode_template_fill,
    transcribe_only: m.flow_output_mode_transcribe_only,
    speaker_mapping: m.flow_output_mode_speaker_mapping,
    http_post: m.flow_output_mode_http_post
  };
  const INPUT_SOURCE_LABELS: Record<string, () => string> = {
    flow_input: m.ai_builder_step_flow_input,
    previous_step: m.ai_builder_step_previous_step,
    all_previous_steps: m.ai_builder_step_all_previous
  };
  function fieldChangeValue(field: StepFieldChange["field"], value: string | null): string {
    if (field === "review_policy") {
      return value === null
        ? m.flow_step_review_policy_none()
        : (REVIEW_POLICY_LABELS[value]?.() ?? value);
    }
    if (value === null || value === "") return m.ai_builder_step_change_none();
    switch (field) {
      case "input_type":
      case "output_type":
        return simpleTypeLabel(value);
      case "output_mode":
        return OUTPUT_MODE_LABELS[value]?.() ?? value;
      case "input_source":
        return INPUT_SOURCE_LABELS[value]?.() ?? value;
      case "model_ref":
        return modelRefLabel(value);
      default:
        return value;
    }
  }
  function stepFieldChanges(step: StepSpec): StepFieldChangeDisplay[] {
    if (isCreateMode) return [];
    return getStepFieldChanges(step, plan?.proposal.edit?.diff ?? null).map((change) => ({
      field: change.field,
      label: FIELD_CHANGE_LABELS[change.field](),
      previous:
        change.field === "instructions"
          ? (change.previous ?? "")
          : fieldChangeValue(change.field, change.previous ?? null),
      current:
        change.field === "instructions"
          ? (change.current ?? "")
          : fieldChangeValue(change.field, change.current ?? null),
      previousDetail: change.previous_detail ?? null,
      currentDetail: change.current_detail ?? null
    }));
  }

  /**
   * The diagram chip's label. A mechanical step is a feature, not an
   * omission: the node says what the step does. The Details view keeps
   * modelLabel, whose value sits under a "Model" heading.
   */
  function nodeModelLabel(step: StepSpec): string {
    if (step.output_mode === "compose_text") return m.ai_builder_node_mode_compose_text();
    if (step.output_mode === "render_verbatim") return m.ai_builder_node_mode_render_verbatim();
    return modelLabel(step);
  }

  function artifactLabel(step: StepSpec): string | null {
    if (step.output_type === "pdf") return m.flow_output_type_pdf();
    if (step.output_type === "docx") return m.flow_output_type_docx();
    return null;
  }

  // Only these two contract facts mark a node; both come from the plan itself.
  function pausesForReview(step: StepSpec): boolean {
    return step.review_policy != null;
  }
  const mappedStepBounds = $derived(plan?.proposal.execution_shape.mapped_step_upper_bounds ?? []);
  const perFileStepRefs = $derived(new Set(mappedStepBounds.map((bound) => bound.plan_step_ref)));

  const reviewCheckpointSteps = $derived(indexedSteps.filter(({ step }) => pausesForReview(step)));

  const flowInputLabel = $derived.by(() => {
    const entry = steps.find((step) => step.input_source === "flow_input") ?? steps[0];
    return entry ? simpleTypeLabel(entry.input_type ?? "text") : null;
  });
  const flowOutputLabel = $derived.by(() => {
    const last = steps[steps.length - 1];
    return last ? simpleTypeLabel(last.output_type ?? "text") : null;
  });

  function resolveExecutionStepLabel(planStepRef: string): string | null {
    const stepIndex = steps.findIndex((step) => step.plan_step_ref === planStepRef);
    if (stepIndex === -1) return null;
    return `${stepIndex + 1}. ${steps[stepIndex].name}`;
  }
  function executionStepLabel(planStepRef: string): string {
    return resolveExecutionStepLabel(planStepRef) ?? planStepRef;
  }

  const tokenUsage = $derived(buildAIBuilderTokenUsageView(service.session?.telemetry));

  // ---- Disclosures ---------------------------------------------------------

  let whyOpen = $state(false);
  let limitsOpen = $state(false);
  let basisOpen = $state(false);

  const planAssumptions = $derived(plan?.proposal.assumptions ?? []);
  const attachments = $derived(service.session?.attachments ?? []);
  const attachmentWarnings = $derived(service.session?.attachment_warnings ?? []);
  const basisCount = $derived(planAssumptions.length + attachments.length);

  // ---- Edit-mode diff surfaces ---------------------------------------------

  const advisories = $derived<EditAdvisory[]>(plan?.proposal.edit?.advisories ?? []);
  const hasDescriptionAdvisory = $derived(
    advisories.some((a) => a.code === "flow_description_update_required")
  );
  const otherAdvisories = $derived(
    advisories.filter((a) => a.code !== "flow_description_update_required")
  );
  // The server writes advisory prose in English. The stable part of the contract
  // is the code, so a code we know is read in the reader's language and the
  // server's sentence is only the fallback for one we do not know yet.
  function advisoryText(advisory: EditAdvisory): string {
    switch (advisory.code) {
      case "flow_description_update_required":
        return m.ai_builder_advisory_flow_description_update_required();
      case "mapped_file_limit_exceeds_policy":
        return m.ai_builder_advisory_mapped_file_limit_exceeds_policy();
      default:
        return advisory.message;
    }
  }

  const descriptionDiff = $derived.by(() => {
    const change = plan?.proposal.edit?.diff?.flow_property_changes?.["flow_description"];
    if (!change) return null;
    return { previous: String(change[0] ?? ""), proposed: String(change[1] ?? "") };
  });
  const removedStepChanges = $derived(getRemovedStepChanges(plan?.proposal.edit?.diff ?? null));

  // One list of what the proposal changes, read before any step is: the
  // flow's name and description, each added or changed step in flow order,
  // the steps the proposal drops (they are not in the spec, so they have no
  // row elsewhere) and the runtime form fields. Everything comes from the
  // server's diff; an empty list is the honest "nothing changes".
  interface ChangeEntry {
    key: string;
    subject: string;
    what: string;
    /** The proposed step to reveal in the details view; null for a removed step or the description. */
    step: StepSpec | null;
  }
  function fieldsChangedSentence(labels: string[]): string {
    const locale = getLocale();
    const fields = new Intl.ListFormat(locale, { type: "conjunction" }).format(
      labels.map((label) => label.charAt(0).toLocaleLowerCase(locale) + label.slice(1))
    );
    const sentence = m.ai_builder_change_list_fields_changed({ fields });
    return sentence.charAt(0).toLocaleUpperCase(locale) + sentence.slice(1);
  }
  const changeList = $derived.by<ChangeEntry[] | null>(() => {
    if (isCreateMode || !plan?.proposal.edit) return null;
    const entries: ChangeEntry[] = [];
    const nameChange = plan.proposal.edit.diff?.flow_property_changes?.["flow_name"];
    if (nameChange) {
      entries.push({
        key: "flow_name",
        subject: m.ai_builder_change_list_name(),
        what: m.ai_builder_change_list_name_what({ name: String(nameChange[1] ?? "") }),
        step: null
      });
    }
    if (descriptionDiff) {
      entries.push({
        key: "flow_description",
        subject: m.ai_builder_change_list_description(),
        what: m.ai_builder_change_list_description_what(),
        step: null
      });
    }
    for (const { step, index } of indexedSteps) {
      const badge = changeBadge(step);
      if (badge === null) continue;
      const labels = stepFieldChanges(step).map((change) => change.label);
      entries.push({
        key: step.plan_step_ref,
        subject: m.ai_builder_change_request_scope({ step: index + 1, name: step.name }),
        what:
          badge === "new"
            ? m.ai_builder_change_list_new_step()
            : labels.length > 0
              ? fieldsChangedSentence(labels)
              : m.ai_builder_change_list_updated(),
        step
      });
    }
    for (const change of removedStepChanges) {
      entries.push({
        key: `removed:${change.step_ref ?? change.step_name}`,
        subject: change.step_name,
        what: m.ai_builder_change_list_removed(),
        step: null
      });
    }
    const formChanges = plan.proposal.edit.diff?.form_changes ?? [];
    if (formChanges.length > 0) {
      const count = (kind: (typeof formChanges)[number]["kind"]) =>
        String(formChanges.filter((change) => change.kind === kind).length);
      const parts = [
        formChanges.some((c) => c.kind === "added")
          ? m.ai_builder_change_list_form_added({ count: count("added") })
          : null,
        formChanges.some((c) => c.kind === "modified")
          ? m.ai_builder_change_list_form_modified({ count: count("modified") })
          : null,
        formChanges.some((c) => c.kind === "removed")
          ? m.ai_builder_change_list_form_removed({ count: count("removed") })
          : null
      ].filter((part) => part !== null);
      entries.push({
        key: "form_fields",
        subject: m.ai_builder_form_fields_title(),
        what: new Intl.ListFormat(getLocale(), { type: "conjunction" }).format(parts.map(String)),
        step: null
      });
    }
    return entries;
  });
  // The critic's warnings ask for a change; INFO entries are facts about the
  // flow as it already was (a pre-existing gap on a step this edit did not
  // touch) and must read as information, never as work to do.
  const planLintWarnings = $derived(
    (plan?.proposal.lint_warnings ?? []).filter((warning) => warning.severity !== "info")
  );
  const planFlowNotes = $derived(
    (plan?.proposal.lint_warnings ?? []).filter((warning) => warning.severity === "info")
  );
  // The lint message is the critic's repair instruction, written for the
  // model; the screen only ever shows its own calm copy for a note.
  const flowNoteCopy: Record<string, () => string> = {
    json_output_no_contract: () => m.ai_builder_flow_note_json_output_no_contract(),
    json_output_text_interpolation: () => m.ai_builder_flow_note_json_output_text_interpolation(),
    shadowed_form_field_bare_reference: () =>
      m.ai_builder_flow_note_shadowed_form_field_bare_reference(),
    unused_form_field: () => m.ai_builder_flow_note_unused_form_field(),
    vague_step_name: () => m.ai_builder_flow_note_vague_step_name()
  };
  const flowNoteText = (note: { code: string }): string =>
    (flowNoteCopy[note.code] ?? m.ai_builder_flow_note_generic)();

  // ---- Errors, conflicts, prerequisites ------------------------------------

  const isPublishedError = $derived(service.applyError?.code === "flow_is_published");
  const isUnpublishedApplyFailure = $derived(
    service.applyError?.code === "flow_unpublished_apply_failed"
  );
  const isGeneralApplyError = $derived(
    service.applyError !== null &&
      service.conflict === null &&
      !isPublishedError &&
      !isUnpublishedApplyFailure
  );
  const createFailed = $derived(isGeneralApplyError && isCreateMode);
  const createOutcomeUnknown = $derived(createFailed && service.createFailureOutcome === "unknown");
  const generalApplyErrorMessage = $derived.by(() => {
    if (!service.applyError) return "";
    if (service.applyError.code === "transcription_model_required") {
      return m.ai_builder_missing_transcription_model_description();
    }
    return service.applyError.message;
  });
  const publishedVersion = $derived(
    service.applyError?.code === "flow_is_published" &&
      typeof service.applyError.details.published_version === "number"
      ? service.applyError.details.published_version
      : null
  );

  const applyPrerequisites = $derived(
    getAIBuilderApplyPrerequisites({
      plan,
      targetKind: service.session?.target_kind,
      transcriptionModels: $currentSpace.transcription_models
    })
  );
  const isMissingSpaceTranscriptionModel = $derived(
    hasAIBuilderApplyBlocker(applyPrerequisites, "transcription_model_required")
  );
  const applyBlockedByPrerequisites = $derived(!applyPrerequisites.canApply);

  const diagnosticSession = $derived(buildAIBuilderDiagnosticReportSession(service.session));
  const diagnosticPlan = $derived(buildAIBuilderDiagnosticReportPlan(plan));
  const applyErrorDiagnosticReport = $derived(
    service.applyError
      ? buildAIBuilderDiagnosticReport({
          kind: "error",
          surface: "plan_apply",
          error: service.applyError,
          session: diagnosticSession,
          plan: diagnosticPlan
        })
      : null
  );
  const generationErrorDiagnosticReport = $derived(
    service.error
      ? buildAIBuilderDiagnosticReport({
          kind: "error",
          surface: "chat_stream",
          error: service.error,
          session: diagnosticSession,
          plan: diagnosticPlan
        })
      : null
  );
  const planQualityDiagnosticReport = $derived(
    plan && planLintWarnings.length > 0
      ? buildAIBuilderDiagnosticReport({
          kind: "quality",
          surface: "plan_quality",
          issue_kind: AIBuilderIssueKind.QualityWarning,
          session: diagnosticSession,
          plan: diagnosticPlan,
          details: {
            lint_warning_count: planLintWarnings.length,
            advisory_count: advisories.length
          }
        })
      : null
  );

  const conflictDescription = $derived.by(() => {
    switch (service.conflict?.kind) {
      case "send_in_progress":
        return m.ai_builder_conflict_send_in_progress();
      case "stale_plan":
        return m.ai_builder_conflict_stale_plan();
      default:
        return m.ai_builder_conflict_stale_revision();
    }
  });

  // One presentation owner names the failure the server actually reported
  // and the one best next step the driver allows; this screen renders it.
  const generationFailure = $derived(
    service.error
      ? describeFailure({
          error: service.error,
          latestTurn: service.latestTurn,
          capabilities: service.failureRecoveryCapabilities,
          context: {
            surface: "generation",
            targetKind: service.session?.target_kind ?? "create",
            offersStartFresh: false
          }
        })
      : null
  );
  const generationFailureBusy = $derived(service.isStreaming || service.isRecoveringLatestTurn);

  // The displayed failure is observed once, with the class the user saw; the
  // driver reuses the identity across rerenders and refreshes of the same one.
  $effect(() => {
    if (!showGenerationFailure) return;
    const error = service.error;
    const kind = untrack(() => generationFailure?.kind ?? null);
    if (!error || !kind) return;
    service.reportFailureDisplayed({ surface: "generation", presentedAs: kind }, error);
  });
  // An apply failure is shown by this screen's own cards.
  $effect(() => {
    const error = service.applyError;
    if (error) service.reportFailureDisplayed({ surface: "apply", presentedAs: null }, error);
  });

  // ---- Failure card motion ------------------------------------------------
  // One authored moment: the working state giving way to the card. The card
  // mounts closed, is painted once, then opens; it never replays for a
  // rerender of the same failure. There is no exit: work resuming simply
  // replaces it.
  let generationCardEl = $state<HTMLElement | undefined>();
  let generationCardOpened = $state(false);
  $effect(() => {
    const el = generationCardEl;
    if (!el) {
      generationCardOpened = false;
      return;
    }
    void el.offsetHeight;
    generationCardOpened = true;
  });

  function progressStatusLabel(status: AIBuilderStatus | null): string {
    if (status === "repairing") return m.ai_builder_status_repairing();
    if (status === "architecture_revised") return m.ai_builder_updating_plan();
    return service.hasSeenPlanInSession ? m.ai_builder_updating_plan() : m.ai_builder_generating();
  }

  // ---- Actions -------------------------------------------------------------

  const focusStepIndex = $derived.by(() => {
    if (!plan) return null;
    return getReviewFocusStepIndex(plan.proposal.spec.steps, plan.proposal.edit?.diff ?? null);
  });

  let approveDialogOpen = $state(false);
  let changeOpen = $state(false);
  let changeScope = $state<{ step: StepSpec; stepNumber: number } | null>(null);
  let changeRequestRef = $state<BuilderChangeRequest | undefined>();

  const changeScopeLabel = $derived(
    changeScope
      ? m.ai_builder_change_request_scope({
          step: changeScope.stepNumber,
          name: changeScope.step.name
        })
      : null
  );

  const isLocked = $derived(
    service.isBusy || service.isRevisingPlan || createOutcomeUnknown || service.conflict !== null
  );

  function scopeChangeToStep(step: StepSpec, stepNumber: number) {
    changeScope = { step, stepNumber };
    changeOpen = true;
    void changeRequestRef?.focusInput();
  }

  function editContextForChange(): AIBuilderPlanEditContext | null {
    if (!plan) return null;
    if (!changeScope) {
      return { kind: "proposed_plan", scope: "whole_plan", plan_id: plan.plan_id };
    }
    return {
      kind: "proposed_plan",
      scope: "step",
      plan_id: plan.plan_id,
      target_plan_step_ref: changeScope.step.plan_step_ref,
      target_existing_step_ref: changeScope.step.existing_step_ref,
      target_step_name: changeScope.step.name,
      target_step_number: changeScope.stepNumber
    };
  }

  function handleChangeSend(text: string) {
    const editContext = editContextForChange();
    if (!editContext) return;
    changeOpen = false;
    changeScope = null;
    void service.sendMessage(text, undefined, undefined, editContext);
  }

  // The created flow opens on its own page. A beat between "skapat" and the
  // navigation lets the reader see the success before the page changes.
  // Reading time is the same for everyone; only the drawing of the check
  // is subject to reduced motion, and CSS owns that.
  const OPEN_AFTER_CREATE_MS = 900;
  // Navigating on behalf of a screen the reader has already left would pull
  // them back; the beat is cancelled by unmount.
  let mounted = true;
  onDestroy(() => {
    mounted = false;
  });

  // The confirm dialog stays open as the progress surface: it shows the
  // request in flight, then the created moment, and the flow opens from
  // there. Only a failure closes it, and then the failure panel takes focus.
  const approvePhase = $derived<ApprovePhase>(
    isCreateMode
      ? service.applyResult
        ? "created"
        : service.isCreating
          ? "pending"
          : "idle"
      : service.pendingOperationKind === "applying"
        ? "pending"
        : "idle"
  );
  let createFailureEl = $state<HTMLDivElement | null>(null);
  // Where an edit-mode failure leaves the reader: the footer's status column,
  // whose live region narrates the rest.
  let footerStatusEl = $state<HTMLDivElement | null>(null);

  async function handlePrimaryAction() {
    if (isCreateMode) {
      try {
        const result = await service.createFlowFromPlan();
        await new Promise((resolve) => setTimeout(resolve, OPEN_AFTER_CREATE_MS));
        if (!mounted) return;
        // Closed here, not by navigation: a callback that does not leave the
        // screen must not leave a modal behind.
        approveDialogOpen = false;
        onapplied?.({ flow_id: result.flow_id, focusStepIndex });
      } catch {
        // Surfaced through service.applyError / service.createFailureOutcome.
        approveDialogOpen = false;
        await tick();
        createFailureEl?.focus({ preventScroll: true });
        createFailureEl?.scrollIntoView?.({ block: "nearest" });
      }
      return;
    }
    try {
      const result = await service.applyPlan();
      // The edit host stays mounted behind the Builder tab, so the dialog
      // must close itself before the screen hands over.
      approveDialogOpen = false;
      onapplied?.({ flow_id: result.flow_id, focusStepIndex });
    } catch {
      // Surfaced through service state.
      approveDialogOpen = false;
      await tick();
      footerStatusEl?.focus({ preventScroll: true });
    }
  }

  async function handleApprove() {
    try {
      await service.approvePlan();
    } catch {
      // Surfaced through service.applyError / service.conflict.
    }
  }

  async function handleUnpublishAndApply() {
    if (!window.confirm(m.ai_builder_published_flow_confirm())) return;
    try {
      const result = await service.unpublishAndApplyPlan();
      onapplied?.({ flow_id: result.flow_id, focusStepIndex });
    } catch {
      // Surfaced through service state.
    }
  }

  async function runGenerationFailureAction(action: FailureAction) {
    const error = service.error;
    if (!error) return;
    service.reportFailureAction(action.records, error);
    switch (action.kind) {
      case "retry_same_turn":
        await service.retryLatestTurn();
        return;
      case "retry_same_turn_acknowledged":
        await service.acknowledgeAndRetryLatestTurn();
        return;
      case "retry_new_turn":
        await service.resendLatestTurn();
        return;
      case "clarify":
        (onclarify ?? onshowconversation)?.();
        return;
      case "attach_template":
        (onattachtemplate ?? onclarify ?? onshowconversation)?.();
        return;
      case "refresh":
        await service.refreshSession();
        return;
      case "start_fresh":
      case "dismiss":
        // Never produced for the generation surface.
        return;
    }
  }
</script>

{#snippet disclosure(title: string, isOpen: boolean, toggle: () => void, body: Snippet)}
  <div class="border-dimmer border-t">
    <button
      type="button"
      class="hover:bg-secondary focus-visible:ring-accent-stronger flex w-full items-center gap-2 px-[1.375rem] py-3 text-left text-[0.84375rem] font-bold transition-colors focus-visible:ring-2 focus-visible:outline-none max-sm:px-3.5"
      aria-expanded={isOpen}
      onclick={toggle}
    >
      <span class="text-primary">{title}</span>
      <IconChevronDown
        class="text-secondary ml-auto size-3.5 shrink-0 ease-out motion-safe:transition-transform motion-safe:duration-(--duration-quick) motion-safe:ease-(--ease-smooth-out) {isOpen
          ? 'rotate-180'
          : ''}"
        aria-hidden="true"
      />
    </button>
    {#if isOpen}
      <div class="px-[1.375rem] pb-4 max-sm:px-3.5">{@render body()}</div>
    {/if}
  </div>
{/snippet}

{#snippet conflictCard()}
  <div class="border-warning-default/40 bg-warning-dimmer rounded-lg border p-3.5" role="status">
    <p class="text-warning-stronger text-[0.8125rem] font-semibold">
      {m.ai_builder_conflict_elsewhere_title()}
    </p>
    <p class="text-warning-stronger/80 mt-0.5 text-xs leading-relaxed text-pretty">
      {conflictDescription}
    </p>
    <div class="mt-3 flex flex-wrap gap-2">
      <Button size="sm" onclick={() => void service.recoverFromConflict()}>
        {m.ai_builder_conflict_refresh()}
      </Button>
      <Button
        variant="outline"
        size="sm"
        onclick={() => {
          service.dismissConflict();
          service.dismissPlanPane();
        }}
      >
        {m.ai_builder_conflict_start_over()}
      </Button>
      <FlowAIBuilderDiagnosticCopyButton report={applyErrorDiagnosticReport} size="sm" />
    </div>
  </div>
{/snippet}

{#if plan && spec}
  <div class="bg-secondary flex min-h-0 flex-1 flex-col">
    <!-- Bottom padding clears the sticky action bar so it never covers the
         change box or the last step. -->
    <div
      class="flex flex-1 justify-center px-7 pt-6 pb-28 max-lg:px-5 max-md:px-4 max-sm:pt-4 max-sm:pb-40"
    >
      <div class="w-full {BUILDER_COLUMN.review}">
        <!-- Turn receipts and blockers, above the plan they describe -->
        {#if justUpdated}
          <div
            class="border-accent-default/30 bg-accent-dimmer text-accent-stronger mb-3 flex flex-wrap items-baseline gap-2 rounded-[9px] border px-3.5 py-2.5 text-xs"
            role="status"
            aria-live="polite"
          >
            <span class="font-semibold">{m.ai_builder_plan_updated_announce()}</span>
            <span class="text-pretty">
              {revisedStepCount > 0
                ? m.ai_builder_plan_updated_detail({ count: revisedStepCount })
                : m.ai_builder_plan_updated_no_step_changes()}
            </span>
          </div>
        {/if}

        {#if service.latestReviewNote}
          <div
            class="border-default bg-secondary text-primary mb-3 flex flex-wrap items-baseline gap-2.5 rounded-[9px] border px-3.5 py-3 text-xs"
            role="status"
            aria-live="polite"
          >
            <span class="min-w-0 flex-1 leading-relaxed text-pretty">
              {service.latestReviewNote}
            </span>
            <Button
              variant="link"
              size="xs"
              class="text-accent-stronger ml-auto h-auto p-0 font-semibold whitespace-nowrap"
              onclick={() => service.dismissReviewNote()}
            >
              {m.ai_builder_review_note_acknowledge()}
            </Button>
          </div>
        {/if}

        {#if service.conflict}
          <div class="mb-3">{@render conflictCard()}</div>
        {/if}

        {#if attachmentWarnings.length > 0}
          <div
            class="border-warning-default/40 bg-warning-dimmer mb-3 rounded-[9px] border px-3.5 py-2.5"
            role="status"
            aria-live="polite"
          >
            <p class="text-warning-stronger text-[0.8125rem] font-semibold">
              {m.ai_builder_reference_material()}
            </p>
            <p class="text-warning-stronger/80 mt-0.5 text-xs leading-relaxed">
              {attachmentWarnings[0]}
            </p>
          </div>
        {/if}

        {#if isMissingSpaceTranscriptionModel}
          <div
            class="border-warning-default/40 bg-warning-dimmer mb-3 rounded-[9px] border px-3.5 py-2.5"
            role="status"
            aria-live="polite"
          >
            <p class="text-warning-stronger text-[0.8125rem] font-semibold">
              {m.ai_builder_missing_transcription_model_title()}
            </p>
            <p class="text-warning-stronger/80 mt-0.5 text-xs leading-relaxed text-pretty">
              {m.ai_builder_missing_transcription_model_description()}
            </p>
          </div>
        {/if}

        <!-- The plan document -->
        <article
          class="border-default bg-primary relative overflow-hidden rounded-xl border"
          aria-busy={service.isRevisingPlan}
          aria-labelledby="builder-plan-heading"
        >
          {#if service.isRevisingPlan}
            <div
              class="bg-primary/70 absolute inset-0 z-10 flex items-start justify-center pt-[5.625rem]"
            >
              <span
                class="border-default bg-primary text-primary inline-flex items-center rounded-full border px-3.5 py-2 text-xs font-semibold shadow-sm"
                role="status"
                aria-live="polite"
              >
                {m.ai_builder_revising_overlay()}
              </span>
            </div>
          {/if}

          <header class="px-[1.375rem] pt-5 pb-4 max-sm:px-3.5">
            <div class="flex items-start justify-between gap-3">
              <div class="flex flex-wrap items-center gap-2">
                <span
                  class="bg-accent-dimmer text-accent-stronger inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold"
                >
                  {isCreateMode ? m.ai_builder_draft_pill() : m.ai_builder_change_pill()}
                </span>
                <span class="text-secondary text-xs">
                  <!-- An edit said "the published version keeps running unchanged",
                       which is false for a draft that was never published. The pill
                       already says this is an unpublished proposal, the diff chips
                       say what changed, and the footer says nothing changes until
                       approval, so the header carries only the scale. -->
                  {isCreateMode
                    ? m.ai_builder_plan_meta_steps_nothing_created({ count: stepCount })
                    : m.ai_builder_plan_meta_steps_only({ count: stepCount })}
                </span>
              </div>
              {#if tokenUsage}
                <TokenUsageBadge
                  total={formatAIBuilderTokenCount(tokenUsage.total, getLocale())}
                  input={formatAIBuilderTokenCount(tokenUsage.prompt, getLocale())}
                  output={formatAIBuilderTokenCount(tokenUsage.completion, getLocale())}
                  note={tokenUsage.estimated
                    ? m.ai_builder_token_usage_estimated_note()
                    : m.ai_builder_token_usage_provider_note()}
                  estimated={tokenUsage.estimated}
                />
              {/if}
            </div>
            <h2
              id="builder-plan-heading"
              class="text-primary mt-2.5 text-[1.375rem] font-extrabold tracking-[-0.025em] text-pretty"
              tabindex="-1"
              data-builder-screen-heading
            >
              {isScopedStepReview && activeStepScope
                ? m.ai_builder_saved_step_plan_title({
                    step: activeStepScope.stepNumber,
                    name: activeStepScope.stepName
                  })
                : spec.flow_name}
            </h2>
            {#if isScopedStepReview && activeStepScope}
              <p class="text-secondary mt-1.5 max-w-[70ch] text-[0.9375rem] leading-relaxed">
                {m.ai_builder_saved_step_review_scope()}
              </p>
            {:else if spec.flow_description && !descriptionDiff && !hasDescriptionAdvisory}
              <p
                class="text-secondary mt-1.5 max-w-[70ch] text-[0.9375rem] leading-relaxed text-pretty"
              >
                {spec.flow_description}
              </p>
            {/if}
          </header>

          {#if changeList}
            <section
              class="border-dimmer border-t px-[1.375rem] py-4 max-sm:px-3.5"
              aria-labelledby="builder-change-list-heading"
              data-testid="edit-change-list"
            >
              <h3 id="builder-change-list-heading" class="text-primary text-[0.84375rem] font-bold">
                {m.ai_builder_change_list_title()}
              </h3>
              {#if changeList.length === 0}
                <p class="text-secondary mt-2 max-w-[72ch] text-[0.8125rem] leading-relaxed">
                  {m.ai_builder_change_list_none()}
                </p>
              {:else}
                <ol class="m-0 mt-1 flex list-none flex-col p-0">
                  {#each changeList as entry (entry.key)}
                    <li class="border-dimmer border-t text-[0.8125rem] first:border-t-0">
                      {#if entry.step}
                        {@const step = entry.step}
                        <!-- The row opens its step in the details view. -->
                        <button
                          type="button"
                          class="hover:bg-secondary focus-visible:ring-accent-stronger -mx-2 flex min-h-11 w-[calc(100%+1rem)] flex-wrap content-center items-baseline gap-x-3 gap-y-0.5 rounded-md px-2 py-2 text-left focus-visible:ring-2 focus-visible:outline-none"
                          onclick={() => void revealStep(step)}
                        >
                          <span class="text-primary font-semibold">{entry.subject}</span>
                          <span class="text-secondary min-w-0 flex-1 text-pretty">{entry.what}</span
                          >
                        </button>
                      {:else}
                        <div
                          class="flex min-h-11 flex-wrap content-center items-baseline gap-x-3 gap-y-0.5 py-2"
                        >
                          <span class="text-primary font-semibold">{entry.subject}</span>
                          <span class="text-secondary min-w-0 flex-1 text-pretty">{entry.what}</span
                          >
                        </div>
                      {/if}
                    </li>
                  {/each}
                </ol>
              {/if}
            </section>
          {/if}

          {#if descriptionDiff || hasDescriptionAdvisory}
            <section
              class="border-dimmer border-t px-[1.375rem] py-4 max-sm:px-3.5"
              aria-live="polite"
            >
              <h3 class="text-primary mb-2 text-[0.84375rem] font-bold">
                {m.ai_builder_description_diff_title()}
              </h3>
              {#if descriptionDiff}
                <p
                  class="text-secondary decoration-stronger text-[0.8125rem] leading-relaxed break-words line-through"
                  aria-label={m.ai_builder_description_current()}
                >
                  {descriptionDiff.previous}
                </p>
                <p
                  class="bg-secondary text-primary mt-2 rounded-md px-3 py-2 text-[0.8125rem] leading-relaxed break-words"
                  aria-label={m.ai_builder_description_proposed()}
                >
                  {descriptionDiff.proposed}
                </p>
              {:else}
                <p class="text-secondary text-[0.8125rem] leading-relaxed">
                  {m.ai_builder_advisory_flow_description_update_required()}
                </p>
                <Button
                  variant="outline"
                  size="sm"
                  class="mt-3"
                  disabled={isLocked}
                  onclick={() => void service.revisePlan("keep_current_description")}
                >
                  {m.ai_builder_description_keep_current()}
                </Button>
              {/if}
            </section>
          {/if}

          {#if plan.proposal.plan_rationale}
            {#snippet whyBody()}
              <p class="text-secondary max-w-[72ch] text-[0.8125rem] leading-relaxed text-pretty">
                {plan.proposal.plan_rationale}
              </p>
            {/snippet}
            {@render disclosure(
              isScopedStepReview ? m.ai_builder_why_this_change() : m.ai_builder_why_this_design(),
              whyOpen,
              () => (whyOpen = !whyOpen),
              whyBody
            )}
          {/if}

          {#snippet limitsBody()}
            <p class="text-secondary max-w-[72ch] text-[0.8125rem] leading-relaxed text-pretty">
              {m.ai_builder_execution_profile_description()}
            </p>
            <dl class="mt-3 flex flex-col">
              {#each [[m.ai_builder_execution_completion_model(), plan.proposal.execution_shape.completion_model_step_count], [m.ai_builder_execution_transcription_model(), plan.proposal.execution_shape.transcription_model_step_count], [m.ai_builder_execution_deterministic(), plan.proposal.execution_shape.deterministic_step_count], [m.ai_builder_execution_schema_constrained(), plan.proposal.execution_shape.schema_constrained_step_count]] as [label, value] (label)}
                <div class="border-dimmer flex items-baseline gap-4 border-t py-1.5">
                  <dt class="text-secondary text-[0.8125rem]">{label}</dt>
                  <dd class="text-primary ml-auto text-[0.8125rem] font-semibold tabular-nums">
                    {value}
                  </dd>
                </div>
              {/each}
            </dl>
            <h4 class="text-primary mt-4 text-[0.8125rem] font-bold">
              {m.ai_builder_execution_mapped_limits()}
            </h4>
            {#if mappedStepBounds.length > 0}
              <ul
                class="text-secondary mt-1.5 flex flex-col gap-1 text-[0.8125rem] leading-relaxed"
              >
                {#each mappedStepBounds as bound (bound.plan_step_ref)}
                  <li>
                    {bound.execution_mode === "per_source"
                      ? m.ai_builder_execution_per_source_limit({
                          step: executionStepLabel(bound.plan_step_ref),
                          count: bound.maximum_items
                        })
                      : m.ai_builder_execution_per_item_limit({
                          step: executionStepLabel(bound.plan_step_ref),
                          count: bound.maximum_items
                        })}
                  </li>
                {/each}
              </ul>
            {:else}
              <p class="text-secondary mt-1.5 text-[0.8125rem] leading-relaxed">
                {m.ai_builder_execution_no_mapped_steps()}
              </p>
            {/if}
          {/snippet}
          {@render disclosure(
            m.ai_builder_execution_profile(),
            limitsOpen,
            () => (limitsOpen = !limitsOpen),
            limitsBody
          )}

          {#if basisCount > 0}
            {#snippet basisBody()}
              <p class="text-secondary max-w-[72ch] text-[0.8125rem] leading-relaxed text-pretty">
                {m.ai_builder_plan_basis_description()}
              </p>
              {#if planAssumptions.length > 0}
                <ul class="m-0 flex list-none flex-col p-0">
                  {#each planAssumptions as assumption (assumption)}
                    <li
                      class="border-dimmer text-secondary border-t py-2 text-[0.8125rem] leading-relaxed text-pretty"
                    >
                      {assumption}
                    </li>
                  {/each}
                </ul>
              {/if}
              {#if attachments.length > 0}
                <h4 class="text-primary mt-3 text-[0.8125rem] font-bold">
                  {m.ai_builder_reference_material()}
                </h4>
                <ul class="m-0 flex list-none flex-col p-0">
                  {#each attachments as file (file.id)}
                    <li
                      class="border-dimmer text-secondary flex items-baseline gap-2 border-t py-2 text-[0.8125rem]"
                    >
                      <span class="min-w-0 flex-1 truncate">{file.name}</span>
                      <span class="shrink-0 font-mono text-xs tabular-nums">
                        {m.kb({ value: Math.max(1, Math.round(file.size / 1024)) })}
                      </span>
                    </li>
                  {/each}
                </ul>
              {/if}
            {/snippet}
            {@render disclosure(
              m.ai_builder_plan_basis({ count: basisCount }),
              basisOpen,
              () => (basisOpen = !basisOpen),
              basisBody
            )}
          {/if}

          {#if otherAdvisories.length > 0}
            <section
              class="border-dimmer border-t px-[1.375rem] py-4 max-sm:px-3.5"
              aria-live="polite"
            >
              <h3 class="text-primary mb-2 text-[0.84375rem] font-bold">
                {m.ai_builder_advisory_section_title()}
              </h3>
              <ul class="flex list-none flex-col gap-1.5 p-0">
                {#each otherAdvisories as advisory (advisory.code)}
                  <li
                    class="rounded-md px-3 py-2 text-[0.8125rem] leading-relaxed
                      {advisory.severity === 'warning'
                      ? 'bg-warning-dimmer text-warning-stronger'
                      : advisory.severity === 'error'
                        ? 'bg-negative-dimmer text-negative-stronger'
                        : 'bg-secondary text-secondary'}"
                  >
                    {advisoryText(advisory)}
                  </li>
                {/each}
              </ul>
            </section>
          {/if}

          {#if spec.form_fields && spec.form_fields.length > 0}
            <section class="border-dimmer border-t px-[1.375rem] py-4 max-sm:px-3.5">
              <h3 class="text-primary mb-2 text-[0.84375rem] font-bold">
                {m.ai_builder_form_fields_title()}
              </h3>
              <div class="grid gap-2.5 sm:grid-cols-2">
                {#each spec.form_fields as field (`${field.name}-${field.type}`)}
                  <div class="border-dimmer bg-secondary rounded-lg border p-3">
                    <div class="text-primary truncate text-[0.8125rem] font-semibold">
                      {field.label}
                    </div>
                    <div class="text-secondary mt-1 flex flex-wrap items-center gap-x-2 text-xs">
                      <span class="font-mono">{field.name}</span>
                      <span aria-hidden="true">·</span>
                      <span>{fieldTypeLabel(field.type)}</span>
                      <span aria-hidden="true">·</span>
                      <span>
                        {field.required === true
                          ? m.ai_builder_form_field_required()
                          : m.ai_builder_form_field_optional()}
                      </span>
                    </div>
                  </div>
                {/each}
              </div>
            </section>
          {/if}

          {#if planLintWarnings.length > 0}
            <section class="border-dimmer border-t px-[1.375rem] py-4 max-sm:px-3.5">
              <div class="mb-2 flex flex-wrap items-center justify-between gap-2">
                <h3
                  class="text-warning-stronger flex items-center gap-1.5 text-[0.84375rem] font-bold"
                >
                  <IconAlertTriangle class="size-3.5" aria-hidden="true" />
                  {m.ai_builder_quality_warnings()}
                </h3>
                <FlowAIBuilderDiagnosticCopyButton
                  report={planQualityDiagnosticReport}
                  variant="ghost"
                  size="xs"
                  class="text-warning-stronger hover:bg-warning-dimmer/80"
                />
              </div>
              <ul class="flex list-none flex-col gap-1.5 p-0">
                {#each planLintWarnings as warning (`${warning.step_ref ?? "flow"}-${warning.code}-${warning.message}`)}
                  <li
                    class="bg-warning-dimmer/60 text-warning-stronger rounded-md px-3 py-2 text-[0.8125rem] leading-relaxed"
                  >
                    {#if warning.step_ref}
                      <span class="font-semibold">{executionStepLabel(warning.step_ref)}</span>
                      <span class="text-warning-stronger/60 mx-1" aria-hidden="true">·</span>
                    {/if}
                    {warning.message}
                  </li>
                {/each}
              </ul>
            </section>
          {/if}

          {#if planFlowNotes.length > 0}
            <section class="border-dimmer border-t px-[1.375rem] py-4 max-sm:px-3.5">
              <h3 class="text-secondary flex items-center gap-1.5 text-[0.84375rem] font-bold">
                <IconInfo class="size-3.5" aria-hidden="true" />
                {m.ai_builder_flow_notes()}
              </h3>
              <ul class="mt-2 flex list-none flex-col gap-1.5 p-0">
                {#each planFlowNotes as note (`${note.step_ref ?? "flow"}-${note.code}-${note.message}`)}
                  <li class="text-secondary rounded-md px-3 py-2 text-[0.8125rem] leading-relaxed">
                    {#if note.step_ref}
                      <span class="text-primary font-semibold"
                        >{executionStepLabel(note.step_ref)}</span
                      >
                      <span class="text-secondary/60 mx-1" aria-hidden="true">·</span>
                    {/if}
                    {flowNoteText(note)}
                  </li>
                {/each}
              </ul>
            </section>
          {/if}

          <!-- How the flow works: the diagram, or a card per step -->
          <Tabs.Root value={stepsView} onValueChange={handleStepsViewChange}>
            <div
              class="border-dimmer flex flex-wrap items-center gap-2.5 border-t px-[1.375rem] pt-4 pb-1.5 max-sm:px-3.5"
            >
              <h3 class="text-primary text-[0.84375rem] font-bold">
                {isScopedStepReview
                  ? m.ai_builder_step_change_review_title()
                  : m.ai_builder_how_flow_works()}
              </h3>
              {#if stepChangeCounts}
                <!-- Byggspec §9: four counters, so the size of the change is
                     read before any step is. -->
                <ul class="flex list-none flex-wrap items-center gap-1.5 p-0">
                  {#each [{ key: "added", count: stepChangeCounts.added, tone: "bg-positive-default" }, { key: "modified", count: stepChangeCounts.modified, tone: "bg-accent-default" }, { key: "unchanged", count: stepChangeCounts.unchanged, tone: "bg-border-stronger" }, { key: "removed", count: stepChangeCounts.removed, tone: "bg-border-stronger" }] as counter (counter.key)}
                    {#if counter.count > 0}
                      <li
                        class="border-default bg-primary text-secondary inline-flex h-[1.625rem] items-center gap-1.5 rounded-full border px-2.5 text-xs"
                      >
                        <span
                          class="size-[0.4375rem] rounded-full {counter.tone}"
                          aria-hidden="true"
                        ></span>
                        {counter.key === "added"
                          ? m.ai_builder_diff_added({ count: String(counter.count) })
                          : counter.key === "modified"
                            ? m.ai_builder_diff_modified({ count: String(counter.count) })
                            : counter.key === "unchanged"
                              ? m.ai_builder_diff_unchanged({ count: String(counter.count) })
                              : m.ai_builder_diff_removed({ count: String(counter.count) })}
                      </li>
                    {/if}
                  {/each}
                </ul>
                {#if stepChangeCounts.unchanged > 0 && (stepChangeCounts.added > 0 || stepChangeCounts.modified > 0)}
                  <label
                    class="text-secondary flex min-h-7 cursor-pointer items-center gap-1.5 text-xs"
                  >
                    <Checkbox bind:checked={onlyChanges} />
                    {m.ai_builder_diff_only_changes()}
                  </label>
                {/if}
              {/if}
              <Tabs.List class="ml-auto h-9">
                <Tabs.Trigger value="diagram" class="px-3 py-1 text-xs">
                  {m.ai_builder_canvas_tab_diagram()}
                </Tabs.Trigger>
                <Tabs.Trigger value="details" class="px-3 py-1 text-xs">
                  {m.ai_builder_canvas_tab_details()}
                </Tabs.Trigger>
              </Tabs.List>
            </div>

            <Tabs.Content value="diagram" class="px-[1.375rem] pt-3 pb-[1.375rem] max-sm:px-3.5">
              {#if reviewCheckpointSteps.length > 0}
                <div
                  class="border-warning-default/40 bg-warning-dimmer text-warning-stronger mx-auto mb-3 flex max-w-[47.5rem] flex-wrap items-baseline gap-1.5 rounded-lg border px-3 py-2 text-xs"
                >
                  <span class="text-pretty">
                    {m.ai_builder_review_checkpoint_note({ count: reviewCheckpointSteps.length })}
                  </span>
                  {#each reviewCheckpointSteps as { step, index } (step.plan_step_ref)}
                    <button
                      type="button"
                      class="bg-warning-default/20 text-warning-stronger focus-visible:ring-warning-stronger inline-flex min-h-7 items-center rounded-full px-2 text-xs font-semibold focus-visible:ring-2 focus-visible:outline-none"
                      onclick={() => void revealStep(step)}
                    >
                      {m.ai_builder_step_label({ step: index + 1 })}
                    </button>
                  {/each}
                </div>
              {/if}

              <ol class="mx-auto my-0 flex max-w-[43.75rem] list-none flex-col p-0">
                {#if flowInputLabel}
                  <li
                    class="border-dimmer bg-secondary flex items-center gap-2.5 rounded-[9px] border px-3 py-2.5"
                  >
                    <span class="text-secondary text-xs font-bold tracking-[0.04em]">
                      {m.ai_builder_flow_in()}
                    </span>
                    <span class="text-primary text-[0.8125rem] font-semibold">
                      {m.ai_builder_flow_in_value({ type: flowInputLabel })}
                    </span>
                  </li>
                {/if}
                {#each visibleSteps as { step, index } (step.plan_step_ref)}
                  <li>
                    <div
                      class="border-stronger mx-auto h-3.5 w-px border-l"
                      aria-hidden="true"
                    ></div>
                    <BuilderStepNode
                      stepNumber={index + 1}
                      name={step.name}
                      ioLabel={ioLabel(step)}
                      modelLabel={nodeModelLabel(step)}
                      artifactLabel={artifactLabel(step)}
                      pausesForReview={pausesForReview(step)}
                      perFile={perFileStepRefs.has(step.plan_step_ref)}
                      changeBadge={!isCreateMode && changeBadge(step) === null
                        ? "unchanged"
                        : changeBadge(step)}
                      quiet={!isCreateMode && changeBadge(step) === null}
                    />
                  </li>
                {/each}
                {#if flowOutputLabel}
                  <li>
                    <div
                      class="border-stronger mx-auto h-3.5 w-px border-l"
                      aria-hidden="true"
                    ></div>
                    <div
                      class="border-dimmer bg-secondary flex items-center gap-2.5 rounded-[9px] border px-3 py-2.5"
                    >
                      <span class="text-secondary text-xs font-bold tracking-[0.04em]">
                        {m.ai_builder_flow_out()}
                      </span>
                      <span class="text-primary text-[0.8125rem] font-semibold">
                        {m.ai_builder_flow_out_value({ type: flowOutputLabel })}
                      </span>
                    </div>
                  </li>
                {/if}
              </ol>
            </Tabs.Content>

            <Tabs.Content value="details" class="px-[1.375rem] pt-3 pb-[1.375rem] max-sm:px-3.5">
              <ol bind:this={detailsListEl} class="my-0 flex list-none flex-col gap-2 p-0">
                {#each detailSteps as { step, index } (step.plan_step_ref)}
                  <li data-plan-step-ref={step.plan_step_ref}>
                    <BuilderStepDetails
                      {step}
                      stepNumber={index + 1}
                      open={openStepRefs.has(step.plan_step_ref)}
                      onopenchange={(open) => setStepOpen(step, open)}
                      ioLabel={ioLabel(step)}
                      modelLabel={modelLabel(step)}
                      changeBadge={changeBadge(step)}
                      fieldChanges={stepFieldChanges(step)}
                      pausesForReview={pausesForReview(step)}
                      perFile={perFileStepRefs.has(step.plan_step_ref)}
                      canRequestChange={plan.status === "proposed"}
                      resolveInputStepLabel={resolveExecutionStepLabel}
                      onrequestchange={() => scopeChangeToStep(step, index + 1)}
                      buildDiagnosticReport={() =>
                        buildAIBuilderDiagnosticReport({
                          kind: "quality",
                          surface: "step_quality",
                          issue_kind: AIBuilderIssueKind.Other,
                          session: diagnosticSession,
                          plan: diagnosticPlan,
                          step: {
                            plan_step_ref: step.plan_step_ref,
                            step_name: step.name,
                            step_number: index + 1,
                            input_type: step.input_type,
                            output_type: step.output_type
                          },
                          details: { actual_output_type: step.output_type }
                        })}
                    />
                  </li>
                {/each}
              </ol>
            </Tabs.Content>
          </Tabs.Root>
        </article>

        <!-- Ask for a change, in place -->
        <div class="mt-3.5">
          <BuilderChangeRequest
            bind:this={changeRequestRef}
            bind:open={changeOpen}
            scopeLabel={changeScopeLabel}
            disabled={isLocked || !service.canSendMessage}
            sendBlockedReason={service.modelSendBlockMessage}
            onclearscope={() => (changeScope = null)}
            onsend={handleChangeSend}
          />
        </div>

        {#if service.applyResult && !isCreateMode}
          <div
            class="border-positive-default/40 bg-positive-dimmer mt-3.5 flex items-start gap-3 rounded-[9px] border px-3.5 py-3"
            role="status"
            aria-live="polite"
          >
            <svg
              class="success-mark text-positive-stronger mt-px size-6 shrink-0"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
              aria-hidden="true"
            >
              <circle class="success-ring" cx="12" cy="12" r="10" />
              <path class="success-tick" d="m8 12.5 2.6 2.6L16 9.5" />
            </svg>
            <div class="min-w-0 flex-1">
              <p class="text-positive-stronger text-[0.8125rem] font-semibold">
                {m.ai_builder_applied_success_edit()}
              </p>
              <p class="text-positive-stronger/80 mt-0.5 text-xs leading-relaxed">
                {m.ai_builder_applied_counts({
                  created: service.applyResult.steps_created,
                  updated: service.applyResult.steps_updated,
                  removed: service.applyResult.steps_removed
                })}
              </p>
              {#if service.canContinueEditing}
                <Button
                  variant="outline"
                  size="sm"
                  class="mt-3"
                  onclick={() => void service.continueEditing()}
                >
                  {m.ai_builder_continue_editing()}
                </Button>
              {/if}
            </div>
          </div>
        {/if}

        {#if isPublishedError}
          <div
            class="border-warning-default/40 bg-warning-dimmer mt-3.5 rounded-[9px] border px-3.5 py-3"
            role="status"
            aria-live="polite"
          >
            <p class="text-warning-stronger text-[0.8125rem] font-semibold">
              {m.ai_builder_published_flow_title()}
            </p>
            <p class="text-warning-stronger/80 mt-0.5 text-xs leading-relaxed">
              {m.ai_builder_published_flow_description({ version: String(publishedVersion ?? "") })}
            </p>
            <div class="mt-2.5 flex flex-wrap gap-2">
              <Button size="sm" disabled={service.isBusy} onclick={handleUnpublishAndApply}>
                {service.pendingOperationKind === "unpublishing"
                  ? m.ai_builder_applying()
                  : m.ai_builder_published_flow_unpublish()}
              </Button>
              <Button variant="outline" size="sm" onclick={() => service.dismissApplyError()}>
                {m.ai_builder_dismiss()}
              </Button>
              <FlowAIBuilderDiagnosticCopyButton report={applyErrorDiagnosticReport} size="sm" />
            </div>
          </div>
        {/if}

        {#if isUnpublishedApplyFailure}
          <div
            class="border-warning-default/40 bg-warning-dimmer mt-3.5 rounded-[9px] border px-3.5 py-3"
            role="status"
            aria-live="polite"
          >
            <p class="text-warning-stronger text-[0.8125rem] font-semibold">
              {m.ai_builder_unpublished_apply_failed_title()}
            </p>
            <p class="text-warning-stronger/80 mt-0.5 text-xs leading-relaxed">
              {m.ai_builder_unpublished_apply_failed_description({
                message: service.applyError?.message ?? ""
              })}
            </p>
            <div class="mt-2.5 flex flex-wrap gap-2">
              <Button variant="outline" size="sm" onclick={() => service.dismissApplyError()}>
                {m.ai_builder_dismiss()}
              </Button>
              <FlowAIBuilderDiagnosticCopyButton report={applyErrorDiagnosticReport} size="sm" />
            </div>
          </div>
        {/if}

        {#if isGeneralApplyError && isCreateMode}
          <div
            bind:this={createFailureEl}
            class="border-warning-default/40 bg-warning-dimmer mt-3.5 rounded-[9px] border px-3.5 py-3"
            role="status"
            aria-live="polite"
            tabindex="-1"
          >
            <p class="text-warning-stronger text-[0.8125rem] font-semibold">
              {createOutcomeUnknown
                ? m.ai_builder_create_unknown_title()
                : m.ai_builder_create_failed_title()}
            </p>
            <p class="text-warning-stronger/80 mt-0.5 text-xs leading-relaxed text-pretty">
              {#if createOutcomeUnknown}
                {m.ai_builder_create_unknown_body()}
              {:else}
                {m.ai_builder_create_failed_body()}
                {m.ai_builder_create_failed_retry_note()}
              {/if}
            </p>
            {#if !createOutcomeUnknown}
              <p class="text-warning-stronger/80 mt-1 text-xs">{m.ai_builder_plan_unchanged()}</p>
            {/if}
            <div class="mt-2.5 flex flex-wrap gap-2">
              <FlowAIBuilderDiagnosticCopyButton report={applyErrorDiagnosticReport} size="sm" />
            </div>
          </div>
        {:else if isGeneralApplyError}
          <div
            class="border-warning-default/40 bg-warning-dimmer mt-3.5 rounded-[9px] border px-3.5 py-3"
            role="status"
            aria-live="polite"
          >
            <p class="text-warning-stronger text-[0.8125rem] font-semibold">
              {m.ai_builder_apply_failed_title()}
            </p>
            <p class="text-warning-stronger/80 mt-0.5 text-xs leading-relaxed">
              {m.ai_builder_apply_failed_description({ message: generalApplyErrorMessage })}
            </p>
            <div class="mt-2.5 flex flex-wrap gap-2">
              <Button variant="outline" size="sm" onclick={() => service.dismissApplyError()}>
                {m.ai_builder_dismiss()}
              </Button>
              <FlowAIBuilderDiagnosticCopyButton report={applyErrorDiagnosticReport} size="sm" />
            </div>
          </div>
        {/if}
      </div>
    </div>

    <!-- Nothing is created until this bar says so -->
    <div
      class="border-default bg-primary/95 sticky bottom-0 z-20 shrink-0 border-t px-7 py-3 pb-[calc(0.75rem+env(safe-area-inset-bottom))] backdrop-blur max-sm:px-3"
    >
      <div
        bind:this={footerStatusEl}
        tabindex="-1"
        class="mx-auto flex flex-wrap items-center gap-2.5 outline-none {BUILDER_COLUMN.review}"
      >
        {#if isCreateMode && service.applyResult}
          <!-- The one authored moment of the flow, in the bar the reader just
               used: the check draws itself, the line says what happened, and
               the page moves on. -->
          <div class="flex items-center gap-3" role="status" aria-live="polite">
            <svg
              class="success-mark text-positive-stronger size-6 shrink-0"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
              aria-hidden="true"
            >
              <circle class="success-ring" cx="12" cy="12" r="10" />
              <path class="success-tick" d="m8 12.5 2.6 2.6L16 9.5" />
            </svg>
            <div class="flex flex-col">
              <span class="text-primary text-[0.8125rem] font-semibold">
                {m.ai_builder_applied_success()}
              </span>
              <span class="text-secondary text-xs">{m.ai_builder_applied_opening()}</span>
            </div>
          </div>
        {:else}
          <div class="flex flex-col max-sm:w-full">
            <!-- An edit changes nothing until approved; applying it unpublishes a
                 published flow first (the backend rejects apply while published). -->
            <span class="text-secondary text-xs">
              {isCreateMode
                ? m.ai_builder_footer_steps_nothing_created({ count: stepCount })
                : m.ai_builder_footer_steps_nothing_changed({ count: stepCount })}
            </span>
            <span class="text-secondary text-xs text-pretty max-sm:hidden">
              {isCreateMode
                ? m.ai_builder_footer_draft_not_running()
                : m.ai_builder_footer_edit_unpublishes()}
            </span>
            {#if service.isRevisingPlan}
              <span
                class="text-accent-stronger text-xs font-semibold"
                role="status"
                aria-live="polite"
              >
                {m.ai_builder_footer_locked_while_revising()}
              </span>
            {:else if planNotApprovable}
              <!-- A change request left the session waiting for a plan that never
                 came; the shown plan is context, not something to approve. -->
              <span class="text-warning-stronger text-xs font-semibold" role="status">
                {m.ai_builder_footer_plan_needs_update()}
              </span>
            {/if}
          </div>
        {/if}
        <!-- On a phone the primary action sits on top, within thumb reach. -->
        <div class="ml-auto flex gap-2 max-sm:w-full max-sm:flex-col-reverse">
          {#if !service.applyResult}
            <Button
              variant="outline"
              size="sm"
              class="max-sm:min-h-11"
              disabled={isLocked}
              onclick={() => void service.changeRequirements()}
            >
              {m.ai_builder_modify()}
            </Button>
          {/if}

          {#if isCreateMode}
            {#if !service.applyResult && (service.canApprove || service.canApply || service.isCreating || createFailed)}
              <Button
                size="sm"
                class="max-sm:min-h-11"
                disabled={service.isBusy ||
                  service.isRevisingPlan ||
                  applyBlockedByPrerequisites ||
                  service.conflict !== null}
                onclick={() => (approveDialogOpen = true)}
              >
                {#if service.isCreating}
                  <IconLoaderCircle
                    class="size-3.5 animate-spin motion-reduce:animate-none"
                    aria-hidden="true"
                  />
                {/if}
                {service.isCreating
                  ? m.ai_builder_creating()
                  : createFailed
                    ? m.ai_builder_turn_retry()
                    : m.ai_builder_approve_create()}
              </Button>
            {/if}
          {:else}
            {#if service.canApprove || service.pendingOperationKind === "approving"}
              <Button
                size="sm"
                class="max-sm:min-h-11"
                disabled={isLocked}
                onclick={() => void handleApprove()}
              >
                {service.pendingOperationKind === "approving"
                  ? m.ai_builder_approving()
                  : m.ai_builder_approve()}
              </Button>
            {/if}
            {#if service.canApply || service.pendingOperationKind === "applying"}
              <Button
                size="sm"
                class="max-sm:min-h-11"
                disabled={isLocked || isPublishedError || applyBlockedByPrerequisites}
                onclick={() => (approveDialogOpen = true)}
              >
                {service.pendingOperationKind === "applying"
                  ? m.ai_builder_applying()
                  : m.ai_builder_apply()}
              </Button>
            {/if}
          {/if}
        </div>
      </div>
    </div>
  </div>

  <BuilderApproveDialog
    bind:open={approveDialogOpen}
    mode={isCreateMode ? "create" : "edit"}
    {stepCount}
    phase={approvePhase}
    onconfirm={() => void handlePrimaryAction()}
  />
{:else if service.conflict}
  <div
    class="bg-secondary flex flex-1 justify-center px-7 pt-6 pb-10 max-lg:px-5 max-md:px-4 max-sm:pt-4"
  >
    <div class="w-full max-w-[43.75rem]">{@render conflictCard()}</div>
  </div>
{:else if showGenerationFailure && generationFailure}
  <div
    class="bg-secondary flex flex-1 justify-center px-7 pt-6 pb-10 max-lg:px-5 max-md:px-4 max-sm:pt-4"
  >
    <div class="w-full {BUILDER_COLUMN.review}">
      <div
        bind:this={generationCardEl}
        class="t-panel-slide border-default bg-primary rounded-xl border p-6 max-sm:p-4"
        data-open={generationCardOpened}
        role="status"
        aria-live="polite"
      >
        <div class="flex items-start gap-3.5">
          <IconAlertTriangle
            class="text-warning-stronger mt-0.5 size-[1.125rem] shrink-0"
            aria-hidden="true"
          />
          <div class="max-w-[60ch] min-w-0">
            <h2
              class="text-primary text-[0.9375rem] leading-snug font-bold text-balance"
              tabindex="-1"
              data-builder-screen-heading
            >
              {generationFailure.heading}
            </h2>
            <p class="text-secondary mt-1.5 text-[0.8125rem] leading-relaxed text-pretty">
              {generationFailure.consequence}
            </p>
            <div class="mt-5 flex flex-wrap items-center gap-2">
              {#if generationFailure.primary}
                {@const primary = generationFailure.primary}
                <Button
                  size="sm"
                  disabled={generationFailureBusy}
                  onclick={() => void runGenerationFailureAction(primary)}
                >
                  {primary.label}
                </Button>
              {/if}
              {#if generationFailure.secondary}
                {@const secondary = generationFailure.secondary}
                <Button
                  variant="outline"
                  size="sm"
                  disabled={generationFailureBusy}
                  onclick={() => void runGenerationFailureAction(secondary)}
                >
                  {secondary.label}
                </Button>
              {/if}
            </div>
            <div class="mt-5 flex flex-wrap items-center gap-x-3 gap-y-1">
              {#if generationFailure.technical}
                {@const technical = generationFailure.technical}
                <p class="text-secondary text-xs leading-relaxed select-text">
                  <span>{m.ai_builder_failure_technical_code({ code: technical.code })}</span>
                  {#if technical.requestId}
                    <span aria-hidden="true"> · </span>
                    <span>
                      {m.ai_builder_failure_technical_request({ request: technical.requestId })}
                    </span>
                  {/if}
                </p>
              {/if}
              <FlowAIBuilderDiagnosticCopyButton
                report={generationErrorDiagnosticReport}
                variant="ghost"
                size="xs"
                onselect={() => {
                  if (service.error)
                    service.reportFailureAction("diagnostic_copied", service.error);
                }}
              />
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
{:else if service.statusMessage || service.isStreaming}
  <div class="bg-secondary flex flex-1 flex-col items-center justify-center px-4 py-10 text-center">
    <div class="progress-ring mb-4 size-10 rounded-full border-[3px]"></div>
    <p class="text-primary text-sm font-medium" role="status" aria-live="polite">
      {progressStatusLabel(service.statusMessage)}
    </p>
    <p class="text-secondary mt-1 max-w-[28ch] text-xs leading-relaxed text-pretty">
      {m.ai_builder_wait_expectation()}
    </p>
  </div>
{:else}
  <div class="bg-secondary flex flex-1 flex-col items-center justify-center px-4 py-10 text-center">
    <p class="text-secondary max-w-[32ch] text-sm leading-relaxed">{m.ai_builder_plan_empty()}</p>
  </div>
{/if}

<style lang="postcss">
  /* transitions-dev: panel reveal (07) for the failure card, the one authored
     moment of this screen. The tokens live in app.css. */
  .t-panel-slide {
    transform: translateY(var(--panel-translate-y));
    opacity: 0;
    filter: blur(var(--panel-blur));
    pointer-events: none;
    will-change: transform, opacity, filter;
  }
  .t-panel-slide[data-open="true"] {
    transform: translateY(0);
    opacity: 1;
    filter: blur(0);
    pointer-events: auto;
    transition:
      transform var(--panel-open-dur) var(--panel-ease),
      opacity var(--panel-open-dur) var(--panel-ease),
      filter var(--panel-open-dur) var(--panel-ease);
  }
  @media (prefers-reduced-motion: reduce) {
    .t-panel-slide {
      transition: none !important;
      transform: none !important;
      filter: none !important;
    }
  }

  .success-ring,
  .success-tick {
    stroke-dasharray: 64;
    stroke-dashoffset: 64;
    animation: success-draw var(--duration-very-slow) var(--ease-smooth-out) forwards;
  }
  .success-tick {
    stroke-dasharray: 16;
    stroke-dashoffset: 16;
    animation-delay: calc(var(--duration-very-slow) * 0.52);
  }
  @keyframes success-draw {
    to {
      stroke-dashoffset: 0;
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .success-ring,
    .success-tick {
      animation: none;
      stroke-dashoffset: 0;
    }
  }
  @reference "@eneo/ui/styles";

  .progress-ring {
    border-color: var(--border-default);
    border-top-color: var(--accent-default);
    animation: builder-spin 1s var(--ease-linear) infinite;
  }

  @keyframes builder-spin {
    from {
      transform: rotate(0deg);
    }
    to {
      transform: rotate(360deg);
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .progress-ring {
      animation: none;
    }
  }
</style>
