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
  import { answerPhrase, contractFieldCount, inSentence, readsLabel } from "./builderStepPhrases";
  import FlowAIBuilderDiagnosticCopyButton from "./FlowAIBuilderDiagnosticCopyButton.svelte";
  import { getAIBuilderService } from "./FlowAIBuilderService.svelte.ts";
  import { describeFailure, type FailureAction } from "./aiBuilderFailurePresentation";
  import { fieldTypeLabel } from "./aiBuilderSummaryText";
  import type {
    AIBuilderEditContext,
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
    /** Resolves once the host has shown the applied flow; the dialog waits for it. */
    onapplied?: (detail: {
      flow_id: string;
      focusStepIndex: number | null;
    }) => void | Promise<void>;
    /** The flow being edited is published: applying is refused until it is unpublished. */
    flowIsPublished?: boolean;
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
    flowIsPublished = false,
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

  let seenPlan: {
    sessionId: string;
    planId: string;
    planKey: string;
    stamped: boolean;
    spec: FlowDraftSpecCore;
  } | null = null;
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
    const stamped = Boolean(currentPlan.updated_at || currentPlan.spec_hash);
    if (seenPlan === null || seenPlan.sessionId !== sessionId) {
      // A resumed draft's first plan is not an update the user just caused.
      justUpdated = false;
      previousSpec = null;
    } else if (seenPlan.planKey === planKey) {
      return;
    } else if (seenPlan.planId === currentPlan.plan_id && !seenPlan.stamped) {
      // The streamed plan carries no server stamps; the session refresh that
      // fills them in is the same proposal, not an update.
    } else {
      justUpdated = true;
      previousSpec = seenPlan.spec;
    }
    seenPlan = {
      sessionId,
      planId: currentPlan.plan_id,
      planKey,
      stamped,
      spec: currentPlan.proposal.spec
    };
  });

  // Create-mode plans carry no server diff, so the markers come from comparing
  // the replaced plan with the new one. Edit mode keeps the authored diff.
  const revisedStepRefs = $derived.by(() => {
    if (!isCreateMode || !justUpdated || !spec) return new Set<string>();
    return getRevisedStepRefs(previousSpec, spec);
  });

  function changeBadge(step: StepSpec): "new" | "updated" | "changes" | null {
    if (isCreateMode) {
      return revisedStepRefs.has(step.plan_step_ref) ? "updated" : null;
    }
    const kind = getStepChangeKind(step, plan?.proposal.edit?.diff ?? null);
    if (kind === "added") return "new";
    if (kind === "modified") return "changes";
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
  const scopedTargetIndex = $derived(
    isScopedStepReview ? steps.findIndex((step) => isScopedTargetStep(step)) : -1
  );
  const scopedTargetStep = $derived(scopedTargetIndex >= 0 ? steps[scopedTargetIndex] : null);
  // The step a scoped review is about. While a plan is reworked it may come
  // back without its scope for a moment; the launch's scope holds the title.
  const scopedTitle = $derived.by(() => {
    if (activeStepScope && (isScopedStepReview || service.isRevisingPlan)) {
      return { step: activeStepScope.stepNumber, name: activeStepScope.stepName };
    }
    if (scopedTargetStep) return { step: scopedTargetIndex + 1, name: scopedTargetStep.name };
    return null;
  });
  function planStepNumber(planStepRef: string): number | null {
    const index = steps.findIndex((step) => step.plan_step_ref === planStepRef);
    return index === -1 ? null : index + 1;
  }

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
  const changedStepCount = $derived(
    stepChangeCounts
      ? stepChangeCounts.added + stepChangeCounts.modified + stepChangeCounts.removed
      : 0
  );
  // The dialog names a lone changed step instead of counting it.
  const changedStepLine = $derived.by(() => {
    if (changedStepCount !== 1 || (stepChangeCounts?.removed ?? 0) > 0) return null;
    const index = steps.findIndex((step) => changeBadge(step) !== null);
    if (index === -1) return null;
    const step = m.ai_builder_step_choice_item({ step: index + 1, name: steps[index].name });
    return changeBadge(steps[index]) === "new"
      ? m.ai_builder_approve_dialog_step_added({ step })
      : m.ai_builder_approve_dialog_step_changes({ step });
  });
  // Byggspec §9: four counters, so the size of the change is read before any
  // step is. Swedish inflects the adjective for one step ("1 ändrat").
  const diffCounters = $derived(
    stepChangeCounts
      ? [
          {
            key: "added",
            count: stepChangeCounts.added,
            tone: "bg-positive-default",
            one: m.ai_builder_diff_added_one,
            other: m.ai_builder_diff_added
          },
          {
            key: "modified",
            count: stepChangeCounts.modified,
            tone: "bg-accent-default",
            one: m.ai_builder_diff_modified_one,
            other: m.ai_builder_diff_modified
          },
          {
            key: "unchanged",
            count: stepChangeCounts.unchanged,
            tone: "bg-border-stronger",
            one: m.ai_builder_diff_unchanged_one,
            other: m.ai_builder_diff_unchanged
          },
          {
            key: "removed",
            count: stepChangeCounts.removed,
            tone: "bg-border-stronger",
            one: m.ai_builder_diff_removed_one,
            other: m.ai_builder_diff_removed
          }
        ].filter((counter) => counter.count > 0)
      : []
  );
  // The diagram always draws the whole chain (unchanged steps are quiet); the
  // details list shows what changes and folds the rest behind one row. A
  // scoped review's target is the featured card, so the list leaves it out.
  let showUnchanged = $state(false);
  let requestExpanded = $state(false);
  // A long flow reads like a long diff: the changed steps with one step of
  // context on each side (what feeds them, what reads them), and every other
  // run of unchanged steps folded into one row the reader can open.
  type DiagramRow =
    | { kind: "step"; step: StepSpec; index: number }
    | { kind: "gap"; key: string; first: number; last: number };
  const openGaps = new SvelteSet<string>();
  let diagramListEl = $state<HTMLOListElement | null>(null);
  // The button goes away with its row, so focus moves to the first step it showed.
  async function openGap(key: string, first: number) {
    openGaps.add(key);
    await tick();
    diagramListEl?.querySelector<HTMLElement>(`[data-diagram-step="${first}"]`)?.focus();
  }
  const diagramRows = $derived.by((): DiagramRow[] => {
    const all = indexedSteps.map(({ step, index }) => ({ kind: "step" as const, step, index }));
    const changed = all.filter(({ step }) => changeBadge(step) !== null).map(({ index }) => index);
    if (isCreateMode || changed.length === 0) return all;
    const context = new Set(changed.flatMap((index) => [index - 1, index, index + 1]));
    const rows: DiagramRow[] = [];
    let run: typeof all = [];
    const endRun = () => {
      const key = run[0]?.step.plan_step_ref;
      if (run.length >= 2 && !openGaps.has(key)) {
        rows.push({
          kind: "gap",
          key,
          first: run[0].index + 1,
          last: run[run.length - 1].index + 1
        });
      } else {
        rows.push(...run);
      }
      run = [];
    };
    for (const row of all) {
      if (context.has(row.index)) {
        endRun();
        rows.push(row);
      } else {
        run.push(row);
      }
    }
    endRun();
    return rows;
  });
  const listableSteps = $derived(
    isScopedStepReview ? indexedSteps.filter(({ step }) => !isScopedTargetStep(step)) : indexedSteps
  );
  const hiddenUnchangedSteps = $derived(
    isCreateMode || showUnchanged
      ? []
      : listableSteps.filter(({ step }) => changeBadge(step) === null)
  );
  const detailSteps = $derived(
    hiddenUnchangedSteps.length === 0
      ? listableSteps
      : listableSteps.filter(({ step }) => changeBadge(step) !== null)
  );
  const unchangedStepCountInList = $derived(
    isCreateMode ? 0 : listableSteps.filter(({ step }) => changeBadge(step) === null).length
  );

  // ---- Steps view and per-step disclosure ----------------------------------

  type StepsView = "diagram" | "details";
  let stepsViewPreference = $state<{ planId: string; view: StepsView } | null>(null);
  const stepsView = $derived.by<StepsView>(() => {
    const planId = plan?.plan_id ?? null;
    if (planId && stepsViewPreference?.planId === planId) return stepsViewPreference.view;
    // A scoped review shows its step in the featured card; the flow card
    // opens on the overview.
    return "diagram";
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
    // A scoped review's target is the featured card, open by definition.
    if (isScopedStepReview) return;
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
  let featuredEl = $state<HTMLElement | undefined>();
  async function revealStep(step: StepSpec): Promise<void> {
    if (isScopedStepReview && isScopedTargetStep(step)) {
      featuredEl?.focus({ preventScroll: true });
      featuredEl?.scrollIntoView?.({ block: "start" });
      return;
    }
    if (!isCreateMode && changeBadge(step) === null) showUnchanged = true;
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
      previousValue: change.previous ?? null,
      currentValue: change.current ?? null,
      previousDetail: change.previous_detail ?? null,
      currentDetail: change.current_detail ?? null
    }));
  }

  /** The diagram line under a step's name: what it reads and what it answers with. */
  function nodeDetail(step: StepSpec, stepNumber: number): string {
    return m.ai_builder_node_reads_answers({
      reads: inSentence(readsLabel(step, stepNumber, planStepNumber), getLocale()),
      answer: answerPhrase(step.output_type, contractFieldCount(step.output_contract))
    });
  }

  /**
   * A mechanical step is a feature, not an omission: the node says what the
   * step does. AI steps name no model here; the Details view keeps it.
   */
  function nodeModeLabel(step: StepSpec): string | null {
    if (step.output_mode === "compose_text") return m.ai_builder_node_mode_compose_text();
    if (step.output_mode === "render_verbatim") return m.ai_builder_node_mode_render_verbatim();
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
  // Only a request long enough to be cut is clamped, and then always with the
  // control that opens it: nothing of what the reader asked for hides silently.
  const requestIsLong = $derived.by(() => {
    const request = service.latestUserRequest ?? "";
    return request.length > 240 || request.split("\n").length > 6;
  });
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
  // What applying did or why it stopped, said at the end of the main column.
  const hasApplyOutcome = $derived(
    (service.applyResult !== null && !isCreateMode) ||
      isPublishedError ||
      isUnpublishedApplyFailure ||
      isGeneralApplyError
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
  let chosenChangeScope = $state<{ step: StepSpec; stepNumber: number } | null>(null);
  // A one-step review keeps its follow-ups on that step: the box starts
  // scoped to it, and clearing the chip is how the reader widens it.
  let scopeWidened = $state(false);
  const changeScope = $derived(
    chosenChangeScope ??
      (scopedTargetStep && !scopeWidened
        ? { step: scopedTargetStep, stepNumber: scopedTargetIndex + 1 }
        : null)
  );
  let changeRequestRef = $state<BuilderChangeRequest | undefined>();

  const changeScopeLabel = $derived(
    changeScope
      ? m.ai_builder_change_request_scope({
          step: changeScope.stepNumber,
          name: changeScope.step.name
        })
      : null
  );
  // A failure repair keeps its step whatever the reader does: the backend
  // refuses a wider request there, so its chip cannot be cleared.
  const scopeLocked = $derived(service.activeStepScopeLocked);
  function clearChangeScope() {
    if (scopeLocked) return;
    chosenChangeScope = null;
    scopeWidened = true;
  }

  const isLocked = $derived(
    service.isBusy || service.isRevisingPlan || createOutcomeUnknown || service.conflict !== null
  );

  function scopeChangeToStep(step: StepSpec, stepNumber: number) {
    chosenChangeScope = { step, stepNumber };
    changeOpen = true;
    void changeRequestRef?.focusInput();
  }

  function editContextForChange(): AIBuilderEditContext | null {
    if (!plan) return null;
    if (!changeScope) {
      // A locked repair never widens: it sends the scope it holds.
      if (scopeLocked) return service.activeStepTransportContext;
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
    chosenChangeScope = null;
    scopeWidened = false;
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

  // Set from the applied result until the host has shown the updated flow, so
  // the reader never sees this screen's applied state flash past.
  let handingOver = $state(false);
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
      : service.pendingOperationKind === "approving" ||
          service.pendingOperationKind === "applying" ||
          handingOver
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
      // One confirmation for the reader. The server keeps approve and apply as
      // two audited steps for edits (its atomic create path refuses edit
      // plans), so the dialog runs both; an approved plan whose apply failed
      // goes straight to apply.
      if (service.canApprove) await service.approvePlan();
      const result = await service.applyPlan();
      handingOver = true;
      await onapplied?.({ flow_id: result.flow_id, focusStepIndex });
      // The edit host stays mounted behind the Builder tab, so the dialog
      // closes itself once the updated flow is on screen.
      approveDialogOpen = false;
    } catch {
      // Surfaced through service state.
      approveDialogOpen = false;
      await tick();
      footerStatusEl?.focus({ preventScroll: true });
    } finally {
      handingOver = false;
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
  <div>
    <button
      type="button"
      class="hover:bg-secondary focus-visible:ring-accent-stronger flex w-full items-center gap-2 px-5 py-3.5 text-left text-[0.84375rem] font-bold transition-colors focus-visible:ring-2 focus-visible:outline-none focus-visible:ring-inset max-sm:px-4"
      aria-expanded={isOpen}
      onclick={toggle}
    >
      <span class="text-primary">{title}</span>
      <IconChevronDown
        class="text-secondary ml-auto size-3.5 shrink-0 motion-safe:transition-transform motion-safe:duration-(--duration-fast) motion-safe:ease-(--ease-smooth-out) {isOpen
          ? 'rotate-180'
          : ''}"
        aria-hidden="true"
      />
    </button>
    {#if isOpen}
      <div class="px-5 pb-5 max-sm:px-4">{@render body()}</div>
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

        <!-- One sheet: the heading spans it, the change leads the main column
             and what it rests on sits beside it, divided by hairlines rather
             than split into cards. -->
        <div class="border-default bg-primary @container rounded-xl border">
          <header class="flex items-start gap-4 px-6 pt-5 pb-4 max-sm:px-4">
            <div class="min-w-0 flex-1">
              <h2
                id="builder-plan-heading"
                class="text-primary text-[1.375rem] font-extrabold tracking-[-0.025em] text-pretty"
                tabindex="-1"
                data-builder-screen-heading
              >
                {scopedTitle
                  ? m.ai_builder_saved_step_plan_title({
                      step: scopedTitle.step,
                      name: scopedTitle.name
                    })
                  : spec.flow_name}
              </h2>
              {#if scopedTitle}
                <p class="text-secondary mt-1 max-w-[70ch] text-[0.9375rem] leading-relaxed">
                  {m.ai_builder_saved_step_review_scope()}
                </p>
              {:else}
                <!-- The status and the scale follow the title instead of sitting
                     above it. An edit said "the published version keeps running
                     unchanged", which is false for a draft that was never
                     published; the footer says nothing changes until approval. -->
                <p class="text-secondary mt-1 text-[0.8125rem]">
                  {isCreateMode ? m.ai_builder_draft_pill() : m.ai_builder_change_pill()}
                  <span aria-hidden="true">·</span>
                  {isCreateMode
                    ? m.ai_builder_plan_meta_steps_nothing_created({ count: stepCount })
                    : m.ai_builder_plan_meta_steps_only({ count: stepCount })}
                </p>
                {#if spec.flow_description && !descriptionDiff && !hasDescriptionAdvisory}
                  <p
                    class="text-secondary mt-2 max-w-[70ch] text-[0.9375rem] leading-relaxed text-pretty"
                  >
                    {spec.flow_description}
                  </p>
                {/if}
              {/if}
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
          </header>
          <div
            class="border-default grid border-t @min-[60rem]:grid-cols-[minmax(0,1fr)_20rem] @min-[80rem]:grid-cols-[minmax(0,1fr)_24rem]"
          >
            <div class="relative min-w-0" aria-busy={service.isRevisingPlan}>
              {#if service.isRevisingPlan}
                <div
                  class="bg-primary/70 absolute inset-0 z-10 flex items-start justify-center pt-16"
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
              <div class="divide-dimmer flex flex-col divide-y">
                {#if scopedTargetStep}
                  <!-- The step this review is about, leading the page. -->
                  <section
                    bind:this={featuredEl}
                    tabindex="-1"
                    class="px-6 pt-5 pb-6 outline-none max-sm:px-4"
                    aria-labelledby="builder-change-heading"
                    data-testid="scoped-change-card"
                  >
                    <!-- The summary sentence below is the visible heading. -->
                    <h3 id="builder-change-heading" class="sr-only">
                      {m.ai_builder_change_card_title()}
                    </h3>
                    <BuilderStepDetails
                      featured
                      step={scopedTargetStep}
                      stepNumber={scopedTargetIndex + 1}
                      open
                      detail={nodeDetail(scopedTargetStep, scopedTargetIndex + 1)}
                      modelLabel={modelLabel(scopedTargetStep)}
                      changeBadge={changeBadge(scopedTargetStep)}
                      fieldChanges={stepFieldChanges(scopedTargetStep)}
                      pausesForReview={pausesForReview(scopedTargetStep)}
                      perFile={perFileStepRefs.has(scopedTargetStep.plan_step_ref)}
                      canRequestChange={plan.status === "proposed"}
                      resolveInputStepLabel={resolveExecutionStepLabel}
                      resolveStepNumber={planStepNumber}
                      onrequestchange={() =>
                        scopeChangeToStep(scopedTargetStep, scopedTargetIndex + 1)}
                    />
                  </section>
                {/if}
                {#if changeList && !isScopedStepReview}
                  <section
                    class="px-6 py-5 max-sm:px-4"
                    aria-labelledby="builder-change-list-heading"
                    data-testid="edit-change-list"
                  >
                    <h3
                      id="builder-change-list-heading"
                      class="text-primary text-[0.9375rem] font-bold"
                    >
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
                                <span class="text-secondary min-w-0 flex-1 text-pretty"
                                  >{entry.what}</span
                                >
                              </button>
                            {:else}
                              <div
                                class="flex min-h-11 flex-wrap content-center items-baseline gap-x-3 gap-y-0.5 py-2"
                              >
                                <span class="text-primary font-semibold">{entry.subject}</span>
                                <span class="text-secondary min-w-0 flex-1 text-pretty"
                                  >{entry.what}</span
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
                  <section class="px-6 py-5 max-sm:px-4" aria-live="polite">
                    <h3 class="text-primary mb-2 text-[0.9375rem] font-bold">
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
                {#if otherAdvisories.length > 0}
                  <section class="px-6 py-5 max-sm:px-4" aria-live="polite">
                    <h3 class="text-primary mb-2 text-[0.9375rem] font-bold">
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
                {#if planLintWarnings.length > 0}
                  <section class="px-6 py-5 max-sm:px-4">
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
                            <span class="font-semibold">{executionStepLabel(warning.step_ref)}</span
                            >
                            <span class="text-warning-stronger/60 mx-1" aria-hidden="true">·</span>
                          {/if}
                          {warning.message}
                        </li>
                      {/each}
                    </ul>
                  </section>
                {/if}
                {#snippet flowDiagram()}
                  {#if reviewCheckpointSteps.length > 0}
                    <div
                      class="border-warning-default/40 bg-warning-dimmer text-warning-stronger mx-auto mb-3 flex max-w-[47.5rem] flex-wrap items-baseline gap-1.5 rounded-lg border px-3 py-2 text-xs"
                    >
                      <span class="text-pretty">
                        {m.ai_builder_review_checkpoint_note({
                          count: reviewCheckpointSteps.length
                        })}
                      </span>
                      {#each reviewCheckpointSteps as { step, index } (step.plan_step_ref)}
                        {#if isScopedStepReview && !isScopedTargetStep(step)}
                          <!-- A one-step review has no step list to open it in. -->
                          <span
                            class="bg-warning-default/20 text-warning-stronger inline-flex min-h-7 items-center rounded-full px-2 text-xs font-semibold"
                          >
                            {m.ai_builder_step_label({ step: index + 1 })}
                          </span>
                        {:else}
                          <button
                            type="button"
                            class="bg-warning-default/20 text-warning-stronger focus-visible:ring-warning-stronger inline-flex min-h-7 items-center rounded-full px-2 text-xs font-semibold focus-visible:ring-2 focus-visible:outline-none"
                            onclick={() => void revealStep(step)}
                          >
                            {m.ai_builder_step_label({ step: index + 1 })}
                          </button>
                        {/if}
                      {/each}
                    </div>
                  {/if}

                  <ol
                    bind:this={diagramListEl}
                    class="mx-auto my-0 flex max-w-[43.75rem] list-none flex-col p-0"
                  >
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
                    {#each diagramRows as row (row.kind === "gap" ? `gap-${row.key}` : row.step.plan_step_ref)}
                      {#if row.kind === "gap"}
                        <li>
                          <div
                            class="border-stronger mx-auto h-3.5 w-px border-l"
                            aria-hidden="true"
                          ></div>
                          <div
                            class="border-default text-secondary flex flex-wrap items-center gap-x-3 gap-y-1 rounded-[10px] border border-dashed px-3.5 py-2.5 text-[0.8125rem]"
                          >
                            <span>
                              {m.ai_builder_diagram_gap({
                                first: String(row.first),
                                last: String(row.last)
                              })}
                            </span>
                            <Button
                              variant="link"
                              size="xs"
                              class="text-accent-stronger ml-auto h-auto p-0 font-semibold underline underline-offset-2"
                              onclick={() => void openGap(row.key, row.first)}
                            >
                              {m.ai_builder_review_unchanged_show()}
                            </Button>
                          </div>
                        </li>
                      {:else}
                        {@const { step, index } = row}
                        <li
                          data-diagram-step={index + 1}
                          tabindex="-1"
                          class="focus-visible:ring-accent-stronger rounded-[10px] outline-none focus-visible:ring-2"
                        >
                          <div
                            class="border-stronger mx-auto h-3.5 w-px border-l"
                            aria-hidden="true"
                          ></div>
                          <BuilderStepNode
                            stepNumber={index + 1}
                            name={step.name}
                            detail={nodeDetail(step, index + 1)}
                            modeLabel={nodeModeLabel(step)}
                            pausesForReview={pausesForReview(step)}
                            perFile={perFileStepRefs.has(step.plan_step_ref)}
                            changeBadge={changeBadge(step)}
                            quiet={!isCreateMode && changeBadge(step) === null}
                          />
                        </li>
                      {/if}
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
                {/snippet}
                <article aria-labelledby="builder-flow-heading">
                  <!-- How the flow works: the diagram, or a card per step. A one-step
                       review shows the diagram alone: its step is shown above and
                       every other step is unchanged, so a step list would be empty. -->
                  {#if isScopedStepReview}
                    <div class="px-6 pt-5 pb-1.5 max-sm:px-4">
                      <h3 id="builder-flow-heading" class="text-primary text-[0.9375rem] font-bold">
                        {m.ai_builder_flow_card_title_edit()}
                      </h3>
                    </div>
                    <div class="px-6 pt-3 pb-6 max-sm:px-4">{@render flowDiagram()}</div>
                  {:else}
                    <Tabs.Root value={stepsView} onValueChange={handleStepsViewChange}>
                      <div class="flex flex-wrap items-center gap-2.5 px-6 pt-5 pb-1.5 max-sm:px-4">
                        <h3
                          id="builder-flow-heading"
                          class="text-primary text-[0.9375rem] font-bold"
                        >
                          {isCreateMode
                            ? m.ai_builder_how_flow_works()
                            : m.ai_builder_flow_card_title_edit()}
                        </h3>
                        {#if stepChangeCounts && !isScopedStepReview}
                          <ul class="flex list-none flex-wrap items-center gap-1.5 p-0">
                            {#each diffCounters as counter (counter.key)}
                              <li
                                class="border-default bg-primary text-secondary inline-flex h-[1.625rem] items-center gap-1.5 rounded-full border px-2.5 text-xs"
                              >
                                <span
                                  class="size-[0.4375rem] rounded-full {counter.tone}"
                                  aria-hidden="true"
                                ></span>
                                {(counter.count === 1 ? counter.one : counter.other)({
                                  count: String(counter.count)
                                })}
                              </li>
                            {/each}
                          </ul>
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

                      <Tabs.Content value="diagram" class="px-6 pt-3 pb-6 max-sm:px-4">
                        {@render flowDiagram()}
                      </Tabs.Content>

                      <Tabs.Content value="details" class="px-6 pt-3 pb-6 max-sm:px-4">
                        <ol
                          bind:this={detailsListEl}
                          class="my-0 flex list-none flex-col gap-2 p-0"
                        >
                          {#each detailSteps as { step, index } (step.plan_step_ref)}
                            <li data-plan-step-ref={step.plan_step_ref}>
                              <BuilderStepDetails
                                {step}
                                stepNumber={index + 1}
                                open={openStepRefs.has(step.plan_step_ref)}
                                onopenchange={(open) => setStepOpen(step, open)}
                                detail={nodeDetail(step, index + 1)}
                                modelLabel={modelLabel(step)}
                                changeBadge={changeBadge(step)}
                                quiet={!isCreateMode && changeBadge(step) === null}
                                fieldChanges={stepFieldChanges(step)}
                                pausesForReview={pausesForReview(step)}
                                perFile={perFileStepRefs.has(step.plan_step_ref)}
                                canRequestChange={plan.status === "proposed"}
                                resolveInputStepLabel={resolveExecutionStepLabel}
                                resolveStepNumber={planStepNumber}
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
                        {#if unchangedStepCountInList > 0}
                          <!-- What the list leaves out, said where it is left out. -->
                          <p
                            class="text-secondary mt-3 flex flex-wrap items-baseline gap-x-2 text-[0.8125rem]"
                          >
                            {#if hiddenUnchangedSteps.length > 0}
                              <span>
                                {hiddenUnchangedSteps.length === 1
                                  ? m.ai_builder_review_unchanged_hidden_one()
                                  : m.ai_builder_review_unchanged_hidden({
                                      count: String(hiddenUnchangedSteps.length)
                                    })}
                              </span>
                              <Button
                                variant="link"
                                size="xs"
                                class="text-accent-stronger h-auto p-0 font-semibold underline underline-offset-2"
                                onclick={() => (showUnchanged = true)}
                              >
                                {m.ai_builder_review_unchanged_show()}
                              </Button>
                            {:else}
                              <Button
                                variant="link"
                                size="xs"
                                class="text-accent-stronger h-auto p-0 font-semibold underline underline-offset-2"
                                onclick={() => (showUnchanged = false)}
                              >
                                {m.ai_builder_review_unchanged_hide()}
                              </Button>
                            {/if}
                          </p>
                        {/if}
                      </Tabs.Content>
                    </Tabs.Root>
                  {/if}
                </article>
                {#if spec.form_fields && spec.form_fields.length > 0}
                  <section class="px-6 py-5 max-sm:px-4">
                    <h3 class="text-primary mb-2 text-[0.9375rem] font-bold">
                      {m.ai_builder_form_fields_title()}
                    </h3>
                    <div class="grid gap-x-8 gap-y-3 sm:grid-cols-2">
                      {#each spec.form_fields as field (`${field.name}-${field.type}`)}
                        <div class="min-w-0">
                          <div class="text-primary truncate text-[0.8125rem] font-semibold">
                            {field.label}
                          </div>
                          <div
                            class="text-secondary mt-1 flex flex-wrap items-center gap-x-2 text-xs"
                          >
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
                <!-- Ask for a change, in place -->
                <div>
                  <BuilderChangeRequest
                    flush
                    bind:this={changeRequestRef}
                    bind:open={changeOpen}
                    scopeLabel={changeScopeLabel}
                    disabled={isLocked || !service.canSendMessage}
                    sendBlockedReason={service.modelSendBlockMessage}
                    onclearscope={scopeLocked ? undefined : clearChangeScope}
                    onsend={handleChangeSend}
                  />
                </div>

                {#if hasApplyOutcome}
                  <div class="flex flex-col gap-3 px-6 py-5 max-sm:px-4">
                    {#if service.applyResult && !isCreateMode}
                      <div
                        class="border-positive-default/40 bg-positive-dimmer flex items-start gap-3 rounded-[9px] border px-3.5 py-3"
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
                        class="border-warning-default/40 bg-warning-dimmer rounded-[9px] border px-3.5 py-3"
                        role="status"
                        aria-live="polite"
                      >
                        <p class="text-warning-stronger text-[0.8125rem] font-semibold">
                          {m.ai_builder_published_flow_title()}
                        </p>
                        <p class="text-warning-stronger/80 mt-0.5 text-xs leading-relaxed">
                          {m.ai_builder_published_flow_description({
                            version: String(publishedVersion ?? "")
                          })}
                        </p>
                        <div class="mt-2.5 flex flex-wrap gap-2">
                          <Button
                            size="sm"
                            disabled={service.isBusy}
                            onclick={handleUnpublishAndApply}
                          >
                            {service.pendingOperationKind === "unpublishing"
                              ? m.ai_builder_applying()
                              : m.ai_builder_published_flow_unpublish()}
                          </Button>
                          <Button
                            variant="outline"
                            size="sm"
                            onclick={() => service.dismissApplyError()}
                          >
                            {m.ai_builder_dismiss()}
                          </Button>
                          <FlowAIBuilderDiagnosticCopyButton
                            report={applyErrorDiagnosticReport}
                            size="sm"
                          />
                        </div>
                      </div>
                    {/if}

                    {#if isUnpublishedApplyFailure}
                      <div
                        class="border-warning-default/40 bg-warning-dimmer rounded-[9px] border px-3.5 py-3"
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
                          <Button
                            variant="outline"
                            size="sm"
                            onclick={() => service.dismissApplyError()}
                          >
                            {m.ai_builder_dismiss()}
                          </Button>
                          <FlowAIBuilderDiagnosticCopyButton
                            report={applyErrorDiagnosticReport}
                            size="sm"
                          />
                        </div>
                      </div>
                    {/if}

                    {#if isGeneralApplyError && isCreateMode}
                      <div
                        bind:this={createFailureEl}
                        class="border-warning-default/40 bg-warning-dimmer rounded-[9px] border px-3.5 py-3"
                        role="status"
                        aria-live="polite"
                        tabindex="-1"
                      >
                        <p class="text-warning-stronger text-[0.8125rem] font-semibold">
                          {createOutcomeUnknown
                            ? m.ai_builder_create_unknown_title()
                            : m.ai_builder_create_failed_title()}
                        </p>
                        <p
                          class="text-warning-stronger/80 mt-0.5 text-xs leading-relaxed text-pretty"
                        >
                          {#if createOutcomeUnknown}
                            {m.ai_builder_create_unknown_body()}
                          {:else}
                            {m.ai_builder_create_failed_body()}
                            {m.ai_builder_create_failed_retry_note()}
                          {/if}
                        </p>
                        {#if !createOutcomeUnknown}
                          <p class="text-warning-stronger/80 mt-1 text-xs">
                            {m.ai_builder_plan_unchanged()}
                          </p>
                        {/if}
                        <div class="mt-2.5 flex flex-wrap gap-2">
                          <FlowAIBuilderDiagnosticCopyButton
                            report={applyErrorDiagnosticReport}
                            size="sm"
                          />
                        </div>
                      </div>
                    {:else if isGeneralApplyError}
                      <div
                        class="border-warning-default/40 bg-warning-dimmer rounded-[9px] border px-3.5 py-3"
                        role="status"
                        aria-live="polite"
                      >
                        <p class="text-warning-stronger text-[0.8125rem] font-semibold">
                          {m.ai_builder_apply_failed_title()}
                        </p>
                        <p class="text-warning-stronger/80 mt-0.5 text-xs leading-relaxed">
                          {m.ai_builder_apply_failed_description({
                            message: generalApplyErrorMessage
                          })}
                        </p>
                        <div class="mt-2.5 flex flex-wrap gap-2">
                          <Button
                            variant="outline"
                            size="sm"
                            onclick={() => service.dismissApplyError()}
                          >
                            {m.ai_builder_dismiss()}
                          </Button>
                          <FlowAIBuilderDiagnosticCopyButton
                            report={applyErrorDiagnosticReport}
                            size="sm"
                          />
                        </div>
                      </div>
                    {/if}
                  </div>
                {/if}
              </div>
            </div>
            <!-- What the proposal rests on, beside the change: quieter type, no
               boxes, one hairline between each part. -->
            <aside
              class="border-default divide-dimmer flex min-w-0 flex-col divide-y border-t @min-[60rem]:border-t-0 @min-[60rem]:border-l"
              aria-label={m.ai_builder_review_context_label()}
            >
              {#if service.latestUserRequest}
                <section class="px-5 py-5 max-sm:px-4">
                  <h3 class="text-primary mb-1.5 text-[0.84375rem] font-bold">
                    {m.ai_builder_requirements_user_request()}
                  </h3>
                  <p
                    class="text-primary text-[0.8125rem] leading-relaxed break-words whitespace-pre-wrap"
                    class:line-clamp-6={requestIsLong && !requestExpanded}
                  >
                    <q>{service.latestUserRequest}</q>
                  </p>
                  {#if requestIsLong}
                    <Button
                      variant="link"
                      size="xs"
                      class="text-accent-stronger mt-1 h-auto p-0 text-xs font-medium underline underline-offset-2"
                      onclick={() => (requestExpanded = !requestExpanded)}
                    >
                      {requestExpanded ? m.ai_builder_show_less() : m.ai_builder_show_more()}
                    </Button>
                  {/if}
                </section>
              {/if}
              {#if plan.proposal.plan_rationale}
                {#snippet whyBody()}
                  <p
                    class="text-secondary max-w-[72ch] text-[0.8125rem] leading-relaxed text-pretty"
                  >
                    {plan.proposal.plan_rationale}
                  </p>
                {/snippet}
                <!-- The model's own reasoning: one click away, since the change
                   and the request above already say what matters. -->
                {@render disclosure(
                  isScopedStepReview
                    ? m.ai_builder_why_this_change()
                    : m.ai_builder_why_this_design(),
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
              <!-- How the whole flow runs says nothing about a one-step change. -->
              {#if !isScopedStepReview}
                {@render disclosure(
                  m.ai_builder_execution_profile(),
                  limitsOpen,
                  () => (limitsOpen = !limitsOpen),
                  limitsBody
                )}
              {/if}
              {#if basisCount > 0}
                {#snippet basisBody()}
                  <p
                    class="text-secondary max-w-[72ch] text-[0.8125rem] leading-relaxed text-pretty"
                  >
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
              {#if planFlowNotes.length > 0}
                <section class="px-5 py-5 max-sm:px-4">
                  <h3 class="text-secondary flex items-center gap-1.5 text-[0.84375rem] font-bold">
                    <IconInfo class="size-3.5" aria-hidden="true" />
                    {m.ai_builder_flow_notes()}
                  </h3>
                  <ul class="mt-2 flex list-none flex-col gap-1.5 p-0">
                    {#each planFlowNotes as note (`${note.step_ref ?? "flow"}-${note.code}-${note.message}`)}
                      <li
                        class="text-secondary rounded-md px-3 py-2 text-[0.8125rem] leading-relaxed"
                      >
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
            </aside>
          </div>
        </div>
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
                : m.ai_builder_footer_steps_change_when_approved({ count: changedStepCount })}
            </span>
            {#if isCreateMode || flowIsPublished}
              <span class="text-secondary text-xs text-pretty max-sm:hidden">
                {isCreateMode
                  ? m.ai_builder_footer_draft_not_running()
                  : m.ai_builder_footer_edit_unpublishes()}
              </span>
            {/if}
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
          {#if !service.applyResult && !isScopedStepReview}
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
          {:else if service.canApprove || service.canApply || service.pendingOperationKind === "approving" || service.pendingOperationKind === "applying"}
            <!-- Approving and applying are one decision for the reader: the
                 dialog confirms it and runs both. "Tillämpa" remains for a plan
                 approved earlier whose apply did not go through. -->
            <Button
              size="sm"
              class="max-sm:min-h-11"
              disabled={isLocked || isPublishedError || applyBlockedByPrerequisites}
              onclick={() => (approveDialogOpen = true)}
            >
              {service.pendingOperationKind === "approving" ||
              service.pendingOperationKind === "applying"
                ? m.ai_builder_updating_flow()
                : service.canApply
                  ? m.ai_builder_apply()
                  : m.ai_builder_approve()}
            </Button>
          {/if}
        </div>
      </div>
    </div>
  </div>

  <BuilderApproveDialog
    bind:open={approveDialogOpen}
    mode={isCreateMode ? "create" : "edit"}
    {stepCount}
    {changedStepCount}
    unchangedStepCount={stepChangeCounts?.unchanged ?? 0}
    {changedStepLine}
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
    <div class="w-full {BUILDER_COLUMN.standard}">
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
