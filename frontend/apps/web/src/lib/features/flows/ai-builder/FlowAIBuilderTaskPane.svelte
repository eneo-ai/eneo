<script lang="ts">
  /**
   * Structured left pane for the plan-review state (handoff §2, §3.1):
   * task summary with expander, Syfte/Indata/Resultat definition grid,
   * decisions from the clarification answers, one Collapsible each for
   * assumptions and the conversation (BoundedLog). Pure props — the chat
   * shell owns all service state.
   */
  import { untrack } from "svelte";
  import { m } from "$lib/paraglide/messages";
  import { getLocale } from "$lib/paraglide/runtime";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Collapsible from "$lib/components/ui/collapsible/index.js";
  import FlowAIBuilderBoundedLog from "./FlowAIBuilderBoundedLog.svelte";
  import type { ChatMessage, RequirementsSummary } from "./protocol";

  interface Props {
    taskText: string;
    requirements: RequirementsSummary | null;
    messages: ChatMessage[];
    disabled?: boolean;
    onedittask?: () => void;
  }

  let { taskText, requirements, messages, disabled = false, onedittask }: Props = $props();

  // ~3 clamped lines at the pane's measure. Static threshold instead of a
  // scrollHeight probe: deterministic in jsdom and stable under font zoom —
  // a short text that happens to wrap once simply shows no expander.
  const CLAMP_CHAR_THRESHOLD = 280;

  let taskExpanded = $state(false);
  const isClampable = $derived(taskText.length > CLAMP_CHAR_THRESHOLD);

  const numberFormatter = new Intl.NumberFormat(getLocale());
  const taskCharCount = $derived(numberFormatter.format(taskText.length));

  const decisions = $derived(requirements?.key_decisions ?? []);
  const assumptions = $derived(requirements?.assumptions ?? []);

  let assumptionsOpen = $state(false);
  let conversationOpen = $state(false);

  // The log renders only messages with visible content; ALL unseen/NYTT
  // bookkeeping is based on this same filtered sequence — raw indices would
  // drift as soon as an empty assistant envelope precedes a new message.
  const logMessages = $derived(messages.filter((message) => message.content.trim().length > 0));

  // "NYTT" bookkeeping: messages arriving while the conversation section is
  // closed are marked with a divider the next time it opens (§2 BoundedLog).
  // Messages present at mount were the visible transcript — already seen.
  // svelte-ignore state_referenced_locally
  let seenCount = $state(logMessages.length);
  let newSinceIndex = $state<number | null>(null);

  $effect(() => {
    if (!conversationOpen) return;
    const length = logMessages.length;
    // untrack: the effect reads AND writes seenCount; tracking it would
    // re-run immediately and clear the divider before it ever renders.
    untrack(() => {
      newSinceIndex = seenCount < length ? seenCount : null;
      seenCount = length;
    });
  });

  const unseenCount = $derived(conversationOpen ? 0 : Math.max(0, logMessages.length - seenCount));
</script>

