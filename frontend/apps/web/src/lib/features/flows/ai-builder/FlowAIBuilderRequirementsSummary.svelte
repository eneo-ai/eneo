<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import { Button } from "@intric/ui";
  import type { RequirementsSummary } from "./protocol";

  interface Props {
    summary: RequirementsSummary;
    confirmed?: boolean;
    active?: boolean;
    onconfirm?: () => void;
    onchange?: () => void;
  }

  let { summary, confirmed = false, active = true, onconfirm, onchange }: Props = $props();
</script>

<div class="req-card" class:confirmed>
  <header class="req-header">
    <span class="req-icon">
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="size-3.5">
        <path fill-rule="evenodd" d="M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0Zm-7-4a1 1 0 1 1-2 0 1 1 0 0 1 2 0ZM9 9a.75.75 0 0 0 0 1.5h.253a.25.25 0 0 1 .244.304l-.459 2.066A1.75 1.75 0 0 0 10.747 15H11a.75.75 0 0 0 0-1.5h-.253a.25.25 0 0 1-.244-.304l.459-2.066A1.75 1.75 0 0 0 9.253 9H9Z" clip-rule="evenodd" />
      </svg>
    </span>
    <h4 class="req-title">{m.ai_builder_requirements_title()}</h4>
  </header>

  <p class="req-summary">{summary.summary}</p>

  <!-- Key decisions -->
  {#if summary.key_decisions.length > 0}
    <div class="req-decisions">
      <p class="req-section-label">{m.ai_builder_requirements_decisions()}</p>
      <dl class="decisions-list">
        {#each summary.key_decisions as decision (decision.topic)}
          <div class="decision-entry">
            <dt class="decision-topic">{decision.topic}</dt>
            <dd class="decision-value">{decision.decision}</dd>
          </div>
        {/each}
      </dl>
    </div>
  {/if}

  <!-- Input / Output -->
  <div class="req-io">
    <div class="io-block">
      <span class="io-label">{m.ai_builder_requirements_input()}</span>
      <span class="io-value">{summary.input_description}</span>
    </div>
    <div class="io-block">
      <span class="io-label">{m.ai_builder_requirements_output()}</span>
      <span class="io-value">{summary.output_description}</span>
    </div>
  </div>

  {#if summary.assumptions && summary.assumptions.length > 0}
    <div class="req-notes">
      <p class="req-notes-label">{m.ai_builder_assumptions()}</p>
      <ul class="notes-list">
        {#each summary.assumptions as assumption (assumption)}
          <li>{assumption}</li>
        {/each}
      </ul>
    </div>
  {/if}

  <!-- Manual setup notes -->
  {#if summary.manual_setup_notes && summary.manual_setup_notes.length > 0}
    <div class="req-notes">
      <p class="req-notes-label">{m.ai_builder_requirements_manual_notes()}</p>
      <ul class="notes-list">
        {#each summary.manual_setup_notes as note (note)}
          <li>{note}</li>
        {/each}
      </ul>
    </div>
  {/if}

  <!-- Actions -->
  {#if !confirmed && active && onconfirm && onchange}
    <div class="req-actions">
      <Button variant="primary" size="small" onclick={onconfirm}>
        {m.ai_builder_requirements_confirm()}
      </Button>
      <Button variant="outlined" size="small" onclick={onchange}>
        {m.ai_builder_requirements_change()}
      </Button>
    </div>
  {:else if !active}
    <div class="req-superseded">
      {m.ai_builder_requirements_superseded()}
    </div>
  {/if}
</div>

<style lang="postcss">
  @reference "@intric/ui/styles";

  .req-card {
    margin-top: 0.75rem;
    padding-bottom: 0.75rem;
    border-radius: 0.75rem;
    border: 1px solid var(--border-default);
    background: var(--bg-primary);
    overflow: hidden;
    transition: opacity 0.25s ease, border-color 0.25s ease;
  }

  .req-card.confirmed {
    opacity: 0.6;
    pointer-events: none;
  }

  .req-superseded {
    padding: 0.375rem 1rem 0;
    color: var(--text-muted);
    font-size: 0.75rem;
    font-weight: 500;
  }

  /* --- Header --- */

  .req-header {
    display: flex;
    align-items: center;
    gap: 0.375rem;
    padding: 0.75rem 1rem 0;
  }

  .req-icon {
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--accent-default);
    flex-shrink: 0;
  }

  .req-title {
    font-size: 0.875rem;
    font-weight: 650;
    color: var(--text-primary);
    letter-spacing: -0.01em;
  }

  /* --- Summary --- */

  .req-summary {
    padding: 0.5rem 1rem 0;
    font-size: 0.8125rem;
    line-height: 1.55;
    color: var(--text-secondary);
  }

  /* --- Decisions --- */

  .req-decisions {
    margin: 0.625rem 0.75rem 0;
    padding: 0.5rem 0.625rem;
    border-radius: 0.5rem;
    background: var(--bg-secondary);
  }

  .req-section-label {
    font-size: 0.8125rem;
    font-weight: 650;
    color: var(--text-primary);
    margin-bottom: 0.375rem;
    letter-spacing: -0.01em;
  }

  .decisions-list {
    display: flex;
    flex-direction: column;
    gap: 0;
  }

  .decision-entry {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 0.25rem 0.625rem;
    padding: 0.375rem 0;
    align-items: first baseline;
  }

  .decision-entry + .decision-entry {
    border-top: 1px solid var(--border-default);
  }

  .decision-topic {
    font-size: 0.8125rem;
    font-weight: 600;
    color: var(--text-primary);
    white-space: nowrap;
  }

  .decision-value {
    font-size: 0.8125rem;
    color: var(--text-secondary);
    line-height: 1.5;
  }

  /* --- Input / Output --- */

  .req-io {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0.75rem;
    padding: 0.75rem 1rem 0;
    margin-top: 0.25rem;
    border-top: 1px solid var(--border-default);
  }

  .io-block {
    display: flex;
    flex-direction: column;
    gap: 0.1875rem;
  }

  .io-label {
    font-size: 0.6875rem;
    font-weight: 600;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }

  .io-value {
    font-size: 0.8125rem;
    color: var(--text-primary);
    line-height: 1.5;
  }

  /* --- Manual notes --- */

  .req-notes {
    margin: 0.625rem 0.75rem 0;
    padding: 0.5rem 0.625rem;
    border-radius: 0.5rem;
    background: oklch(from var(--accent-default) l c h / 0.06);
  }

  .req-notes-label {
    font-size: 0.6875rem;
    font-weight: 600;
    color: var(--accent-stronger);
    margin-bottom: 0.25rem;
  }

  .notes-list {
    display: flex;
    flex-direction: column;
    gap: 0.1875rem;
    list-style: none;
    padding: 0;
    margin: 0;
  }

  .notes-list li {
    font-size: 0.75rem;
    color: var(--accent-default);
    line-height: 1.45;
    padding-left: 0.75rem;
    position: relative;
  }

  .notes-list li::before {
    content: "";
    position: absolute;
    left: 0;
    top: 0.5em;
    width: 0.25rem;
    height: 0.25rem;
    border-radius: 9999px;
    background: currentColor;
    opacity: 0.4;
  }

  /* --- Actions --- */

  .req-actions {
    display: flex;
    gap: 0.375rem;
    padding: 0.375rem 1rem 0;
  }
</style>
