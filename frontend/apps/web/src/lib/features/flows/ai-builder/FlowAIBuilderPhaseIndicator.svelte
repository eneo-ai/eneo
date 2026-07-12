<script lang="ts">
  /* eslint-disable eneo/no-raw-color -- the style block derives every colour
     from theme tokens; the only oklch() call rebuilds the active pip's token
     colour (currentColor) with reduced alpha for its halo. */
  import { m } from "$lib/paraglide/messages";
  import type { AIBuilderPhase } from "./protocol";

  interface Props {
    phase: AIBuilderPhase;
    answeredCount?: number;
  }

  let { phase, answeredCount = 0 }: Props = $props();

  // The four backend phases collapse into a calmer three-state status so the
  // conversation, not a wizard, is the spine: the AI understands, then
  // proposes, then the plan is ready.
  const phases: { label: () => string }[] = [
    { label: () => m.ai_builder_phase_understanding() },
    { label: () => m.ai_builder_phase_proposing() },
    { label: () => m.ai_builder_phase_ready() }
  ];

  const phaseToDisplayIndex: Record<AIBuilderPhase, number> = {
    discovering: 0,
    confirming: 0,
    building: 1,
    reviewing: 2
  };

  const currentIndex = $derived(phaseToDisplayIndex[phase]);

  function stateFor(index: number): "completed" | "active" | "upcoming" {
    if (index < currentIndex) return "completed";
    if (index === currentIndex) return "active";
    return "upcoming";
  }
</script>

