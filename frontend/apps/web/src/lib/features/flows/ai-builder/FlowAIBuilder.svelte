<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import { getLocale } from "$lib/paraglide/runtime";
  import { resolve } from "$app/paths";
  import { onMount, tick } from "svelte";
  import { SvelteMap, SvelteSet } from "svelte/reactivity";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Skeleton } from "$lib/components/ui/skeleton/index.js";
  import IconCheck from "@lucide/svelte/icons/check";
  import IconAlertTriangle from "@lucide/svelte/icons/triangle-alert";
  import IconMessageSquare from "@lucide/svelte/icons/message-square-text";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import BuilderPhaseRail, { type BuilderPhaseIndex } from "./BuilderPhaseRail.svelte";
  import BuilderTaskScreen from "./BuilderTaskScreen.svelte";
  import BuilderQuestionScreen from "./BuilderQuestionScreen.svelte";
  import BuilderReplyScreen from "./BuilderReplyScreen.svelte";
  import BuilderConfirmScreen from "./BuilderConfirmScreen.svelte";
  import BuilderBuildScreen from "./BuilderBuildScreen.svelte";
  import BuilderTurnAlert from "./BuilderTurnAlert.svelte";
  import BuilderConversationScreen from "./BuilderConversationScreen.svelte";
  import BuilderReviewScreen from "./BuilderReviewScreen.svelte";
  import { getAIBuilderService } from "./FlowAIBuilderService.svelte.ts";
  import type {
    AIBuilderSavedFlowStepScope,
    AIBuilderSuggestChangeIntent,
    ChatMessage,
    RequirementsSummary
  } from "./protocol";
  import {
    delegatedQuestionAnswer,
    type StructuredQuestionAnswerPayload
  } from "./structuredQuestionAnswer";

  interface Props {
    targetKind?: "create" | "edit";
    onapplied?: (detail: { flow_id: string; focusStepIndex: number | null }) => void;
    /** A draft chosen in the Flöden list; the page opens that session instead of a new one. */
    resumeSessionId?: string | null;
  }

  let { targetKind = "edit", onapplied, resumeSessionId = null }: Props = $props();

  const service = getAIBuilderService();
  const {
    state: { currentSpace }
  } = getSpacesManager();

  let taskScreenRef = $state<BuilderTaskScreen | undefined>();
  let conversationRef = $state<BuilderConversationScreen | undefined>();
  let conversationOpen = $state(false);
  let pendingSavedFlowStepScope = $state<AIBuilderSavedFlowStepScope | null>(null);
  let showReplaceEditSessionDialog = $state(false);
  let resumeFailed = $state(false);

  // ---- Session bootstrap ---------------------------------------------------

  onMount(() => {
    if (service.hasSession) return;
    if (targetKind === "create" && resumeSessionId) {
      void resumeChosenDraft(resumeSessionId);
    } else if (targetKind === "create") {
      // A new task always gets its own session; unfinished drafts live in the
      // Flöden list, so the builder never has to guess which one to reopen.
      void service.createSession("create");
    } else {
      void service.initialize(targetKind);
    }
  });

  async function resumeChosenDraft(sessionId: string) {
    await service.resumeSession(sessionId);
    if (!service.hasSession) resumeFailed = true;
  }

  // ---- Phase and screen ----------------------------------------------------

  const phaseIndex = $derived<BuilderPhaseIndex>(
    service.phase === "reviewing" ? 2 : service.phase === "building" ? 1 : 0
  );
  // A completed phase can be revisited without leaving the current one.
  let peekPhase = $state<BuilderPhaseIndex | null>(null);
  let lastPhaseIndex: BuilderPhaseIndex | null = null;
  $effect(() => {
    if (lastPhaseIndex !== null && phaseIndex !== lastPhaseIndex) {
      peekPhase = null;
      editingQuestionId = null;
    }
    lastPhaseIndex = phaseIndex;
  });
  const viewingPhase = $derived<BuilderPhaseIndex>(peekPhase ?? phaseIndex);

  const lastMessage = $derived<ChatMessage | undefined>(
    service.messages[service.messages.length - 1]
  );
  const pendingQuestionMessage = $derived.by(() => {
    const message = lastMessage;
    return message?.question && !service.isQuestionAnswered(message.question.question_id)
      ? message
      : null;
  });
  let editingQuestionId = $state<string | null>(null);
  const editingQuestionMessage = $derived.by(() => {
    if (!editingQuestionId) return null;
    for (let i = service.messages.length - 1; i >= 0; i -= 1) {
      const message = service.messages[i];
      if (message?.question?.question_id === editingQuestionId) return message;
    }
    return null;
  });
  const questionMessage = $derived(editingQuestionMessage ?? pendingQuestionMessage);

  const askedQuestionIds = $derived.by(() => {
    const ids: string[] = [];
    for (const message of service.messages) {
      const id = message.question?.question_id;
      if (id && !ids.includes(id)) ids.push(id);
    }
    return ids;
  });
  const answerLabelByQuestionId = $derived.by(() => {
    const labels = new SvelteMap<string, string>();
    for (const message of service.messages) {
      const id = message.questionAnswer?.question_id;
      if (id && message.content.trim()) labels.set(id, message.content.trim());
    }
    return labels;
  });
  const delegatedQuestionIds = $derived.by(() => {
    const ids = new SvelteSet<string>();
    for (const message of service.messages) {
      const answer = message.questionAnswer;
      if (answer?.question_id && answer.delegated === true) ids.add(answer.question_id);
    }
    return ids;
  });
  const answeredQuestions = $derived(
    askedQuestionIds
      .filter((id) => service.isQuestionAnswered(id))
      .map((id) => ({
        questionId: id,
        question:
          service.messages.find((message) => message.question?.question_id === id)?.question
            ?.question ?? "",
        answerLabel: answerLabelByQuestionId.get(id) ?? "",
        // Eneo settled this one; the answer is still the user's to change.
        delegated: delegatedQuestionIds.has(id)
      }))
  );
  const questionNumber = $derived.by(() => {
    const id = questionMessage?.question?.question_id;
    if (!id) return 1;
    const index = askedQuestionIds.indexOf(id);
    return index === -1 ? askedQuestionIds.length + 1 : index + 1;
  });

  const latestSummaryMessageIndex = $derived.by(() => {
    for (let i = service.messages.length - 1; i >= 0; i -= 1) {
      if (service.messages[i]?.requirementsSummary) return i;
    }
    return -1;
  });
  const latestSummary = $derived(
    latestSummaryMessageIndex === -1
      ? null
      : (service.messages[latestSummaryMessageIndex]?.requirementsSummary ?? null)
  );
  // "Uppdaterad — bekräfta igen": an earlier version of the requirements was
  // confirmed and this newer version replaced it, so the old confirmation
  // cannot carry over.
  const summaryIsStale = $derived.by(() => {
    const latest = latestSummary;
    if (!latest || service.isRequirementsSummaryConfirmed(latest)) return false;
    return service.messages.some(
      (message) =>
        message.requirementsSummary &&
        message.requirementsSummary.requirements_version !== latest.requirements_version &&
        service.isRequirementsSummaryConfirmed(message.requirementsSummary)
    );
  });
  function latestUserRequestBefore(index: number): string | null {
    for (let cursor = index - 1; cursor >= 0; cursor -= 1) {
      const message = service.messages[cursor];
      if (!message || message.role !== "user") continue;
      const metadata = message.metadata ?? {};
      if (metadata.requirements_confirmed === true || message.questionAnswer !== undefined)
        continue;
      const content = message.content.trim();
      if (content.length > 0) return content;
    }
    return null;
  }
  const lastAssistantText = $derived.by(() => {
    for (let i = service.messages.length - 1; i >= 0; i -= 1) {
      const message = service.messages[i];
      if (message?.role === "assistant" && message.content.trim()) return message.content.trim();
      if (message?.role === "user") return null;
    }
    return null;
  });

  type Screen = "task" | "question" | "reply" | "confirm" | "build" | "review" | "conversation";
  const screen = $derived<Screen>(
    (() => {
      // The transcript is a screen of its own; it replaces the phase screen
      // instead of covering it.
      if (conversationOpen) return "conversation";
      if (viewingPhase === 2) return "review";
      if (viewingPhase === 1) return "build";
      // Changing an earlier answer happens on the confirmation, above the card
      // it rewrites. Before any summary exists there is no card, so the
      // question still owns the screen.
      if (editingQuestionMessage) return latestSummary ? "confirm" : "question";
      if (pendingQuestionMessage) return "question";
      if (service.phase === "confirming" && latestSummary && peekPhase === null) return "confirm";
      if (service.messages.length === 0 && !service.isStreaming) return "task";
      if (latestSummary && phaseIndex > 0) return "confirm";
      return "reply";
    })()
  );

  // ---- Screen change: announce it, then hand focus to the new heading -------
  // A screen swap is a navigation for anyone not watching the viewport, so it
  // is spoken once and the caret lands on the heading of what just appeared.

  // A second question is a new screen even though `screen` stays "question".
  const screenKey = $derived(
    screen === "question" ? `question:${questionMessage?.question?.question_id ?? ""}` : screen
  );
  const screenAnnouncement = $derived.by(() => {
    switch (screen) {
      case "question":
        return questionMessage?.question
          ? m.ai_builder_announce_question({
              number: String(questionNumber),
              question: questionMessage.question.question
            })
          : "";
      case "confirm":
        return m.ai_builder_requirements_title();
      case "build":
        return m.ai_builder_rail_planning();
      case "review":
        return m.ai_builder_announce_review();
      default:
        return "";
    }
  });
  let screenAnnouncementText = $state("");
  let builderRootEl = $state<HTMLElement | null>(null);
  let announcedScreenKey: string | null = null;
  $effect(() => {
    const key = screenKey;
    const text = screenAnnouncement;
    // Bootstrap and resume settle on a screen without the user doing anything.
    if (!service.hasSession || service.isInitializing) {
      announcedScreenKey = null;
      return;
    }
    if (announcedScreenKey === null || key === announcedScreenKey) {
      announcedScreenKey = key;
      return;
    }
    announcedScreenKey = key;
    if (!text) return;
    screenAnnouncementText = text;
    void focusScreenHeading();
  });

  async function focusScreenHeading() {
    await tick();
    const active = document.activeElement;
    // Never yank the caret out of a composer mid-sentence.
    if (
      active instanceof HTMLElement &&
      (active.tagName === "TEXTAREA" || active.tagName === "INPUT" || active.isContentEditable)
    ) {
      return;
    }
    builderRootEl?.querySelector<HTMLElement>("[data-builder-screen-heading]")?.focus();
  }

  // The server records the message before it works on it, so a recorded turn
  // that failed is not lost — the turn alert below owns that case. Only a
  // request that never got an answer leaves the draft genuinely uncertain.
  const savingProblem = $derived(service.error?.code === "network");

  // ---- Error ownership ------------------------------------------------------
  // Once generation is visible, the plan surface keeps ownership of any
  // failure so the same error cannot flash on two surfaces.
  let hadGenerationStatus = $state(false);
  $effect(() => {
    if (!service.hasSession) {
      hadGenerationStatus = false;
    } else if (
      service.statusMessage !== null ||
      service.hasSeenPlanInSession ||
      (service.phase === "building" && service.isStreaming)
    ) {
      hadGenerationStatus = true;
    }
  });
  const planSurfaceOwnsError = $derived(
    hadGenerationStatus && service.error !== null && service.currentPlan === null
  );
  const generationFailedWithoutPlan = $derived(
    planSurfaceOwnsError && service.streamState === "failed"
  );

  // ---- Actions --------------------------------------------------------------

  const activeEditContext = $derived(service.activeStepTransportContext);
  const savedFlowStepScopeLabel = $derived.by(() => {
    const scope = service.activeStepScope;
    if (!scope) return null;
    return m.ai_builder_edit_context_step({ step: scope.stepNumber, name: scope.stepName });
  });

  function handleQuestionAnswer(payload: StructuredQuestionAnswerPayload) {
    editingQuestionId = null;
    void service.sendMessage(payload.text, payload.questionAnswer, undefined, activeEditContext);
  }

  function handleDelegateQuestion(questionId: string) {
    editingQuestionId = null;
    void service.sendMessage(
      "",
      delegatedQuestionAnswer(questionId, getLocale()),
      undefined,
      activeEditContext
    );
  }

  function handleEditAnswer(questionId: string) {
    editingQuestionId = questionId;
    peekPhase = 0;
    conversationOpen = false;
  }

  function handleRequirementsConfirm() {
    void service.confirmRequirements(activeEditContext);
  }

  /** "Ljud → PDF-dokument": the recap is a glance, so the server's full
   *  sentences ("Primär indata vid körning: Dokument.") are reduced to the
   *  thing named after the colon. */
  function summaryTerm(sentence: string | null | undefined): string {
    const text = (sentence ?? "").trim();
    const named = text.includes(":") ? text.slice(text.indexOf(":") + 1) : text;
    return named.trim().replace(/[.\s]+$/, "");
  }

  function buildConfirmedLine(summary: RequirementsSummary | null): string | null {
    if (!summary) return null;
    const input = summaryTerm(summary.input_description);
    const output = summaryTerm(summary.output_description);
    if (!input && !output) return null;
    return input && output ? `${input} → ${output}` : input || output;
  }

  function handleRequirementsChange(text: string) {
    void service.changeRequirements(text);
  }

  function handleSuggestChange(intent: AIBuilderSuggestChangeIntent) {
    conversationOpen = true;
    void conversationRef?.focusComposer(intent);
  }

  function handleRailSelect(phase: BuilderPhaseIndex) {
    // The build phase has nothing to revisit once it is done.
    if (phase === 1 && phaseIndex !== 1) return;
    editingQuestionId = null;
    peekPhase = phase === phaseIndex ? null : phase;
  }

  const visibleMessageCount = $derived(
    service.messages.filter(
      (message) =>
        message.content.trim().length > 0 || message.question || message.requirementsSummary
    ).length
  );

  const otherDraftCount = $derived(
    service.recoverableCreateDrafts.filter(
      (draft) => draft.session_id !== service.session?.session_id
    ).length
  );
  const flowsHref = $derived(resolve(`/spaces/${$currentSpace.routeId}/flows`));

  // ---- Edit host contract ---------------------------------------------------

  // A cold launch from the flow editor can call in before the session exists
  // and the task screen is mounted; the focus request waits for the real composer.
  let pendingTaskFocus = $state<{ placeholder: string } | null>(null);
  $effect(() => {
    if (pendingTaskFocus && taskScreenRef) {
      taskScreenRef.focusInput(pendingTaskFocus);
      pendingTaskFocus = null;
    }
  });

  async function activateSavedFlowStep(scope: AIBuilderSavedFlowStepScope) {
    service.setSavedFlowStepScope(scope);
    peekPhase = null;
    await tick();
    const focus = { placeholder: m.ai_builder_saved_step_prompt_placeholder() };
    if (taskScreenRef) {
      taskScreenRef.focusInput(focus);
    } else {
      pendingTaskFocus = focus;
    }
  }

  // The flow editor may launch a saved-step edit before this shell's session
  // exists. Edit bootstrap resumes an ongoing session when there is one, so the
  // "replace the ongoing edit?" decision must wait until that is known.
  let pendingSavedFlowStepLaunch = $state<AIBuilderSavedFlowStepScope | null>(null);
  $effect(() => {
    const scope = pendingSavedFlowStepLaunch;
    if (scope && service.hasSession && !service.isInitializing) {
      pendingSavedFlowStepLaunch = null;
      void launchSavedFlowStep(scope);
    }
  });

  async function launchSavedFlowStep(scope: AIBuilderSavedFlowStepScope) {
    // A resumed session can carry a plan before the plan itself has loaded;
    // its latest_plan_id already says the edit is ongoing.
    if (
      service.messages.length > 0 ||
      service.currentPlan !== null ||
      service.session?.latest_plan_id != null
    ) {
      pendingSavedFlowStepScope = scope;
      showReplaceEditSessionDialog = true;
      return;
    }
    await activateSavedFlowStep(scope);
  }

  export async function focusSavedFlowStep(scope: AIBuilderSavedFlowStepScope) {
    if (!service.hasSession || service.isInitializing) {
      pendingSavedFlowStepLaunch = scope;
      return;
    }
    await launchSavedFlowStep(scope);
  }

  function cancelSavedFlowStepReplacement() {
    pendingSavedFlowStepScope = null;
  }

  async function confirmSavedFlowStepReplacement() {
    const scope = pendingSavedFlowStepScope;
    if (scope === null) return;
    conversationRef?.resetComposerContext();
    await service.startFreshSession("edit");
    pendingSavedFlowStepScope = null;
    await activateSavedFlowStep(scope);
  }

  const canStartOver = $derived(
    targetKind === "edit" &&
      service.hasSession &&
      (service.messages.length > 0 || service.currentPlan !== null) &&
      !service.isStreaming
  );

  function handleStartOver() {
    conversationRef?.resetComposerContext();
    void service.startFreshSession("edit");
  }
