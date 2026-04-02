<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import type { AIBuilderPhase } from "./protocol";

  interface Props {
    phase: AIBuilderPhase;
    answeredCount?: number;
  }

  let { phase, answeredCount = 0 }: Props = $props();

  const phases: { key: AIBuilderPhase; label: () => string }[] = [
    { key: "discovering", label: () => m.ai_builder_phase_discovering() },
    { key: "confirming", label: () => m.ai_builder_phase_confirming() },
    { key: "building", label: () => m.ai_builder_phase_building() },
    { key: "reviewing", label: () => m.ai_builder_phase_reviewing() }
  ];

  const phaseOrder: AIBuilderPhase[] = ["discovering", "confirming", "building", "reviewing"];

  function getPhaseState(
    stepKey: AIBuilderPhase,
    currentPhase: AIBuilderPhase
  ): "completed" | "active" | "upcoming" {
    const stepIndex = phaseOrder.indexOf(stepKey);
    const currentIndex = phaseOrder.indexOf(currentPhase);
    if (stepIndex < currentIndex) return "completed";
    if (stepIndex === currentIndex) return "active";
    return "upcoming";
  }
</script>

<nav class="phase-bar" aria-label="AI Builder progress">
  {#each phases as step, i (step.key)}
    {@const state = getPhaseState(step.key, phase)}
    <div class="phase-step" class:active={state === "active"} class:completed={state === "completed"} class:upcoming={state === "upcoming"}>
      <span class="phase-pip">
        {#if state === "completed"}
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="pip-icon">
            <path
              fill-rule="evenodd"
              d="M16.704 4.153a.75.75 0 0 1 .143 1.052l-8 10.5a.75.75 0 0 1-1.127.075l-4.5-4.5a.75.75 0 0 1 1.06-1.06l3.894 3.893 7.48-9.817a.75.75 0 0 1 1.05-.143Z"
              clip-rule="evenodd"
            />
          </svg>
        {:else}
          <span class="pip-number">{i + 1}</span>
        {/if}
      </span>
      <span class="phase-text">{step.label()}</span>
      {#if step.key === "discovering" && state === "active" && answeredCount > 0}
        <span class="phase-counter">{m.ai_builder_questions_answered({ count: answeredCount })}</span>
      {/if}
    </div>
    {#if i < phases.length - 1}
      <span class="phase-rule" class:filled={state === "completed"}></span>
    {/if}
  {/each}
</nav>

<style lang="postcss">
  @reference "@intric/ui/styles";

  .phase-bar {
    display: flex;
    align-items: center;
    padding: 0.75rem 1.5rem;
    background: var(--bg-primary);
    gap: 0;
  }

  .phase-step {
    display: flex;
    align-items: center;
    gap: 0.375rem;
    flex-shrink: 0;
  }

  .phase-pip {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 1.5rem;
    height: 1.5rem;
    border-radius: 9999px;
    border: 1px solid var(--border-default);
    background: var(--bg-secondary);
    color: var(--text-muted);
    flex-shrink: 0;
    transition: all 0.4s cubic-bezier(0.16, 1, 0.3, 1);
  }

  .pip-number {
    font-size: 0.6875rem;
    font-weight: 600;
    line-height: 1;
  }

  .pip-icon {
    width: 0.75rem;
    height: 0.75rem;
  }

  .phase-text {
    font-size: 0.8125rem;
    font-weight: 500;
    color: var(--text-muted);
    white-space: nowrap;
    transition: color 0.3s ease;
  }

  /* --- Active --- */

  .phase-step.active .phase-pip {
    width: 1.75rem;
    height: 1.75rem;
    border-color: var(--accent-default);
    background: var(--accent-default);
    color: white;
    box-shadow: 0 0 0 4px oklch(from var(--accent-default) l c h / 0.15);
  }

  .phase-step.active .phase-text {
    color: var(--text-primary);
    font-weight: 600;
  }

  /* --- Completed --- */

  .phase-step.completed .phase-pip {
    border-color: var(--border-default);
    background: var(--bg-primary);
    color: var(--text-primary);
  }

  .phase-step.completed .phase-text {
    color: var(--text-primary);
  }

  /* --- Rule (connector) --- */

  .phase-rule {
    flex: 1;
    height: 1px;
    min-width: 0.75rem;
    margin: 0 0.5rem;
    background: var(--border-default);
    transition: background 0.4s cubic-bezier(0.16, 1, 0.3, 1);
  }

  .phase-rule.filled {
    background: var(--accent-default);
  }

  .phase-counter {
    font-size: 0.6875rem;
    color: var(--text-muted);
    white-space: nowrap;
  }

  /* --- Responsive --- */

  @media (max-width: 540px) {
    .phase-text,
    .phase-counter {
      display: none;
    }

    .phase-bar {
      justify-content: center;
      padding: 0.5rem 1rem;
    }

    .phase-rule {
      min-width: 1.5rem;
      max-width: 3rem;
    }
  }
</style>
