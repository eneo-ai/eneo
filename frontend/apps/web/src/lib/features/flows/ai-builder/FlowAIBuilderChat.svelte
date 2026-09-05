<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import FlowAIBuilderMessage from "./FlowAIBuilderMessage.svelte";
  import FlowAIBuilderInput from "./FlowAIBuilderInput.svelte";
  import { getAIBuilderService } from "./FlowAIBuilderService.svelte.ts";
  import { buildAnswerLabels } from "./aiBuilderAnswerLabel";
  import type { AIBuilderPlanEditContext, AIBuilderSuggestChangeIntent } from "./protocol";

  interface Props {
    /** Reopen an answered question on the phase screen. */
    oneditanswer?: (questionId: string) => void;
  }

  let { oneditanswer }: Props = $props();

  const service = getAIBuilderService();

  // Question id -> the answer as the user reads it back; the same projection
  // the phase screens use, so a delegated answer reads the same in both.
  const answerLabelByQuestionId = $derived(buildAnswerLabels(service.messages));

  let inputRef = $state<FlowAIBuilderInput | undefined>();
  let pendingEditContext = $state<AIBuilderPlanEditContext | null>(null);
  const activeEditContext = $derived(pendingEditContext ?? service.activeStepTransportContext);
  const savedFlowStepScopeLabel = $derived.by(() => {
    const scope = service.activeStepScope;
    if (!scope || pendingEditContext) return null;
    return m.ai_builder_edit_context_step({ step: scope.stepNumber, name: scope.stepName });
  });

  const generatingText = $derived(
    service.statusMessage === "reading_sources"
      ? m.ai_builder_reply_reading_sources()
      : service.statusMessage === "understanding_request"
        ? m.ai_builder_reply_understanding()
        : service.hasSeenPlanInSession
          ? m.ai_builder_updating_plan()
          : m.ai_builder_generating()
  );

  export function focusInput(intent?: string | AIBuilderSuggestChangeIntent) {
    if (typeof intent === "string") {
      pendingEditContext = null;
      inputRef?.focus(intent ? { placeholder: intent } : undefined);
      return;
    }
    pendingEditContext = intent?.editContext ?? null;
    inputRef?.focus(
      intent ? { placeholder: intent.placeholder, prefill: intent.prefill } : undefined
    );
  }

  function clearPendingEditContext() {
    pendingEditContext = null;
  }

  function clearActiveEditContext() {
    if (pendingEditContext) {
      clearPendingEditContext();
    } else {
      service.clearActiveStepScope();
    }
    inputRef?.clearActivePlaceholder();
  }

  $effect(() => {
    if (!pendingEditContext) return;
    const currentPlanId = service.currentPlan?.plan_id ?? null;
    if (!service.hasSession || (currentPlanId && currentPlanId !== pendingEditContext.plan_id)) {
      clearPendingEditContext();
    }
  });

  // Called by the shell before it starts a fresh session, so a scoped-edit
  // placeholder cannot leak into the new conversation.
  export function resetComposerContext() {
    clearPendingEditContext();
    service.resetStepScope();
    inputRef?.clearActivePlaceholder();
  }

  let scrollContainer = $state<HTMLDivElement | undefined>();

  $effect(() => {
    void service.messages.length;
    void service.isStreaming;
    const target = scrollContainer;
    if (target) {
      requestAnimationFrame(() => {
        target.scrollTop = target.scrollHeight;
      });
    }
  });

  const visibleMessages = $derived(
    service.messages.filter(
      (message) =>
        message.content.trim().length > 0 ||
        message.question ||
        message.requirementsSummary ||
        message.plan
    )
  );
</script>

<div class="flex min-h-0 flex-1 flex-col">
  <!-- Keyboard users can focus and arrow-scroll the pane without a pointer. -->
  <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
  <div
    bind:this={scrollContainer}
    role="region"
    aria-label={m.ai_builder_conversation_aria()}
    tabindex="0"
    class="focus-visible:ring-accent-default/40 min-h-0 flex-1 overflow-y-auto px-4 py-4 focus-visible:ring-2 focus-visible:outline-none focus-visible:ring-inset"
  >
    {#if visibleMessages.length === 0}
      <p class="text-secondary py-6 text-center text-sm">{m.ai_builder_conversation_empty()}</p>
    {/if}
    {#each service.messages as message, i (`msg-${i}`)}
      <FlowAIBuilderMessage
        role={message.role}
        content={message.content}
        isLast={i === service.messages.length - 1}
        isStreaming={service.isStreaming && i === service.messages.length - 1}
        interactionDisabled={service.isCreating}
        question={message.question}
        questionAnswered={message.question
          ? service.isQuestionAnswered(message.question.question_id)
          : false}
        questionAnswerLabel={message.question
          ? (answerLabelByQuestionId.get(message.question.question_id) ?? null)
          : null}
        onEditAnswer={message.question && oneditanswer
          ? () => oneditanswer?.(message.question!.question_id)
          : undefined}
        requirementsSummary={message.requirementsSummary}
        requirementsConfirmed={message.requirementsSummary
          ? service.isRequirementsSummaryConfirmed(message.requirementsSummary)
          : false}
        requirementsActive={message.requirementsSummary
          ? service.isLatestRequirementsSummary(message.requirementsSummary)
          : false}
      />
    {/each}
    {#if service.isStreaming && service.messages[service.messages.length - 1]?.role === "user"}
      <div class="mt-4 py-2">
        <div class="generating-badge" role="status" aria-label={generatingText}>
          <span class="generating-dots" aria-hidden="true">
            <span></span>
            <span></span>
            <span></span>
          </span>
          <span class="text-[0.8125rem] leading-tight font-medium">{generatingText}</span>
        </div>
      </div>
    {/if}
  </div>

  {#if service.hasSession}
    <div class="border-default bg-primary shrink-0 border-t px-3 pt-3 pb-3">
      <FlowAIBuilderInput
        bind:this={inputRef}
        editContext={activeEditContext}
        editContextLabel={savedFlowStepScopeLabel}
        oncleareditcontext={clearActiveEditContext}
        refinement={service.currentPlan !== null}
        placeholder={service.currentPlan === null && service.messages.length > 0
          ? m.ai_builder_conversation_placeholder()
          : null}
      />
    </div>
  {/if}
</div>

<style lang="postcss">
  @reference "@eneo/ui/styles";

  .generating-badge {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    color: var(--text-secondary);
  }

  .generating-dots {
    display: inline-flex;
    gap: 0.2rem;
  }

  .generating-dots span {
    width: 0.3125rem;
    height: 0.3125rem;
    border-radius: 999px;
    background: currentColor;
    animation: dot-pulse 1.2s ease-in-out infinite;
  }

  .generating-dots span:nth-child(2) {
    animation-delay: 0.15s;
  }

  .generating-dots span:nth-child(3) {
    animation-delay: 0.3s;
  }

  @keyframes dot-pulse {
    0%,
    80%,
    100% {
      opacity: 0.35;
    }
    40% {
      opacity: 1;
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .generating-dots span {
      animation: none;
      opacity: 0.7;
    }
  }
</style>