<nav class="phase-bar" aria-label={m.ai_builder_progress_aria()}>
  <!-- Text form for narrow containers (handoff §1.1): the full bar degrades to
       "Steg N av 3 — …" below the split threshold. Only one form is ever in
       the accessibility tree; the other is display:none. -->
  <p class="phase-compact" aria-current="step">
    {m.ai_builder_phase_step_of({
      step: currentIndex + 1,
      total: phases.length,
      label: phases[currentIndex]?.label() ?? ""
    })}
  </p>
  <ol class="phase-list" role="list">
    {#each phases as step, i (i)}
      {@const state = stateFor(i)}
      <li
        class="phase-step"
        class:active={state === "active"}
        class:completed={state === "completed"}
        class:upcoming={state === "upcoming"}
        aria-current={state === "active" ? "step" : undefined}
      >
        <span class="phase-pip" aria-hidden="true">
          {#if state === "completed"}
            <svg
              xmlns="http://www.w3.org/2000/svg"
              viewBox="0 0 20 20"
              fill="currentColor"
              class="pip-icon"
            >
              <path
                fill-rule="evenodd"
                d="M16.704 4.153a.75.75 0 0 1 .143 1.052l-8 10.5a.75.75 0 0 1-1.127.075l-4.5-4.5a.75.75 0 0 1 1.06-1.06l3.894 3.893 7.48-9.817a.75.75 0 0 1 1.05-.143Z"
                clip-rule="evenodd"
              />
            </svg>
          {:else if state === "active"}
            <span class="pip-dot"></span>
          {:else}
            <span class="pip-number">{i + 1}</span>
          {/if}
        </span>
        <span class="phase-labels">
          <span class="phase-text">{step.label()}</span>
          {#if i === 0 && phase === "discovering" && state === "active" && answeredCount > 0}
            <span class="phase-counter"
              >{m.ai_builder_questions_answered({ count: answeredCount })}</span
            >
          {/if}
        </span>
      </li>
      {#if i < phases.length - 1}
        <li class="phase-rule" class:filled={state === "completed"} aria-hidden="true"></li>
      {/if}
    {/each}
  </ol>
</nav>

<style lang="postcss">
  @reference "@eneo/ui/styles";

  .phase-bar {
    width: 100%;
    padding: 0.75rem 1.5rem;
    background: var(--background-primary);
  }

  .phase-compact {
    display: none;
    margin: 0;
    font-size: 0.8125rem;
    font-weight: 500;
    line-height: 1.2;
    color: var(--text-primary);
  }

  .phase-list {
    display: flex;
    align-items: center;
    list-style: none;
    margin: 0;
    padding: 0;
    gap: 0;
  }

  .phase-step {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    flex-shrink: 0;
    min-width: 0;
  }

  .phase-pip {
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    width: 1.5rem;
    height: 1.5rem;
    border-radius: 9999px;
    border: 1px solid var(--border-default);
    background: var(--background-primary);
    color: var(--text-muted);
    transition:
      width 0.3s cubic-bezier(0.16, 1, 0.3, 1),
      height 0.3s cubic-bezier(0.16, 1, 0.3, 1),
      background 0.3s ease,
      border-color 0.3s ease,
      color 0.3s ease,
      box-shadow 0.3s ease;
  }

  .pip-number {
    font-size: 0.6875rem;
    font-weight: 600;
    line-height: 1;
    letter-spacing: 0.01em;
    color: var(--text-muted);
  }

  .pip-icon {
    width: 0.8125rem;
    height: 0.8125rem;
  }

  .pip-dot {
    width: 0.4375rem;
    height: 0.4375rem;
    border-radius: 9999px;
    background: currentColor;
    box-shadow: 0 0 0 3px oklch(from currentColor l c h / 0.2);
    animation: pip-pulse 2.4s cubic-bezier(0.4, 0, 0.6, 1) infinite;
  }

  .phase-labels {
    display: inline-flex;
    align-items: baseline;
    gap: 0.375rem;
    min-width: 0;
  }

  .phase-text {
    font-size: 0.8125rem;
    font-weight: 500;
    line-height: 1.2;
    color: var(--text-secondary);
    white-space: nowrap;
    transition: color 0.25s ease;
  }

  /* --- Active --- */

  .phase-step.active .phase-pip {
    border-color: var(--accent-default);
    background: var(--accent-default);
    color: var(--text-on-fill);
  }

  .phase-step.active .phase-text {
    color: var(--text-primary);
    font-weight: 600;
    letter-spacing: -0.005em;
  }

  /* --- Completed --- */

  .phase-step.completed .phase-pip {
    border-color: var(--accent-default);
    background: var(--accent-default);
    color: var(--text-on-fill);
  }

  .phase-step.completed .phase-text {
    color: var(--text-primary);
  }

  /* --- Rule (connector) --- */

  .phase-rule {
    flex: 1;
    height: 1px;
    min-width: 0.75rem;
    margin: 0 0.625rem;
    background: var(--border-default);
    list-style: none;
    transition: background 0.3s cubic-bezier(0.16, 1, 0.3, 1);
  }

  .phase-rule.filled {
    background: var(--accent-default);
  }

  .phase-counter {
    font-size: 0.6875rem;
    font-weight: 500;
    line-height: 1;
    color: var(--text-secondary);
    letter-spacing: 0.02em;
    text-transform: uppercase;
    padding: 0.0625rem 0.4375rem;
    border-radius: 9999px;
    background: var(--background-secondary);
    white-space: nowrap;
  }

  @keyframes pip-pulse {
    0%,
    100% {
      opacity: 1;
      transform: scale(1);
    }
    50% {
      opacity: 0.65;
      transform: scale(0.85);
    }
  }

  /* --- Responsive --- */

  /* Narrow builder container (tabs/mobile layouts): text form replaces the
     full bar. Outside a "builder" container the full bar always renders.
     Must stay after the base rules — equal specificity, source order decides. */
  @container builder (max-width: 1039.98px) {
    .phase-compact {
      display: block;
    }

    .phase-list {
      display: none;
    }
  }

  @media (max-width: 640px) {
    .phase-bar {
      padding: 0.625rem 1rem;
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .pip-dot {
      animation: none;
      opacity: 0.9;
    }

    .phase-pip,
    .phase-text,
    .phase-rule {
      transition: none;
    }
  }
</style>
