<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Separator } from "$lib/components/ui/separator/index.js";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import * as Card from "$lib/components/ui/card/index.js";
  import FlowAIBuilderStepCard from "./FlowAIBuilderStepCard.svelte";
  import { getAIBuilderService } from "./FlowAIBuilderService.svelte.ts";
  import type { EditAdvisory } from "./protocol";
  import {
    getFirstChangedStepIndex,
    getRemovedStepChanges,
    getStepChangeKind
  } from "./flowAIBuilderPlanDiff";
  interface Props {
    onapplied?: (detail: { flow_id: string; focusStepIndex: number | null }) => void;
    onsuggestchange?: (prefill: string) => void;
  }

  let { onapplied, onsuggestchange }: Props = $props();

  const service = getAIBuilderService();

  // Description diff helpers
  let descriptionDiff = $derived.by(() => {
    const plan = service.currentPlan;
    if (!plan?.edit_diff?.flow_property_changes) return null;
    const change = plan.edit_diff.flow_property_changes["flow_description"];
    if (!change) return null;
    return { previous: String(change[0] ?? ""), proposed: String(change[1] ?? "") };
  });

  let advisories = $derived<EditAdvisory[]>(service.currentPlan?.edit_advisories ?? []);

  let hasDescriptionAdvisory = $derived(
    advisories.some((a) => a.code === "flow_description_update_required")
  );

  let isPublishedError = $derived(service.applyError?.code === "flow_is_published");

  let publishedVersion = $derived(
    isPublishedError ? (service.applyError?.context?.published_version as number | null) : null
  );

  function resolveModelName(ref: string | null): string | null {
    if (!ref) return null;
    return service.availableModels.find((m) => m.id === ref)?.name ?? ref;
  }

  let isApproving = $state(false);
  let isApplying = $state(false);
  let removedStepChanges = $derived(getRemovedStepChanges(service.currentPlan?.edit_diff ?? null));
  let focusStepIndex = $derived.by(() => {
    const plan = service.currentPlan;
    if (!plan) return null;
    return getFirstChangedStepIndex(plan.envelope.spec.steps, plan.edit_diff ?? null);
  });

  // Track whether a plan existed before streaming started (for context-aware progress text)
  let hadPlanBefore = $state(false);

  $effect(() => {
    if (service.currentPlan) {
      hadPlanBefore = true;
    }
    if (!service.hasSession) {
      hadPlanBefore = false;
    }
  });

  async function handleApprove() {
    if (isApproving) return; // Guard against double-clicks
    isApproving = true;
    try {
      await service.approvePlan();
    } catch {
      // Error or conflict is set on service
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
      // Error or conflict is set on service
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

<div class="flex min-h-0 flex-1 flex-col">
  {#if service.currentPlan}
    {@const plan = service.currentPlan}
    {@const spec = plan.envelope.spec}

    <!-- Scrollable content area -->
    <div class="flex-1 overflow-y-auto p-4 md:p-6">
      {#if service.isConflict}
        <!-- Conflict recovery banner -->
        <Alert.Root class="border-warning-default bg-warning-dimmer mb-4 rounded-xl">
          <Alert.Title class="text-warning-stronger text-sm font-semibold">
            {m.ai_builder_conflict_title()}
          </Alert.Title>
          <Alert.Description class="text-warning-default mt-1 text-xs leading-relaxed">
            {m.ai_builder_conflict_description()}
          </Alert.Description>
          <div class="mt-3 flex gap-2">
            <Button variant="default" size="sm" onclick={handleConflictRegenerate}>
              {m.ai_builder_conflict_regenerate()}
            </Button>
            <Button variant="outline" size="sm" onclick={() => service.dismissConflict()}>
              {m.ai_builder_conflict_cancel()}
            </Button>
          </div>
        </Alert.Root>
      {/if}

      <!-- Plan card -->
      <Card.Root
        class="plan-card-enter mx-auto max-w-3xl shadow-[0_20px_40px_-15px_rgba(0,0,0,0.05),0_1px_3px_rgba(0,0,0,0.02)]"
      >
        <!-- Header -->
        <Card.Header class="px-6 pt-6 pb-0">
          <Card.Title class="text-primary text-lg font-semibold tracking-tight"
            >{spec.flow_name}</Card.Title
          >
          {#if spec.flow_description && !descriptionDiff && !hasDescriptionAdvisory}
            <Card.Description
              class="text-secondary mt-1 text-[0.8125rem] leading-relaxed break-words"
              >{spec.flow_description}</Card.Description
            >
          {/if}
        </Card.Header>

        <!-- Description diff -- flat layout, no nested cards -->
        {#if descriptionDiff || hasDescriptionAdvisory}
          <div class="section-enter border-default border-t px-6 py-4" aria-live="polite">
            <p class="text-secondary mb-2 text-[0.8125rem] font-medium">
              {m.ai_builder_description_diff_title()}
            </p>
            {#if descriptionDiff}
              <div class="flex flex-col gap-3">
                <p
                  class="description-diff-old text-muted text-[0.8125rem] leading-relaxed break-words line-through"
                  aria-label={m.ai_builder_description_current()}
                >
                  {descriptionDiff.previous}
                </p>
                <p
                  class="border-accent-default text-primary border-l-[3px] pl-3 text-[0.8125rem] leading-relaxed break-words"
                  aria-label={m.ai_builder_description_proposed()}
                >
                  {descriptionDiff.proposed}
                </p>
              </div>
            {:else if hasDescriptionAdvisory}
              <p class="text-secondary mb-3 text-[0.8125rem] leading-relaxed">
                {advisories.find((a) => a.code === "flow_description_update_required")?.message}
              </p>
              <div class="flex flex-wrap gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onclick={() => service.revisePlan("keep_current_description")}
                >
                  {m.ai_builder_description_keep_current()}
                </Button>
              </div>
            {/if}
          </div>
        {/if}

        <!-- Edit advisories (non-description) -->
        {#if advisories.filter((a) => a.code !== "flow_description_update_required").length > 0}
          <Alert.Root
            class="border-warning-default bg-warning-dimmer mx-6 mb-3 rounded-lg px-4 py-3"
            aria-live="polite"
          >
            <Alert.Title class="text-warning-stronger text-[0.8125rem] font-semibold"
              >{m.ai_builder_advisory_section_title()}</Alert.Title
            >
            {#each advisories.filter((a) => a.code !== "flow_description_update_required") as advisory (advisory.code)}
              <div
                class="mb-1 rounded-md px-2.5 py-1.5 text-[0.8125rem] leading-relaxed
                {advisory.severity === 'info' ? 'bg-info-dimmer text-info-default' : ''}
                {advisory.severity === 'warning' ? 'bg-warning-dimmer text-warning-stronger' : ''}
                {advisory.severity === 'error' ? 'bg-negative-dimmer text-negative-default' : ''}"
              >
                <span>{advisory.message}</span>
              </div>
            {/each}
          </Alert.Root>
        {/if}

        <!-- Assumptions -->
        {#if plan.envelope.assumptions.length > 0}
          <div class="border-default bg-secondary/30 mx-6 mb-4 rounded-lg border px-4 py-3">
            <p class="text-primary mb-1.5 text-sm font-semibold">
              {m.ai_builder_assumptions()}
            </p>
            <ul class="text-secondary flex flex-col gap-1.5 text-sm leading-relaxed">
              {#each plan.envelope.assumptions as assumption (assumption)}
                <li class="flex items-start gap-2">
                  <span class="mt-2 block size-1 shrink-0 rounded-full bg-current opacity-40"
                  ></span>
                  <span>{assumption}</span>
                </li>
              {/each}
            </ul>
          </div>
        {/if}

        {#if plan.envelope.plan_rationale}
          <div class="border-default border-t px-6 py-4">
            <p class="text-primary mb-1 text-sm font-medium">
              {m.ai_builder_plan_rationale()}
            </p>
            <p class="text-secondary text-sm leading-relaxed">
              {plan.envelope.plan_rationale}
            </p>
          </div>
        {/if}

        {#if spec.form_fields && spec.form_fields.length > 0}
          <div class="border-default border-t px-6 py-4">
            <p class="text-primary mb-1.5 text-[0.8125rem] font-medium">
              {m.ai_builder_form_fields_title()}
            </p>
            <div class="grid gap-3 sm:grid-cols-2">
              {#each spec.form_fields as field (`${field.name}-${field.type}`)}
                <div class="border-default bg-secondary rounded-[0.625rem] border p-3">
                  <div class="mb-1 flex flex-wrap items-center justify-between gap-2">
                    <span class="text-primary text-[0.8125rem] font-semibold">{field.label}</span>
                    <span
                      class="border-default bg-primary text-secondary rounded-full border px-2 py-0.5 text-xs"
                      >{field.type}</span
                    >
                  </div>
                  <div class="text-secondary flex flex-wrap items-center gap-2 text-xs">
                    <span>{field.name}</span>
                    <span
                      >{field.required
                        ? m.ai_builder_form_field_required()
                        : m.ai_builder_form_field_optional()}</span
                    >
                  </div>
                  {#if field.options && field.options.length > 0}
                    <div class="mt-2 flex flex-wrap items-center gap-2">
                      {#each field.options as option (option)}
                        <span
                          class="border-default bg-primary text-secondary rounded-full border px-2 py-0.5 text-xs"
                          >{option}</span
                        >
                      {/each}
                    </div>
                  {/if}
                </div>
              {/each}
            </div>
          </div>
        {/if}

        <!-- Lint warnings -->
        {#if plan.envelope.lint_warnings.length > 0}
          <Alert.Root
            class="border-warning-default bg-warning-dimmer mx-6 mb-6 rounded-lg px-5 py-4"
          >
            <div class="mb-2 flex items-center gap-1.5">
              <svg
                xmlns="http://www.w3.org/2000/svg"
                viewBox="0 0 16 16"
                fill="currentColor"
                class="text-warning-stronger size-3.5 shrink-0"
              >
                <path
                  fill-rule="evenodd"
                  d="M6.701 2.25c.577-1 2.02-1 2.598 0l5.196 9a1.5 1.5 0 0 1-1.299 2.25H2.804a1.5 1.5 0 0 1-1.3-2.25l5.197-9ZM8 4a.75.75 0 0 1 .75.75v3a.75.75 0 0 1-1.5 0v-3A.75.75 0 0 1 8 4Zm0 8a1 1 0 1 0 0-2 1 1 0 0 0 0 2Z"
                  clip-rule="evenodd"
                />
              </svg>
              <span class="text-warning-stronger text-[0.8125rem] font-semibold"
                >{m.ai_builder_quality_warnings()}</span
              >
            </div>
            <ul class="flex flex-col gap-1.5">
              {#each plan.envelope.lint_warnings as warning (`${warning.step_ref ?? "flow"}-${warning.code}-${warning.message}`)}
                <li
                  class="lint-item text-warning-stronger relative pl-5 text-[0.8125rem] leading-relaxed"
                >
                  {#if warning.step_ref}
                    <span class="mr-1 font-semibold">{warning.step_ref}:</span>
                  {/if}
                  <span>{warning.message}</span>
                </li>
              {/each}
            </ul>
          </Alert.Root>
        {/if}

        <!-- Steps -->
        <Card.Content class="px-6 pb-6">
          {#each spec.steps as step, i (step.plan_step_ref)}
            <FlowAIBuilderStepCard
              {step}
              stepNumber={i + 1}
              changeKind={getStepChangeKind(step, plan.edit_diff ?? null)}
              {resolveModelName}
              isFirst={i === 0}
              isLast={i === spec.steps.length - 1}
              planStatus={plan.status}
              onsuggestchange={(prefill) => onsuggestchange?.(prefill)}
            />
          {/each}
        </Card.Content>

        {#if removedStepChanges.length > 0}
          <div class="mx-6 mb-6">
            <Separator class="mb-4" />
            <p class="text-primary mb-2 text-[0.8125rem] font-semibold tracking-tight">
              {m.ai_builder_removed_steps_title()}
            </p>
            <ul class="flex flex-col gap-2">
              {#each removedStepChanges as change (`${change.step_ref ?? change.step_name}-${change.kind}`)}
                <li
                  class="border-default bg-secondary flex items-center gap-2.5 rounded-xl border border-dashed px-3.5 py-3"
                >
                  <Badge
                    variant="outline"
                    class="border-warning-default/20 bg-warning-dimmer text-warning-stronger text-[0.6875rem] font-bold tracking-wide uppercase"
                    >{m.ai_builder_badge_removed()}</Badge
                  >
                  <span class="text-primary text-sm font-medium">{change.step_name}</span>
                </li>
              {/each}
            </ul>
          </div>
        {/if}
      </Card.Root>

      <!-- Applied result -->
      {#if service.applyResult}
        <Alert.Root class="border-positive-default/40 bg-positive-dimmer mt-4 rounded-xl px-5 py-4">
          <Alert.Title class="text-positive-stronger text-sm font-medium">
            {m.ai_builder_applied_success()}
          </Alert.Title>
          <Alert.Description class="text-positive-default mt-1 text-xs">
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

    <!-- Published flow banner -- near actions where the error originated -->
    {#if isPublishedError}
      <Alert.Root
        class="border-warning-default bg-warning-dimmer shrink-0 rounded-none border-x-0 border-b-0 px-4 py-3"
        aria-live="polite"
      >
        <Alert.Title class="text-warning-stronger text-[0.8125rem] font-semibold"
          >{m.ai_builder_published_flow_title()}</Alert.Title
        >
        <Alert.Description class="text-warning-default mt-1 text-[0.8125rem] leading-relaxed">
          {m.ai_builder_published_flow_description({ version: String(publishedVersion ?? "") })}
        </Alert.Description>
        <div class="mt-2">
          <Button variant="outline" size="sm" onclick={() => service.dismissApplyError()}>
            {m.ai_builder_conflict_cancel()}
          </Button>
        </div>
      </Alert.Root>
    {/if}

    <!-- Action buttons -- pinned at bottom, always visible -->
    <div
      class="plan-actions border-default bg-primary relative flex shrink-0 flex-col gap-2 border-t px-4 pt-3 pb-4 sm:flex-row"
    >
      {#if service.canApprove}
        <Button variant="positive" onclick={handleApprove} disabled={isApproving || isApplying}>
          {isApproving ? m.ai_builder_approving() : m.ai_builder_approve()}
        </Button>
      {/if}

      {#if service.canApply}
        <Button variant="default" onclick={handleApply} disabled={isApproving || isApplying}>
          {isApplying ? m.ai_builder_applying() : m.ai_builder_apply()}
        </Button>
      {/if}

      {#if !service.applyResult}
        <Button variant="outline" onclick={handleModify} disabled={isApproving || isApplying}>
          {m.ai_builder_modify()}
        </Button>
      {/if}
    </div>
  {:else if service.isConflict}
    <!-- Conflict recovery banner (no plan state) -->
    <div class="flex-1 overflow-y-auto p-4 md:p-6">
      <Alert.Root class="border-warning-default bg-warning-dimmer rounded-xl px-5 py-4">
        <Alert.Title class="text-warning-stronger text-sm font-semibold">
          {m.ai_builder_conflict_title()}
        </Alert.Title>
        <Alert.Description class="text-warning-default mt-1 text-xs leading-relaxed">
          {m.ai_builder_conflict_description()}
        </Alert.Description>
        <div class="mt-3 flex gap-2">
          <Button variant="default" size="sm" onclick={handleConflictRegenerate}>
            {m.ai_builder_conflict_regenerate()}
          </Button>
          <Button variant="outline" size="sm" onclick={() => service.dismissConflict()}>
            {m.ai_builder_conflict_cancel()}
          </Button>
        </div>
      </Alert.Root>
    </div>
  {:else if service.statusMessage || service.isStreaming}
    <!-- Progress state -->
    <div class="flex flex-1 flex-col items-center justify-center text-center opacity-65">
      <div class="progress-ring mb-5 size-12 rounded-full border-[3px]"></div>
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
    <!-- Empty state -->
    <div class="flex flex-1 flex-col items-center justify-center text-center opacity-65">
      <div
        class="border-default bg-primary text-muted mb-4 flex size-14 items-center justify-center rounded-2xl border"
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="1.5"
          class="size-8"
        >
          <path
            stroke-linecap="round"
            stroke-linejoin="round"
            d="M3.75 12h16.5m-16.5 3.75h16.5M3.75 19.5h16.5M5.625 4.5h12.75a1.875 1.875 0 0 1 0 3.75H5.625a1.875 1.875 0 0 1 0-3.75Z"
          />
        </svg>
      </div>
      <p class="text-secondary text-sm">{m.ai_builder_plan_empty()}</p>
    </div>
  {/if}
</div>

<style lang="postcss">
  @reference "@intric/ui/styles";

  /* Animations that require @keyframes -- cannot be expressed as Tailwind utilities */
  .plan-card-enter {
    animation: plan-card-enter 0.6s cubic-bezier(0.16, 1, 0.3, 1);
  }

  @keyframes plan-card-enter {
    from {
      opacity: 0;
      transform: translateY(1rem);
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
      transform: translateY(0.5rem);
    }
    to {
      opacity: 1;
      transform: translateY(0);
    }
  }

  /* Description diff strikethrough -- oklch relative color not safe in Tailwind arbitrary values */
  .description-diff-old {
    text-decoration-color: oklch(from var(--text-muted) l c h / 0.4);
  }

  /* Lint bullet -- ::before pseudo-element with positioning */
  .lint-item::before {
    content: "";
    position: absolute;
    left: 0.375rem;
    top: 0.55em;
    width: 0.25rem;
    height: 0.25rem;
    border-radius: 9999px;
    background: currentColor;
    opacity: 0.5;
  }

  /* Progress spinner -- requires border-color from CSS custom property with oklch */
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

  /* Gradient fade above action bar -- ::before with linear-gradient */
  .plan-actions::before {
    content: "";
    position: absolute;
    top: -2rem;
    left: 0;
    right: 0;
    height: 2rem;
    background: linear-gradient(to top, var(--bg-primary), transparent);
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
