<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import { fade } from "svelte/transition";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import FlowAIBuilderDiagnosticCopyButton from "./FlowAIBuilderDiagnosticCopyButton.svelte";
  import FlowAIBuilderMessage from "./FlowAIBuilderMessage.svelte";
  import FlowAIBuilderInput from "./FlowAIBuilderInput.svelte";
  import { getAIBuilderService } from "./FlowAIBuilderService.svelte.ts";
  import {
    buildAIBuilderDiagnosticReport,
    buildAIBuilderDiagnosticReportPlan,
    buildAIBuilderDiagnosticReportSession
  } from "./aiBuilderDiagnosticReport";
  import type { AIBuilderPlanEditContext, AIBuilderSuggestChangeIntent } from "./protocol";
  import type { StructuredQuestionAnswerPayload } from "./structuredQuestionAnswer";

  interface Props {
    targetKind?: "create" | "edit";
  }

  let { targetKind = "edit" }: Props = $props();

  const service = getAIBuilderService();
  const isEditMode = $derived(targetKind === "edit");

  const showEmptyState = $derived(
    service.messages.length === 0 &&
      !service.isStreaming &&
      !service.currentPlan &&
      !service.isConflict &&
      !service.statusMessage
  );
  const streamErrorDiagnosticReport = $derived.by(() =>
    service.error
      ? buildAIBuilderDiagnosticReport({
          kind: "error",
          surface: "chat_stream",
          error: service.error,
          session: buildAIBuilderDiagnosticReportSession(service.session),
          plan: buildAIBuilderDiagnosticReportPlan(service.currentPlan)
        })
      : null
  );
  const turnRecoveryState = $derived(service.turnRecoveryState);
  const turnIsActive = $derived(
    service.latestTurnState === "open" || service.latestTurnState === "processing"
  );
  const turnRefreshFailed = $derived(service.authoritativeRefreshFailed && service.error !== null);
  const turnRecoveryTitle = $derived(
    turnRecoveryState === "failed_before_provider"
      ? m.ai_builder_turn_failed_before_provider_title()
      : turnRecoveryState === "provider_outcome_unknown"
        ? m.ai_builder_turn_provider_outcome_unknown_title()
        : turnIsActive
          ? m.ai_builder_turn_active_title()
          : null
  );
  const turnRecoveryDescription = $derived(
    turnRecoveryState === "failed_before_provider"
      ? m.ai_builder_turn_failed_before_provider_description()
      : turnRecoveryState === "provider_outcome_unknown"
        ? m.ai_builder_turn_provider_outcome_unknown_description()
        : turnIsActive
          ? m.ai_builder_turn_active_description()
          : null
  );
  let isRefreshingTurn = $state(false);

  async function handleTurnRetry() {
    if (turnRecoveryState === "failed_before_provider") {
      await service.retryLatestTurn();
      return;
    }
    if (turnRecoveryState === "provider_outcome_unknown") {
      await service.acknowledgeAndRetryLatestTurn();
    }
  }

  async function handleTurnRefresh() {
    if (isRefreshingTurn) return;
    isRefreshingTurn = true;
    try {
      await service.refreshSession();
    } finally {
      isRefreshingTurn = false;
    }
  }

  function handleQuestionAnswer(answer: StructuredQuestionAnswerPayload) {
    service.sendMessage(answer.text, answer.questionAnswer, undefined, pendingEditContext);
  }

  function latestUserRequestBefore(index: number): string | null {
    for (let cursor = index - 1; cursor >= 0; cursor -= 1) {
      const message = service.messages[cursor];
      if (!message || message.role !== "user") continue;
      const metadata = message.metadata ?? {};
      // Control replies confirm the builder state; edit-context messages are still user intent.
      if (metadata.requirements_confirmed === true || "question_answer" in metadata) continue;
      const content = message.content.trim();
      if (content.length > 0) return content;
    }
    return null;
  }

  let inputRef = $state<FlowAIBuilderInput | undefined>();
  let pendingEditContext = $state<AIBuilderPlanEditContext | null>(null);

  const generatingText = $derived(
    service.hasSeenPlanInSession ? m.ai_builder_updating_plan() : m.ai_builder_generating()
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
    inputRef?.clearActivePlaceholder();
  }

  $effect(() => {
    if (!pendingEditContext) return;
    const currentPlanId = service.currentPlan?.plan_id ?? null;
    if (!service.hasSession || (currentPlanId && currentPlanId !== pendingEditContext.plan_id)) {
      clearPendingEditContext();
    }
  });

  function handleRequirementsConfirm() {
    service.confirmRequirements();
  }

  function handleRequirementsChange() {
    clearPendingEditContext();
    inputRef?.focus({ placeholder: m.ai_builder_requirements_change_hint() });
  }

  // Called by the shell before it starts a fresh session, so a scoped-edit
  // placeholder cannot leak into the new conversation.
  export function resetComposerContext() {
    clearPendingEditContext();
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

  $effect(() => {
    void service.messages.length;
    void service.isStreaming;
    scrollToBottom();
  });
</script>

<div
  class="flex flex-col @[1040px]/builder:min-h-0 @[1040px]/builder:flex-1 @[1040px]/builder:overflow-hidden"
  class:items-center={showEmptyState}
  class:justify-center={showEmptyState}
  class:max-md:min-h-[calc(100dvh-var(--page-header-h,4rem))]={showEmptyState}
>
  {#if service.error || turnRecoveryState || turnIsActive}
    <div
      class="w-full shrink-0 px-4 pt-3 max-sm:px-3 max-sm:pt-2"
      transition:fade={{ duration: 160 }}
    >
      <Alert.Root
        variant={turnIsActive && !service.error ? "default" : "destructive"}
        class="grid grid-cols-[auto_minmax(0,1fr)] items-start gap-x-3 rounded-lg px-3.5 py-3"
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 20 20"
          fill="currentColor"
          class="mt-0.5 size-4 shrink-0"
          aria-hidden="true"
        >
          <path
            fill-rule="evenodd"
            d="M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0Zm-7-4a1 1 0 1 0-2 0v4a1 1 0 1 0 2 0V6Zm-1 8a1 1 0 1 0 0-2 1 1 0 0 0 0 2Z"
            clip-rule="evenodd"
          />
        </svg>
        <div class="min-w-0">
          {#if turnRecoveryTitle}
            <Alert.Title class="text-sm leading-snug">{turnRecoveryTitle}</Alert.Title>
          {/if}
          <Alert.Description
            id="ai-builder-turn-recovery-description"
            class="text-[0.8125rem] leading-relaxed"
          >
            {turnRecoveryDescription ?? service.error?.message ?? ""}
            {#if turnRecoveryDescription && turnRefreshFailed}
              <span class="mt-1 block">{m.ai_builder_turn_refresh_failed()}</span>
            {:else if turnRecoveryDescription && service.error}
              <span class="mt-1 block">{service.error.message}</span>
            {/if}
          </Alert.Description>
          <div
            class="mt-3 flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center"
            aria-busy={service.isStreaming || service.isRecoveringLatestTurn}
          >
            {#if turnRecoveryState}
              <Button
                variant={turnRecoveryState === "provider_outcome_unknown"
                  ? "destructive"
                  : "default"}
                size="sm"
                class="w-full whitespace-normal sm:w-auto"
                disabled={service.isStreaming || service.isRecoveringLatestTurn}
                aria-describedby="ai-builder-turn-recovery-description"
                onclick={handleTurnRetry}
              >
                {service.isStreaming || service.isRecoveringLatestTurn
                  ? m.ai_builder_turn_retrying()
                  : turnRecoveryState === "provider_outcome_unknown"
                    ? m.ai_builder_turn_retry_with_cost_acknowledgement()
                    : m.ai_builder_turn_retry()}
              </Button>
            {:else if turnIsActive}
              <Button
                variant="default"
                size="sm"
                disabled={isRefreshingTurn}
                aria-describedby="ai-builder-turn-recovery-description"
                onclick={handleTurnRefresh}
              >
                {m.refresh()}
              </Button>
            {/if}
            {#if streamErrorDiagnosticReport}
              <FlowAIBuilderDiagnosticCopyButton
                report={streamErrorDiagnosticReport}
                variant="ghost"
                size="xs"
                class="text-destructive hover:bg-destructive/10 hover:text-destructive"
              />
            {/if}
            {#if !turnRecoveryState && service.error}
              <Button
                variant="ghost"
                size="xs"
                class="text-destructive hover:bg-destructive/10 hover:text-destructive"
                onclick={() => service.clearError()}
              >
                {m.ai_builder_dismiss()}
              </Button>
            {/if}
          </div>
        </div>
      </Alert.Root>
    </div>
  {/if}

  {#if showEmptyState}
    <div class="flex-1" aria-hidden="true"></div>
    <div
      class="empty-welcome relative flex w-full max-w-[32rem] flex-col items-center px-6 pb-6 text-center max-sm:px-4"
      transition:fade={{ duration: 200 }}
    >
      <span class="welcome-glyph" aria-hidden="true">
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none">
          <path
            d="M6.75 6.25h3.5v3.5h-3.5v-3.5Zm7 0h3.5v3.5h-3.5v-3.5Zm-7 8h3.5v3.5h-3.5v-3.5Zm3.5-6.25h2.5m-2.5 8h2.5m0-8v8m0-4h4.5"
            stroke="currentColor"
            stroke-width="1.5"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
        </svg>
      </span>
      <h2
        class="text-primary mt-4 text-[clamp(1.375rem,4vw,1.75rem)] leading-[1.15] font-semibold tracking-[-0.015em] text-balance"
      >
        {isEditMode ? m.ai_builder_welcome_title_edit() : m.ai_builder_welcome_title()}
      </h2>
      <p
        class="text-secondary mt-2.5 max-w-[28rem] text-[clamp(0.875rem,2.4vw,0.9375rem)] leading-relaxed text-balance"
      >
        {isEditMode ? m.ai_builder_welcome_description_edit() : m.ai_builder_welcome_description()}
      </p>
    </div>
  {:else}
    <!-- Focusable scroll owner (handoff §1.3): keyboard users can reach and
         arrow-scroll the pane content without a pointer. -->
    <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
    <div
      bind:this={scrollContainer}
      role="region"
      aria-label={m.ai_builder_task_pane_aria()}
      tabindex="0"
      class="focus-visible:ring-accent-default/40 scroll-pb-4 px-4 py-6 focus-visible:ring-2 focus-visible:outline-none focus-visible:ring-inset max-sm:px-3 max-sm:py-4 @[1040px]/builder:flex-1 @[1040px]/builder:overflow-y-auto"
    >
      <div class="mx-auto max-w-[71ch]">
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
            requirementsSummary={message.requirementsSummary}
            requirementsUserRequest={message.requirementsSummary
              ? latestUserRequestBefore(i)
              : null}
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
    </div>
  {/if}

  <!-- Composer: bottom of the pane in split view; pinned to the viewport
       bottom while the page scrolls in the narrow (tabs) layouts. -->
  <div
    class="bg-primary border-border-default sticky bottom-0 z-10 w-full border-t px-4 pt-3 pb-4 max-sm:px-2 max-sm:pt-2 max-sm:pb-3 @[1040px]/builder:static"
    class:input-area-hero={showEmptyState}
  >
    <FlowAIBuilderInput
      bind:this={inputRef}
      editContext={pendingEditContext}
      oncleareditcontext={clearPendingEditContext}
    />
  </div>
  {#if showEmptyState}
    <div class="flex-1" aria-hidden="true"></div>
  {/if}
</div>

<style lang="postcss">
  @reference "@eneo/ui/styles";

  .empty-welcome {
    opacity: 0;
    animation: fade-up 0.5s cubic-bezier(0.16, 1, 0.3, 1) 0.1s forwards;
  }

  .welcome-glyph {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 3rem;
    height: 3rem;
    border-radius: 0.875rem;
    border: 1px solid var(--border-dimmer);
    background: var(--background-secondary);
    color: var(--accent-default);
    box-shadow: var(--shadow-xs);
  }

  .welcome-glyph svg {
    width: 1.375rem;
    height: 1.375rem;
  }

  .input-area-hero {
    max-width: 40rem;
    border-top: none;
    padding: 0 0 2rem;
    background: transparent;
    opacity: 0;
    animation: fade-up 0.45s cubic-bezier(0.16, 1, 0.3, 1) forwards;
  }

  .input-area-hero :global(.input-container) {
    box-shadow:
      var(--shadow-xs),
      inset 0 1px 2px var(--shadow-default);
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
    @apply border-accent-default/20 bg-accent-dimmer inline-flex items-center gap-2.5 rounded-full border px-3.5 py-2;
    width: fit-content;
    color: var(--accent-stronger);
  }

  .generating-dots {
    display: inline-flex;
    align-items: center;
    gap: 0.1875rem;
  }

  .generating-dots span {
    width: 0.375rem;
    height: 0.375rem;
    border-radius: 999px;
    background: currentColor;
    opacity: 0.35;
    animation: generating-dot 1.2s ease-in-out infinite;
  }

  .generating-dots span:nth-child(2) {
    animation-delay: 0.15s;
  }

  .generating-dots span:nth-child(3) {
    animation-delay: 0.3s;
  }

  @keyframes generating-dot {
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
      opacity: 0.6;
    }

    .empty-welcome,
    .input-area-hero {
      animation: none;
      opacity: 1;
    }
  }
</style>
