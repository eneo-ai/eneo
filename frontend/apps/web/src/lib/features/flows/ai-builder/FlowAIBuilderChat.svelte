<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import FlowAIBuilderMessage from "./FlowAIBuilderMessage.svelte";
  import FlowAIBuilderInput from "./FlowAIBuilderInput.svelte";
  import FlowAIBuilderPhaseIndicator from "./FlowAIBuilderPhaseIndicator.svelte";
  import { shouldShowEditStartOver } from "./flowAIBuilderReset";
  import { getAIBuilderService } from "./FlowAIBuilderService.svelte.ts";
  import type { StructuredQuestionAnswerPayload } from "./structuredQuestionAnswer";

  interface Props {
    targetKind?: "create" | "edit";
  }

  let { targetKind = "edit" }: Props = $props();

  const service = getAIBuilderService();
  const isEditMode = $derived(targetKind === "edit");
  const canStartOver = $derived(
    shouldShowEditStartOver({
      targetKind,
      hasSession: service.hasSession,
      messageCount: service.messages.length,
      hasPlan: service.currentPlan !== null,
      isConflict: service.isConflict,
      statusMessage: service.statusMessage,
      hasApplyError: service.applyError !== null,
      hasApplyResult: service.applyResult !== null,
      isStreaming: service.isStreaming
    })
  );

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

  let inputRef = $state<FlowAIBuilderInput | undefined>();

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

  function handleStartOver() {
    void service.startFreshSession("edit");
  }

  let scrollContainer = $state<HTMLDivElement | undefined>();

  function scrollToBottom() {
    const target = scrollContainer;
    if (target) {
      requestAnimationFrame(() => {
        target.scrollTop = target.scrollHeight;
      });
    }
  }

  const answeredQuestionCount = $derived.by(() => {
    const ids = new Set<string>();
    for (const msg of service.messages) {
      const qa =
        msg.metadata && typeof msg.metadata === "object" && "question_answer" in msg.metadata
          ? msg.metadata.question_answer
          : null;
      if (
        qa &&
        typeof qa === "object" &&
        "question_id" in qa &&
        typeof qa.question_id === "string"
      ) {
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

<div
  class="flex min-h-0 flex-1 flex-col overflow-hidden"
  class:items-center={showEmptyState}
  class:justify-center={showEmptyState}
  class:px-6={showEmptyState}
  class:max-sm:px-4={showEmptyState}
>
  {#if service.messages.length > 0 || canStartOver}
    <div class="border-border-default flex w-full shrink-0 items-center border-b backdrop-blur-sm">
      {#if service.messages.length > 0}
        <div class="min-w-0 flex-1">
          <FlowAIBuilderPhaseIndicator
            phase={service.phase}
            answeredCount={answeredQuestionCount}
          />
        </div>
      {:else}
        <div class="min-h-0 flex-1" aria-hidden="true"></div>
      {/if}

      {#if canStartOver}
        <button
          class="bg-primary text-secondary border-border-default hover:bg-secondary hover:text-primary mr-4 shrink-0 cursor-pointer rounded-full border px-3 py-1.5 text-[0.8125rem] leading-none font-medium whitespace-nowrap transition-all duration-150 ease-out"
          onclick={handleStartOver}
        >
          {m.ai_builder_start_fresh()}
        </button>
      {/if}
    </div>
  {/if}

  {#if showEmptyState}
    <!-- Empty state: welcome + input centered -->
    <div class="flex-1"></div>
    <div class="empty-welcome mb-6 max-w-md text-center">
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
            questionAnswered={message.question
              ? service.isQuestionAnswered(message.question.question_id)
              : false}
            requirementsSummary={message.requirementsSummary}
            requirementsConfirmed={message.requirementsSummary
              ? service.isRequirementsSummaryConfirmed(message.requirementsSummary)
              : false}
            requirementsActive={message.requirementsSummary
              ? service.isLatestRequirementsSummary(message.requirementsSummary)
              : false}
            onQuestionAnswer={message.question ? handleQuestionAnswer : undefined}
            onRequirementsConfirm={message.requirementsSummary &&
            service.isLatestRequirementsSummary(message.requirementsSummary)
              ? handleRequirementsConfirm
              : undefined}
            onRequirementsChange={message.requirementsSummary &&
            service.isLatestRequirementsSummary(message.requirementsSummary)
              ? handleRequirementsChange
              : undefined}
          />
        {/each}
        {#if service.isStreaming && service.messages[service.messages.length - 1]?.role === "user"}
          <!-- Thinking indicator — shown while waiting for LLM response -->
          <div class="mt-4 py-2">
            <div class="generating-badge" role="status" aria-label={generatingText}>
              <span class="generating-orb" aria-hidden="true"></span>
              <span class="relative z-[1] text-[0.8125rem] leading-tight font-medium"
                >{generatingText}</span
              >
            </div>
          </div>
        {/if}
      </div>
    </div>
  {/if}

  <!-- Error banner -->
  {#if service.error}
    <div class="mx-4 mb-2">
      <Alert.Root
        variant="destructive"
        class="flex items-center gap-3 rounded-lg px-4 py-2.5 text-sm"
      >
        <Alert.Description class="flex-1">{service.error}</Alert.Description>
        <Alert.Action>
          <button class="text-negative-default ml-2 underline" onclick={() => service.clearError()}>
            {m.ai_builder_dismiss()}
          </button>
        </Alert.Action>
      </Alert.Root>
    </div>
  {/if}

  <!-- Input area -->
  <div
    class="bg-primary border-border-default border-t px-4 pt-3 pb-4 max-sm:px-2 max-sm:pt-2 max-sm:pb-3"
    class:input-area-hero={showEmptyState}
  >
    <FlowAIBuilderInput bind:this={inputRef} />
  </div>
  {#if showEmptyState}
    <div class="flex-1"></div>
  {/if}
</div>

<style lang="postcss">
  @reference "@intric/ui/styles";

  /* --- Welcome + hero input entrance animation --- */

  .empty-welcome {
    opacity: 0;
    animation: fade-up 0.5s cubic-bezier(0.16, 1, 0.3, 1) 0.1s forwards;
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

  /* --- Generating indicator --- */

  .generating-badge {
    @apply relative inline-flex items-center gap-2.5 overflow-hidden rounded-full px-4 py-2;
    width: fit-content;
    isolation: isolate;
    background: oklch(from var(--accent-default) l c h / 0.1);
    color: var(--accent-stronger);
    box-shadow: 0 4px 12px -2px oklch(from var(--accent-default) l c h / 0.1);
  }

  .generating-orb {
    @apply size-2 shrink-0 rounded-full;
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
</style>