</script>

{#if service.isInitializing || (!service.hasSession && !resumeFailed && !service.error)}
  <div class="flex flex-1 flex-col gap-8 p-6" aria-hidden="true">
    <Skeleton class="h-10 w-full rounded-lg" />
    <div class="flex flex-col gap-3">
      <Skeleton class="h-4 w-4/5 rounded" />
      <Skeleton class="h-4 w-3/5 rounded" />
      <Skeleton class="h-4 w-2/5 rounded" />
    </div>
  </div>
{:else if resumeFailed && !service.hasSession}
  <div class="flex flex-1 items-center justify-center p-6">
    <div class="max-w-[40ch] text-center">
      <p class="text-primary font-semibold">{m.ai_builder_resume_failed_title()}</p>
      <p class="text-secondary mt-1 text-sm">{service.error?.message ?? ""}</p>
      <div class="mt-4 flex justify-center gap-2">
        <Button variant="outline" href={flowsHref}>{m.ai_builder_resume_failed_back()}</Button>
        <Button
          onclick={() => {
            resumeFailed = false;
            void service.createSession("create");
          }}
        >
          {m.ai_builder_resume_failed_new()}
        </Button>
      </div>
    </div>
  </div>
{:else}
  <div
    bind:this={builderRootEl}
    class="bg-secondary @container/builder flex min-h-0 w-full flex-1 flex-col"
  >
    <p class="sr-only" role="status" aria-live="polite" data-builder-announcer>
      {screenAnnouncementText}
    </p>
    <!-- Phase header: rail + saved state + the conversation one gesture away.
         The header column is as wide as the review card and centred with it,
         so the rail starts on the same line as the plan the user reads most. -->
    <div class="bg-primary border-default sticky top-0 z-20 shrink-0 border-b px-7 max-sm:px-3">
      <div class="mx-auto flex max-w-[63.75rem] items-center gap-3 pt-3 2xl:max-w-[75rem]">
        {#if savingProblem}
          <span
            class="text-warning-stronger inline-flex items-center gap-1.5 text-xs font-semibold"
            title={m.ai_builder_saved_state_problem_title()}
            role="status"
          >
            <IconAlertTriangle class="size-3.5" aria-hidden="true" />
            {m.ai_builder_saved_state_problem()}
          </span>
        {:else if service.hasSession && service.messages.length > 0}
          <span
            class="text-secondary inline-flex items-center gap-1.5 text-xs"
            title={m.ai_builder_saved_state_title()}
          >
            <span
              class="bg-positive-dimmer text-positive-stronger inline-flex size-[0.9375rem] items-center justify-center rounded-full"
              aria-hidden="true"
            >
              <IconCheck class="size-2.5" strokeWidth={3.5} />
            </span>
            {m.ai_builder_saved_state_auto()}
          </span>
        {:else}
          <span class="text-secondary text-xs">{m.ai_builder_saved_state_new()}</span>
        {/if}
        <div class="ml-auto flex items-center gap-2">
          {#if canStartOver}
            <Button
              variant="ghost"
              size="sm"
              onclick={handleStartOver}
              disabled={service.isCreating}
            >
              {m.ai_builder_start_fresh()}
            </Button>
          {/if}
          <Button
            variant="outline"
            size="sm"
            class="gap-1.5"
            aria-pressed={conversationOpen}
            aria-label={m.ai_builder_conversation_button_aria({
              count: String(visibleMessageCount)
            })}
            title={m.ai_builder_conversation_button_title()}
            onclick={() => (conversationOpen = !conversationOpen)}
          >
            <IconMessageSquare class="size-3.5" />
            {m.ai_builder_conversation_button()}
            <span
              class="bg-tertiary text-secondary inline-flex h-[1.125rem] min-w-[1.125rem] items-center justify-center rounded-full px-1.5 text-[0.6875rem] font-bold"
            >
              {visibleMessageCount}
            </span>
          </Button>
        </div>
      </div>
      <div class="mx-auto max-w-[63.75rem] py-3 2xl:max-w-[75rem]">
        <BuilderPhaseRail current={phaseIndex} viewing={viewingPhase} onselect={handleRailSelect} />
      </div>
    </div>

    <div class="flex min-h-0 flex-1 flex-col overflow-y-auto">
      <BuilderTurnAlert
        {targetKind}
        suppressStreamError={generationFailedWithoutPlan}
        onbeforestartfresh={() => conversationRef?.resetComposerContext()}
      />

      {#if screen === "conversation"}
        <BuilderConversationScreen
          bind:this={conversationRef}
          oneditanswer={handleEditAnswer}
          onclose={() => (conversationOpen = false)}
        />
      {:else if screen === "task"}
        <BuilderTaskScreen
          bind:this={taskScreenRef}
          {targetKind}
          {otherDraftCount}
          {flowsHref}
          editContext={activeEditContext}
          editContextLabel={savedFlowStepScopeLabel}
          oncleareditcontext={() => service.clearActiveStepScope()}
        />
      {:else if screen === "question" && questionMessage}
        <BuilderQuestionScreen
          {questionMessage}
          {questionNumber}
          answered={answeredQuestions}
          {editingQuestionId}
          disabled={service.isCreating || service.isStreaming}
          onanswer={handleQuestionAnswer}
          ondelegate={handleDelegateQuestion}
          onedit={handleEditAnswer}
          oncanceledit={() => (editingQuestionId = null)}
        />
      {:else if screen === "confirm" && latestSummary}
        <BuilderConfirmScreen
          summary={latestSummary}
          userRequest={latestUserRequestBefore(latestSummaryMessageIndex)}
          savedFlowStepScope={service.activeStepScope}
          attachments={service.session?.attachments ?? []}
          answered={answeredQuestions}
          noQuestions={askedQuestionIds.length === 0}
          confirmed={service.isRequirementsSummaryConfirmed(latestSummary)}
          stale={summaryIsStale}
          readOnly={phaseIndex > 0}
          disabled={service.isCreating || service.isStreaming}
          editingQuestion={editingQuestionMessage}
          editingQuestionNumber={questionNumber}
          onanswer={handleQuestionAnswer}
          ondelegate={handleDelegateQuestion}
          oncanceledit={() => (editingQuestionId = null)}
          onconfirm={handleRequirementsConfirm}
          onchange={handleRequirementsChange}
          oneditanswer={handleEditAnswer}
        />
      {:else if screen === "build" && generationFailedWithoutPlan}
        <!-- A failed generation keeps its one existing failure/retry surface. -->
        <div class="bg-primary flex min-h-0 flex-1 flex-col">
          <BuilderReviewScreen
            showGenerationFailure={true}
            onapplied={(detail) => onapplied?.(detail)}
            onsuggestchange={handleSuggestChange}
            onshowconversation={() => (conversationOpen = true)}
          />
        </div>
      {:else if screen === "build"}
        <BuilderBuildScreen
          status={service.statusMessage}
          stepCount={service.currentPlan?.proposal.spec.steps.length ?? 5}
          confirmedLine={buildConfirmedLine(latestSummary)}
          onshowconfirmation={() => (peekPhase = 0)}
        />
      {:else if screen === "review"}
        <div class="bg-primary flex min-h-0 flex-1 flex-col">
          <BuilderReviewScreen
            showGenerationFailure={generationFailedWithoutPlan}
            onapplied={(detail) => onapplied?.(detail)}
            onsuggestchange={handleSuggestChange}
            onshowconversation={() => (conversationOpen = true)}
          />
        </div>
      {:else}
        <BuilderReplyScreen
          waiting={service.isStreaming}
          assistantText={lastAssistantText}
          editContext={activeEditContext}
          editContextLabel={savedFlowStepScopeLabel}
          oncleareditcontext={() => service.clearActiveStepScope()}
        />
      {/if}
    </div>
  </div>
{/if}

<AlertDialog.Root bind:open={showReplaceEditSessionDialog}>
  <AlertDialog.Content>
    <AlertDialog.Header>
      <AlertDialog.Title>{m.ai_builder_replace_edit_title()}</AlertDialog.Title>
      <AlertDialog.Description>
        {m.ai_builder_replace_edit_description({
          stepName: pendingSavedFlowStepScope?.stepName ?? m.flow_step_unnamed()
        })}
      </AlertDialog.Description>
    </AlertDialog.Header>
    <AlertDialog.Footer>
      <AlertDialog.Cancel onclick={cancelSavedFlowStepReplacement}>
        {m.ai_builder_replace_edit_cancel()}
      </AlertDialog.Cancel>
      <AlertDialog.Action variant="destructive" onclick={confirmSavedFlowStepReplacement}>
        {m.ai_builder_replace_edit_action()}
      </AlertDialog.Action>
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>
