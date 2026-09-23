<script lang="ts">
  import { BUILDER_COLUMN } from "./builderColumns";
  import { m } from "$lib/paraglide/messages";
  import { getLocale } from "$lib/paraglide/runtime";
  import { resolve } from "$app/paths";
  import { onMount, tick } from "svelte";
  import { prefersReducedMotion } from "$lib/core/prefersReducedMotion";
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
  import BuilderRepairScreen from "./BuilderRepairScreen.svelte";
  import type { FlowRunFailureRepairTarget } from "$lib/features/flows/flowRunFailureRepair";
  import FlowAIBuilderModelSelect from "./FlowAIBuilderModelSelect.svelte";
  import FlowAIBuilderReasoningSelect from "./FlowAIBuilderReasoningSelect.svelte";
  import { getAIBuilderService } from "./FlowAIBuilderService.svelte.ts";
  import { summaryTerm } from "./aiBuilderSummaryText";
  import { buildAnswerLabels } from "./aiBuilderAnswerLabel";
  import type { StructuredInputFieldAnswer } from "./structuredQuestionAnswer";
  import { reopenQuestionRequest } from "./structuredQuestionAnswer";
  import type {
    AIBuilderCarriedRequest,
    AIBuilderSavedFlowStepScope,
    AIBuilderStepChoice,
    ChatMessage,
    RequirementsSummary,
    AIBuilderReviewReference
  } from "./protocol";
  import { isDiscoveryStatus } from "./protocol";
  import {
    delegatedQuestionAnswer,
    type StructuredQuestionAnswerPayload
  } from "./structuredQuestionAnswer";

  interface Props {
    targetKind?: "create" | "edit";
    /** The host shows the saved state and Samtal on its own title row. */
    statusInPageHeader?: boolean;
    onapplied?: (detail: {
      flow_id: string;
      focusStepIndex: number | null;
    }) => void | Promise<void>;
    /** The flow being edited is published: applying is refused until it is unpublished. */
    flowIsPublished?: boolean;
    /** Whether the user may review the published version's runs; the page
     *  decides from the role permission and both entry points follow it. */
    canReview?: boolean;
    /** A draft chosen in the Flöden list; the page opens that session instead of a new one. */
    resumeSessionId?: string | null;
    /** Edit mode: the saved steps a first message may be scoped to. */
    stepChoices?: AIBuilderStepChoice[] | null;
    /** Create mode: a dropped flow package is handed to the importer. */
    onpackage?: (detail: { file: File; text: string }) => void;
  }

  let {
    targetKind = "edit",
    statusInPageHeader = false,
    onapplied,
    flowIsPublished = false,
    canReview = false,
    resumeSessionId = null,
    stepChoices = null,
    onpackage
  }: Props = $props();

  const service = getAIBuilderService();
  const {
    state: { currentSpace }
  } = getSpacesManager();

  let taskScreenRef = $state<BuilderTaskScreen | undefined>();
  let conversationRef = $state<BuilderConversationScreen | undefined>();
  let pendingSavedFlowStepScope = $state<AIBuilderSavedFlowStepScope | null>(null);
  let showReplaceEditSessionDialog = $state(false);
  // Every attempt to get a session on screen goes through `bootstrap`, and a
  // failed attempt is kept so Retry repeats exactly that attempt.
  type BootstrapAttempt = "resume" | "session";
  let failedAttempt = $state<BootstrapAttempt | null>(null);

  // ---- Session bootstrap ---------------------------------------------------

  onMount(() => {
    void bootstrap(targetKind === "create" && resumeSessionId ? "resume" : "session");
  });

  async function bootstrap(attempt: BootstrapAttempt) {
    failedAttempt = null;
    if (service.hasSession) return;
    try {
      if (attempt === "resume" && resumeSessionId) {
        await service.resumeSession(resumeSessionId);
      } else if (targetKind === "create") {
        // A new task always gets its own session; unfinished drafts live in
        // the Flöden list, so the builder never has to guess which to reopen.
        await service.createSession("create");
      } else {
        await service.initialize(targetKind);
      }
    } catch {
      // The driver has already put its typed error on the state.
    }
    if (!service.hasSession) failedAttempt = attempt;
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
      dropAnswerEdit();
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
      if (
        (service.review.status !== "closed" || service.failureRepair.status !== "closed") &&
        viewingPhase === 0
      )
        return "findings";
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

  // Screens that start turns without a composer of their own show the model
  // controls here, so the model a turn or a retry runs is always named on the
  // screen that starts it, and a blocked model's reason and way out are too.
  const showModelNotice = $derived(
    service.hasSession &&
      ((screen === "findings" && service.failureRepair.status !== "closed") ||
        (screen === "question" && Boolean(questionMessage)) ||
        (screen === "confirm" && Boolean(latestSummary)) ||
        screen === "build" ||
        screen === "review")
  );

  // One column per screen: the rail, the status row and the content sit in it,
  // so nothing floats beside the card it belongs to.
  const columnClass = $derived.by(() => {
    switch (screen) {
      case "review":
        // A failure or conflict without a plan is a message, not a sheet.
        return service.currentPlan ? BUILDER_COLUMN.review : BUILDER_COLUMN.standard;
      case "task":
        return BUILDER_COLUMN.task;
      case "findings":
        return BUILDER_COLUMN.standard;
      case "question":
      case "reply":
        return BUILDER_COLUMN.question;
      default:
        return BUILDER_COLUMN.standard;
    }
  });

  // ---- Screen change: announce it, then hand focus to the new heading -------
  // A screen swap is a navigation for anyone not watching the viewport, so it
  // is spoken once and the caret lands on the heading of what just appeared.
  // Changing an earlier answer is the one move that is not a navigation: the
  // question opens in place, so focus goes to it, and when it closes focus
  // returns to the chip or row it was opened from, with the page left where
  // the reader was.

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
        return targetKind === "edit"
          ? m.ai_builder_requirements_title_edit()
          : m.ai_builder_requirements_title();
      case "findings":
        return m.ai_builder_review_title();
      case "build":
        return targetKind === "edit"
          ? m.ai_builder_rail_planning_edit()
          : m.ai_builder_rail_planning();
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
  let screenScrollEl = $state<HTMLElement | null>(null);
  const reducedMotion = prefersReducedMotion();
  let announcedScreenKey: string | null = null;
  let settledEditingQuestionId: string | null = null;
  $effect(() => {
    const key = screenKey;
    const text = screenAnnouncement;
    const editing = editingQuestionId;
    // Bootstrap and resume settle on a screen without the user doing anything.
    if (!service.hasSession || service.isInitializing) {
      announcedScreenKey = null;
      settledEditingQuestionId = null;
      return;
    }
    if (announcedScreenKey === null) {
      announcedScreenKey = key;
      settledEditingQuestionId = editing;
      return;
    }
    const screenChanged = key !== announcedScreenKey;
    const openedEditing = editing !== null && editing !== settledEditingQuestionId;
    const closedEditing = editing === null ? settledEditingQuestionId : null;
    announcedScreenKey = key;
    settledEditingQuestionId = editing;
    if (!screenChanged && !openedEditing && closedEditing === null) return;
    if (screenChanged && text) screenAnnouncementText = text;
    void settleFocus({ screenChanged, openedEditing, closedEditing });
  });

  /** Leave an answer edit without a hand-back: the rail or a phase change
   *  already moves the reader somewhere new. */
  function dropAnswerEdit() {
    editingQuestionId = null;
    settledEditingQuestionId = null;
  }

  async function settleFocus(change: {
    screenChanged: boolean;
    openedEditing: boolean;
    closedEditing: string | null;
  }) {
    await tick();
    const active = document.activeElement;
    // Never yank the caret out of a composer mid-sentence.
    if (
      active instanceof HTMLElement &&
      (active.tagName === "TEXTAREA" || active.tagName === "INPUT" || active.isContentEditable)
    ) {
      return;
    }
    const root = builderRootEl;
    if (!root) return;
    if (change.closedEditing !== null) {
      // The control that opened the editor, when it is still on screen; a
      // question can have more than one (an answer chip and the runtime-fields
      // button), so the first match is only the fallback.
      const opened = editOrigin;
      editOrigin = null;
      const origin =
        opened?.isConnected && opened.dataset.editQuestion === change.closedEditing
          ? opened
          : [...root.querySelectorAll<HTMLElement>("[data-edit-question]")].find(
              (candidate) => candidate.dataset.editQuestion === change.closedEditing
            );
      if (origin) {
        // The row keeps its place on screen whether or not it can take focus
        // yet: a sent answer disables it while the turn runs.
        origin.scrollIntoView({ block: "nearest" });
        if (!origin.matches(":disabled")) {
          origin.focus({ preventScroll: true });
          return;
        }
        root
          .querySelector<HTMLElement>("[data-builder-screen-heading]")
          ?.focus({ preventScroll: true });
        return;
      }
    }
    // Focus alone, never a scroll: a browser may scroll the nearest scrollable
    // ancestor to reveal the heading, which drags a horizontally scrollable row
    // (the answer chips on a phone) out of place.
    const editor = change.openedEditing
      ? root.querySelector<HTMLElement>("[data-builder-answer-editor]")
      : null;
    (editor ?? root)
      .querySelector<HTMLElement>("[data-builder-screen-heading]")
      ?.focus({ preventScroll: true });
    // A new screen starts at its top: the previous screen may have been
    // scrolled to its foot, and the reader would otherwise land mid-card. The
    // screen column owns the vertical scroll, so reset it there; a horizontally
    // scrollable row inside it is never moved.
    if (change.screenChanged && screenScrollEl) screenScrollEl.scrollTop = 0;
    // The reopened question sits above the card, which on a long card is off
    // screen: from where the user clicked, nothing would appear to happen.
    editor?.scrollIntoView({ block: "nearest", behavior: reducedMotion ? "auto" : "smooth" });
  }

  // ---- Error ownership ------------------------------------------------------
  // Once generation is visible, the plan surface keeps ownership of any
  // failure so the same error cannot flash on two surfaces.
  let hadGenerationStatus = $state(false);
  $effect(() => {
    if (!service.hasSession) {
      hadGenerationStatus = false;
    } else if (
      (service.statusMessage !== null && !isDiscoveryStatus(service.statusMessage)) ||
      service.hasSeenPlanInSession ||
      (service.phase === "building" && service.isStreaming)
    ) {
      hadGenerationStatus = true;
    }
  });
  // A generation failure the server persisted with the turn, shown again
  // after a resume: no stream ran here, but the plan surface still owns it.
  const restoredGenerationFailure = $derived(
    service.phase === "building" &&
      !service.isStreaming &&
      service.currentPlan === null &&
      service.latestTurn?.state === "committed" &&
      service.latestTurn.error != null &&
      service.error !== null &&
      service.error.request_id === service.latestTurn.error.request_id
  );
  const planSurfaceOwnsError = $derived(
    (hadGenerationStatus || restoredGenerationFailure) &&
      service.error !== null &&
      service.currentPlan === null
  );
  const generationFailedWithoutPlan = $derived(
    planSurfaceOwnsError && (service.streamState === "failed" || restoredGenerationFailure)
  );
  // The plan surface claims the failure from the moment it arrives inside
  // the stream until the settled failure surface is up, so the turn alert
  // never shows the same error first.
  const planSurfaceClaimsError = $derived(
    planSurfaceOwnsError &&
      (service.isStreaming || service.streamState === "failed" || restoredGenerationFailure)
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

  // The bootstrap failure panel displays the error before a session exists;
  // it is observed here since no listed surface owns it.
  $effect(() => {
    const error = service.error;
    if (failedAttempt !== null && !service.hasSession && error) {
      service.reportFailureDisplayed({ surface: null, presentedAs: null }, error);
    }
  });

  // Rewording the task after a failed generation: the transcript, with every
  // answer still in place, and the caret already in the composer.
  async function handleClarifyTask() {
    service.conversationOpen = true;
    await tick();
    await conversationRef?.focusComposer();
  }

  // Same transcript, different destination: a card that asked for a DOCX puts
  // the user on the attach control instead of the composer.
  async function handleAttachTemplate() {
    service.conversationOpen = true;
    await tick();
    await conversationRef?.focusAttachControl();
  }

  // The control that opened the editor. Passed by the screen, since a pointer
  // click does not focus a button in every browser; the focused element is
  // the fallback for callers that cannot pass it (the conversation).
  let editOrigin: HTMLElement | null = null;
  function handleEditAnswer(questionId: string, origin?: HTMLElement | null) {
    const active = document.activeElement;
    editOrigin =
      origin ??
      (active instanceof HTMLElement && active.dataset.editQuestion === questionId ? active : null);
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
    dropAnswerEdit();
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
  let pendingTaskFocus = $state<{ placeholder?: string; prefill?: string } | null>(null);
  $effect(() => {
    if (pendingTaskFocus && taskScreenRef) {
      taskScreenRef.focusInput(pendingTaskFocus);
      pendingTaskFocus = null;
    }
  });

  // A request carried in from a package names changes to particular steps;
  // read as a whole-flow edit it would rewrite prompts the model never saw.
  // It waits in the composer until a step is chosen, and the requirement
  // lifts with the first delivered turn.
  let carriedRequest = $state<AIBuilderCarriedRequest | null>(null);
  const requireStepScope = $derived(
    carriedRequest?.requireStepScope === true && service.messages.length === 0
  );

  /** Bring a request from outside the conversation into the composer. */
  export function carryRequest(request: AIBuilderCarriedRequest) {
    carriedRequest = request;
    pendingTaskFocus = { prefill: request.text };
  }

  /** The saved steps a first message may be scoped to: none once a proposal
   *  exists, because a saved-step scope only opens the first one. */
  const firstTurnStepChoices = $derived(
    targetKind === "edit" && service.currentPlan === null && service.session?.latest_plan_id == null
      ? stepChoices
      : null
  );

  function selectStepChoice(choice: AIBuilderStepChoice) {
    service.setSavedFlowStepScope({
      editContext: { kind: "saved_flow_step", flow_step_id: choice.id },
      stepName: choice.name,
      stepNumber: choice.order
    });
  }

  async function activateSavedFlowStep(scope: AIBuilderSavedFlowStepScope) {
    service.setSavedFlowStepScope(scope);
    peekPhase = null;
    await tick();
    // The task screen words its own placeholder from the scope.
    const focus = scope.request ? { prefill: scope.request } : {};
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

  /** The last change is already in the flow and its session takes no more
   *  turns: a new launch starts a fresh session without asking. */
  async function freshSessionAfterApply(): Promise<boolean> {
    if (!service.isApplied) return true;
    try {
      return await service.startFreshSession("edit");
    } catch {
      return false;
    }
  }

  async function launchSavedFlowStep(scope: AIBuilderSavedFlowStepScope) {
    // The session fact (latest_plan_id) says the edit is ongoing; the decision
    // reads it rather than the hydrated plan.
    if (service.hasOpenWork) {
      pendingSavedFlowStepScope = scope;
      showReplaceEditSessionDialog = true;
      return;
    }
    if (!(await freshSessionAfterApply())) return;
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
    if (service.hasOpenWork) {
      pendingReviewReplacement = true;
      showReplaceEditSessionDialog = true;
      return;
    }
    if (!(await freshSessionAfterApply())) return;
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
    reviewContext: AIBuilderReviewReference;
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

  // Handing a failed step over is the review's transition with a target: it
  // waits for the session, asks before replacing an ongoing edit, drops any
  // saved-step scope, and lands on the first phase where the launch renders.
  let pendingFailureRepairLaunch = $state<FlowRunFailureRepairTarget | null>(null);
  let pendingFailureRepairTarget = $state<FlowRunFailureRepairTarget | null>(null);
  $effect(() => {
    const target = pendingFailureRepairLaunch;
    if (target && service.hasSession && !service.isInitializing) {
      pendingFailureRepairLaunch = null;
      void launchFailureRepairNow(target);
    }
  });

  async function launchFailureRepairNow(target: FlowRunFailureRepairTarget) {
    if (service.hasOpenWork) {
      pendingFailureRepairTarget = target;
      showReplaceEditSessionDialog = true;
      return;
    }
    if (!(await freshSessionAfterApply())) return;
    await activateFailureRepair(target);
  }

  async function activateFailureRepair(target: FlowRunFailureRepairTarget) {
    service.clearActiveStepScope();
    peekPhase = null;
    await service.openFailureRepair(target);
  }

  /** Hand a failed step of a run to the Builder from outside it. */
  export async function launchFailureRepair(target: FlowRunFailureRepairTarget) {
    if (!service.hasSession || service.isInitializing) {
      pendingFailureRepairLaunch = target;
      return;
    }
    await launchFailureRepairNow(target);
  }

  function cancelSavedFlowStepReplacement() {
    showReplaceEditSessionDialog = false;
    pendingSavedFlowStepScope = null;
    pendingReviewReplacement = false;
    pendingFailureRepairTarget = null;
  }

  async function confirmSavedFlowStepReplacement() {
    const scope = pendingSavedFlowStepScope;
    const review = pendingReviewReplacement;
    const repair = pendingFailureRepairTarget;
    if (scope === null && !review && repair === null) return;
    // Close the question before the replacement runs: the fresh session
    // takes a moment, and a dialog left open across it re-reads its state
    // and asks again, about a step that was never named.
    showReplaceEditSessionDialog = false;
    pendingSavedFlowStepScope = null;
    pendingReviewReplacement = false;
    pendingFailureRepairTarget = null;
    // The driver skips the replacement while work is in flight (the old
    // session stays, and the next launch asks again) and rejects when the
    // create fails (the session it had is kept, carrying the driver's own
    // error, so the launch can simply be asked for again). Neither outcome
    // may open the step or review. The composer context of the replaced
    // session is owned by that session and simply stops applying.
    let replaced = false;
    try {
      replaced = await service.startFreshSession("edit");
    } catch {
      return;
    }
    if (!replaced) return;
    if (scope !== null) {
      await activateSavedFlowStep(scope);
    } else if (repair !== null) {
      await activateFailureRepair(repair);
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

  // A refused create is the driver's own error to show, not an unhandled
  // rejection; the scoped composer context stays with the session it belongs to.
  async function discardChangeAndStartOver() {
    showDiscardChangeDialog = false;
    try {
      await service.startFreshSession("edit");
    } catch {
      return;
    }
  }
</script>

{#if service.isInitializing || (!service.hasSession && failedAttempt === null)}
  <div class="flex flex-1 flex-col gap-8 p-6" aria-hidden="true">
    <Skeleton class="h-10 w-full rounded-lg" />
    <div class="flex flex-col gap-3">
      <Skeleton class="h-4 w-4/5 rounded" />
      <Skeleton class="h-4 w-3/5 rounded" />
      <Skeleton class="h-4 w-2/5 rounded" />
    </div>
  </div>
{:else if failedAttempt !== null && !service.hasSession}
  <div class="flex flex-1 items-center justify-center p-6">
    <div class="max-w-[40ch] text-center" role="alert">
      <h2 class="text-primary font-semibold">
        {failedAttempt === "resume"
          ? m.ai_builder_resume_failed_title()
          : m.ai_builder_bootstrap_failed_title()}
      </h2>
      <p class="text-secondary mt-1 text-sm">{service.error?.message ?? ""}</p>
      <div class="mt-4 flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:justify-center">
        <Button variant="outline" class="w-full sm:w-auto" href={flowsHref}>
          {m.ai_builder_resume_failed_back()}
        </Button>
        {#if failedAttempt === "resume" || targetKind === "edit"}
          <!-- Resuming a draft and an edit session (resume-first on the server)
               are safe to repeat. A create-mode session is an unconditional
               insert: after an ambiguous outcome a retry could persist a second
               draft, so that case sends the user to the Flows list, where any
               draft the server did create is recoverable. -->
          <Button
            variant={failedAttempt === "resume" ? "outline" : "default"}
            class="w-full sm:w-auto"
            onclick={() => bootstrap(failedAttempt ?? "session")}
          >
            {m.ai_builder_turn_retry()}
          </Button>
        {/if}
        {#if failedAttempt === "resume"}
          <Button class="w-full sm:w-auto" onclick={() => bootstrap("session")}>
            {m.ai_builder_resume_failed_new()}
          </Button>
        {/if}
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
    <!-- Phase header: one row, the rail where the reader is and the saved
         state with the conversation at its far end. The row is as wide as the
         screen's column and centred with it, so the rail starts on the same
         line as the plan the user reads most; a narrow column wraps it. -->
    <div class="bg-primary border-default sticky top-0 z-20 shrink-0 border-b px-7 max-sm:px-3">
      <div class="mx-auto flex w-full flex-wrap items-center gap-x-6 gap-y-2 py-3 {columnClass}">
        <div class="min-w-[18rem] flex-1">
          <BuilderPhaseRail
            current={phaseIndex}
            viewing={viewingPhase}
            isEdit={targetKind === "edit"}
            onselect={handleRailSelect}
          />
        </div>
        {#if !statusInPageHeader || canStartOver}
          <!-- The status belongs on the title row; a host that has no room for
               it there (the flow page's tab bar) keeps it here. -->
          <div class="ml-auto flex items-center gap-3">
            {#if !statusInPageHeader}
              <BuilderSessionStatus isEdit={targetKind === "edit"} />
            {/if}
            {#if canStartOver}
              <Button
                variant="outline"
                size="sm"
                onclick={handleStartOver}
                disabled={service.isCreating}
              >
                {m.ai_builder_start_fresh()}
              </Button>
            {/if}
          </div>
        {/if}
      </div>
    </div>

    <div class="flex min-h-0 flex-1 flex-col overflow-y-auto" bind:this={screenScrollEl}>
      <BuilderTurnAlert {targetKind} {columnClass} suppressStreamError={planSurfaceClaimsError} />
      {#if showModelNotice}
        <div class="px-7 pt-3 max-sm:px-3" data-testid="ai-builder-model-notice">
          <!-- The trigger's own inset is pulled back so its icon starts on the
               card's left edge. -->
          <div class="mx-auto flex w-full flex-wrap items-center gap-2 {columnClass}">
            <div class="-ml-2.5 flex min-w-0 flex-wrap items-center gap-2">
              <FlowAIBuilderModelSelect />
            </div>
          </div>
        </div>
      {/if}

      {#if screen === "conversation"}
        <BuilderConversationScreen
          bind:this={conversationRef}
          oneditanswer={handleEditAnswer}
          onclose={() => service.closeConversation()}
        />
      {:else if screen === "findings" && service.failureRepair.status !== "closed"}
        <BuilderRepairScreen
          repair={service.failureRepair}
          disabled={!service.canSendMessage || service.modelSendBlock !== null}
          onprepare={prepareChangeFromFinding}
          onclose={() => service.closeFailureRepair()}
          onretry={(target) => void service.openFailureRepair(target)}
        />
      {:else if screen === "findings"}
        <BuilderFindingsScreen
          review={service.review}
          suggestions={service.suggestions}
          disabled={!service.canSendMessage || service.modelSendBlock !== null}
          onprepare={prepareChangeFromFinding}
          onsuggest={() => void service.requestSuggestions()}
          onclose={() => service.closeReview()}
          onretry={() => void service.openReview()}
        >
          {#snippet plannerControls()}
            <FlowAIBuilderModelSelect />
            <FlowAIBuilderReasoningSelect />
            <!-- This listing is held to the runs' classification, so a model the
                 space offers elsewhere can be missing here. -->
            <p class="text-secondary basis-full text-[0.8125rem] text-pretty">
              {m.ai_builder_review_model_eligibility_hint()}
            </p>
          {/snippet}
        </BuilderFindingsScreen>
      {:else if screen === "task"}
        <BuilderTaskScreen
          bind:this={taskScreenRef}
          {targetKind}
          {otherDraftCount}
          {flowsHref}
          editContext={activeEditContext}
          editContextLabel={savedFlowStepScopeLabel}
          editContextLocked={service.activeStepScopeLocked}
          oncleareditcontext={() => service.clearActiveStepScope()}
          onopenreview={canReview ? () => void launchReview() : undefined}
          stepChoices={firstTurnStepChoices}
          onselectstep={selectStepChoice}
          {requireStepScope}
          onpackage={targetKind === "create" ? onpackage : undefined}
          stepIntent={service.savedFlowStepScope?.intent ?? null}
          stepNow={service.savedFlowStepScope?.current ?? null}
          stepNumber={service.activeStepScope?.stepNumber ?? null}
          flowSteps={stepChoices}
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
          sendBlockedReason={service.modelSendBlockMessage}
          onanswer={handleQuestionAnswer}
          ondelegate={handleDelegateQuestion}
          onedit={handleEditAnswer}
          oncanceledit={() => (editingQuestionId = null)}
        />
      {:else if screen === "confirm" && latestSummary}
        <BuilderConfirmScreen
          summary={latestSummary}
          userRequest={service.latestUserRequestBefore(latestSummaryMessageIndex)}
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
          sendBlockedReason={service.modelSendBlockMessage}
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
            {flowIsPublished}
            onshowconversation={() => (service.conversationOpen = true)}
            onclarify={handleClarifyTask}
            onattachtemplate={handleAttachTemplate}
          />
        </div>
      {:else if screen === "build"}
        <BuilderBuildScreen
          status={service.statusMessage}
          mode={targetKind}
          flowSteps={targetKind === "edit" ? stepChoices : null}
          targetStepNumber={service.activeStepScope?.stepNumber ?? null}
          stepCount={service.currentPlan?.proposal.spec.steps.length ?? 5}
          confirmedLine={buildConfirmedLine(latestSummary)}
          onshowconfirmation={() => (peekPhase = 0)}
        />
      {:else if screen === "review"}
        <div class="bg-primary flex min-h-0 flex-1 flex-col">
          <BuilderReviewScreen
            showGenerationFailure={generationFailedWithoutPlan}
            onapplied={(detail) => onapplied?.(detail)}
            {flowIsPublished}
            onshowconversation={() => (service.conversationOpen = true)}
            onclarify={handleClarifyTask}
            onattachtemplate={handleAttachTemplate}
          />
        </div>
      {:else}
        <BuilderReplyScreen
          waiting={service.isStreaming ||
            service.latestTurnState === "open" ||
            service.latestTurnState === "processing"}
          status={service.statusMessage}
          assistantText={lastAssistantText}
          editContext={activeEditContext}
          editContextLabel={savedFlowStepScopeLabel}
          editContextLocked={service.activeStepScopeLocked}
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
    <AlertDialog.Footer class="border-border">
      <AlertDialog.Cancel>{m.cancel()}</AlertDialog.Cancel>
      <AlertDialog.Action variant="destructive" onclick={discardChangeAndStartOver}>
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
          : pendingFailureRepairTarget !== null
            ? m.ai_builder_replace_edit_description_repair({
                step: String(pendingFailureRepairTarget.stepOrder)
              })
            : m.ai_builder_replace_edit_description({
                stepName: pendingSavedFlowStepScope?.stepName ?? m.flow_step_unnamed()
              })}
      </AlertDialog.Description>
    </AlertDialog.Header>
    <AlertDialog.Footer class="border-border">
      <AlertDialog.Cancel onclick={cancelSavedFlowStepReplacement}>
        {m.ai_builder_replace_edit_cancel()}
      </AlertDialog.Cancel>
      <AlertDialog.Action
        variant="destructive"
        disabled={service.isStreaming || service.isBusy}
        onclick={confirmSavedFlowStepReplacement}
      >
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
