<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import { Button } from "@intric/ui";
  import FlowAIBuilderStepCard from "./FlowAIBuilderStepCard.svelte";
  import { getAIBuilderService } from "./FlowAIBuilderService.svelte.ts";
  interface Props {
    onapplied?: (detail: { flow_id: string }) => void;
    onsuggestchange?: (prefill: string) => void;
  }

  let { onapplied, onsuggestchange }: Props = $props();

  const service = getAIBuilderService();

  function resolveModelName(ref: string | null): string | null {
    if (!ref) return null;
    return service.availableModels.find((m) => m.id === ref)?.name ?? ref;
  }

  let isApproving = $state(false);
  let isApplying = $state(false);
  let planRevisionRequested = $state(false);

  // Track whether a plan existed before streaming started (for context-aware progress text)
  let hadPlanBefore = $state(false);

  // Reset muted state when a new plan arrives
  $effect(() => {
    if (service.currentPlan) {
      planRevisionRequested = false;
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
      onapplied?.({ flow_id: result.flow_id });
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
    planRevisionRequested = true;
    service.changeRequirements();
  }

  function handleConflictRegenerate() {
    service.dismissPlanPane();
  }
</script>

<div class="plan-pane">
  {#if planRevisionRequested}
    <div class="revision-overlay">
      <div class="revision-overlay-content">
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" class="size-5 animate-spin-slow">
          <path stroke-linecap="round" stroke-linejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0 3.181 3.183a8.25 8.25 0 0 0 13.803-3.7M4.031 9.865a8.25 8.25 0 0 1 13.803-3.7l3.181 3.182" />
        </svg>
        <span>{m.ai_builder_modifying_plan()}</span>
      </div>
    </div>
  {/if}
  {#if service.currentPlan}
    {@const plan = service.currentPlan}
    {@const spec = plan.envelope.spec}

    <!-- Scrollable content area -->
    <div class="plan-scroll">
      {#if service.isConflict}
        <!-- Conflict recovery banner -->
        <div class="conflict-banner">
          <h4 class="text-warning-stronger text-sm font-semibold">
            {m.ai_builder_conflict_title()}
          </h4>
          <p class="text-warning-default mt-1 text-xs leading-relaxed">
            {m.ai_builder_conflict_description()}
          </p>
          <div class="mt-3 flex gap-2">
            <Button variant="primary" size="small" onclick={handleConflictRegenerate}>
              {m.ai_builder_conflict_regenerate()}
            </Button>
            <Button variant="outlined" size="small" onclick={() => service.dismissConflict()}>
              {m.ai_builder_conflict_cancel()}
            </Button>
          </div>
        </div>
      {/if}

      <!-- Plan card -->
      <div class="plan-card">
        <!-- Header -->
        <div class="plan-header">
          <h3 class="text-primary text-lg font-semibold tracking-tight">{spec.flow_name}</h3>
          {#if spec.flow_description}
            <p class="text-secondary mt-1.5 text-[0.8125rem] leading-relaxed">{spec.flow_description}</p>
          {/if}
        </div>

        <!-- Assumptions -->
        {#if plan.envelope.assumptions.length > 0}
          <div class="assumptions-section">
            <p class="text-primary mb-2 text-[0.8125rem] font-semibold tracking-tight">
              {m.ai_builder_assumptions()}
            </p>
            <ul class="text-secondary space-y-1.5 text-[0.8125rem] leading-relaxed">
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
          <div class="rationale-section">
            <p class="text-primary mb-1.5 text-[0.8125rem] font-medium">{m.ai_builder_plan_rationale()}</p>
            <p class="text-secondary text-[0.8125rem] leading-relaxed">{plan.envelope.plan_rationale}</p>
          </div>
        {/if}

        {#if spec.form_fields && spec.form_fields.length > 0}
          <div class="form-fields-section">
            <p class="text-primary mb-1.5 text-[0.8125rem] font-medium">
              {m.ai_builder_form_fields_title()}
            </p>
            <div class="form-fields-list">
              {#each spec.form_fields as field (`${field.name}-${field.type}`)}
                <div class="form-field-card">
                  <div class="form-field-header">
                    <span class="form-field-label">{field.label}</span>
                    <span class="form-field-type">{field.type}</span>
                  </div>
                  <div class="form-field-meta">
                    <span>{field.name}</span>
                    <span>{field.required ? m.ai_builder_form_field_required() : m.ai_builder_form_field_optional()}</span>
                  </div>
                  {#if field.options && field.options.length > 0}
                    <div class="form-field-options">
                      {#each field.options as option (option)}
                        <span class="form-field-option">{option}</span>
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
          <div class="lint-section">
            <div class="lint-header">
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" class="lint-icon">
                <path fill-rule="evenodd" d="M6.701 2.25c.577-1 2.02-1 2.598 0l5.196 9a1.5 1.5 0 0 1-1.299 2.25H2.804a1.5 1.5 0 0 1-1.3-2.25l5.197-9ZM8 4a.75.75 0 0 1 .75.75v3a.75.75 0 0 1-1.5 0v-3A.75.75 0 0 1 8 4Zm0 8a1 1 0 1 0 0-2 1 1 0 0 0 0 2Z" clip-rule="evenodd" />
              </svg>
              <span class="lint-title">{m.ai_builder_quality_warnings()}</span>
            </div>
            <ul class="lint-list">
              {#each plan.envelope.lint_warnings as warning (`${warning.step_ref ?? "flow"}-${warning.code}-${warning.message}`)}
                <li class="lint-item">
                  {#if warning.step_ref}
                    <span class="lint-ref">{warning.step_ref}:</span>
                  {/if}
                  <span>{warning.message}</span>
                </li>
              {/each}
            </ul>
          </div>
        {/if}

        <!-- Steps -->
        <div class="steps-container">
          {#each spec.steps as step, i (step.plan_step_ref)}
            <FlowAIBuilderStepCard
              {step}
              stepNumber={i + 1}
              {resolveModelName}
              isFirst={i === 0}
              isLast={i === spec.steps.length - 1}
              planStatus={plan.status}
              onsuggestchange={(prefill) => onsuggestchange?.(prefill)}
            />
          {/each}
        </div>
      </div>

      <!-- Applied result -->
      {#if service.applyResult}
        <div class="applied-result">
          <p class="text-positive-stronger text-sm font-medium">
            {m.ai_builder_applied_success()}
          </p>
          <p class="text-positive-default mt-1 text-xs">
            {service.applyResult.steps_created}
            {m.ai_builder_created()},
            {service.applyResult.steps_updated}
            {m.ai_builder_updated()},
            {service.applyResult.steps_removed}
            {m.ai_builder_removed()}
          </p>
          {#if service.canContinueEditing}
            <div class="mt-3">
              <Button variant="outlined" size="small" onclick={handleContinueEditing}>
                {m.ai_builder_continue_editing()}
              </Button>
            </div>
          {/if}
        </div>
      {/if}
    </div>

    <!-- Action buttons — pinned at bottom, always visible -->
    <div class="plan-actions">
      {#if service.canApprove}
        <Button variant="positive" onclick={handleApprove} disabled={isApproving || isApplying}>
          {isApproving ? m.ai_builder_approving() : m.ai_builder_approve()}
        </Button>
      {/if}

      {#if service.canApply}
        <Button variant="primary" onclick={handleApply} disabled={isApproving || isApplying}>
          {isApplying ? m.ai_builder_applying() : m.ai_builder_apply()}
        </Button>
      {/if}

      {#if !service.applyResult}
        <Button variant="outlined" onclick={handleModify} disabled={isApproving || isApplying}>
          {m.ai_builder_modify()}
        </Button>
      {/if}
    </div>
  {:else if service.isConflict}
    <!-- Conflict recovery banner (no plan state) -->
    <div class="plan-scroll">
      <div class="conflict-banner">
        <h4 class="text-warning-stronger text-sm font-semibold">
          {m.ai_builder_conflict_title()}
        </h4>
        <p class="text-warning-default mt-1 text-xs leading-relaxed">
          {m.ai_builder_conflict_description()}
        </p>
        <div class="mt-3 flex gap-2">
          <Button variant="primary" size="small" onclick={handleConflictRegenerate}>
            {m.ai_builder_conflict_regenerate()}
          </Button>
          <Button variant="outlined" size="small" onclick={() => service.dismissConflict()}>
            {m.ai_builder_conflict_cancel()}
          </Button>
        </div>
      </div>
    </div>
  {:else if service.statusMessage || service.isStreaming}
    <!-- Progress state -->
    <div class="empty-state">
      <div class="progress-ring"></div>
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
    <div class="empty-state">
      <div class="empty-icon">
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

  .plan-pane {
    display: flex;
    flex-direction: column;
    flex: 1;
    min-height: 0;
    position: relative;
  }

  .revision-overlay {
    position: absolute;
    inset: 0;
    z-index: 10;
    display: flex;
    align-items: center;
    justify-content: center;
    background: oklch(from var(--bg-primary) l c h / 0.75);
    backdrop-filter: blur(2px);
    pointer-events: auto;
    animation: overlay-fade-in 0.25s ease;
  }

  .revision-overlay-content {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    color: var(--text-secondary);
    font-size: 0.875rem;
    font-weight: 500;
  }

  @keyframes overlay-fade-in {
    from { opacity: 0; }
    to { opacity: 1; }
  }

  .plan-scroll {
    flex: 1;
    overflow-y: auto;
    padding: 1rem;
  }

  @media (min-width: 768px) {
    .plan-scroll {
      padding: 1.5rem;
    }
  }

  .conflict-banner {
    margin-bottom: 1rem;
    border-radius: 0.75rem;
    border: 1px solid var(--border-warning-default);
    background: var(--bg-warning-dimmer);
    padding: 1rem 1.25rem;
  }

  .plan-card {
    border-radius: 1rem;
    border: 1px solid var(--border-default);
    background: var(--bg-primary);
    box-shadow:
      0 20px 40px -15px rgba(0, 0, 0, 0.05),
      0 1px 3px rgba(0, 0, 0, 0.02);
    max-width: 48rem;
    margin: 0 auto;
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

  .form-fields-section {
    padding: 1rem 1.5rem;
    border-top: 1px solid var(--border-default);
  }

  .form-fields-list {
    display: grid;
    gap: 0.75rem;
  }

  @media (min-width: 640px) {
    .form-fields-list {
      grid-template-columns: 1fr 1fr;
    }
  }

  .form-field-card {
    border: 1px solid var(--border-default);
    border-radius: 0.625rem;
    padding: 0.75rem;
    background: var(--bg-secondary);
  }

  .form-field-header,
  .form-field-meta,
  .form-field-options {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    align-items: center;
  }

  .form-field-header {
    justify-content: space-between;
    margin-bottom: 0.25rem;
  }

  .form-field-label {
    color: var(--text-primary);
    font-size: 0.8125rem;
    font-weight: 600;
  }

  .form-field-type,
  .form-field-option {
    border: 1px solid var(--border-default);
    border-radius: 999px;
    padding: 0.125rem 0.5rem;
    font-size: 0.75rem;
    color: var(--text-secondary);
    background: var(--bg-primary);
  }

  .form-field-meta {
    color: var(--text-secondary);
    font-size: 0.75rem;
  }

  .plan-header {
    padding: 1.5rem 1.5rem 1.25rem;
  }

  .assumptions-section {
    margin: 0 1.5rem 1.5rem;
    padding: 1rem 1.25rem;
    border-radius: 0.75rem;
    background: var(--bg-secondary);
    border: 1px solid var(--border-default);
  }

  .rationale-section {
    padding: 1.25rem 1.5rem;
    border-top: 1px solid var(--border-default);
  }

  .lint-section {
    margin: 0 1.5rem 1.5rem;
    padding: 1rem 1.25rem;
    border-radius: 0.5rem;
    border: 1px solid var(--border-warning-default);
    background: var(--bg-warning-dimmer);
  }

  .lint-header {
    display: flex;
    align-items: center;
    gap: 0.375rem;
    margin-bottom: 0.5rem;
  }

  .lint-icon {
    width: 0.875rem;
    height: 0.875rem;
    color: var(--text-warning-stronger);
    flex-shrink: 0;
  }

  .lint-title {
    font-size: 0.8125rem;
    font-weight: 600;
    color: var(--text-warning-stronger);
  }

  .lint-list {
    list-style: none;
    padding: 0;
    margin: 0;
    display: flex;
    flex-direction: column;
    gap: 0.375rem;
  }

  .lint-item {
    font-size: 0.8125rem;
    line-height: 1.5;
    color: var(--text-warning-stronger);
    padding-left: 1.25rem;
    position: relative;
  }

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

  .lint-ref {
    font-weight: 600;
    margin-right: 0.25rem;
  }

  .steps-container {
    padding: 0 1.5rem 1.5rem;
  }

  .plan-actions {
    position: relative;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    padding: 0.75rem 1rem 1rem;
    flex-shrink: 0;
    border-top: 1px solid var(--border-default);
    background: var(--bg-primary);
  }

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

  @media (min-width: 640px) {
    .plan-actions {
      flex-direction: row;
    }
  }

  .applied-result {
    margin-top: 1rem;
    padding: 1rem 1.25rem;
    border-radius: 0.75rem;
    background: var(--bg-positive-dimmer);
  }

  .empty-state {
    display: flex;
    flex: 1;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    text-align: center;
    opacity: 0.65;
  }

  .empty-icon {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 3.5rem;
    height: 3.5rem;
    margin-bottom: 1rem;
    border-radius: 1rem;
    background: var(--bg-primary);
    border: 1px solid var(--border-default);
    color: var(--text-muted);
  }

  .progress-ring {
    width: 3rem;
    height: 3rem;
    margin-bottom: 1.25rem;
    border-radius: 50%;
    border: 3px solid oklch(from var(--accent-default) l c h / 0.15);
    border-top-color: var(--accent-default);
    animation: spin-slow 1s linear infinite;
  }

  :global(.animate-spin-slow) {
    animation: spin-slow 2s linear infinite;
  }

  @keyframes spin-slow {
    from { transform: rotate(0deg); }
    to { transform: rotate(360deg); }
  }

  @media (prefers-reduced-motion: reduce) {
    :global(.animate-spin-slow) {
      animation: none;
    }

    .plan-card,
    .revision-overlay {
      animation: none;
    }
  }
</style>
