<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import { toast } from "svelte-sonner";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import * as Collapsible from "$lib/components/ui/collapsible/index.js";
  import * as Tabs from "$lib/components/ui/tabs/index.js";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import FlowAIBuilderDiagnosticCopyButton from "./FlowAIBuilderDiagnosticCopyButton.svelte";
  import FlowAIBuilderStepCard from "./FlowAIBuilderStepCard.svelte";
  import FlowAIBuilderCanvas from "./FlowAIBuilderCanvas.svelte";
  import FlowAIBuilderTokenUsage from "./FlowAIBuilderTokenUsage.svelte";
  import { getAIBuilderService } from "./FlowAIBuilderService.svelte.ts";
  import type {
    AIBuilderStatus,
    AIBuilderSuggestChangeIntent,
    EditAdvisory,
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
  import {
    getAIBuilderApplyPrerequisites,
    hasAIBuilderApplyBlocker
  } from "./flowAIBuilderApplyPrerequisites";

  interface Props {
    onapplied?: (detail: { flow_id: string; focusStepIndex: number | null }) => void;
    onsuggestchange?: (intent: AIBuilderSuggestChangeIntent) => void;
    /** A generation attempt failed before a plan became available. */
    showGenerationFailure?: boolean;
    /** Narrow layouts: bring the conversation (task pane) back into view. */
    onshowconversation?: () => void;
  }

  let {
    onapplied,
    onsuggestchange,
    showGenerationFailure = false,
    onshowconversation
  }: Props = $props();

  const service = getAIBuilderService();
  const isCreateMode = $derived(service.session?.target_kind === "create");
  const activeStepScope = $derived(service.activeStepScope);
  let assumptionsOpen = $state(false);
  let executionProfileOpen = $state(false);
  // Use the builder container, not the viewport, for the initial state because
  // the collapsible app sidebar changes the space available to this pane.
  let rationaleOpen = $state(false);
  let rationaleTouched = false;
  let paneRoot = $state<HTMLElement | undefined>();

  function handleRationaleOpenChange(open: boolean) {
    rationaleTouched = true;
    rationaleOpen = open;
  }

  $effect(() => {
    const root = paneRoot;
    if (!root || typeof ResizeObserver === "undefined") return;
    let container: HTMLElement | null = root.parentElement;
    while (container && getComputedStyle(container).containerName !== "builder") {
      container = container.parentElement;
    }
    const observed = container ?? root;
    const applyDefault = (width: number) => {
      if (!rationaleTouched) rationaleOpen = !isScopedStepReview && width >= 768;
    };
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) applyDefault(entry.contentRect.width);
    });
    observer.observe(observed);
    applyDefault(observed.getBoundingClientRect().width);
    return () => observer.disconnect();
  });
  const {
    state: { currentSpace }
  } = getSpacesManager();

  type StepsView = "diagram" | "details";
  let stepsViewPreference = $state<{ planId: string; view: StepsView } | null>(null);

  // ---- Derivations ---------------------------------------------------------

  const descriptionDiff = $derived.by(() => {
    const editDiff = service.currentPlan?.proposal.edit?.diff;
    if (!editDiff?.flow_property_changes) return null;
    const change = editDiff.flow_property_changes["flow_description"];
    if (!change) return null;
    return { previous: String(change[0] ?? ""), proposed: String(change[1] ?? "") };
  });

  const advisories = $derived<EditAdvisory[]>(service.currentPlan?.proposal.edit?.advisories ?? []);
  const hasDescriptionAdvisory = $derived(
    advisories.some((a) => a.code === "flow_description_update_required")
  );
  const otherAdvisories = $derived(
    advisories.filter((a) => a.code !== "flow_description_update_required")
  );

  const isPublishedError = $derived(service.applyError?.code === "flow_is_published");
  const isUnpublishedApplyFailure = $derived(
    service.applyError?.code === "flow_unpublished_apply_failed"
  );
  const isGeneralApplyError = $derived(
    service.applyError !== null &&
      !service.isConflict &&
      !isPublishedError &&
      !isUnpublishedApplyFailure
  );
  const createFailed = $derived(isGeneralApplyError && isCreateMode);
  const createOutcomeUnknown = $derived(createFailed && service.createFailureOutcome === "unknown");
  const applyPrerequisites = $derived(
    getAIBuilderApplyPrerequisites({
      plan: service.currentPlan,
      targetKind: service.session?.target_kind,
      transcriptionModels: $currentSpace.transcription_models
    })
  );
  const isMissingSpaceTranscriptionModel = $derived(
    hasAIBuilderApplyBlocker(applyPrerequisites, "transcription_model_required")
  );
  const applyBlockedByPrerequisites = $derived(!applyPrerequisites.canApply);
  const generalApplyErrorMessage = $derived.by(() => {
    if (!service.applyError) return "";
    if (service.applyError.code === "transcription_model_required") {
      return m.ai_builder_missing_transcription_model_description();
    }
    return service.applyError.message;
  });

  function progressStatusLabel(status: AIBuilderStatus | null): string {
    if (status === null) {
      return service.hasSeenPlanInSession
        ? m.ai_builder_updating_plan()
        : m.ai_builder_generating();
    }

    switch (status) {
      case "architecture_committed":
        return service.hasSeenPlanInSession
          ? m.ai_builder_updating_plan()
          : m.ai_builder_generating();
      case "architecture_revised":
        return m.ai_builder_updating_plan();
      case "repairing":
        return m.ai_builder_status_repairing();
    }
  }
  const diagnosticSession = $derived.by(() =>
    buildAIBuilderDiagnosticReportSession(service.session)
  );
  const diagnosticPlan = $derived.by(() => buildAIBuilderDiagnosticReportPlan(service.currentPlan));
  const applyErrorDiagnosticReport = $derived.by(() =>
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
  const publishedVersion = $derived(
    service.applyError?.code === "flow_is_published"
      ? typeof service.applyError.details.published_version === "number"
        ? service.applyError.details.published_version
        : null
      : null
  );

  function resolveModelName(ref: string | null): string | null {
    if (!ref) return null;
    return service.availableModels.find((model) => model.id === ref)?.name ?? ref;
  }

  function resolveExecutionStepLabel(planStepRef: string): string | null {
    const steps = service.currentPlan?.proposal.spec.steps ?? [];
    const stepIndex = steps.findIndex((step) => step.plan_step_ref === planStepRef);
    if (stepIndex === -1) return null;
    return `${stepIndex + 1}. ${steps[stepIndex].name}`;
  }

  function executionStepLabel(planStepRef: string): string {
    return resolveExecutionStepLabel(planStepRef) ?? planStepRef;
  }

  let isApproving = $state(false);
  let isApplying = $state(false);
  let isUnpublishingAndApplying = $state(false);

  // An unknown provider outcome must keep its explicit cost acknowledgement.
  const turnRecoveryState = $derived(service.turnRecoveryState);
  async function handleGenerationRetry() {
    if (turnRecoveryState === "failed_before_provider") {
      await service.retryLatestTurn();
    } else if (turnRecoveryState === "provider_outcome_unknown") {
      await service.acknowledgeAndRetryLatestTurn();
    }
  }
  const generationErrorDiagnosticReport = $derived.by(() =>
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

  // Only a replacement plan in the same session counts as an update. This
  // prevents a resumed session's first loaded plan from appearing newly changed.
  let lastPlanOwner: { sessionId: string; planKey: string } | null = null;
  let justUpdated = $state(false);
  $effect(() => {
    const plan = service.currentPlan;
    const sessionId = service.session?.session_id ?? null;
    if (service.isStreaming || service.statusMessage !== null) {
      justUpdated = false;
    }
    if (!sessionId || !plan) return;
    const planKey = `${plan.plan_id}:${plan.updated_at ?? ""}:${plan.spec_hash ?? ""}`;
    if (lastPlanOwner?.sessionId === sessionId && lastPlanOwner.planKey !== planKey) {
      justUpdated = true;
    } else if (lastPlanOwner?.sessionId !== sessionId) {
      justUpdated = false;
    }
    lastPlanOwner = { sessionId, planKey };
  });

  const removedStepChanges = $derived(
    getRemovedStepChanges(service.currentPlan?.proposal.edit?.diff ?? null)
  );
  const scopedTargetExistingStepRef = $derived(
    service.currentPlan?.proposal.edit?.scoped_target_existing_step_ref ?? null
  );
  const scopedTargetPlanStepRef = $derived(
    service.currentPlan?.proposal.edit?.scoped_target_plan_step_ref ?? null
  );
  const isScopedStepReview = $derived(
    scopedTargetExistingStepRef !== null || scopedTargetPlanStepRef !== null
  );
  function isScopedTargetStep(step: StepSpec): boolean {
    return scopedTargetPlanStepRef
      ? step.plan_step_ref === scopedTargetPlanStepRef
      : step.existing_step_ref === scopedTargetExistingStepRef;
  }
  const stepsView = $derived.by<StepsView>(() => {
    const planId = service.currentPlan?.plan_id ?? null;
    if (planId && stepsViewPreference?.planId === planId) {
      return stepsViewPreference.view;
    }
    return isScopedStepReview ? "details" : "diagram";
  });
  function handleStepsViewChange(view: string): void {
    const planId = service.currentPlan?.plan_id;
    if (!planId || (view !== "diagram" && view !== "details")) return;
    stepsViewPreference = { planId, view };
  }
  const focusStepIndex = $derived.by(() => {
    const plan = service.currentPlan;
    if (!plan) return null;
    return getReviewFocusStepIndex(plan.proposal.spec.steps, plan.proposal.edit?.diff ?? null);
  });

  const attachments = $derived(service.session?.attachments ?? []);
  const attachmentWarnings = $derived(service.session?.attachment_warnings ?? []);
  const hasAttachments = $derived(attachments.length > 0);

  const stepCount = $derived(service.currentPlan?.proposal.spec.steps.length ?? 0);
  const planAssumptions = $derived(service.currentPlan?.proposal.assumptions ?? []);
  const planLintWarnings = $derived(service.currentPlan?.proposal.lint_warnings ?? []);
  const planQualityDiagnosticReport = $derived.by(() =>
    service.currentPlan && planLintWarnings.length > 0
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

  // Reference material drawer — default-open when no plan, closed after plan arrives.
  // Keep an independent user-intent flag so explicit user toggles survive plan refresh.
  let userReferenceOpen = $state<boolean | null>(null);
  const referenceOpen = $derived(userReferenceOpen ?? !service.currentPlan);
  function handleReferenceOpenChange(open: boolean) {
    userReferenceOpen = open;
  }

  // ---- Actions -------------------------------------------------------------

  async function handleApprove() {
    if (isApproving) return;
    isApproving = true;
    try {
      await service.approvePlan();
    } catch {
      // surfaced via service.applyError / service.isConflict
    } finally {
      isApproving = false;
    }
  }

  // Create mode: one atomic action — the driver approves and materializes in a
  // single backend call and owns the interaction lock (service.isCreating).
  async function handleCreate() {
    if (service.isCreating || applyBlockedByPrerequisites) return;
    try {
      const result = await service.createFlowFromPlan();
      toast.success(m.ai_builder_created_toast());
      onapplied?.({ flow_id: result.flow_id, focusStepIndex });
    } catch {
      // surfaced via service.applyError / service.createFailureOutcome
    }
  }

  async function handleApply() {
    if (
      isApplying ||
      isUnpublishingAndApplying ||
      isPublishedError ||
      applyBlockedByPrerequisites
    ) {
      return;
    }
    isApplying = true;
    try {
      const result = await service.applyPlan();
      onapplied?.({ flow_id: result.flow_id, focusStepIndex });
    } catch {
      // surfaced via service state
    } finally {
      isApplying = false;
    }
  }

  async function handleUnpublishAndApply() {
    if (isApplying || isUnpublishingAndApplying) return;
    if (!window.confirm(m.ai_builder_published_flow_confirm())) return;
    isUnpublishingAndApplying = true;
    try {
      const result = await service.unpublishAndApplyPlan();
      onapplied?.({ flow_id: result.flow_id, focusStepIndex });
    } catch {
      // surfaced via service state
    } finally {
      isUnpublishingAndApplying = false;
    }
  }

  async function handleContinueEditing() {
    await service.continueEditing();
  }

  function handleModify() {
    service.changeRequirements();
  }

  function handleConflictRegenerate() {
    service.dismissPlanPane();
  }
</script>

<div
  bind:this={paneRoot}
  class="bg-secondary/40 flex flex-col @[1040px]/builder:min-h-0 @[1040px]/builder:flex-1"
>
  {#if service.currentPlan}
    {@const plan = service.currentPlan}
    {@const spec = plan.proposal.spec}
    {@const indexedSteps = spec.steps.map((step, index) => ({ step, index }))}
    {@const detailSteps = isScopedStepReview
      ? [
          ...indexedSteps.filter(({ step }) => isScopedTargetStep(step)),
          ...indexedSteps.filter(({ step }) => !isScopedTargetStep(step))
        ]
      : indexedSteps}

    <!-- Keyboard-focusable scroll region in split view; narrow layouts use the page scroller. -->
    <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
    <div
      role="region"
      aria-label={m.ai_builder_plan_pane_aria()}
      aria-labelledby="plan-heading"
      tabindex="0"
      class="focus-visible:ring-accent-default/40 scroll-pb-4 focus-visible:ring-2 focus-visible:outline-none focus-visible:ring-inset @[1040px]/builder:flex-1 @[1040px]/builder:overflow-y-auto"
    >
      <div
        class="mx-auto flex max-w-[800px] flex-col gap-4 px-4 py-5 md:px-6 md:py-6 @[1400px]/builder:max-w-[840px]"
      >
        <!-- Attachment warnings (transient, near the top so users see it) -->
        {#if attachmentWarnings.length > 0}
          <Alert.Root
            class="border-warning-default/40 bg-warning-dimmer rounded-lg"
            role="status"
            aria-live="polite"
          >
            <Alert.Title class="text-warning-stronger text-[0.8125rem] font-semibold">
              {m.ai_builder_reference_material()}
            </Alert.Title>
            <Alert.Description class="text-warning-stronger/80 mt-0.5 text-xs leading-relaxed">
              {attachmentWarnings[0]}
            </Alert.Description>
          </Alert.Root>
        {/if}

        {#if isMissingSpaceTranscriptionModel}
          <Alert.Root
            class="border-warning-default/40 bg-warning-dimmer rounded-lg"
            role="status"
            aria-live="polite"
          >
            <Alert.Title class="text-warning-stronger text-[0.8125rem] font-semibold">
              {m.ai_builder_missing_transcription_model_title()}
            </Alert.Title>
            <Alert.Description class="text-warning-stronger/80 mt-0.5 text-xs leading-relaxed">
              {m.ai_builder_missing_transcription_model_description()}
            </Alert.Description>
          </Alert.Root>
        {/if}

        <!-- Conflict recovery banner ---------------------------------------->
        {#if service.isConflict}
          <Alert.Root
            class="border-warning-default/40 bg-warning-dimmer rounded-lg"
            role="status"
            aria-live="polite"
          >
            <Alert.Title class="text-warning-stronger text-[0.8125rem] font-semibold">
              {m.ai_builder_conflict_title()}
            </Alert.Title>
            <Alert.Description class="text-warning-stronger/80 mt-0.5 text-xs leading-relaxed">
              {m.ai_builder_conflict_description()}
            </Alert.Description>
            <div class="mt-3 flex flex-wrap gap-2">
              <Button variant="default" size="sm" onclick={handleConflictRegenerate}>
                {m.ai_builder_conflict_regenerate()}
              </Button>
              <Button variant="outline" size="sm" onclick={() => service.dismissConflict()}>
                {m.ai_builder_conflict_cancel()}
              </Button>
              <FlowAIBuilderDiagnosticCopyButton report={applyErrorDiagnosticReport} size="sm" />
            </div>
          </Alert.Root>
        {/if}

        <!-- Reference material (collapsible row) ---------------------------->
        {#if hasAttachments}
          <Collapsible.Root open={referenceOpen} onOpenChange={handleReferenceOpenChange}>
            <div
              class="border-default bg-primary ring-foreground/10 overflow-hidden rounded-xl border ring-1"
            >
              <Collapsible.Trigger
                class="hover:bg-hover-dimmer/40 aria-expanded:bg-secondary/30 focus-visible:ring-accent-default/30 flex w-full items-center gap-2.5 px-4 py-2.5 text-left transition-colors focus-visible:ring-2 focus-visible:outline-none"
              >
                <span
                  class="bg-accent-default/10 text-accent-default flex size-6 shrink-0 items-center justify-center rounded-md"
                  aria-hidden="true"
                >
                  <svg
                    xmlns="http://www.w3.org/2000/svg"
                    viewBox="0 0 20 20"
                    fill="currentColor"
                    class="size-3.5"
                  >
                    <path
                      fill-rule="evenodd"
                      d="M15.621 4.379a3 3 0 0 0-4.242 0l-7 7a3 3 0 0 0 4.241 4.243h.001l.497-.5a.75.75 0 0 1 1.064 1.057l-.498.501-.002.002a4.5 4.5 0 0 1-6.364-6.364l7-7a4.5 4.5 0 0 1 6.368 6.36l-3.455 3.553A2.625 2.625 0 1 1 9.52 9.52l3.45-3.451a.75.75 0 1 1 1.061 1.06l-3.45 3.451a1.125 1.125 0 0 0 1.587 1.595l3.454-3.553a3 3 0 0 0 0-4.242Z"
                      clip-rule="evenodd"
                    />
                  </svg>
                </span>
                <span class="text-primary flex-1 text-[0.8125rem] font-medium">
                  {m.ai_builder_reference_material()}
                </span>
                <Badge variant="outline" class="h-5 px-1.5 text-xs tabular-nums">
                  {attachments.length}
                </Badge>
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  viewBox="0 0 16 16"
                  fill="currentColor"
                  class="text-muted size-4 transition-transform duration-200 ease-out {referenceOpen
                    ? 'rotate-180'
                    : ''}"
                  aria-hidden="true"
                >
                  <path
                    fill-rule="evenodd"
                    d="M4.22 6.22a.75.75 0 0 1 1.06 0L8 8.94l2.72-2.72a.75.75 0 1 1 1.06 1.06l-3.25 3.25a.75.75 0 0 1-1.06 0L4.22 7.28a.75.75 0 0 1 0-1.06Z"
                    clip-rule="evenodd"
                  />
                </svg>
              </Collapsible.Trigger>

              <Collapsible.Content class="collapsible-animate">
                <div class="border-default border-t">
                  <ul class="divide-default flex flex-col divide-y">
                    {#each attachments as file (file.id)}
                      <li
                        class="hover:bg-secondary/40 flex items-center gap-3 px-4 py-2 transition-colors"
                      >
                        <div class="min-w-0 flex-1">
                          <div class="text-primary truncate text-[0.8125rem] font-medium">
                            {file.name}
                          </div>
                          <div class="text-muted truncate text-xs">{file.mimetype}</div>
                        </div>
                        <span
                          class="text-muted shrink-0 font-mono text-xs tabular-nums"
                          aria-label={m.file_size()}
                        >
                          {m.kb({ value: Math.max(1, Math.round(file.size / 1024)) })}
                        </span>
                      </li>
                    {/each}
                  </ul>
                </div>
              </Collapsible.Content>
            </div>
          </Collapsible.Root>
        {/if}

        <!-- Plan panel (flat; no nested cards) ------------------------------>
        <article
          class="plan-card-enter border-default bg-primary ring-foreground/10 flex flex-col overflow-hidden rounded-xl border shadow-sm ring-1"
          aria-labelledby="plan-heading"
        >
          <!-- Plan heading band -->
          <header class="flex flex-col gap-2 px-5 pt-5 pb-4 md:px-6">
            <div class="flex flex-wrap items-center gap-2">
              <Badge
                variant="outline"
                class="bg-accent-default/8 border-accent-default/25 text-accent-stronger h-5 px-1.5 text-xs font-semibold"
              >
                {m.ai_builder_draft_pill()}
              </Badge>
              <span class="text-muted text-xs tabular-nums">
                {m.flow_run_step_count({ count: stepCount })}
              </span>
              <span class="text-muted text-xs">·</span>
              <span class="text-muted text-xs max-sm:hidden">
                {m.ai_builder_plan_meta_nothing_created()}
              </span>
              <span class="text-muted text-xs sm:hidden">
                {m.ai_builder_plan_meta_nothing_created_short()}
              </span>
              {#if justUpdated}
                <span class="text-positive-stronger text-xs font-medium">
                  {m.ai_builder_plan_updated_receipt()}
                </span>
              {/if}
              <FlowAIBuilderTokenUsage telemetry={service.session?.telemetry} />
            </div>
            <h2
              id="plan-heading"
              class="text-primary text-[1.125rem] leading-tight font-semibold tracking-[-0.015em]"
            >
              {isScopedStepReview && activeStepScope
                ? m.ai_builder_saved_step_plan_title({
                    step: activeStepScope.stepNumber,
                    name: activeStepScope.stepName
                  })
                : spec.flow_name}
            </h2>
            {#if isScopedStepReview && activeStepScope}
              <p class="text-secondary text-[0.8125rem] leading-relaxed">
                {m.ai_builder_saved_step_review_scope()}
              </p>
            {:else if spec.flow_description && !descriptionDiff && !hasDescriptionAdvisory}
              <p class="text-secondary text-[0.8125rem] leading-relaxed">
                {spec.flow_description}
              </p>
            {/if}
          </header>

          <!-- Description diff / advisory -->
          {#if descriptionDiff || hasDescriptionAdvisory}
            <section
              class="section-enter border-default border-t px-5 py-4 md:px-6"
              aria-live="polite"
            >
              <h3 class="text-primary mb-2 text-sm font-semibold">
                {m.ai_builder_description_diff_title()}
              </h3>
              {#if descriptionDiff}
                <div class="flex flex-col gap-2">
                  <p
                    class="description-diff-old text-muted text-[0.8125rem] leading-relaxed break-words line-through"
                    aria-label={m.ai_builder_description_current()}
                  >
                    {descriptionDiff.previous}
                  </p>
                  <p
                    class="bg-accent-default/6 text-primary rounded-md px-3 py-2 text-[0.8125rem] leading-relaxed break-words"
                    aria-label={m.ai_builder_description_proposed()}
                  >
                    {descriptionDiff.proposed}
                  </p>
                </div>
              {:else if hasDescriptionAdvisory}
                <p class="text-secondary text-[0.8125rem] leading-relaxed">
                  {advisories.find((a) => a.code === "flow_description_update_required")?.message}
                </p>
                <div class="mt-3 flex flex-wrap gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onclick={() => service.revisePlan("keep_current_description")}
                    disabled={service.isCreating}
                  >
                    {m.ai_builder_description_keep_current()}
                  </Button>
                </div>
              {/if}
            </section>
          {/if}

          {#snippet supportingPlanContext()}
            {#if plan.proposal.plan_rationale}
              <section class="border-default border-t px-5 py-4 md:px-6">
                <Collapsible.Root open={rationaleOpen} onOpenChange={handleRationaleOpenChange}>
                  <h3 class="text-sm">
                    <Collapsible.Trigger class="section-heading-trigger">
                      <span>
                        {isScopedStepReview
                          ? m.ai_builder_why_this_change()
                          : m.ai_builder_why_this_design()}
                      </span>
                      <svg
                        xmlns="http://www.w3.org/2000/svg"
                        viewBox="0 0 16 16"
                        fill="currentColor"
                        class="size-3.5 shrink-0 transition-transform duration-200 ease-out {rationaleOpen
                          ? 'rotate-180'
                          : ''}"
                        aria-hidden="true"
                      >
                        <path
                          fill-rule="evenodd"
                          d="M4.22 6.22a.75.75 0 0 1 1.06 0L8 8.94l2.72-2.72a.75.75 0 1 1 1.06 1.06l-3.25 3.25a.75.75 0 0 1-1.06 0L4.22 7.28a.75.75 0 0 1 0-1.06Z"
                          clip-rule="evenodd"
                        />
                      </svg>
                    </Collapsible.Trigger>
                  </h3>
                  <Collapsible.Content class="collapsible-animate">
                    <p class="text-secondary mt-2 text-[0.8125rem] leading-relaxed">
                      {plan.proposal.plan_rationale}
                    </p>
                  </Collapsible.Content>
                </Collapsible.Root>
              </section>
            {/if}

            {#if plan.proposal.execution_shape}
              <section class="border-default border-t px-5 py-4 md:px-6">
                <Collapsible.Root bind:open={executionProfileOpen}>
                  <h3 class="text-sm">
                    <Collapsible.Trigger class="section-heading-trigger">
                      <span>{m.ai_builder_execution_profile()}</span>
                      <svg
                        xmlns="http://www.w3.org/2000/svg"
                        viewBox="0 0 16 16"
                        fill="currentColor"
                        class="size-3.5 shrink-0 transition-transform duration-200 ease-out {executionProfileOpen
                          ? 'rotate-180'
                          : ''}"
                        aria-hidden="true"
                      >
                        <path
                          fill-rule="evenodd"
                          d="M4.22 6.22a.75.75 0 0 1 1.06 0L8 8.94l2.72-2.72a.75.75 0 1 1 1.06 1.06l-3.25 3.25a.75.75 0 0 1-1.06 0L4.22 7.28a.75.75 0 0 1 0-1.06Z"
                          clip-rule="evenodd"
                        />
                      </svg>
                    </Collapsible.Trigger>
                  </h3>
                  <Collapsible.Content class="collapsible-animate">
                    <p class="text-secondary mt-2 text-[0.8125rem] leading-relaxed">
                      {m.ai_builder_execution_profile_description()}
                    </p>
                    <dl class="mt-3 grid grid-cols-[minmax(0,1fr)_auto] gap-x-4 gap-y-2">
                      <dt class="text-secondary text-[0.8125rem]">
                        {m.ai_builder_execution_completion_model()}
                      </dt>
                      <dd
                        class="text-primary text-right text-[0.8125rem] font-semibold tabular-nums"
                      >
                        {plan.proposal.execution_shape.completion_model_step_count}
                      </dd>
                      <dt class="text-secondary text-[0.8125rem]">
                        {m.ai_builder_execution_transcription_model()}
                      </dt>
                      <dd
                        class="text-primary text-right text-[0.8125rem] font-semibold tabular-nums"
                      >
                        {plan.proposal.execution_shape.transcription_model_step_count}
                      </dd>
                      <dt class="text-secondary text-[0.8125rem]">
                        {m.ai_builder_execution_deterministic()}
                      </dt>
                      <dd
                        class="text-primary text-right text-[0.8125rem] font-semibold tabular-nums"
                      >
                        {plan.proposal.execution_shape.deterministic_step_count}
                      </dd>
                      <dt class="text-secondary text-[0.8125rem]">
                        {m.ai_builder_execution_schema_constrained()}
                      </dt>
                      <dd
                        class="text-primary text-right text-[0.8125rem] font-semibold tabular-nums"
                      >
                        {plan.proposal.execution_shape.schema_constrained_step_count}
                      </dd>
                    </dl>
                    <h4 class="text-primary mt-4 text-[0.8125rem] font-semibold">
                      {m.ai_builder_execution_mapped_limits()}
                    </h4>
                    {@const mappedStepBounds =
                      plan.proposal.execution_shape.mapped_step_upper_bounds ?? []}
                    {#if mappedStepBounds.length > 0}
                      <ul
                        class="text-secondary mt-1.5 flex flex-col gap-1 text-[0.8125rem] leading-relaxed"
                      >
                        {#each mappedStepBounds as bound (bound.plan_step_ref)}
                          <li>
                            {#if bound.execution_mode === "per_source"}
                              {m.ai_builder_execution_per_source_limit({
                                step: executionStepLabel(bound.plan_step_ref),
                                count: bound.maximum_items
                              })}
                            {:else}
                              {m.ai_builder_execution_per_item_limit({
                                step: executionStepLabel(bound.plan_step_ref),
                                count: bound.maximum_items
                              })}
                            {/if}
                          </li>
                        {/each}
                      </ul>
                    {:else}
                      <p class="text-secondary mt-1.5 text-[0.8125rem] leading-relaxed">
                        {m.ai_builder_execution_no_mapped_steps()}
                      </p>
                    {/if}
                  </Collapsible.Content>
                </Collapsible.Root>
              </section>
            {/if}

            {#if planAssumptions.length > 0}
              <section class="border-default border-t px-5 py-4 md:px-6">
                <Collapsible.Root bind:open={assumptionsOpen}>
                  <h3 class="text-sm">
                    <Collapsible.Trigger class="section-heading-trigger">
                      <span>{m.ai_builder_technical_assumptions()} ({planAssumptions.length})</span>
                      <svg
                        xmlns="http://www.w3.org/2000/svg"
                        viewBox="0 0 16 16"
                        fill="currentColor"
                        class="size-3.5 shrink-0 transition-transform duration-200 ease-out {assumptionsOpen
                          ? 'rotate-180'
                          : ''}"
                        aria-hidden="true"
                      >
                        <path
                          fill-rule="evenodd"
                          d="M4.22 6.22a.75.75 0 0 1 1.06 0L8 8.94l2.72-2.72a.75.75 0 1 1 1.06 1.06l-3.25 3.25a.75.75 0 0 1-1.06 0L4.22 7.28a.75.75 0 0 1 0-1.06Z"
                          clip-rule="evenodd"
                        />
                      </svg>
                    </Collapsible.Trigger>
                  </h3>
                  <Collapsible.Content class="collapsible-animate">
                    <ul
                      class="bg-secondary/40 divide-default mt-2 flex flex-col divide-y rounded-lg px-3 py-0.5"
                    >
                      {#each planAssumptions as assumption (assumption)}
                        <li class="text-secondary py-2 text-[0.8125rem] leading-relaxed">
                          {assumption}
                        </li>
                      {/each}
                    </ul>
                  </Collapsible.Content>
                </Collapsible.Root>
              </section>
            {/if}
          {/snippet}

          {#if !isScopedStepReview}
            {@render supportingPlanContext()}
          {/if}

          <!-- Edit advisories (non-description) -->
          {#if otherAdvisories.length > 0}
            <section class="border-default border-t px-5 py-4 md:px-6" aria-live="polite">
              <h3 class="text-primary mb-2 text-sm font-semibold">
                {m.ai_builder_advisory_section_title()}
              </h3>
              <ul class="flex flex-col gap-1.5">
                {#each otherAdvisories as advisory (advisory.code)}
                  <li
                    class="rounded-md px-3 py-2 text-[0.8125rem] leading-relaxed
                      {advisory.severity === 'info' ? 'bg-accent-default/6 text-secondary' : ''}
                      {advisory.severity === 'warning'
                      ? 'bg-warning-dimmer text-warning-stronger'
                      : ''}
                      {advisory.severity === 'error'
                      ? 'bg-negative-dimmer text-negative-default'
                      : ''}"
                  >
                    {advisory.message}
                  </li>
                {/each}
              </ul>
            </section>
          {/if}

          <!-- Form fields -->
          {#if spec.form_fields && spec.form_fields.length > 0}
            <section class="border-default border-t px-5 py-4 md:px-6">
              <h3 class="text-primary mb-2 text-sm font-semibold">
                {m.ai_builder_form_fields_title()}
              </h3>
              <div class="grid gap-2.5 sm:grid-cols-2">
                {#each spec.form_fields as field (`${field.name}-${field.type}`)}
                  <div class="border-default bg-secondary/40 rounded-lg border p-3">
                    <div class="mb-1 flex items-center justify-between gap-2">
                      <span class="text-primary truncate text-[0.8125rem] font-semibold">
                        {field.label}
                      </span>
                      <span
                        class="border-default text-muted bg-primary rounded-full border px-1.5 py-0.5 font-mono text-xs"
                      >
                        {field.type}
                      </span>
                    </div>
                    <div class="text-muted flex flex-wrap items-center gap-x-2 text-xs">
                      <span class="font-mono">{field.name}</span>
                      <span>·</span>
                      <span>
                        {field.required === true
                          ? m.ai_builder_form_field_required()
                          : m.ai_builder_form_field_optional()}
                      </span>
                    </div>
                    {#if field.options && field.options.length > 0}
                      <div class="mt-2 flex flex-wrap gap-1">
                        {#each field.options as option (option)}
                          <span
                            class="border-default text-secondary rounded-full border px-2 py-0.5 text-xs"
                          >
                            {option}
                          </span>
                        {/each}
                      </div>
                    {/if}
                  </div>
                {/each}
              </div>
            </section>
          {/if}

          <!-- Lint warnings -->
          {#if planLintWarnings.length > 0}
            <section class="border-default border-t px-5 py-4 md:px-6">
              <div class="mb-2 flex flex-wrap items-center justify-between gap-2">
                <h3 class="text-warning-stronger flex items-center gap-1.5 text-sm font-semibold">
                  <svg
                    xmlns="http://www.w3.org/2000/svg"
                    viewBox="0 0 16 16"
                    fill="currentColor"
                    class="size-3.5"
                    aria-hidden="true"
                  >
                    <path
                      fill-rule="evenodd"
                      d="M6.701 2.25c.577-1 2.02-1 2.598 0l5.196 9a1.5 1.5 0 0 1-1.299 2.25H2.804a1.5 1.5 0 0 1-1.3-2.25l5.197-9ZM8 4a.75.75 0 0 1 .75.75v3a.75.75 0 0 1-1.5 0v-3A.75.75 0 0 1 8 4Zm0 8a1 1 0 1 0 0-2 1 1 0 0 0 0 2Z"
                      clip-rule="evenodd"
                    />
                  </svg>
                  {m.ai_builder_quality_warnings()}
                </h3>
                <FlowAIBuilderDiagnosticCopyButton
                  report={planQualityDiagnosticReport}
                  variant="ghost"
                  size="xs"
                  class="text-warning-stronger hover:bg-warning-dimmer/80"
                />
              </div>
              <ul class="flex flex-col gap-1.5">
                {#each planLintWarnings as warning (`${warning.step_ref ?? "flow"}-${warning.code}-${warning.message}`)}
                  <li
                    class="bg-warning-dimmer/60 text-warning-stronger rounded-md px-3 py-2 text-[0.8125rem] leading-relaxed"
                  >
                    {#if warning.step_ref}
                      <span class="font-mono text-[12px] font-semibold">{warning.step_ref}</span>
                      <span class="text-warning-stronger/60 mx-1">·</span>
                    {/if}
                    {warning.message}
                  </li>
                {/each}
              </ul>
            </section>
          {/if}

          <!-- Steps: the living diagram or the detailed step-card list -->
          <section class="border-default border-t px-5 py-4 md:px-6">
            <Tabs.Root value={stepsView} onValueChange={handleStepsViewChange}>
              <div class="mb-3 flex items-center justify-between gap-3">
                <h3 class="text-primary text-sm font-semibold">
                  {isScopedStepReview
                    ? m.ai_builder_step_change_review_title()
                    : m.ai_builder_how_flow_works()}
                </h3>
                <Tabs.List class="h-8">
                  {#if isScopedStepReview}
                    <Tabs.Trigger value="details" class="px-3 py-1 text-xs">
                      {m.ai_builder_canvas_tab_details()}
                    </Tabs.Trigger>
                    <Tabs.Trigger value="diagram" class="px-3 py-1 text-xs">
                      {m.ai_builder_canvas_tab_diagram()}
                    </Tabs.Trigger>
                  {:else}
                    <Tabs.Trigger value="diagram" class="px-3 py-1 text-xs">
                      {m.ai_builder_canvas_tab_diagram()}
                    </Tabs.Trigger>
                    <Tabs.Trigger value="details" class="px-3 py-1 text-xs">
                      {m.ai_builder_canvas_tab_details()}
                    </Tabs.Trigger>
                  {/if}
                </Tabs.List>
              </div>
              <Tabs.Content value="diagram">
                <FlowAIBuilderCanvas {spec} isStreaming={service.isStreaming} />
              </Tabs.Content>
              <Tabs.Content value="details">
                <ol class="m-0 flex list-none flex-col p-0">
                  {#each detailSteps as { step, index } (`${plan.plan_id}:${step.plan_step_ref}`)}
                    <li>
                      <FlowAIBuilderStepCard
                        {step}
                        stepNumber={index + 1}
                        planId={plan.plan_id}
                        changeKind={getStepChangeKind(step, plan.proposal.edit?.diff ?? null)}
                        {resolveModelName}
                        resolveInputStepLabel={resolveExecutionStepLabel}
                        isFirst={index === 0}
                        isLast={index === spec.steps.length - 1}
                        planStatus={plan.status}
                        openByDefault={isScopedStepReview && isScopedTargetStep(step)}
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
                            details: {
                              actual_output_type: step.output_type
                            }
                          })}
                        onsuggestchange={(intent) => onsuggestchange?.(intent)}
                      />
                    </li>
                  {/each}
                </ol>
              </Tabs.Content>
            </Tabs.Root>
          </section>

          {#if isScopedStepReview}
            {@render supportingPlanContext()}
          {/if}

          <!-- Removed steps -->
          {#if removedStepChanges.length > 0}
            <section class="border-default border-t px-5 py-4 md:px-6">
              <h3 class="text-primary mb-2 text-sm font-semibold">
                {m.ai_builder_removed_steps_title()}
              </h3>
              <ul class="flex flex-col gap-1">
                {#each removedStepChanges as change (`${change.step_ref ?? change.step_name}-${change.kind}`)}
                  <li class="text-muted flex items-center gap-2 py-1 text-[0.8125rem] leading-snug">
                    <Badge
                      variant="outline"
                      class="border-warning-default/25 bg-warning-dimmer text-warning-stronger h-5 shrink-0 px-1.5 text-xs font-semibold tracking-wide uppercase"
                    >
                      {m.ai_builder_badge_removed()}
                    </Badge>
                    <span class="text-secondary decoration-muted/40 truncate line-through">
                      {change.step_name}
                    </span>
                  </li>
                {/each}
              </ul>
            </section>
          {/if}
        </article>

        <!-- Applied result ---------------------------------------------------->
        {#if service.applyResult}
          <Alert.Root
            class="border-positive-default/40 bg-positive-dimmer rounded-lg"
            role="status"
            aria-live="polite"
          >
            <Alert.Title class="text-positive-stronger text-[0.8125rem] font-semibold">
              {m.ai_builder_applied_success()}
            </Alert.Title>
            <Alert.Description class="text-positive-stronger/80 mt-0.5 text-xs leading-relaxed">
              {service.applyResult.steps_created}
              {m.ai_builder_created()},
              {service.applyResult.steps_updated}
              {m.ai_builder_updated()},
              {service.applyResult.steps_removed}
              {m.ai_builder_removed()}
            </Alert.Description>
            {#if service.canContinueEditing}
              <div class="mt-3">
                <Button variant="outline" size="sm" onclick={handleContinueEditing}>
                  {m.ai_builder_continue_editing()}
                </Button>
              </div>
            {/if}
          </Alert.Root>
        {/if}
      </div>
    </div>

    <!-- Published flow banner (sits just above the action bar) ------------->
    {#if isPublishedError}
      <Alert.Root
        class="border-warning-default/40 bg-warning-dimmer shrink-0 rounded-none border-x-0 border-b-0"
        role="status"
        aria-live="polite"
      >
        <div class="mx-auto max-w-[800px] px-4 py-3 md:px-6 @[1400px]/builder:max-w-[840px]">
          <Alert.Title class="text-warning-stronger text-[0.8125rem] font-semibold">
            {m.ai_builder_published_flow_title()}
          </Alert.Title>
          <Alert.Description class="text-warning-stronger/80 mt-0.5 text-xs leading-relaxed">
            {m.ai_builder_published_flow_description({
              version: String(publishedVersion ?? "")
            })}
          </Alert.Description>
          <div class="mt-2 flex flex-wrap gap-2">
            <Button
              variant="default"
              size="sm"
              onclick={handleUnpublishAndApply}
              disabled={isApplying || isUnpublishingAndApplying}
            >
              {isUnpublishingAndApplying
                ? m.ai_builder_applying()
                : m.ai_builder_published_flow_unpublish()}
            </Button>
            <Button variant="outline" size="sm" onclick={() => service.dismissApplyError()}>
              {m.ai_builder_conflict_cancel()}
            </Button>
            <FlowAIBuilderDiagnosticCopyButton report={applyErrorDiagnosticReport} size="sm" />
          </div>
        </div>
      </Alert.Root>
    {/if}

    {#if isUnpublishedApplyFailure}
      <Alert.Root
        class="border-warning-default/40 bg-warning-dimmer shrink-0 rounded-none border-x-0 border-b-0"
        role="status"
        aria-live="polite"
      >
        <div class="mx-auto max-w-[800px] px-4 py-3 md:px-6 @[1400px]/builder:max-w-[840px]">
          <Alert.Title class="text-warning-stronger text-[0.8125rem] font-semibold">
            {m.ai_builder_unpublished_apply_failed_title()}
          </Alert.Title>
          <Alert.Description class="text-warning-stronger/80 mt-0.5 text-xs leading-relaxed">
            {m.ai_builder_unpublished_apply_failed_description({
              message: service.applyError?.message ?? ""
            })}
          </Alert.Description>
          <div class="mt-2">
            <div class="flex flex-wrap gap-2">
              <Button variant="outline" size="sm" onclick={() => service.dismissApplyError()}>
                {m.ai_builder_dismiss()}
              </Button>
              <FlowAIBuilderDiagnosticCopyButton report={applyErrorDiagnosticReport} size="sm" />
            </div>
          </div>
        </div>
      </Alert.Root>
    {/if}

    {#if isGeneralApplyError && isCreateMode}
      <!-- Keep the retry in the action bar. Claim that nothing was saved only
           for a confirmed failure; an unknown outcome uses neutral copy because
           the idempotent endpoint may replay an already-created flow. -->
      <Alert.Root
        class="border-warning-default/40 bg-warning-dimmer shrink-0 rounded-none border-x-0 border-b-0"
        role="status"
        aria-live="polite"
      >
        <div class="mx-auto max-w-[800px] px-4 py-3 md:px-6 @[1400px]/builder:max-w-[840px]">
          <Alert.Title class="text-warning-stronger text-[0.8125rem] font-semibold">
            {createOutcomeUnknown
              ? m.ai_builder_create_unknown_title()
              : m.ai_builder_create_failed_title()}
          </Alert.Title>
          <Alert.Description class="text-warning-stronger/80 mt-0.5 text-xs leading-relaxed">
            {#if createOutcomeUnknown}
              {m.ai_builder_create_unknown_body()}
            {:else}
              {m.ai_builder_create_failed_body()}
              {m.ai_builder_create_failed_retry_note()}
            {/if}
          </Alert.Description>
          {#if !createOutcomeUnknown}
            <p class="text-warning-stronger/80 mt-1 text-xs">{m.ai_builder_plan_unchanged()}</p>
          {/if}
          <div class="mt-2 flex flex-wrap gap-2">
            <FlowAIBuilderDiagnosticCopyButton report={applyErrorDiagnosticReport} size="sm" />
          </div>
        </div>
      </Alert.Root>
    {:else if isGeneralApplyError}
      <Alert.Root
        class="border-warning-default/40 bg-warning-dimmer shrink-0 rounded-none border-x-0 border-b-0"
        role="status"
        aria-live="polite"
      >
        <div class="mx-auto max-w-[800px] px-4 py-3 md:px-6 @[1400px]/builder:max-w-[840px]">
          <Alert.Title class="text-warning-stronger text-[0.8125rem] font-semibold">
            {m.ai_builder_apply_failed_title()}
          </Alert.Title>
          <Alert.Description class="text-warning-stronger/80 mt-0.5 text-xs leading-relaxed">
            {m.ai_builder_apply_failed_description({
              message: generalApplyErrorMessage
            })}
          </Alert.Description>
          <div class="mt-2 flex flex-wrap gap-2">
            <Button variant="outline" size="sm" onclick={() => service.dismissApplyError()}>
              {m.ai_builder_dismiss()}
            </Button>
            <FlowAIBuilderDiagnosticCopyButton report={applyErrorDiagnosticReport} size="sm" />
          </div>
        </div>
      </Alert.Root>
    {/if}

    <!-- Pinned to the page bottom in narrow layouts and contained by the plan pane in split view. -->
    <div
      class="border-default bg-primary sticky bottom-0 z-10 shrink-0 border-t pb-[env(safe-area-inset-bottom)] @[1040px]/builder:static"
    >
      <div
        class="mx-auto flex max-w-[800px] flex-col-reverse items-stretch gap-2 px-4 py-3 sm:flex-row sm:items-center md:px-6 @[1400px]/builder:max-w-[840px]"
      >
        {#if !service.applyResult && (service.isCreating || !createFailed)}
          <p
            class="text-secondary mr-auto text-xs max-sm:text-center"
            role="status"
            aria-live="polite"
          >
            {service.isCreating
              ? m.ai_builder_creating_status()
              : m.ai_builder_nothing_created_yet()}
          </p>
        {/if}
        <!-- Announce each plan update once; the visible receipt lives in the header. -->
        <span class="sr-only" role="status" aria-live="polite">
          {justUpdated ? m.ai_builder_plan_updated_announce() : ""}
        </span>

        <!-- Plan refinements belong in the composer, so the action bar has no duplicate path. -->
        {#if !service.applyResult}
          <Button
            variant="ghost"
            size="sm"
            class="max-sm:min-h-11 max-sm:w-full"
            onclick={handleModify}
            disabled={service.isCreating ||
              createOutcomeUnknown ||
              isApproving ||
              isApplying ||
              isUnpublishingAndApplying}
          >
            {m.ai_builder_modify()}
          </Button>
        {/if}

        {#if isCreateMode}
          <!-- Approval and creation are one atomic backend operation. -->
          {#if !service.applyResult && (service.canApprove || service.canApply || service.isCreating || createFailed)}
            <Button
              variant="default"
              size="sm"
              class="min-h-11 max-sm:min-h-12 max-sm:w-full"
              onclick={handleCreate}
              disabled={service.isCreating || applyBlockedByPrerequisites}
            >
              {service.isCreating
                ? m.ai_builder_creating()
                : createFailed
                  ? m.ai_builder_turn_retry()
                  : m.ai_builder_approve_create()}
            </Button>
          {/if}
        {:else}
          {#if service.canApprove}
            <Button
              variant="default"
              size="sm"
              class="max-sm:min-h-11 max-sm:w-full"
              onclick={handleApprove}
              disabled={isApproving || isApplying || isUnpublishingAndApplying}
            >
              {isApproving ? m.ai_builder_approving() : m.ai_builder_approve()}
            </Button>
          {/if}

          {#if service.canApply}
            <Button
              variant="default"
              size="sm"
              class="max-sm:min-h-11 max-sm:w-full"
              onclick={handleApply}
              disabled={isApproving ||
                isApplying ||
                isUnpublishingAndApplying ||
                isPublishedError ||
                applyBlockedByPrerequisites}
            >
              {isApplying ? m.ai_builder_applying() : m.ai_builder_apply()}
            </Button>
          {/if}
        {/if}
      </div>
    </div>
  {:else if service.isConflict}
    <!-- Conflict state without a plan yet --------------------------------- -->
    <div class="flex flex-1 flex-col overflow-y-auto">
      <div class="mx-auto w-full max-w-[800px] px-4 py-6 md:px-6 @[1400px]/builder:max-w-[840px]">
        <Alert.Root class="border-warning-default/40 bg-warning-dimmer rounded-lg">
          <Alert.Title class="text-warning-stronger text-[0.8125rem] font-semibold">
            {m.ai_builder_conflict_title()}
          </Alert.Title>
          <Alert.Description class="text-warning-stronger/80 mt-0.5 text-xs leading-relaxed">
            {m.ai_builder_conflict_description()}
          </Alert.Description>
          <div class="mt-3 flex flex-wrap gap-2">
            <Button variant="default" size="sm" onclick={handleConflictRegenerate}>
              {m.ai_builder_conflict_regenerate()}
            </Button>
            <Button variant="outline" size="sm" onclick={() => service.dismissConflict()}>
              {m.ai_builder_conflict_cancel()}
            </Button>
            <FlowAIBuilderDiagnosticCopyButton report={applyErrorDiagnosticReport} size="sm" />
          </div>
        </Alert.Root>
      </div>
    </div>
  {:else if showGenerationFailure}
    <!-- Report the failure without moving keyboard focus when no plan is available. -->
    <div class="flex flex-1 flex-col overflow-y-auto">
      <div class="mx-auto w-full max-w-[800px] px-4 py-6 md:px-6 @[1400px]/builder:max-w-[840px]">
        <div
          class="border-default bg-primary rounded-xl border p-5"
          role="status"
          aria-live="polite"
        >
          <div class="flex items-start gap-3">
            <svg
              xmlns="http://www.w3.org/2000/svg"
              viewBox="0 0 16 16"
              fill="currentColor"
              class="text-warning-stronger mt-0.5 size-4 shrink-0"
              aria-hidden="true"
            >
              <path
                fill-rule="evenodd"
                d="M6.701 2.25c.577-1 2.02-1 2.598 0l5.196 9a1.5 1.5 0 0 1-1.299 2.25H2.804a1.5 1.5 0 0 1-1.3-2.25l5.197-9ZM8 4a.75.75 0 0 1 .75.75v3a.75.75 0 0 1-1.5 0v-3A.75.75 0 0 1 8 4Zm0 8a1 1 0 1 0 0-2 1 1 0 0 0 0 2Z"
                clip-rule="evenodd"
              />
            </svg>
            <div class="min-w-0">
              <h2 class="text-primary text-sm font-semibold">
                {m.ai_builder_generation_failed_title()}
              </h2>
              <p class="text-secondary mt-1 text-[0.8125rem] leading-relaxed">
                {m.ai_builder_generation_failed_body()}
              </p>
              <div class="mt-3 flex flex-wrap items-center gap-2">
                {#if turnRecoveryState}
                  <Button
                    variant="default"
                    size="sm"
                    disabled={service.isStreaming || service.isRecoveringLatestTurn}
                    onclick={handleGenerationRetry}
                  >
                    {turnRecoveryState === "provider_outcome_unknown"
                      ? m.ai_builder_turn_retry_with_cost_acknowledgement()
                      : m.ai_builder_turn_retry()}
                  </Button>
                {/if}
                <Button
                  variant="outline"
                  size="sm"
                  class="@[1040px]/builder:hidden"
                  onclick={onshowconversation}
                >
                  {m.ai_builder_show_conversation()}
                </Button>
                <FlowAIBuilderDiagnosticCopyButton
                  report={generationErrorDiagnosticReport}
                  variant="ghost"
                  size="xs"
                />
              </div>
              <p class="text-muted mt-3 text-xs leading-relaxed">
                {m.ai_builder_generation_failed_late_note()}
              </p>
              <p class="text-muted mt-1 text-xs leading-relaxed">
                {m.ai_builder_generation_failed_clarify()}
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  {:else if service.statusMessage || service.isStreaming}
    <!-- Show only phases reported by the backend; do not simulate progress. -->
    <div class="flex flex-1 flex-col items-center justify-center px-4 text-center">
      <div class="progress-ring mb-4 size-10 rounded-full border-[3px]"></div>
      <p class="text-primary text-sm font-medium" role="status" aria-live="polite">
        {progressStatusLabel(service.statusMessage)}
      </p>
      <p class="text-muted mt-1 max-w-xs text-xs leading-relaxed">
        {m.ai_builder_wait_expectation()}
      </p>
      <p class="text-muted mt-4 hidden max-w-sm text-xs leading-relaxed @[1040px]/builder:block">
        {m.ai_builder_wait_footer_note()}
      </p>
    </div>
  {:else}
    <!-- Empty state ------------------------------------------------------ -->
    <div class="flex flex-1 flex-col items-center justify-center px-4 text-center">
      <div
        class="border-default bg-primary text-muted mb-4 flex size-14 items-center justify-center rounded-2xl border"
        aria-hidden="true"
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="1.5"
          class="size-7"
        >
          <path
            stroke-linecap="round"
            stroke-linejoin="round"
            d="M3.75 12h16.5m-16.5 3.75h16.5M3.75 19.5h16.5M5.625 4.5h12.75a1.875 1.875 0 0 1 0 3.75H5.625a1.875 1.875 0 0 1 0-3.75Z"
          />
        </svg>
      </div>
      <p class="text-secondary max-w-xs text-sm leading-relaxed">{m.ai_builder_plan_empty()}</p>
    </div>
  {/if}
</div>

<style lang="postcss">
  @reference "@eneo/ui/styles";

  .plan-card-enter {
    animation: plan-card-enter 200ms ease-out;
  }

  @keyframes plan-card-enter {
    from {
      opacity: 0;
    }
    to {
      opacity: 1;
    }
  }

  .section-enter {
    animation: plan-card-enter 200ms ease-out;
  }

  /* Diff strikethrough uses a muted decoration color that works in both themes. */
  .description-diff-old {
    text-decoration-color: var(--border-stronger);
  }

  /* Sentence-case section heading that doubles as a Collapsible trigger. */
  :global(.section-heading-trigger) {
    display: flex;
    width: 100%;
    align-items: center;
    gap: 0.5rem;
    background: transparent;
    border: none;
    padding: 0;
    color: var(--text-primary);
    font-size: 0.875rem;
    font-weight: 600;
    line-height: 1.3;
    text-align: left;
    cursor: pointer;
  }

  :global(.section-heading-trigger:focus-visible) {
    outline: 2px solid var(--accent-default);
    outline-offset: 2px;
    border-radius: var(--radius-sm);
  }

  /* Touch devices get the 44px target the pointer can't make up for.
     Physical px on purpose: the app's 15px root would shrink a rem floor. */
  @media (pointer: coarse) {
    :global(.section-heading-trigger) {
      min-height: 44px;
    }
  }

  .progress-ring {
    border-color: var(--border-default);
    border-top-color: var(--accent-default);
    animation: spin-slow 1s linear infinite;
  }

  @keyframes spin-slow {
    from {
      transform: rotate(0deg);
    }
    to {
      transform: rotate(360deg);
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .plan-card-enter,
    .section-enter {
      animation: none;
    }

    .progress-ring {
      animation: none;
    }
  }
</style>
