<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import FlowAIBuilderMessage from "./FlowAIBuilderMessage.svelte";
  import FlowAIBuilderInput from "./FlowAIBuilderInput.svelte";
  import FlowAIBuilderPhaseIndicator from "./FlowAIBuilderPhaseIndicator.svelte";
  import { getAIBuilderService } from "./FlowAIBuilderService.svelte.ts";
  import type { StructuredQuestionAnswerPayload } from "./structuredQuestionAnswer";

  interface Props {
    targetKind?: "create" | "edit";
  }

  let { targetKind = "edit" }: Props = $props();

  const service = getAIBuilderService();
  const isEditMode = $derived(targetKind === "edit");

  // Only show the centered welcome state when truly empty — no messages and not streaming
  const showEmptyState = $derived(
    service.messages.length === 0 &&
    !service.isStreaming &&
    !service.currentPlan &&
    !service.isConflict &&
    !service.statusMessage
  );

  function handleQuestionAnswer(answer: StructuredQuestionAnswerPayload) {
    service.sendMessage(answer.text, answer.questionAnswer);
  }

  let inputRef: FlowAIBuilderInput;

  // Track if a plan existed before (for context-aware generating text)
  let hadPlanBefore = $state(false);
  $effect(() => {
    if (service.currentPlan !== null) hadPlanBefore = true;
    if (!service.hasSession) hadPlanBefore = false;
  });
  const generatingText = $derived(
    hadPlanBefore ? m.ai_builder_updating_plan() : m.ai_builder_generating()
  );

  export function focusInput(prefill?: string) {
    inputRef?.focus(prefill ? { placeholder: prefill } : undefined);
  }

  function handleRequirementsConfirm() {
    service.confirmRequirements();
  }

  function handleRequirementsChange() {
    inputRef?.focus({ placeholder: m.ai_builder_requirements_change_hint() });
  }

  let scrollContainer: HTMLDivElement;

  function scrollToBottom() {
    if (scrollContainer) {
      requestAnimationFrame(() => {
        scrollContainer.scrollTop = scrollContainer.scrollHeight;
      });
    }
  }

  const answeredQuestionCount = $derived.by(() => {
    const ids = new Set<string>();
    for (const msg of service.messages) {
      const qa = msg.metadata && typeof msg.metadata === "object" && "question_answer" in msg.metadata
        ? msg.metadata.question_answer
        : null;
      if (qa && typeof qa === "object" && "question_id" in qa && typeof qa.question_id === "string") {
        ids.add(qa.question_id);
      }
    }
    return ids.size;
  });

  // Auto-scroll when messages change or streaming state changes
  $effect(() => {
    void service.messages.length;
    void service.isStreaming;
    scrollToBottom();
  });

</script>