<!-- Spacing is owned by the chat scroller that hosts this pane. -->
<div class="task-pane flex flex-col gap-6">
  <section class="flex flex-col gap-2.5" aria-labelledby="ai-builder-task-heading">
    <div class="flex items-center justify-between gap-2">
      <h2 id="ai-builder-task-heading" class="text-primary text-sm font-semibold">
        {m.ai_builder_task_heading()}
      </h2>
      {#if onedittask}
        <Button variant="ghost" size="xs" onclick={onedittask} {disabled}>
          {m.ai_builder_requirements_change()}
        </Button>
      {/if}
    </div>

    <p
      class="text-secondary text-sm leading-relaxed break-words whitespace-pre-wrap"
      class:task-clamp={isClampable && !taskExpanded}
    >
      {taskText}
    </p>

    {#if isClampable}
      <button
        type="button"
        class="text-accent-default hover:text-accent-stronger focus-visible:ring-accent-default/30 w-fit cursor-pointer rounded text-[0.8125rem] font-medium focus-visible:ring-2 focus-visible:outline-none"
        aria-expanded={taskExpanded}
        onclick={() => (taskExpanded = !taskExpanded)}
      >
        {taskExpanded
          ? m.ai_builder_task_collapse()
          : m.ai_builder_task_expand({ count: taskCharCount })}
      </button>
    {/if}

    {#if requirements}
      <dl class="definition-grid mt-1">
        <dt>{m.ai_builder_task_purpose()}</dt>
        <dd>{requirements.summary}</dd>
        <dt>{m.ai_builder_requirements_input()}</dt>
        <dd>{requirements.input_description}</dd>
        <dt>{m.ai_builder_task_result()}</dt>
        <dd>{requirements.output_description}</dd>
      </dl>
    {/if}
  </section>

  {#if decisions.length > 0}
    <section class="flex flex-col gap-2" aria-labelledby="ai-builder-decisions-heading">
      <h2 id="ai-builder-decisions-heading" class="text-primary text-sm font-semibold">
        {m.ai_builder_decisions_from_answers()}
      </h2>
      <dl class="definition-grid">
        {#each decisions as decision (decision.topic)}
          <dt>{decision.topic}</dt>
          <dd>{decision.decision}</dd>
        {/each}
      </dl>
    </section>
  {/if}

  {#if assumptions.length > 0}
    <Collapsible.Root bind:open={assumptionsOpen}>
      <h2 class="text-sm">
        <Collapsible.Trigger class="section-trigger">
          <span>{m.ai_builder_assumptions()} ({assumptions.length})</span>
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
      </h2>
      <Collapsible.Content class="collapsible-animate">
        <ul
          class="bg-secondary/40 divide-default mt-2 flex flex-col divide-y rounded-lg px-3 py-0.5"
        >
          {#each assumptions as assumption (assumption)}
            <li class="text-secondary py-2 text-[0.8125rem] leading-relaxed">
              {assumption}
            </li>
          {/each}
        </ul>
      </Collapsible.Content>
    </Collapsible.Root>
  {/if}

  {#if logMessages.length > 0}
    <Collapsible.Root bind:open={conversationOpen}>
      <h2 class="text-sm">
        <Collapsible.Trigger class="section-trigger">
          <span>{m.ai_builder_conversation_heading({ count: logMessages.length })}</span>
          {#if unseenCount > 0}
            <span class="new-badge">
              {unseenCount === 1
                ? m.ai_builder_conversation_new_one()
                : m.ai_builder_conversation_new_many({ count: unseenCount })}
            </span>
          {/if}
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 16 16"
            fill="currentColor"
            class="size-3.5 shrink-0 transition-transform duration-200 ease-out {conversationOpen
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
      </h2>
      <Collapsible.Content class="collapsible-animate">
        <div class="mt-2">
          <FlowAIBuilderBoundedLog messages={logMessages} {newSinceIndex} />
        </div>
      </Collapsible.Content>
    </Collapsible.Root>
  {/if}
</div>

<style lang="postcss">
  @reference "@eneo/ui/styles";

  .task-pane {
    /* Own container so the definition grid can stack on the PANE's width —
       the builder container only knows the full workspace width (§2). */
    container-type: inline-size;
    container-name: taskpane;
  }

  .task-clamp {
    display: -webkit-box;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 3;
    overflow: hidden;
  }

  /* Short viewports get one less summary line before the fold (§1.5). */
  @media (max-height: 639.98px) {
    .task-clamp {
      -webkit-line-clamp: 2;
    }
  }

  /* 88px label column + free value column; stacked below narrow pane widths. */
  .definition-grid {
    display: grid;
    grid-template-columns: 1fr;
    gap: 0.25rem 1rem;
    margin: 0;
  }

  @container taskpane (min-width: 420px) {
    .definition-grid {
      grid-template-columns: 88px 1fr;
      row-gap: 0.5rem;
    }
  }

  .definition-grid dt {
    color: var(--text-secondary);
    font-size: 0.8125rem;
    font-weight: 400;
  }

  .definition-grid dd {
    margin: 0;
    color: var(--text-primary);
    font-size: 0.875rem;
    line-height: 1.5;
    overflow-wrap: break-word;
  }

  .task-pane :global(.section-trigger) {
    display: flex;
    width: 100%;
    align-items: center;
    gap: 0.5rem;
    background: transparent;
    border: none;
    padding: 0.25rem 0;
    color: var(--text-primary);
    font-size: 0.875rem;
    font-weight: 700;
    line-height: 1.3;
    text-align: left;
    cursor: pointer;
  }

  .task-pane :global(.section-trigger:focus-visible) {
    outline: 2px solid var(--accent-default);
    outline-offset: 2px;
    border-radius: var(--radius-sm);
  }

  .task-pane :global(.section-trigger svg:last-child) {
    margin-left: auto;
  }

  .new-badge {
    display: inline-flex;
    align-items: center;
    border-radius: 999px;
    padding: 0.0625rem 0.5rem;
    background: var(--accent-dimmer);
    color: var(--accent-stronger);
    font-size: 0.6875rem;
    font-weight: 600;
  }
</style>
