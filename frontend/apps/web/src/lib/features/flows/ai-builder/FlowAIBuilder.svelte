<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import { getLocale } from "$lib/paraglide/runtime";
  import { resolve } from "$app/paths";
  import { onMount, tick } from "svelte";
  import { SvelteSet } from "svelte/reactivity";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Skeleton } from "$lib/components/ui/skeleton/index.js";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import BuilderPhaseRail, { type BuilderPhaseIndex } from "./BuilderPhaseRail.svelte";
  import BuilderTaskScreen from "./BuilderTaskScreen.svelte";
  import BuilderQuestionScreen from "./BuilderQuestionScreen.svelte";
  import BuilderReplyScreen from "./BuilderReplyScreen.svelte";
  import BuilderConfirmScreen from "./BuilderConfirmScreen.svelte";
  import BuilderBuildScreen from "./BuilderBuildScreen.svelte";
  import BuilderTurnAlert from "./BuilderTurnAlert.svelte";
  import BuilderConversationScreen from "./BuilderConversationScreen.svelte";
  import BuilderSessionStatus from "./BuilderSessionStatus.svelte";
  import BuilderReviewScreen from "./BuilderReviewScreen.svelte";
  import BuilderFindingsScreen from "./BuilderFindingsScreen.svelte";
  import { getAIBuilderService } from "./FlowAIBuilderService.svelte.ts";
  import { summaryTerm } from "./aiBuilderSummaryText";
  import { buildAnswerLabels } from "./aiBuilderAnswerLabel";
  import type { StructuredInputFieldAnswer } from "./structuredQuestionAnswer";
  import { reopenQuestionRequest } from "./structuredQuestionAnswer";
  import type {
    AIBuilderSavedFlowStepScope,
    ChatMessage,
    RequirementsSummary,
    AIBuilderReviewContext
  } from "./protocol";
  import {
    delegatedQuestionAnswer,
    type StructuredQuestionAnswerPayload
  } from "./structuredQuestionAnswer";

  interface Props {
    targetKind?: "create" | "edit";
    /** The host shows the saved state and Samtal on its own title row. */
    statusInPageHeader?: boolean;
    onapplied?: (detail: { flow_id: string; focusStepIndex: number | null }) => void;
    /** A draft chosen in the Flöden list; the page opens that session instead of a new one. */
    resumeSessionId?: string | null;
  }

  let {
    targetKind = "edit",
    statusInPageHeader = false,
    onapplied,
    resumeSessionId = null
  }: Props = $props();

  const service = getAIBuilderService();
  const {
    state: { currentSpace }
  } = getSpacesManager();

  let taskScreenRef = $state<BuilderTaskScreen | undefined>();
  let conversationRef = $state<BuilderConversationScreen | undefined>();
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
  // What the newest answer to the question being edited settled: the
  // options it selected, or the text the user typed instead. The editor
  // starts from that, whether the user or Eneo (delegated) settled it.
  const editingAnswer = $derived.by(() => {
    if (!editingQuestionId) return null;
    for (let i = service.messages.length - 1; i >= 0; i -= 1) {
      const answer = service.messages[i]?.questionAnswer;
      if (answer?.question_id === editingQuestionId) return answer;
    }
    return null;
  });
  const editingAnsweredOptionIds = $derived.by(() => {
    const answer = editingAnswer;
    if (!answer) return null;
    if (answer.selected_option_ids?.length) return [...answer.selected_option_ids];
    return answer.selected_option_id ? [answer.selected_option_id] : null;
  });
  const editingAnsweredCustomValue = $derived(editingAnswer?.custom_value ?? null);

  const askedQuestionIds = $derived.by(() => {
    const ids: string[] = [];
    for (const message of service.messages) {
      const id = message.question?.question_id;
      if (id && !ids.includes(id)) ids.push(id);
    }
    return ids;
  });
  const answerLabelByQuestionId = $derived(buildAnswerLabels(service.messages));
  /** A question still open is answered by whatever the user last sent for it,
   *  which is deliberately not bounded by the summary. */
  const pendingFieldAnswer = $derived.by(() => {
    const id = questionMessage?.question?.question_id;
    if (!id) return null;
    for (let i = service.messages.length - 1; i >= 0; i -= 1) {
      const answer = service.messages[i]?.questionAnswer;
      if (answer?.question_id === id && answer.input_fields?.length) {
        return answer.input_fields as StructuredInputFieldAnswer[];
      }
    }
    return null;
  });
  // Only the newest answer to a question says whether Eneo chose it: a
  // question handed to Eneo and later answered by the user is the user's.
  const delegatedQuestionIds = $derived.by(() => {
    const ids = new SvelteSet<string>();
    const seen = new SvelteSet<string>();
    for (let i = service.messages.length - 1; i >= 0; i -= 1) {
      const answer = service.messages[i]?.questionAnswer;
      if (!answer?.question_id || seen.has(answer.question_id)) continue;
      seen.add(answer.question_id);
      if (answer.delegated === true) ids.add(answer.question_id);
    }
    return ids;
  });
  // A question can be asked twice with different wording; the newest is the one
  // the user answered, and the one reopening it will show.
  function newestQuestion(questionId: string) {
    for (let i = service.messages.length - 1; i >= 0; i -= 1) {
      const question = service.messages[i]?.question;
      if (question?.question_id === questionId) return question;
    }
    return null;
  }
  const answeredQuestions = $derived(
    askedQuestionIds
      .filter((id) => service.isQuestionAnswered(id))
      .map((id) => newestQuestion(id))
      .filter((question) => question !== null)
      .map((question) => ({
        questionId: question.question_id,
        topic: question.topic ?? null,
        question: question.question,
        answerLabel: answerLabelByQuestionId.get(question.question_id) ?? "",
        // Eneo settled this one; the answer is still the user's to change.
        delegated: delegatedQuestionIds.has(question.question_id)
      }))
  );
  // Only the server can number the questions it put to the user: a re-asked
  // question keeps its number, and position in the transcript does not survive
  // compaction. A record from before the field simply has no number.
  const questionNumber = $derived(questionMessage?.question?.question_index ?? null);

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
  const confirmedFieldAnswer = $derived.by(() => {
    let found: { questionId: string; fields: StructuredInputFieldAnswer[] } | null = null;
    for (const [index, message] of service.messages.entries()) {
      if (latestSummaryMessageIndex !== -1 && index > latestSummaryMessageIndex) break;
      const answer = message.questionAnswer;
      if (answer?.question_id && answer.input_fields?.length) {
        found = {
          questionId: answer.question_id,
          fields: answer.input_fields as StructuredInputFieldAnswer[]
        };
      }
    }
    return found;
  });
  const runtimeFieldsQuestionId = $derived(confirmedFieldAnswer?.questionId ?? null);
  const runtimeFields = $derived(
    (latestSummary?.runtime_input_fields ?? []).map((field) => ({
      label: field.label,
      type: field.type,
      required: field.required,
      purpose: field.purpose,
      options: field.options ?? []
    }))
  );
  const summaryRevisionPending = $derived(
    service.isStreaming &&
      latestSummaryMessageIndex !== -1 &&
      service.messages.some(
        (message, index) => index > latestSummaryMessageIndex && message.role === "user"
      )
  );
  // "Uppdaterad. Bekräfta igen.": an earlier version of the requirements was
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

  type Screen =
    "task" | "question" | "reply" | "confirm" | "build" | "review" | "conversation" | "findings";
  const screen = $derived<Screen>(
    (() => {
      // The transcript is a screen of its own; it replaces the phase screen
      // instead of covering it.
      if (service.conversationOpen) return "conversation";
      // The run review is opened on purpose and closes itself when a finding
      // becomes a message; while open it owns the first phase's screen.
      if (service.review.status !== "closed" && viewingPhase === 0) return "findings";
      if (viewingPhase === 2) return "review";
      if (viewingPhase === 1) return "build";
      // Changing an earlier answer happens on the confirmation, above the card
      // it rewrites. Before any summary exists there is no card, so the
      // question still owns the screen.
      if (editingQuestionMessage) return latestSummary ? "confirm" : "question";
      if (pendingQuestionMessage) return "question";
      if (service.phase === "confirming" && latestSummary && peekPhase === null) return "confirm";
      if (service.messages.length === 0 && !service.isStreaming) return "task";
      // Stepping back to the contract keeps it on screen until the phase moves
      // on: opening a question from the card peeks at phase 0, so closing that
      // question must land back on the card and not on the composer.
      if (latestSummary && (phaseIndex > 0 || peekPhase === 0)) return "confirm";
      return "reply";
    })()
  );

  // One column per screen: the rail, the status row and the content sit in it,
  // so nothing floats beside the card it belongs to.
  const columnClass = $derived.by(() => {
    switch (screen) {
      case "review":
        return "max-w-[53.75rem] 2xl:max-w-[62.5rem]";
      case "task":
        return "max-w-[40.625rem] 2xl:max-w-[45rem]";
      case "findings":
        return "max-w-[43.75rem] 2xl:max-w-[48.125rem]";
      case "question":
      case "reply":
        return "max-w-[41.25rem] 2xl:max-w-[45.625rem]";
      default:
        return "max-w-[43.75rem] 2xl:max-w-[48.125rem]";
    }
  });

  // ---- Screen change: announce it, then hand focus to the new heading -------
  // A screen swap is a navigation for anyone not watching the viewport, so it
  // is spoken once and the caret lands on the heading of what just appeared.

  // A second question is a new screen even though `screen` stays "question".
  const screenKey = $derived(
    screen === "question" ? `question:${questionMessage?.question?.question_id ?? ""}` : screen
  );
  const screenAnnouncement = $derived.by(() => {
    switch (screen) {
      case "question": {
        const question = questionMessage?.question;
        if (!question) return "";
        // An unnumbered question is announced by its words alone.
        return questionNumber === null
          ? question.question
          : m.ai_builder_announce_question({
              number: String(questionNumber),
              question: question.question
            });
      }
      case "confirm":
        return m.ai_builder_requirements_title();
      case "findings":
        return m.ai_builder_review_title();
      case "build":
        return m.ai_builder_rail_planning();
      case "review":
        return m.ai_builder_announce_review();
      case "conversation":
        return m.ai_builder_conversation_title();
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
    // Focus alone, never a scroll: a browser may scroll the nearest scrollable
    // ancestor to reveal the heading, which drags a horizontally scrollable row
    // (the answer chips on a phone) out of place.
    builderRootEl
      ?.querySelector<HTMLElement>("[data-builder-screen-heading]")
      ?.focus({ preventScroll: true });
  }

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
    service.closeConversation();
  }

  /** An assumption has no answer to edit: the server is asked to reopen its
   *  question, pinned to the disclosure the user is looking at. */
  function handleReopenAssumption(questionId: string) {
    const version = latestSummary?.requirements_version;
    if (!version) return;
    editingQuestionId = null;
    void service.sendMessage(
      "",
      reopenQuestionRequest(questionId, version),
      undefined,
      activeEditContext
    );
  }

  function handleRequirementsConfirm() {
    void service.confirmRequirements(activeEditContext);
  }

  function buildConfirmedLine(summary: RequirementsSummary | null): string | null {
    if (!summary) return null;
    const input = summaryTerm(summary.input_description);
    const output = summaryTerm(summary.output_description);
    if (!input && !output) return null;
    return input && output ? `${input} → ${output}` : input || output;
  }

  function handleRequirementsChange(text: string, topic?: string | null) {
    void service.changeRequirements(text, topic);
  }

  function handleRailSelect(phase: BuilderPhaseIndex) {
    // The build phase has nothing to revisit once it is done.
    if (phase === 1 && phaseIndex !== 1) return;
    editingQuestionId = null;
    peekPhase = phase === phaseIndex ? null : phase;
  }

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

  // Opening the run review is one transition: it waits for the session like a
  // saved-step launch, asks before replacing an ongoing edit, drops any
  // saved-step scope, and lands on the first phase where the findings render.
  let pendingReviewLaunch = $state(false);
  let pendingReviewReplacement = $state(false);
  $effect(() => {
    if (pendingReviewLaunch && service.hasSession && !service.isInitializing) {
      pendingReviewLaunch = false;
      void launchReview();
    }
  });

  async function launchReview() {
    if (
      service.messages.length > 0 ||
      service.currentPlan !== null ||
      service.session?.latest_plan_id != null
    ) {
      pendingReviewReplacement = true;
      showReplaceEditSessionDialog = true;
      return;
    }
    await activateReview();
  }

  async function activateReview() {
    service.clearActiveStepScope();
    peekPhase = null;
    await service.openReview();
  }

  /** Open the run review from outside the Builder (the run history tab). */
  export async function openReview() {
    if (!service.hasSession || service.isInitializing) {
      pendingReviewLaunch = true;
      return;
    }
    await launchReview();
  }

  function prepareChangeFromFinding(detail: {
    message: string;
    reviewContext: AIBuilderReviewContext;
  }) {
    // A finding is the whole change request; a lingering saved-step scope
    // would otherwise re-attach itself to the next message.
    service.clearActiveStepScope();
    void service.sendMessage(detail.message, undefined, undefined, null, detail.reviewContext);
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
    pendingReviewReplacement = false;
  }

  async function confirmSavedFlowStepReplacement() {
    const scope = pendingSavedFlowStepScope;
    const review = pendingReviewReplacement;
    if (scope === null && !review) return;
    conversationRef?.resetComposerContext();
    await service.startFreshSession("edit");
    pendingSavedFlowStepScope = null;
    pendingReviewReplacement = false;
    if (scope !== null) {
      await activateSavedFlowStep(scope);
    } else {
      await activateReview();
    }
  }

  const canStartOver = $derived(
    targetKind === "edit" &&
      service.hasSession &&
      (service.messages.length > 0 || service.currentPlan !== null) &&
      !service.isStreaming
  );

  let showDiscardChangeDialog = $state(false);

  function handleStartOver() {
    showDiscardChangeDialog = true;
  }

  function discardChangeAndStartOver() {
    showDiscardChangeDialog = false;
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
      {#if !statusInPageHeader}
        <!-- The status belongs on the title row; a host that has no room for it
             there (the flow page's tab bar) keeps it above the rail. -->
        <div class="mx-auto flex w-full items-center gap-3 pt-3 {columnClass}">
          <BuilderSessionStatus />
          {#if canStartOver}
            <Button
              variant="outline"
              size="sm"
              class="ml-auto"
              onclick={handleStartOver}
              disabled={service.isCreating}
            >
              {m.ai_builder_start_fresh()}
            </Button>
          {/if}
        </div>
      {:else if canStartOver}
        <div class="mx-auto flex w-full justify-end pt-3 {columnClass}">
          <Button
            variant="outline"
            size="sm"
            onclick={handleStartOver}
            disabled={service.isCreating}
          >
            {m.ai_builder_start_fresh()}
          </Button>
        </div>
      {/if}
      <div
        class="mx-auto w-full py-3 {columnClass}"
        class:pt-3={statusInPageHeader && !canStartOver}
      >
        <BuilderPhaseRail
          current={phaseIndex}
          viewing={viewingPhase}
          isEdit={targetKind === "edit"}
          onselect={handleRailSelect}
        />
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
          onclose={() => service.closeConversation()}
        />
      {:else if screen === "findings"}
        <BuilderFindingsScreen
          review={service.review}
          disabled={!service.canSendMessage}
          onprepare={prepareChangeFromFinding}
          onclose={() => service.closeReview()}
          onretry={() => void service.openReview()}
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
          onopenreview={() => void launchReview()}
        />
      {:else if screen === "question" && questionMessage}
        <BuilderQuestionScreen
          {questionMessage}
          {questionNumber}
          answeredFields={pendingFieldAnswer}
          answered={answeredQuestions}
          isEdit={targetKind === "edit"}
          {editingQuestionId}
          {editingAnsweredOptionIds}
          {editingAnsweredCustomValue}
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
          {runtimeFields}
          {runtimeFieldsQuestionId}
          noQuestions={askedQuestionIds.length === 0}
          confirmed={service.isRequirementsSummaryConfirmed(latestSummary)}
          stale={summaryIsStale}
          readOnly={phaseIndex > 0}
          pending={summaryRevisionPending}
          isEdit={targetKind === "edit"}
          disabled={service.isCreating || service.isStreaming}
          editingQuestion={editingQuestionMessage}
          editingFields={editingQuestionMessage?.question?.question_id ===
          confirmedFieldAnswer?.questionId
            ? (confirmedFieldAnswer?.fields ?? null)
            : null}
          editingQuestionNumber={questionNumber}
          {editingAnsweredOptionIds}
          {editingAnsweredCustomValue}
          onanswer={handleQuestionAnswer}
          oncanceledit={() => (editingQuestionId = null)}
          onconfirm={handleRequirementsConfirm}
          onchange={handleRequirementsChange}
          oneditcontentfields={(fieldNames, addedFieldPlacements) => {
            if (!latestSummary) return;
            void service.editNamedContentFields(
              latestSummary.requirements_version,
              fieldNames,
              addedFieldPlacements
            );
          }}
          oneditanswer={handleEditAnswer}
          onreopenassumption={handleReopenAssumption}
        />
      {:else if screen === "build" && generationFailedWithoutPlan}
        <!-- A failed generation keeps its one existing failure/retry surface. -->
        <div class="bg-primary flex min-h-0 flex-1 flex-col">
          <BuilderReviewScreen
            showGenerationFailure={true}
            onapplied={(detail) => onapplied?.(detail)}
            onshowconversation={() => (service.conversationOpen = true)}
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
            onshowconversation={() => (service.conversationOpen = true)}
          />
        </div>
      {:else}
        <BuilderReplyScreen
          waiting={service.isStreaming ||
            service.latestTurnState === "open" ||
            service.latestTurnState === "processing"}
          assistantText={lastAssistantText}
          editContext={activeEditContext}
          editContextLabel={savedFlowStepScopeLabel}
          oncleareditcontext={() => service.clearActiveStepScope()}
        />
      {/if}
    </div>
  </div>
{/if}

<AlertDialog.Root bind:open={showDiscardChangeDialog}>
  <AlertDialog.Content>
    <AlertDialog.Header>
      <AlertDialog.Title>{m.ai_builder_discard_change_title()}</AlertDialog.Title>
      <AlertDialog.Description>{m.ai_builder_discard_change_body()}</AlertDialog.Description>
    </AlertDialog.Header>
    <AlertDialog.Footer>
      <AlertDialog.Cancel>{m.cancel()}</AlertDialog.Cancel>
      <AlertDialog.Action
        class="bg-negative-default text-on-fill hover:bg-negative-stronger"
        onclick={discardChangeAndStartOver}
      >
        {m.ai_builder_discard_change_action()}
      </AlertDialog.Action>
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>

<AlertDialog.Root bind:open={showReplaceEditSessionDialog}>
  <AlertDialog.Content>
    <AlertDialog.Header>
      <AlertDialog.Title>{m.ai_builder_replace_edit_title()}</AlertDialog.Title>
      <AlertDialog.Description>
        {pendingReviewReplacement
          ? m.ai_builder_replace_edit_description_review()
          : m.ai_builder_replace_edit_description({
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

<style lang="postcss">
  /* A screen change hands the caret to the new heading so a screen reader
     announces where it landed. The heading is not tabbable, so the only focus
     it can ever take is that programmatic one — and a ring around a heading
     nobody can reach reads as a text field. Chromium still treats some of
     these as focus-visible, so the rule is unconditional. */
  :global([data-builder-screen-heading]:focus) {
    outline: none;
  }
</style>
