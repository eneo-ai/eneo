<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import IconCheck from "@lucide/svelte/icons/check";

  export type BuilderPhaseIndex = 0 | 1 | 2;

  interface Props {
    /** The phase the session is actually in. */
    current: BuilderPhaseIndex;
    /** The phase whose screen is shown; a completed phase can be revisited. */
    viewing: BuilderPhaseIndex;
    onselect?: (phase: BuilderPhaseIndex) => void;
    /** Changing a published flow: nothing is created, so nothing says so. */
    isEdit?: boolean;
  }

  let { current, viewing, onselect, isEdit = false }: Props = $props();

  const phases: { index: BuilderPhaseIndex; label: () => string }[] = $derived(
    isEdit
      ? [
          { index: 0, label: m.ai_builder_rail_understanding_edit },
          { index: 1, label: m.ai_builder_rail_planning_edit },
          { index: 2, label: m.ai_builder_rail_reviewing_edit }
        ]
      : [
          { index: 0, label: m.ai_builder_rail_understanding },
          { index: 1, label: m.ai_builder_rail_planning },
          { index: 2, label: m.ai_builder_rail_reviewing }
        ]
  );

  function stateFor(index: BuilderPhaseIndex): "done" | "active" | "upcoming" {
    if (index < current) return "done";
    if (index === current) return "active";
    return "upcoming";
  }
</script>

<nav class="phase-rail @container/rail" aria-label={m.ai_builder_progress_aria()}>
  <!-- Narrow: one line. Wide: three pips. Only one form is in the a11y tree.
       Only the current phase and the confirmed requirements can be revisited;
       a finished build phase has nothing to show. -->
  <p class="rail-compact">
    <span class="pip pip-active" aria-hidden="true">{viewing + 1}</span>
    <span class="rail-compact-label" aria-current="step">
      {m.ai_builder_rail_step_of({ step: String(viewing + 1), label: phases[viewing].label() })}
    </span>
  </p>
  <ol class="rail-list" role="list">
    {#each phases as phase, i (phase.index)}
      {@const state = stateFor(phase.index)}
      {@const reachable = phase.index === current || (phase.index === 0 && current > 0)}
      <li class="rail-item">
        <button
          type="button"
          class="rail-button"
          class:is-viewing={viewing === phase.index}
          disabled={!reachable}
          aria-current={viewing === phase.index ? "step" : undefined}
          onclick={() => reachable && onselect?.(phase.index)}
        >
          <span
            class="pip"
            class:pip-done={state === "done"}
            class:pip-active={state === "active"}
            aria-hidden="true"
          >
            {#if state === "done"}
              <IconCheck class="size-3" strokeWidth={3} />
            {:else if state === "active"}
              <span class="pip-dot"></span>
            {:else}
              {phase.index + 1}
            {/if}
          </span>
          <span
            class="rail-label"
            class:is-active={state === "active"}
            class:is-reachable={reachable}
          >
            {phase.label()}
          </span>
        </button>
      </li>
      {#if i < phases.length - 1}
        <li class="rail-rule" class:is-done={state === "done"} aria-hidden="true"></li>
      {/if}
    {/each}
  </ol>
</nav>

<style lang="postcss">
  @reference "@eneo/ui/styles";

  .phase-rail {
    container-type: inline-size;
    width: 100%;
  }
  .rail-compact {
    display: flex;
    align-items: center;
    gap: 0.5625rem;
    margin: 0;
  }
  .rail-compact-label {
    font-size: 0.8125rem;
    font-weight: 700;
    color: var(--text-primary);
  }
  .rail-list {
    display: none;
    list-style: none;
    margin: 0;
    padding: 0;
    align-items: center;
  }
  @container rail (min-width: 40rem) {
    .rail-compact {
      display: none;
    }
    .rail-list {
      display: flex;
    }
  }
  .rail-item {
    flex: none;
  }
  .rail-button {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    border: none;
    background: transparent;
    padding: 0.25rem 0.375rem;
    margin-left: -0.375rem;
    border-radius: 0.5rem;
    cursor: pointer;
    font: inherit;
  }
  .rail-button:disabled {
    cursor: default;
  }
  .rail-button:not(:disabled):hover {
    background: var(--background-secondary);
  }
  .rail-button:focus-visible {
    outline: 2px solid var(--accent-stronger);
    outline-offset: 1px;
  }
  .rail-button.is-viewing:not(:disabled) {
    background: var(--background-secondary);
  }
  .pip {
    width: 1.375rem;
    height: 1.375rem;
    border-radius: 999px;
    flex: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: 0.6875rem;
    font-weight: 700;
    background: var(--background-primary);
    border: 1.5px solid var(--border-stronger);
    color: var(--text-secondary);
    transition:
      background-color 200ms ease-out,
      border-color 200ms ease-out,
      color 200ms ease-out;
  }
  .pip-done,
  .pip-active {
    background: var(--accent-default);
    border-color: var(--accent-default);
    color: var(--text-on-fill);
  }
  .pip-dot {
    width: 0.4375rem;
    height: 0.4375rem;
    border-radius: 999px;
    background: currentColor;
  }
  .rail-label {
    font-size: 0.8125rem;
    font-weight: 500;
    color: var(--text-secondary);
    white-space: nowrap;
    transition: color 200ms ease-out;
  }
  .rail-label.is-reachable {
    color: var(--text-primary);
  }
  .rail-label.is-active {
    font-weight: 700;
  }
  .rail-rule {
    flex: 0 1 5.25rem;
    min-width: 1.125rem;
    height: 1px;
    margin: 0 0.625rem;
    background: var(--border-default);
    transition: background-color 200ms ease-out;
  }
  .rail-rule.is-done {
    background: var(--accent-default);
  }
  @media (prefers-reduced-motion: reduce) {
    .pip,
    .rail-label,
    .rail-rule {
      transition: none;
    }
  }
</style>
