<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import * as Collapsible from "$lib/components/ui/collapsible/index.js";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import FlowAIBuilderStepCard from "./FlowAIBuilderStepCard.svelte";
  import FlowAIBuilderTokenUsage from "./FlowAIBuilderTokenUsage.svelte";
  import { getAIBuilderService } from "./FlowAIBuilderService.svelte.ts";
  import type { AIBuilderSuggestChangeIntent, EditAdvisory } from "./protocol";
  import {
    buildAIBuilderMcpResourceLabelMaps,
    type AIBuilderMcpServerLike
  } from "./flowAIBuilderMcpResources";
  import {
    getFirstChangedStepIndex,
    getRemovedStepChanges,
    getStepChangeKind
  } from "./flowAIBuilderPlanDiff";

  interface Props {
    onapplied?: (detail: { flow_id: string; focusStepIndex: number | null }) => void;
    onsuggestchange?: (intent: AIBuilderSuggestChangeIntent) => void;
  }

  let { onapplied, onsuggestchange }: Props = $props();

  const service = getAIBuilderService();
  const {
    state: { currentSpace }
  } = getSpacesManager();

  // ---- Derivations ---------------------------------------------------------

  const descriptionDiff = $derived.by(() => {
    const plan = service.currentPlan;
    if (!plan?.edit_diff?.flow_property_changes) return null;
    const change = plan.edit_diff.flow_property_changes["flow_description"];
    if (!change) return null;
    return { previous: String(change[0] ?? ""), proposed: String(change[1] ?? "") };
  });

  const advisories = $derived<EditAdvisory[]>(service.currentPlan?.edit_advisories ?? []);
  const hasDescriptionAdvisory = $derived(
    advisories.some((a) => a.code === "flow_description_update_required")
  );
  const otherAdvisories = $derived(
    advisories.filter((a) => a.code !== "flow_description_update_required")
  );

  const isPublishedError = $derived(service.applyError?.code === "flow_is_published");
  const publishedVersion = $derived(
    isPublishedError ? (service.applyError?.context?.published_version as number | null) : null
  );

  function resolveModelName(ref: string | null): string | null {
    if (!ref) return null;
    return service.availableModels.find((model) => model.id === ref)?.name ?? ref;
  }

  const mcpResourceLabels = $derived(
    buildAIBuilderMcpResourceLabelMaps(
      ($currentSpace.mcp_servers ?? []) as unknown as AIBuilderMcpServerLike[]
    )
  );

  function resolveMcpServerName(ref: string): string | null {
    return mcpResourceLabels.serverLabels.get(ref) ?? null;
  }

  function resolveMcpToolName(ref: string): string | null {
    return mcpResourceLabels.toolLabels.get(ref) ?? null;
  }

  let isApproving = $state(false);
  let isApplying = $state(false);

  const removedStepChanges = $derived(
    getRemovedStepChanges(service.currentPlan?.edit_diff ?? null)
  );
  const focusStepIndex = $derived.by(() => {
    const plan = service.currentPlan;
    if (!plan) return null;
    return getFirstChangedStepIndex(plan.envelope.spec.steps, plan.edit_diff ?? null);
  });

  const attachments = $derived(service.session?.attachments ?? []);
  const attachmentWarnings = $derived(service.session?.attachment_warnings ?? []);
  const hasAttachments = $derived(attachments.length > 0);

  const stepCount = $derived(service.currentPlan?.envelope.spec.steps.length ?? 0);

  // Latch: stays true once a plan has been seen during this session so the progress
  // copy can differentiate "Building your flow" from "Updating your plan". Using a
  // reactive latch here is intentional — the value must persist across the brief
  // window when `currentPlan` becomes null during a re-plan stream.
  let hadPlanBefore = $state(false);
  $effect(() => {
    if (service.currentPlan) hadPlanBefore = true;
    if (!service.hasSession) hadPlanBefore = false;
  });

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

  async function handleApply() {
    if (isApplying) return;
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

<div class="bg-secondary/40 flex flex-col md:min-h-0 md:flex-1">
  {#if service.currentPlan}
    {@const plan = service.currentPlan}
    {@const spec = plan.envelope.spec}

    <!-- Scrollable on md+, natural flow on mobile (page scroll handles it) -->
    <div class="md:flex-1 md:overflow-y-auto">
      <div class="mx-auto flex max-w-3xl flex-col gap-4 px-4 py-5 md:px-6 md:py-6">
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
                <Badge variant="outline" class="h-5 px-1.5 text-[10.5px] tabular-nums">
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

              <Collapsible.Content>
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
                          class="text-muted shrink-0 font-mono text-[10.5px] tabular-nums"
                          aria-label="File size"
                        >
                          {Math.max(1, Math.round(file.size / 1024))} KB
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
                class="bg-accent-default/8 border-accent-default/25 text-accent-stronger h-5 px-1.5 text-[10px] font-semibold tracking-wide uppercase"
              >
                {m.ai_builder_draft_pill()}
              </Badge>
              <span class="text-muted text-xs tabular-nums">
                {m.flow_run_step_count({ count: stepCount })}
              </span>
              <span class="text-muted text-xs">·</span>
              <span class="text-muted text-xs">{m.ai_builder_phase_reviewing()}</span>
              <FlowAIBuilderTokenUsage telemetry={service.session?.telemetry} />
            </div>
            <h2
              id="plan-heading"
              class="text-primary text-[1.125rem] leading-tight font-semibold tracking-[-0.015em]"
            >
              {spec.flow_name}
            </h2>
            {#if spec.flow_description && !descriptionDiff && !hasDescriptionAdvisory}
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
              <h3 class="text-muted mb-2 text-[11px] font-semibold tracking-[0.06em] uppercase">
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
                  >
                    {m.ai_builder_description_keep_current()}
                  </Button>
                </div>
              {/if}
            </section>
          {/if}

          <!-- Plan rationale -->
          {#if plan.envelope.plan_rationale}
            <section class="border-default border-t px-5 py-4 md:px-6">
              <h3 class="text-muted mb-1.5 text-[11px] font-semibold tracking-[0.06em] uppercase">
                {m.ai_builder_plan_rationale()}
              </h3>
              <p
                class="border-default bg-secondary/35 text-secondary rounded-lg border px-3 py-2 text-[0.8125rem] leading-relaxed"
              >
                {plan.envelope.plan_rationale}
              </p>
            </section>
          {/if}

          <!-- Assumptions -->
          {#if plan.envelope.assumptions.length > 0}
            <section class="border-default border-t px-5 py-4 md:px-6">
              <h3 class="text-muted mb-2 text-[11px] font-semibold tracking-[0.06em] uppercase">
                {m.ai_builder_assumptions()}
              </h3>
              <ul class="text-secondary flex flex-col gap-1.5 text-[0.8125rem] leading-relaxed">
                {#each plan.envelope.assumptions as assumption (assumption)}
                  <li class="flex items-start gap-2">
                    <span
                      class="bg-muted mt-[0.55em] block size-1 shrink-0 rounded-full opacity-60"
                      aria-hidden="true"
                    ></span>
                    <span>{assumption}</span>
                  </li>
                {/each}
              </ul>
            </section>
          {/if}

          <!-- Edit advisories (non-description) -->
          {#if otherAdvisories.length > 0}
            <section class="border-default border-t px-5 py-4 md:px-6" aria-live="polite">
              <h3 class="text-muted mb-2 text-[11px] font-semibold tracking-[0.06em] uppercase">
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
              <h3 class="text-muted mb-2 text-[11px] font-semibold tracking-[0.06em] uppercase">
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
                        class="border-default text-muted bg-primary rounded-full border px-1.5 py-0.5 font-mono text-[10px]"
                      >
                        {field.type}
                      </span>
                    </div>
                    <div class="text-muted flex flex-wrap items-center gap-x-2 text-[11.5px]">
                      <span class="font-mono">{field.name}</span>
                      <span>·</span>
                      <span>
                        {field.required
                          ? m.ai_builder_form_field_required()
                          : m.ai_builder_form_field_optional()}
                      </span>
                    </div>
                    {#if field.options && field.options.length > 0}
                      <div class="mt-2 flex flex-wrap gap-1">
                        {#each field.options as option (option)}
                          <span
                            class="border-default text-secondary rounded-full border px-2 py-0.5 text-[11px]"
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
          {#if plan.envelope.lint_warnings.length > 0}
            <section class="border-default border-t px-5 py-4 md:px-6">
              <h3
                class="text-warning-stronger mb-2 flex items-center gap-1.5 text-[11px] font-semibold tracking-[0.06em] uppercase"
              >
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
              <ul class="flex flex-col gap-1.5">
                {#each plan.envelope.lint_warnings as warning (`${warning.step_ref ?? "flow"}-${warning.code}-${warning.message}`)}
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

          <!-- Steps -->
          <section class="border-default border-t px-5 py-4 md:px-6">
            <h3 class="text-muted mb-3 text-[11px] font-semibold tracking-[0.06em] uppercase">
              {m.flow_steps()}
            </h3>
            <div class="flex flex-col">
              {#each spec.steps as step, i (step.plan_step_ref)}
                <FlowAIBuilderStepCard
                  {step}
                  stepNumber={i + 1}
                  planId={plan.plan_id}
                  changeKind={getStepChangeKind(step, plan.edit_diff ?? null)}
                  {resolveModelName}
                  {resolveMcpServerName}
                  {resolveMcpToolName}
                  isFirst={i === 0}
                  isLast={i === spec.steps.length - 1}
                  planStatus={plan.status}
                  onsuggestchange={(intent) => onsuggestchange?.(intent)}
                />
              {/each}
            </div>
          </section>

          <!-- Removed steps -->
          {#if removedStepChanges.length > 0}
            <section class="border-default border-t px-5 py-4 md:px-6">
              <h3 class="text-muted mb-2 text-[11px] font-semibold tracking-[0.06em] uppercase">
                {m.ai_builder_removed_steps_title()}
              </h3>
              <ul class="flex flex-col gap-1">
                {#each removedStepChanges as change (`${change.step_ref ?? change.step_name}-${change.kind}`)}
                  <li class="text-muted flex items-center gap-2 py-1 text-[0.8125rem] leading-snug">
                    <Badge
                      variant="outline"
                      class="border-warning-default/25 bg-warning-dimmer text-warning-stronger h-5 shrink-0 px-1.5 text-[10px] font-semibold tracking-wide uppercase"
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
        <div class="mx-auto max-w-3xl px-4 py-3 md:px-6">
          <Alert.Title class="text-warning-stronger text-[0.8125rem] font-semibold">
            {m.ai_builder_published_flow_title()}
          </Alert.Title>
          <Alert.Description class="text-warning-stronger/80 mt-0.5 text-xs leading-relaxed">
            {m.ai_builder_published_flow_description({
              version: String(publishedVersion ?? "")
            })}
          </Alert.Description>
          <div class="mt-2">
            <Button variant="outline" size="sm" onclick={() => service.dismissApplyError()}>
              {m.ai_builder_conflict_cancel()}
            </Button>
          </div>
        </div>
      </Alert.Root>
    {/if}

    <!-- Sticky action bar ----------------------------------------------------->
    <div
      class="plan-actions border-default bg-primary/85 supports-[not(backdrop-filter:blur(0))]:bg-primary relative shrink-0 border-t backdrop-blur-sm"
    >
      <div
        class="mx-auto flex max-w-3xl flex-col-reverse items-stretch gap-2 px-4 py-3 sm:flex-row sm:items-center sm:justify-end md:px-6"
      >
        {#if !service.applyResult && service.canApprove}
          <Button
            variant="ghost"
            size="sm"
            class="max-sm:min-h-11 max-sm:w-full"
            onclick={() =>
              onsuggestchange?.({
                placeholder: m.ai_builder_plan_change_placeholder(),
                editContext: {
                  scope: "whole_plan",
                  plan_id: plan.plan_id
                }
              })}
            disabled={isApproving || isApplying}
          >
            {m.ai_builder_plan_suggest_change()}
          </Button>
        {/if}

        {#if !service.applyResult}
          <Button
            variant="ghost"
            size="sm"
            class="max-sm:min-h-11 max-sm:w-full"
            onclick={handleModify}
            disabled={isApproving || isApplying}
          >
            {m.ai_builder_modify()}
          </Button>
        {/if}

        {#if service.canApprove}
          <Button
            variant="default"
            size="sm"
            class="max-sm:min-h-11 max-sm:w-full"
            onclick={handleApprove}
            disabled={isApproving || isApplying}
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
            disabled={isApproving || isApplying}
          >
            {isApplying ? m.ai_builder_applying() : m.ai_builder_apply()}
          </Button>
        {/if}
      </div>
    </div>
  {:else if service.isConflict}
    <!-- Conflict state without a plan yet --------------------------------- -->
    <div class="flex flex-1 flex-col overflow-y-auto">
      <div class="mx-auto w-full max-w-3xl px-4 py-6 md:px-6">
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
          </div>
        </Alert.Root>
      </div>
    </div>
  {:else if service.statusMessage || service.isStreaming}
    <!-- Progress state --------------------------------------------------- -->
    <div class="flex flex-1 flex-col items-center justify-center px-4 text-center">
      <div class="progress-ring mb-4 size-10 rounded-full border-[3px]"></div>
      <p class="text-primary text-sm font-medium">
        {#if service.statusMessage === "validating"}
          {m.ai_builder_status_validating()}
        {:else if service.statusMessage === "repairing"}
          {m.ai_builder_status_repairing()}
        {:else if service.statusMessage === "finalizing_plan"}
          {m.ai_builder_status_finalizing_plan()}
        {:else if hadPlanBefore}
          {m.ai_builder_updating_plan()}
        {:else}
          {m.ai_builder_generating()}
        {/if}
      </p>
      <p class="text-muted mt-1 text-xs">{m.ai_builder_status_patience()}</p>
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
  @reference "@intric/ui/styles";

  .plan-card-enter {
    animation: plan-card-enter 0.5s cubic-bezier(0.16, 1, 0.3, 1);
  }

  @keyframes plan-card-enter {
    from {
      opacity: 0;
      transform: translateY(0.5rem);
    }
    to {
      opacity: 1;
      transform: translateY(0);
    }
  }

  .section-enter {
    animation: section-enter 0.3s cubic-bezier(0.16, 1, 0.3, 1);
  }

  @keyframes section-enter {
    from {
      opacity: 0;
      transform: translateY(0.25rem);
    }
    to {
      opacity: 1;
      transform: translateY(0);
    }
  }

  /* Diff strikethrough uses a muted decoration color that works in both themes. */
  .description-diff-old {
    text-decoration-color: oklch(from var(--text-muted) l c h / 0.45);
  }

  .progress-ring {
    border-color: oklch(from var(--accent-default) l c h / 0.15);
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

  /* Subtle gradient fade above the sticky action bar so content appears
     to slide underneath rather than getting clipped. */
  .plan-actions::before {
    content: "";
    position: absolute;
    top: -1.5rem;
    left: 0;
    right: 0;
    height: 1.5rem;
    background: linear-gradient(to top, var(--background-primary), transparent);
    pointer-events: none;
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
