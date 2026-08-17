<script lang="ts">
  import type { Snippet } from "svelte";
  import { SvelteSet } from "svelte/reactivity";
  import { m } from "$lib/paraglide/messages";
  import { getLocale } from "$lib/paraglide/runtime";
  import { toast } from "$lib/components/toast";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Tabs from "$lib/components/ui/tabs/index.js";
  import IconChevronDown from "@lucide/svelte/icons/chevron-down";
  import IconAlertTriangle from "@lucide/svelte/icons/triangle-alert";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import BuilderApproveDialog from "./BuilderApproveDialog.svelte";
  import BuilderChangeRequest from "./BuilderChangeRequest.svelte";
  import BuilderStepDetails from "./BuilderStepDetails.svelte";
  import BuilderStepNode from "./BuilderStepNode.svelte";
  import { Checkbox } from "$lib/components/ui/checkbox/index.js";
  import FlowAIBuilderDiagnosticCopyButton from "./FlowAIBuilderDiagnosticCopyButton.svelte";
  import { getAIBuilderService } from "./FlowAIBuilderService.svelte.ts";
  import type {
    AIBuilderPlanEditContext,
    AIBuilderStatus,
    EditAdvisory,
    FlowDraftSpecCore,
    StepSpec
  } from "./protocol";
  import {
    AIBuilderIssueKind,
    buildAIBuilderDiagnosticReport,
    buildAIBuilderDiagnosticReportPlan,
    buildAIBuilderDiagnosticReportSession
  } from "./aiBuilderDiagnosticReport";
  import {
    getReviewFocusStepIndex,
    getRemovedStepChanges,
    getStepChangeKind
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

  interface Props {
    onapplied?: (detail: { flow_id: string; focusStepIndex: number | null }) => void;
    /** The shell's composer route for a change request. This screen asks for
     *  changes in place, so the prop stays part of the contract but unused. */
    /** A generation attempt failed before a plan became available. */
    showGenerationFailure?: boolean;
    /** Narrow layouts: bring the conversation back into view. */
    onshowconversation?: () => void;
  }

  let { onapplied, showGenerationFailure = false, onshowconversation }: Props = $props();

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
    if (!isScopedStepReview) return;
    for (const step of steps) {
      if (isScopedTargetStep(step)) openStepRefs.add(step.plan_step_ref);
    }
  });

  function setStepOpen(step: StepSpec, open: boolean): void {
    if (open) openStepRefs.add(step.plan_step_ref);
    else openStepRefs.delete(step.plan_step_ref);
  }
  function revealStep(step: StepSpec): void {
    const planId = plan?.plan_id;
    if (planId) stepsViewPreference = { planId, view: "details" };
    openStepRefs.add(step.plan_step_ref);
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
    const ref = step.assistant_spec.model_ref;
    if (!ref) return m.ai_builder_node_model_none();
    const known = service.availableModels.find((model) => model.id === ref);
    if (known) return known.name;
    // An unresolved plan-local reference still names the model; "model." is
    // protocol bookkeeping and reads as noise on the step chip.
    return ref.startsWith("model.") ? ref.slice("model.".length) : ref;
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
  const descriptionDiff = $derived.by(() => {
    const change = plan?.proposal.edit?.diff?.flow_property_changes?.["flow_description"];
    if (!change) return null;
    return { previous: String(change[0] ?? ""), proposed: String(change[1] ?? "") };
  });
  const removedStepChanges = $derived(getRemovedStepChanges(plan?.proposal.edit?.diff ?? null));
  const planLintWarnings = $derived(plan?.proposal.lint_warnings ?? []);

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

  const turnRecoveryState = $derived(service.turnRecoveryState);

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

  async function handlePrimaryAction() {
    if (isCreateMode) {
      try {
        const result = await service.createFlowFromPlan();
        toast.success(m.ai_builder_created_toast());
        onapplied?.({ flow_id: result.flow_id, focusStepIndex });
      } catch {
        // Surfaced through service.applyError / service.createFailureOutcome.
      }
      return;
    }
    try {
      const result = await service.applyPlan();
      onapplied?.({ flow_id: result.flow_id, focusStepIndex });
    } catch {
      // Surfaced through service state.
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

  async function handleGenerationRetry() {
    if (turnRecoveryState === "failed_before_provider") {
      await service.retryLatestTurn();
    } else if (turnRecoveryState === "provider_outcome_unknown") {
      await service.acknowledgeAndRetryLatestTurn();
    }
  }
</script>

{#snippet disclosure(title: string, isOpen: boolean, toggle: () => void, body: Snippet)}
  <div class="border-dimmer border-t">
    <button
      type="button"
      class="hover:bg-secondary focus-visible:ring-accent-default/40 flex w-full items-center gap-2 px-[1.375rem] py-3 text-left text-[0.84375rem] font-bold transition-colors focus-visible:ring-2 focus-visible:outline-none max-sm:px-3.5"
      aria-expanded={isOpen}
      onclick={toggle}
    >
      <span class="text-primary">{title}</span>
      <IconChevronDown
        class="text-secondary ml-auto size-3.5 shrink-0 transition-transform duration-200 ease-out {isOpen
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
      <div class="w-full max-w-[53.75rem] 2xl:max-w-[62.5rem]">
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
            <button
              type="button"
              class="text-accent-stronger focus-visible:ring-accent-stronger/40 ml-auto rounded text-xs font-semibold whitespace-nowrap hover:underline focus-visible:ring-2 focus-visible:outline-none"
              onclick={() => service.dismissReviewNote()}
            >
              {m.ai_builder_review_note_acknowledge()}
            </button>
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
            <div class="flex flex-wrap items-center gap-2">
              <span
                class="bg-accent-dimmer text-accent-stronger inline-flex items-center rounded-full px-2.5 py-0.5 text-[0.65625rem] font-bold tracking-[0.03em] uppercase"
              >
                {isCreateMode ? m.ai_builder_draft_pill() : m.ai_builder_change_pill()}
              </span>
              <span class="text-secondary text-xs">
                {isCreateMode
                  ? m.ai_builder_plan_meta_steps_nothing_created({ count: stepCount })
                  : m.ai_builder_plan_meta_steps_not_published({ count: stepCount })}
              </span>
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
              <p class="text-secondary mt-1.5 max-w-[70ch] text-[0.875rem] leading-relaxed">
                {m.ai_builder_saved_step_review_scope()}
              </p>
            {:else if spec.flow_description && !descriptionDiff && !hasDescriptionAdvisory}
              <p
                class="text-secondary mt-1.5 max-w-[70ch] text-[0.875rem] leading-relaxed text-pretty"
              >
                {spec.flow_description}
              </p>
            {/if}
          </header>

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
                  {advisories.find((a) => a.code === "flow_description_update_required")?.message}
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
              {#if tokenUsage}
                <div class="border-dimmer flex items-baseline gap-4 border-t py-1.5">
                  <dt class="text-secondary text-[0.8125rem]">
                    {m.ai_builder_execution_token_usage()}
                  </dt>
                  <dd class="text-primary ml-auto text-[0.8125rem] font-semibold tabular-nums">
                    {tokenUsage.estimated ? "≈ " : ""}{m.ai_builder_token_usage_badge({
                      count: formatAIBuilderTokenCount(tokenUsage.total, getLocale())
                    })}
                  </dd>
                </div>
              {/if}
            </dl>
            {#if tokenUsage}
              <p class="text-secondary mt-2 text-xs leading-relaxed text-pretty">
                {tokenUsage.estimated
                  ? m.ai_builder_token_usage_estimated_note()
                  : m.ai_builder_token_usage_provider_note()}
              </p>
            {/if}
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
                        ? 'bg-negative-dimmer text-negative-default'
                        : 'bg-secondary text-secondary'}"
                  >
                    {advisory.message}
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
                      <span>{field.type}</span>
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
                      <span class="font-mono text-xs font-semibold">{warning.step_ref}</span>
                      <span class="text-warning-stronger/60 mx-1" aria-hidden="true">·</span>
                    {/if}
                    {warning.message}
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
                  <label class="text-secondary flex cursor-pointer items-center gap-1.5 text-xs">
                    <Checkbox bind:checked={onlyChanges} class="size-3.5" />
                    {m.ai_builder_diff_only_changes()}
                  </label>
                {/if}
              {/if}
              <Tabs.List class="ml-auto h-8">
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
                      class="bg-warning-default/20 text-warning-stronger focus-visible:ring-warning-default/50 rounded-full px-2 py-0.5 text-[0.6875rem] font-semibold focus-visible:ring-2 focus-visible:outline-none"
                      onclick={() => revealStep(step)}
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
                    <span class="text-secondary text-[0.6875rem] font-bold tracking-[0.04em]">
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
                      modelLabel={modelLabel(step)}
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
                      <span class="text-secondary text-[0.6875rem] font-bold tracking-[0.04em]">
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
              <ol class="my-0 flex list-none flex-col gap-2 p-0">
                {#each detailSteps as { step, index } (step.plan_step_ref)}
                  <li>
                    <BuilderStepDetails
                      {step}
                      stepNumber={index + 1}
                      open={openStepRefs.has(step.plan_step_ref)}
                      onopenchange={(open) => setStepOpen(step, open)}
                      ioLabel={ioLabel(step)}
                      modelLabel={modelLabel(step)}
                      changeBadge={changeBadge(step)}
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

          {#if removedStepChanges.length > 0}
            <section class="border-dimmer border-t px-[1.375rem] py-4 max-sm:px-3.5">
              <h3 class="text-primary mb-2 text-[0.84375rem] font-bold">
                {m.ai_builder_removed_steps_title()}
              </h3>
              <ul class="flex list-none flex-col gap-1 p-0">
                {#each removedStepChanges as change (`${change.step_ref ?? change.step_name}-${change.kind}`)}
                  <li class="flex items-center gap-2 py-1 text-[0.8125rem]">
                    <span
                      class="bg-warning-dimmer text-warning-stronger inline-flex h-5 shrink-0 items-center rounded-full px-2 text-[0.6875rem] font-semibold uppercase"
                    >
                      {m.ai_builder_badge_removed()}
                    </span>
                    <span class="text-secondary decoration-stronger truncate line-through">
                      {change.step_name}
                    </span>
                  </li>
                {/each}
              </ul>
            </section>
          {/if}
        </article>

        <!-- Ask for a change, in place -->
        <div class="mt-3.5">
          <BuilderChangeRequest
            bind:this={changeRequestRef}
            bind:open={changeOpen}
            scopeLabel={changeScopeLabel}
            disabled={isLocked || !service.canSendMessage}
            onclearscope={() => (changeScope = null)}
            onsend={handleChangeSend}
          />
        </div>

        {#if service.applyResult}
          <div
            class="border-positive-default/40 bg-positive-dimmer mt-3.5 rounded-[9px] border px-3.5 py-3"
            role="status"
            aria-live="polite"
          >
            <p class="text-positive-stronger text-[0.8125rem] font-semibold">
              {m.ai_builder_applied_success()}
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
            class="border-warning-default/40 bg-warning-dimmer mt-3.5 rounded-[9px] border px-3.5 py-3"
            role="status"
            aria-live="polite"
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
      <div class="mx-auto flex max-w-[53.75rem] flex-wrap items-center gap-2.5 2xl:max-w-[62.5rem]">
        <div class="flex flex-col max-sm:w-full">
          <span class="text-secondary text-xs">
            {m.ai_builder_footer_steps_nothing_created({ count: stepCount })}
          </span>
          <span class="text-secondary text-xs text-pretty">
            {m.ai_builder_footer_draft_not_running()}
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
    onconfirm={() => void handlePrimaryAction()}
  />
{:else if service.conflict}
  <div
    class="bg-secondary flex flex-1 justify-center px-7 pt-6 pb-10 max-lg:px-5 max-md:px-4 max-sm:pt-4"
  >
    <div class="w-full max-w-[43.75rem]">{@render conflictCard()}</div>
  </div>
{:else if showGenerationFailure}
  <div
    class="bg-secondary flex flex-1 justify-center px-7 pt-6 pb-10 max-lg:px-5 max-md:px-4 max-sm:pt-4"
  >
    <div class="w-full max-w-[43.75rem]">
      <div class="border-default bg-primary rounded-xl border p-5" role="status" aria-live="polite">
        <div class="flex items-start gap-3">
          <IconAlertTriangle
            class="text-warning-stronger mt-0.5 size-4 shrink-0"
            aria-hidden="true"
          />
          <div class="min-w-0">
            <h2 class="text-primary text-[0.9375rem] font-bold">
              {m.ai_builder_generation_failed_title()}
            </h2>
            <p class="text-secondary mt-1 text-[0.8125rem] leading-relaxed text-pretty">
              {m.ai_builder_generation_failed_body()}
            </p>
            <div class="mt-3 flex flex-wrap items-center gap-2">
              {#if turnRecoveryState}
                <Button
                  size="sm"
                  disabled={service.isStreaming || service.isRecoveringLatestTurn}
                  onclick={() => void handleGenerationRetry()}
                >
                  {turnRecoveryState === "provider_outcome_unknown"
                    ? m.ai_builder_turn_retry_with_cost_acknowledgement()
                    : m.ai_builder_turn_retry()}
                </Button>
              {/if}
              <Button variant="outline" size="sm" onclick={onshowconversation}>
                {m.ai_builder_show_conversation()}
              </Button>
              <FlowAIBuilderDiagnosticCopyButton
                report={generationErrorDiagnosticReport}
                variant="ghost"
                size="xs"
              />
            </div>
            <p class="text-secondary mt-3 text-xs leading-relaxed text-pretty">
              {m.ai_builder_generation_failed_late_note()}
            </p>
            <p class="text-secondary mt-1 text-xs leading-relaxed text-pretty">
              {m.ai_builder_generation_failed_clarify()}
            </p>
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
  @reference "@eneo/ui/styles";

  .progress-ring {
    border-color: var(--border-default);
    border-top-color: var(--accent-default);
    animation: builder-spin 1s linear infinite;
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