<div class="chat-shell" class:chat-shell-empty={showEmptyState}>
  <!-- Phase progress indicator -->
  {#if service.messages.length > 0}
    <FlowAIBuilderPhaseIndicator phase={service.phase} answeredCount={answeredQuestionCount} />
  {/if}

  {#if showEmptyState}
    <!-- Empty state: welcome + input centered -->
    <div class="empty-state-spacer"></div>
    <div class="empty-welcome">
      <h2 class="text-primary text-3xl font-semibold tracking-tighter">
        {isEditMode ? m.ai_builder_welcome_title_edit() : m.ai_builder_welcome_title()}
      </h2>
      <p class="text-secondary mt-2 text-base leading-relaxed">
        {isEditMode ? m.ai_builder_welcome_description_edit() : m.ai_builder_welcome_description()}
      </p>
    </div>
  {:else}
    <!-- Messages area -->
    <div bind:this={scrollContainer} class="flex-1 overflow-y-auto px-4 py-6">
      <div class="mx-auto max-w-[71ch]">
        <!-- Message list -->
        {#each service.messages as message, i (`msg-${i}`)}
          <FlowAIBuilderMessage
            role={message.role}
            content={message.content}
            isLast={i === service.messages.length - 1}
            isStreaming={service.isStreaming && i === service.messages.length - 1}
            question={message.question}
            questionAnswered={message.question ? service.isQuestionAnswered(message.question.question_id) : false}
            requirementsSummary={message.requirementsSummary}
            requirementsConfirmed={
              message.requirementsSummary
                ? service.isRequirementsSummaryConfirmed(message.requirementsSummary)
                : false
            }
            requirementsActive={
              message.requirementsSummary
                ? service.isLatestRequirementsSummary(message.requirementsSummary)
                : false
            }
            onQuestionAnswer={message.question ? handleQuestionAnswer : undefined}
            onRequirementsConfirm={
              message.requirementsSummary && service.isLatestRequirementsSummary(message.requirementsSummary)
                ? handleRequirementsConfirm
                : undefined
            }
            onRequirementsChange={
              message.requirementsSummary && service.isLatestRequirementsSummary(message.requirementsSummary)
                ? handleRequirementsChange
                : undefined
            }
          />
        {/each}
        {#if service.isStreaming && service.messages[service.messages.length - 1]?.role === "user"}
          <!-- Thinking indicator — shown while waiting for LLM response -->
          <div class="mt-4 py-2">
            <div class="generating-badge" role="status" aria-label={generatingText}>
              <span class="generating-orb" aria-hidden="true"></span>
              <span class="generating-text">{generatingText}</span>
            </div>
          </div>
        {/if}
      </div>
    </div>
  {/if}

  <!-- Error banner -->
  {#if service.error}
    <div
      class="bg-negative-dimmer border-negative-default mx-4 mb-2 rounded-lg border px-4 py-2.5 text-sm"
    >
      <span class="text-negative-stronger">{service.error}</span>
      <button class="text-negative-default ml-2 underline" onclick={() => service.clearError()}>
        {m.ai_builder_dismiss()}
      </button>
    </div>
  {/if}

  <!-- Input area -->
  <div class="input-area" class:input-area-hero={showEmptyState}>
    <FlowAIBuilderInput bind:this={inputRef} />
  </div>
  {#if showEmptyState}
    <div class="empty-state-bottom-spacer"></div>
  {/if}
</div>

<style lang="postcss">
  @reference "@intric/ui/styles";

  /* --- Shell layout --- */

  .chat-shell {
    display: flex;
    min-height: 0;
    flex: 1;
    flex-direction: column;
    overflow: hidden;
  }

  .chat-shell-empty {
    justify-content: center;
    align-items: center;
    padding: 0 1.5rem;
  }

  .empty-state-spacer {
    flex: 1;
  }

  .empty-state-bottom-spacer {
    flex: 1;
  }

  .empty-welcome {
    text-align: center;
    margin-bottom: 1.5rem;
    max-width: 28rem;
    opacity: 0;
    animation: fade-up 0.5s cubic-bezier(0.16, 1, 0.3, 1) 0.1s forwards;
  }

  /* --- Input area --- */

  .input-area {
    padding: 0.75rem 1rem 1rem;
    border-top: 1px solid var(--border-default);
    background: var(--bg-primary);
  }

  .input-area-hero {
    width: 100%;
    max-width: 40rem;
    border-top: none;
    padding: 0 0 2rem;
    background: transparent;
    opacity: 0;
    animation: fade-up 0.4s cubic-bezier(0.16, 1, 0.3, 1) forwards;
  }

  .input-area-hero :global(.input-container) {
    box-shadow:
      0 1px 3px oklch(0 0 0 / 0.04),
      inset 0 1px 2px oklch(0 0 0 / 0.03);
    min-height: 4.5rem;
  }

  @keyframes fade-up {
    from {
      opacity: 0;
      transform: translateY(0.5rem);
    }
    to {
      opacity: 1;
      transform: translateY(0);
    }
  }

  .generating-badge {
    @apply relative overflow-hidden rounded-full;
    display: inline-flex;
    align-items: center;
    gap: 0.625rem;
    padding: 0.5rem 1rem;
    width: fit-content;
    isolation: isolate;
    background: oklch(from var(--accent-default) l c h / 0.1);
    color: var(--accent-stronger);
    box-shadow: 0 4px 12px -2px oklch(from var(--accent-default) l c h / 0.1);
  }

  .generating-orb {
    width: 0.5rem;
    height: 0.5rem;
    border-radius: 50%;
    background: currentColor;
    box-shadow: 0 0 8px 2px currentColor;
    animation: orb-pulse 2s ease-in-out infinite;
  }

  @keyframes orb-pulse {
    0%,
    100% {
      opacity: 0.4;
      transform: scale(0.8);
    }
    50% {
      opacity: 1;
      transform: scale(1.2);
    }
  }

  .generating-text {
    position: relative;
    z-index: 1;
    font-size: 0.8125rem;
    line-height: 1.2;
    font-weight: 500;
  }

  /* Flowing gradient underlay */
  .generating-badge::before {
    content: "";
    position: absolute;
    inset: 0;
    background: linear-gradient(
      90deg,
      transparent 0%,
      oklch(from var(--accent-default) l c h / 0.08) 30%,
      oklch(from var(--accent-default) l c h / 0.15) 50%,
      oklch(from var(--accent-default) l c h / 0.08) 70%,
      transparent 100%
    );
    background-size: 200% 100%;
    animation: generating-flow 3s ease-in-out infinite;
    border-radius: inherit;
    pointer-events: none;
  }

  /* Subtle border */
  .generating-badge::after {
    content: "";
    position: absolute;
    inset: 0;
    border-radius: inherit;
    border: 1px solid oklch(from var(--accent-default) l c h / 0.15);
    animation: generating-border 3s ease-in-out infinite;
    pointer-events: none;
  }

  @keyframes generating-flow {
    0%,
    100% {
      background-position: 100% 0;
    }
    50% {
      background-position: 0% 0;
    }
  }

  @keyframes generating-border {
    0%,
    100% {
      border-color: oklch(from var(--accent-default) l c h / 0.1);
    }
    50% {
      border-color: oklch(from var(--accent-default) l c h / 0.25);
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .generating-orb,
    .generating-badge::before,
    .generating-badge::after {
      animation: none;
    }

    .generating-orb {
      opacity: 0.6;
    }

    .generating-badge::after {
      border-color: oklch(from var(--accent-default) l c h / 0.15);
    }

    .empty-welcome,
    .input-area-hero {
      animation: none;
      opacity: 1;
    }
  }

  @media (max-width: 480px) {
    .input-area {
      padding: 0.5rem 0.5rem 0.75rem;
    }

    .chat-shell-empty {
      padding: 0 1rem;
    }
  }
</style>
