import { m } from "$lib/paraglide/messages";
import { getLocale } from "$lib/paraglide/runtime";
import type { EneoFetchFunction, EneoStreamFunction } from "@eneo/eneo-js";
import type {
  PersistedStructuredQuestionAnswerMetadata,
  StructuredQuestion,
  StructuredQuestionAnswerMetadata
} from "./structuredQuestionAnswer";
import {
  buildUnpublishedApplyFailureError,
  isSoftBlockAIBuilderError,
  isStaleApplyError,
  parseAIBuilderError
} from "./aiBuilderError";
import { parseAIBuilderStreamEvent } from "./protocol";
import type {
  AIBuilderConversationMessage,
  AIBuilderDraftSession,
  AIBuilderError,
  AIBuilderModel,
  AIBuilderPhase,
  AIBuilderPlanEditContext,
  AIBuilderSendMessageRequest,
  AIBuilderSession,
  AIBuilderStatus,
  AIBuilderStreamEvent,
  AIBuilderTurnState,
  AIBuilderTurnRecoveryState,
  AIBuilderUsageEventData,
  ApplyError,
  ApplyResult,
  ChatMessage,
  IncomingProposedPlan,
  PlanRevisionType,
  ProposedPlan,
  RequirementsSummary,
  RecoverableAIBuilderDraftSession,
  SessionStatus,
  TargetKind
} from "./protocol";

export interface AIBuilderClientTransport {
  fetch: EneoFetchFunction;
  stream: EneoStreamFunction;
}

const FLOW_AI_BUILDER_ROUTES = {
  sessions: "/api/v1/flows/ai-builder/sessions",
  session: "/api/v1/flows/ai-builder/sessions/{session_id}",
  sessionAttachments: "/api/v1/flows/ai-builder/sessions/{session_id}/attachments/{file_id}",
  sessionCancel: "/api/v1/flows/ai-builder/sessions/{session_id}/cancel",
  sessionMessages: "/api/v1/flows/ai-builder/sessions/{session_id}/messages",
  sessionModels: "/api/v1/flows/ai-builder/sessions/{session_id}/models",
  plan: "/api/v1/flows/ai-builder/plans/{plan_id}",
  planApply: "/api/v1/flows/ai-builder/plans/{plan_id}/apply",
  planApprove: "/api/v1/flows/ai-builder/plans/{plan_id}/approve",
  planRevise: "/api/v1/flows/ai-builder/plans/{plan_id}/revise",
  flowUnpublish: "/api/v1/flows/{id}/unpublish/"
} as const;

export interface FlowAIBuilderState {
  session: AIBuilderSession | null;
  messages: ChatMessage[];
  currentPlan: ProposedPlan | null;
  isStreaming: boolean;
  isInitializing: boolean;
  error: AIBuilderError | null;
  applyError: ApplyError | null;
  applyResult: ApplyResult | null;
  isConflict: boolean;
  statusMessage: AIBuilderStatus | null;
  availableModels: AIBuilderModel[];
  selectedModelId: string | null;
  modelsLoaded: boolean;
  draftSessions: AIBuilderDraftSession[];
}

export function createInitialFlowAIBuilderState(): FlowAIBuilderState {
  return {
    session: null,
    messages: [],
    currentPlan: null,
    isStreaming: false,
    isInitializing: false,
    error: null,
    applyError: null,
    applyResult: null,
    isConflict: false,
    statusMessage: null,
    availableModels: [],
    selectedModelId: null,
    modelsLoaded: false,
    draftSessions: []
  };
}

type FlowAIBuilderListener = (state: Readonly<FlowAIBuilderState>) => void;

interface SessionOperationOwner {
  sessionId: string;
  sessionGeneration: number;
  abortController: AbortController | null;
}

function extractQuestionAnswer(
  metadata: ChatMessage["metadata"] | undefined
): PersistedStructuredQuestionAnswerMetadata | null {
  if (!metadata || typeof metadata !== "object" || !("question_answer" in metadata)) {
    return null;
  }
  const questionAnswer = metadata.question_answer;
  if (!questionAnswer || typeof questionAnswer !== "object") {
    return null;
  }
  return questionAnswer as PersistedStructuredQuestionAnswerMetadata;
}

function toPersistedQuestionAnswerMetadata(
  questionAnswer:
    StructuredQuestionAnswerMetadata | NonNullable<AIBuilderConversationMessage["question_answer"]>
): PersistedStructuredQuestionAnswerMetadata | null {
  if (questionAnswer.kind !== "structured_question_answer") {
    return null;
  }
  const metadata: PersistedStructuredQuestionAnswerMetadata = {};
  if (questionAnswer.question_id !== undefined) {
    metadata.question_id = questionAnswer.question_id;
  }
  if (questionAnswer.selected_option_ids != null) {
    metadata.selected_option_ids = questionAnswer.selected_option_ids;
  }
  if (questionAnswer.selected_values != null) {
    metadata.selected_values = questionAnswer.selected_values;
  }
  if (questionAnswer.custom_value != null) {
    metadata.custom_value = questionAnswer.custom_value;
  }
  return metadata;
}

function assertNever(value: never): never {
  throw new Error(`Unhandled AI Builder stream event: ${JSON.stringify(value)}`);
}

function supersededSessionOperation(): DOMException {
  return new DOMException(
    "The AI Builder session changed before the operation completed.",
    "AbortError"
  );
}

function isRecoverableDraftStatus(
  status: SessionStatus
): status is RecoverableAIBuilderDraftSession["status"] {
  switch (status) {
    case "chatting":
    case "awaiting_approval":
      return true;
    case "applied":
    case "cancelled":
      return false;
  }
  const unhandledStatus: never = status;
  throw new Error(`Unhandled AI Builder session status: ${unhandledStatus}`);
}

function isRecoverableCreateDraft(
  session: AIBuilderDraftSession,
  spaceId: string
): session is RecoverableAIBuilderDraftSession {
  return (
    session.space_id === spaceId &&
    session.target_kind === "create" &&
    session.flow_id === null &&
    isRecoverableDraftStatus(session.status)
  );
}

export class FlowAIBuilderDriver {
  readonly #transport: AIBuilderClientTransport;
  readonly #spaceId: string;
  #flowId: string | null;
  readonly #onChange?: FlowAIBuilderListener;

  #abortController: AbortController | null = null;
  #state: FlowAIBuilderState = createInitialFlowAIBuilderState();
  #initGeneration = 0;
  #sessionGeneration = 0;
  #pendingResumeOwner: Pick<SessionOperationOwner, "sessionId" | "sessionGeneration"> | null = null;
  #requiresAuthoritativeRefresh = false;
  #authoritativeRefreshError = false;
  #isRecoveringLatestTurn = false;

  constructor(
    transport: AIBuilderClientTransport,
    spaceId: string,
    flowId: string | null,
    onChange?: FlowAIBuilderListener
  ) {
    this.#transport = transport;
    this.#spaceId = spaceId;
    this.#flowId = flowId;
    this.#onChange = onChange;
  }

  get state(): Readonly<FlowAIBuilderState> {
    return this.#state;
  }

  get turnRecoveryState(): AIBuilderTurnRecoveryState | null {
    const state = this.latestTurnState;
    return state === "failed_before_provider" || state === "provider_outcome_unknown"
      ? state
      : null;
  }

  get latestTurnState(): AIBuilderTurnState | null {
    return this.#state.session?.latest_turn?.state ?? null;
  }

  get canStartNewTurn(): boolean {
    const state = this.latestTurnState;
    return (
      !this.#requiresAuthoritativeRefresh &&
      !this.#isRecoveringLatestTurn &&
      (state === null || state === "committed")
    );
  }

  get authoritativeRefreshFailed(): boolean {
    return this.#authoritativeRefreshError;
  }

  get isRecoveringLatestTurn(): boolean {
    return this.#isRecoveringLatestTurn;
  }

  seedState(partial: Partial<FlowAIBuilderState>): void {
    Object.assign(this.#state, partial);
    this.#notify();
  }

  clearError(): void {
    this.#state.error = null;
    this.#notify();
  }

  async initialize(targetKind: TargetKind): Promise<void> {
    const gen = ++this.#initGeneration;
    this.#state.isInitializing = true;
    this.#notify();

    try {
      await this.loadDraftSessions();
      if (gen !== this.#initGeneration) return;

      if (targetKind === "edit") {
        await this.createSession("edit");
        return;
      }

      if (this.#hasRecoverableCreateDraft()) {
        return;
      }

      if (gen !== this.#initGeneration) return;
      await this.createSession("create");
    } finally {
      if (gen === this.#initGeneration) {
        this.#state.isInitializing = false;
        this.#notify();
      }
    }
  }

  dismissConflict(): void {
    this.#state.isConflict = false;
    this.#state.applyError = null;
    this.#notify();
  }

  dismissPlanPane(): void {
    this.#state.currentPlan = null;
    this.#state.isConflict = false;
    this.#state.applyError = null;
    this.#state.error = null;
    this.#state.statusMessage = null;
    this.#state.applyResult = null;
    this.#notify();
  }

  selectModel(modelId: string): void {
    this.#state.selectedModelId = modelId;
    this.#notify();
  }

  async createSession(targetKind: TargetKind, options?: { forceNew?: boolean }): Promise<void> {
    ++this.#initGeneration;
    this.abort();
    this.#resetFlowState();
    const sessionGeneration = this.#sessionGeneration;
    this.#state.error = null;
    this.#notify();

    try {
      const result = (await this.#transport.fetch(FLOW_AI_BUILDER_ROUTES.sessions, {
        method: "post",
        requestBody: {
          "application/json": {
            target_kind: targetKind,
            space_id: this.#spaceId,
            flow_id: this.#flowId,
            force_new: options?.forceNew ?? false
          }
        }
      })) as AIBuilderSession;
      if (sessionGeneration !== this.#sessionGeneration) return;
      this.#state.session = result;
      this.#applyCommittedTurnOutcome(result);
      this.#hydrateMessagesFromConversation(result.conversation ?? []);
      this.#notify();
      const owner: SessionOperationOwner = {
        sessionId: result.session_id,
        sessionGeneration,
        abortController: this.#abortController
      };
      await this.#fetchModels(owner);
      await this.#refreshSession(owner);
      if (this.#ownsSession(owner)) {
        await this.loadDraftSessions();
      }
    } catch (e) {
      if (sessionGeneration !== this.#sessionGeneration) return;
      this.#state.error = parseAIBuilderError({
        transport: "apply",
        payload: e,
        fallbackMessage: "Failed to create session"
      });
      await this.loadDraftSessions();
      this.#notify();
      throw e;
    }
  }

  async startFreshSession(targetKind: TargetKind): Promise<void> {
    await this.createSession(targetKind, { forceNew: true });
  }

  async loadDraftSessions(expectedGeneration = this.#sessionGeneration): Promise<void> {
    try {
      const result = (await this.#transport.fetch(FLOW_AI_BUILDER_ROUTES.sessions, {
        method: "get"
      })) as { sessions: AIBuilderDraftSession[] };
      if (expectedGeneration !== this.#sessionGeneration) return;
      this.#state.draftSessions = result.sessions;
      this.#notify();
    } catch {
      // Non-critical — recovery affordances just won't render
    }
  }

  hasRecoverableCreateDraft(): boolean {
    return this.getRecoverableCreateDrafts().length > 0;
  }

  getRecoverableCreateDrafts(): RecoverableAIBuilderDraftSession[] {
    return this.#state.draftSessions.filter((session) =>
      isRecoverableCreateDraft(session, this.#spaceId)
    );
  }

  async resumeSession(sessionId: string): Promise<void> {
    ++this.#initGeneration;
    this.abort();
    this.#resetFlowState();
    const sessionGeneration = this.#sessionGeneration;
    const pendingResumeOwner = { sessionId, sessionGeneration };
    this.#pendingResumeOwner = pendingResumeOwner;
    this.#state.error = null;
    this.#notify();

    let result: AIBuilderSession;
    try {
      result = (await this.#transport.fetch(FLOW_AI_BUILDER_ROUTES.session, {
        method: "get",
        params: { path: { session_id: sessionId } }
      })) as AIBuilderSession;
    } catch (error) {
      if (sessionGeneration !== this.#sessionGeneration) return;
      throw error;
    } finally {
      if (this.#pendingResumeOwner === pendingResumeOwner) {
        this.#pendingResumeOwner = null;
      }
    }
    if (sessionGeneration !== this.#sessionGeneration) return;
    this.#state.session = result;
    this.#applyCommittedTurnOutcome(result);
    this.#hydrateMessagesFromConversation(result.conversation ?? []);
    this.#notify();
    const owner: SessionOperationOwner = {
      sessionId: result.session_id,
      sessionGeneration,
      abortController: this.#abortController
    };
    await this.#fetchModels(owner);
    await this.#syncPlanFromSession(owner);
    await this.loadDraftSessions();
  }

  async discardSession(sessionId: string): Promise<void> {
    await this.#transport.fetch(FLOW_AI_BUILDER_ROUTES.sessionCancel, {
      method: "post",
      params: { path: { session_id: sessionId } }
    });

    const remainingDrafts = this.#state.draftSessions.filter(
      (session) => session.session_id !== sessionId
    );
    const cancelsPendingResume =
      this.#pendingResumeOwner?.sessionId === sessionId &&
      this.#pendingResumeOwner.sessionGeneration === this.#sessionGeneration;
    if (this.#state.session?.session_id === sessionId || cancelsPendingResume) {
      this.abort();
      this.#resetFlowState();
    }
    this.#state.draftSessions = remainingDrafts;
    this.#notify();
    await this.loadDraftSessions();
  }

  async refreshSession(): Promise<boolean> {
    if (!this.#state.session) return false;
    return this.#refreshSession({
      sessionId: this.#state.session.session_id,
      sessionGeneration: this.#sessionGeneration,
      abortController: this.#abortController
    });
  }

  async #refreshSession(owner: SessionOperationOwner): Promise<boolean> {
    if (!this.#ownsSession(owner)) return false;
    const latestTurnState = this.latestTurnState;
    const refreshIsRequired =
      this.#requiresAuthoritativeRefresh ||
      (latestTurnState !== null && latestTurnState !== "committed");

    try {
      const result = (await this.#transport.fetch(FLOW_AI_BUILDER_ROUTES.session, {
        method: "get",
        params: { path: { session_id: owner.sessionId } }
      })) as AIBuilderSession;
      if (!this.#ownsSession(owner)) return false;
      this.#requiresAuthoritativeRefresh = false;
      if (this.#authoritativeRefreshError) {
        this.#state.error = null;
        this.#authoritativeRefreshError = false;
      }
      this.#state.session = result;
      this.#applyCommittedTurnOutcome(result);
      this.#hydrateMessagesFromConversation(result.conversation ?? []);
      this.#notify();
      return this.#syncPlanFromSession(owner);
    } catch (error) {
      if (!this.#ownsSession(owner)) return false;
      this.#requiresAuthoritativeRefresh = refreshIsRequired;
      if (refreshIsRequired && this.#state.error === null) {
        this.#authoritativeRefreshError = true;
        this.#state.error = parseAIBuilderError({
          transport: "apply",
          payload: error,
          fallbackMessage: "Failed to refresh the AI Builder session."
        });
        this.#notify();
      }
      return false;
    }
  }

  async sendMessage(
    message: string,
    questionAnswer?: StructuredQuestionAnswerMetadata,
    fileIds?: string[],
    editContext?: AIBuilderPlanEditContext | null
  ): Promise<void> {
    if (!this.#state.session || this.#state.isStreaming || !this.canStartNewTurn) return;

    const userMsg: ChatMessage = {
      role: "user",
      content: message,
      timestamp: Date.now()
    };
    if (questionAnswer) {
      userMsg.metadata =
        questionAnswer.kind === "requirements_confirmation"
          ? {
              requirements_confirmed: true,
              requirements_version: questionAnswer.requirements_version
            }
          : {
              question_answer: toPersistedQuestionAnswerMetadata(questionAnswer)
            };
    }
    if (editContext) {
      userMsg.metadata = {
        ...(userMsg.metadata ?? {}),
        edit_context: editContext
      };
    }
    const requestBody: AIBuilderSendMessageRequest = {
      client_turn_id: crypto.randomUUID(),
      message,
      ui_language: getLocale()
    };
    if (this.#state.selectedModelId) {
      requestBody.model_id = this.#state.selectedModelId;
    }
    if (questionAnswer) {
      requestBody.question_answer = questionAnswer;
    }
    if (fileIds && fileIds.length > 0) {
      requestBody.file_ids = fileIds;
    }
    if (editContext) {
      requestBody.edit_context = editContext;
    }

    await this.#streamMessageRequest(requestBody, userMsg);
  }

  async retryLatestTurn(): Promise<void> {
    await this.#recoverLatestTurn("failed_before_provider", false);
  }

  async acknowledgeAndRetryLatestTurn(): Promise<void> {
    await this.#recoverLatestTurn("provider_outcome_unknown", true);
  }

  async #recoverLatestTurn(
    expectedState: AIBuilderTurnRecoveryState,
    acknowledgeDuplicateProviderSpend: boolean
  ): Promise<void> {
    if (this.#state.isStreaming || this.#isRecoveringLatestTurn) return;
    const sessionGeneration = this.#sessionGeneration;
    this.#isRecoveringLatestTurn = true;
    this.#notify();

    try {
      if (this.#requiresAuthoritativeRefresh && !(await this.refreshSession())) return;

      const latestTurn = this.#state.session?.latest_turn;
      if (latestTurn?.state !== expectedState) return;

      await this.#streamMessageRequest(
        {
          ...latestTurn.retry_request,
          acknowledge_duplicate_provider_spend: acknowledgeDuplicateProviderSpend
        },
        null
      );
    } finally {
      if (this.#sessionGeneration === sessionGeneration) {
        this.#isRecoveringLatestTurn = false;
        this.#notify();
      }
    }
  }

  async #streamMessageRequest(
    requestBody: AIBuilderSendMessageRequest,
    optimisticUserMessage: ChatMessage | null
  ): Promise<void> {
    const session = this.#state.session;
    if (!session || this.#state.isStreaming) return;
    const isRetry = optimisticUserMessage === null;
    if (isRetry) {
      this.#requiresAuthoritativeRefresh = true;
    }

    this.#state.error = null;
    this.#authoritativeRefreshError = false;
    this.#state.isConflict = false;
    this.#state.isStreaming = true;
    this.#abortController = new AbortController();
    const abortController = this.#abortController;
    const owner: SessionOperationOwner = {
      sessionId: session.session_id,
      sessionGeneration: this.#sessionGeneration,
      abortController
    };
    const ownsCurrentStream = () => this.#ownsSession(owner);

    if (optimisticUserMessage) {
      this.#state.messages = [...this.#state.messages, optimisticUserMessage];
    }
    if (this.#state.currentPlan) {
      this.#state.currentPlan = null;
      this.#state.applyResult = null;
    }
    this.#notify();

    let assistantText = "";
    let receivedUsageEvent = false;
    let receivedDurableStreamEvent = false;
    let receivedStaleQuestionEvent = false;
    let receivedStreamError = false;
    let receivedDone = false;

    try {
      await this.#transport.stream(
        FLOW_AI_BUILDER_ROUTES.sessionMessages,
        {
          params: { path: { session_id: session.session_id } },
          requestBody: {
            "application/json": requestBody
          }
        },
        {
          onMessage: (rawEvent: AIBuilderStreamEvent) => {
            if (!ownsCurrentStream()) return;
            const event = parseAIBuilderStreamEvent(rawEvent);
            switch (event.event) {
              case "text": {
                assistantText += event.data.text;
                if (event.data.text.trim()) {
                  receivedDurableStreamEvent = true;
                }
                this.#updateOrAddAssistantMessage(assistantText);
                return;
              }
              case "plan": {
                receivedDurableStreamEvent = true;
                const data = this.#normalizePlan(event.data);
                this.#state.currentPlan = data;
                this.#state.statusMessage = null;
                this.#updateOrAddAssistantMessage(assistantText, data);
                if (this.#state.session) {
                  this.#state.session = {
                    ...this.#state.session,
                    status: "awaiting_approval",
                    latest_plan_id: data.plan_id
                  };
                }
                this.#notify();
                return;
              }
              case "question": {
                if (this.isQuestionAnswered(event.data.question_id)) {
                  receivedStaleQuestionEvent = true;
                  return;
                }
                receivedDurableStreamEvent = true;
                this.#updateOrAddAssistantMessage(assistantText, undefined, event.data);
                return;
              }
              case "requirements_summary": {
                receivedDurableStreamEvent = true;
                this.#updateOrAddAssistantMessage(assistantText, undefined, undefined, event.data);
                return;
              }
              case "usage": {
                receivedUsageEvent = true;
                this.#updateSessionTelemetry(event.data);
                return;
              }
              case "status": {
                this.#state.statusMessage = event.data.status;
                this.#notify();
                return;
              }
              case "error": {
                receivedStreamError = true;
                const data = parseAIBuilderError({
                  transport: "sse",
                  payload: event.data,
                  fallbackMessage: "The AI Builder stream failed. Please try again."
                });
                const isSoftBlock = isSoftBlockAIBuilderError(data);
                this.#state.error = isSoftBlock ? null : data;
                if (!isSoftBlock) {
                  receivedDurableStreamEvent = true;
                }
                this.#state.statusMessage = null;
                this.#notify();
                return;
              }
              case "done": {
                receivedDone = true;
                this.#state.statusMessage = null;
                this.#notify();
                return;
              }
            }
            assertNever(event);
          },
          onClose: () => {
            if (ownsCurrentStream()) {
              this.#notify();
            }
          }
        },
        abortController
      );

      if (!ownsCurrentStream()) return;
      if ((!receivedDone || receivedStreamError) && !abortController.signal.aborted) {
        this.#requiresAuthoritativeRefresh = true;
      }
      const shouldRefreshAfterStream =
        !receivedDone ||
        isRetry ||
        receivedStreamError ||
        (requestBody.file_ids && requestBody.file_ids.length > 0) ||
        (!receivedUsageEvent && this.#state.currentPlan !== null) ||
        (requestBody.question_answer?.kind === "structured_question_answer" &&
          (!receivedDurableStreamEvent || receivedStaleQuestionEvent));
      if (shouldRefreshAfterStream && !abortController.signal.aborted) {
        await this.#refreshSession(owner);
      }
    } catch (e) {
      if (!abortController.signal.aborted && ownsCurrentStream()) {
        this.#requiresAuthoritativeRefresh = true;
        this.#state.error = parseAIBuilderError({
          transport: "apply",
          payload: e,
          fallbackMessage: "The AI Builder stream failed. Please try again."
        });
        this.#notify();
        await this.#refreshSession(owner);
      }
    } finally {
      if (ownsCurrentStream()) {
        this.#state.isStreaming = false;
        this.#abortController = null;
        this.#notify();
      }
    }
  }

  async approvePlan(): Promise<void> {
    const plan = this.#state.currentPlan;
    const owner = this.#currentSessionOwner();
    if (!plan || !owner) return;
    this.#state.error = null;
    this.#notify();

    try {
      await this.#transport.fetch(FLOW_AI_BUILDER_ROUTES.planApprove, {
        method: "post",
        params: { path: { plan_id: plan.plan_id } }
      });
      if (!this.#ownsPlan(owner, plan.plan_id)) return;
      this.#state.currentPlan = { ...plan, status: "approved" };
      this.#notify();
    } catch (e) {
      if (this.#ownsPlan(owner, plan.plan_id)) {
        this.#state.error = parseAIBuilderError({
          transport: "apply",
          payload: e,
          fallbackMessage: "Failed to approve plan"
        });
        this.#notify();
      }
      throw e;
    }
  }

  async applyPlan(expectedRevision?: number): Promise<ApplyResult> {
    const plan = this.#state.currentPlan;
    const owner = this.#currentSessionOwner();
    if (!plan || !owner) throw new Error("No plan to apply");

    this.#state.error = null;
    this.#state.applyError = null;
    this.#state.isConflict = false;
    this.#notify();

    try {
      const result = (await this.#transport.fetch(FLOW_AI_BUILDER_ROUTES.planApply, {
        method: "post",
        params: { path: { plan_id: plan.plan_id } },
        requestBody: {
          "application/json": {
            expected_revision: expectedRevision ?? null
          }
        }
      })) as ApplyResult;
      if (!this.#ownsPlan(owner, plan.plan_id)) {
        throw supersededSessionOperation();
      }
      this.#flowId = result.flow_id;
      this.#state.applyResult = result;
      this.#state.applyError = null;
      this.#state.currentPlan = { ...plan, status: "applied" };
      if (this.#state.session) {
        this.#state.session = {
          ...this.#state.session,
          flow_id: result.flow_id
        };
      }
      this.#notify();
      await this.#refreshSession(owner);
      return result;
    } catch (e: unknown) {
      if (!this.#ownsPlan(owner, plan.plan_id)) throw e;
      const parsed = parseAIBuilderError({
        transport: "apply",
        payload: e,
        fallbackMessage: "Failed to apply plan"
      });
      this.#state.applyError = parsed;
      this.#state.isConflict = isStaleApplyError(parsed);
      this.#state.error = parsed.code === "unknown" || parsed.code === "network" ? parsed : null;
      this.#notify();
      await this.#refreshSession(owner);
      throw e;
    }
  }

  async unpublishAndApplyPlan(expectedRevision?: number): Promise<ApplyResult> {
    const plan = this.#state.currentPlan;
    const owner = this.#currentSessionOwner();
    if (!plan || !owner) throw new Error("No plan to apply");
    const flowId = this.#publishedApplyFlowId();
    if (!flowId) throw new Error("No published flow to unpublish");

    this.#state.error = null;
    this.#notify();

    try {
      await this.#transport.fetch(FLOW_AI_BUILDER_ROUTES.flowUnpublish, {
        method: "post",
        params: { path: { id: flowId } }
      });
      if (!this.#ownsPlan(owner, plan.plan_id)) {
        throw supersededSessionOperation();
      }
      this.#state.applyError = null;
      this.#state.isConflict = false;
      this.#notify();
    } catch (e) {
      if (!this.#ownsPlan(owner, plan.plan_id)) throw e;
      this.#state.error = parseAIBuilderError({
        transport: "apply",
        payload: e,
        fallbackMessage: "Failed to unpublish flow"
      });
      this.#notify();
      throw e;
    }

    try {
      return await this.applyPlan(expectedRevision);
    } catch (e) {
      if (!this.#ownsPlan(owner, plan.plan_id)) throw e;
      const parsedApplyError = parseAIBuilderError({
        transport: "apply",
        payload: e,
        fallbackMessage: "Failed to apply plan"
      });
      this.#state.applyError = buildUnpublishedApplyFailureError({
        flowId,
        originalError: parsedApplyError
      });
      this.#state.isConflict = isStaleApplyError(parsedApplyError);
      this.#state.error = null;
      this.#notify();
      throw e;
    }
  }

  async removeAttachment(fileId: string): Promise<void> {
    const owner = this.#currentSessionOwner();
    if (!owner) return;

    await this.#transport.fetch(FLOW_AI_BUILDER_ROUTES.sessionAttachments, {
      method: "delete",
      params: { path: { session_id: owner.sessionId, file_id: fileId } }
    });

    if (this.#ownsSession(owner) && this.#state.session?.attachments) {
      this.#state.session = {
        ...this.#state.session,
        attachments: this.#state.session.attachments.filter(
          (attachment) => attachment.id !== fileId
        )
      };
      this.#notify();
    }
  }

  #publishedApplyFlowId(): string | null {
    const applyError = this.#state.applyError;
    const contextFlowId =
      applyError?.code === "flow_is_published" ||
      applyError?.code === "flow_unpublished_apply_failed"
        ? (applyError.diagnostic_context?.flow_id ?? applyError.details.flow_id)
        : null;
    if (typeof contextFlowId === "string" && contextFlowId.length > 0) {
      return contextFlowId;
    }

    if (this.#flowId) {
      return this.#flowId;
    }

    const sessionFlowId = this.#state.session?.flow_id;
    return sessionFlowId ?? null;
  }

  async revisePlan(type: PlanRevisionType): Promise<void> {
    const plan = this.#state.currentPlan;
    const owner = this.#currentSessionOwner();
    if (!plan || !owner) return;

    try {
      const result = (await this.#transport.fetch(FLOW_AI_BUILDER_ROUTES.planRevise, {
        method: "post",
        params: { path: { plan_id: plan.plan_id } },
        requestBody: {
          "application/json": { type }
        }
      })) as IncomingProposedPlan;

      if (!this.#ownsPlan(owner, plan.plan_id)) return;
      this.#state.currentPlan = this.#normalizePlan(result);
      this.#notify();
    } catch (e) {
      if (this.#ownsPlan(owner, plan.plan_id)) {
        this.#state.error = parseAIBuilderError({
          transport: "apply",
          payload: e,
          fallbackMessage: "Failed to revise plan"
        });
        this.#notify();
      }
    }
  }

  dismissApplyError(): void {
    this.#state.applyError = null;
    this.#notify();
  }

  async confirmRequirements(): Promise<void> {
    const latestSummary = this.#getLatestRequirementsSummary();
    if (!latestSummary) return;

    await this.sendMessage(
      m.ai_builder_requirements_confirm_message(),
      latestSummary.requirements_version
        ? {
            kind: "requirements_confirmation",
            requirements_confirmed: true,
            requirements_version: latestSummary.requirements_version
          }
        : { kind: "requirements_confirmation", requirements_confirmed: true }
    );
  }

  async changeRequirements(feedback?: string): Promise<void> {
    const message = feedback?.trim()
      ? m.ai_builder_requirements_change_message({ feedback: feedback.trim() })
      : m.ai_builder_requirements_change_message_empty();
    await this.sendMessage(message);
  }

  derivePhase(): AIBuilderPhase {
    if (this.#state.currentPlan) return "reviewing";
    if (this.#state.isStreaming && this.#state.statusMessage) return "building";

    const latestSummary = this.#getLatestRequirementsSummary();
    if (latestSummary) {
      return this.isRequirementsSummaryConfirmed(latestSummary) ? "building" : "confirming";
    }

    return "discovering";
  }

  isRequirementsSummaryConfirmed(summary: RequirementsSummary): boolean {
    const version = summary.requirements_version;
    if (!version) return false;

    let confirmed = false;
    let seenSummary = false;
    for (const message of this.#state.messages) {
      if (message.requirementsSummary?.requirements_version === version) {
        seenSummary = true;
        confirmed = false;
        continue;
      }

      if (!seenSummary || message.role !== "user") {
        continue;
      }

      if (
        message.metadata?.requirements_confirmed === true &&
        message.metadata?.requirements_version === version
      ) {
        confirmed = true;
        continue;
      }

      confirmed = false;
    }

    return confirmed;
  }

  isLatestRequirementsSummary(summary: RequirementsSummary): boolean {
    const latestSummary = this.#getLatestRequirementsSummary();
    if (!latestSummary) {
      return false;
    }
    if (!latestSummary.requirements_version || !summary.requirements_version) {
      return latestSummary === summary;
    }
    return latestSummary.requirements_version === summary.requirements_version;
  }

  isQuestionAnswered(questionId: string): boolean {
    for (let index = this.#state.messages.length - 1; index >= 0; index -= 1) {
      const questionAnswer = extractQuestionAnswer(this.#state.messages[index]?.metadata);
      if (questionAnswer?.question_id === questionId) {
        return true;
      }
    }
    return false;
  }

  async continueEditing(): Promise<void> {
    const editableFlowId =
      this.#state.applyResult?.flow_id ?? this.#state.session?.flow_id ?? this.#flowId;
    if (!editableFlowId) return;
    this.#flowId = editableFlowId;
    await this.createSession("edit");
  }

  abort(): void {
    this.#abortController?.abort();
    this.#abortController = null;
    this.#state.isStreaming = false;
    this.#notify();
  }

  #notify(): void {
    this.#onChange?.(this.#state);
  }

  #ownsSession(owner: SessionOperationOwner): boolean {
    return (
      this.#sessionGeneration === owner.sessionGeneration &&
      this.#state.session?.session_id === owner.sessionId &&
      this.#abortController === owner.abortController &&
      owner.abortController?.signal.aborted !== true
    );
  }

  #currentSessionOwner(): SessionOperationOwner | null {
    const session = this.#state.session;
    if (!session) return null;
    return {
      sessionId: session.session_id,
      sessionGeneration: this.#sessionGeneration,
      abortController: this.#abortController
    };
  }

  #ownsPlan(owner: SessionOperationOwner, planId: string): boolean {
    return this.#ownsSession(owner) && this.#state.currentPlan?.plan_id === planId;
  }

  #getLatestRequirementsSummary(): RequirementsSummary | null {
    for (let index = this.#state.messages.length - 1; index >= 0; index -= 1) {
      const summary = this.#state.messages[index]?.requirementsSummary;
      if (summary) {
        return summary;
      }
    }
    return null;
  }

  async #fetchModels(owner: SessionOperationOwner): Promise<void> {
    if (!this.#state.session) return;
    if (!this.#ownsSession(owner)) return;

    try {
      const result = (await this.#transport.fetch(FLOW_AI_BUILDER_ROUTES.sessionModels, {
        method: "get",
        params: { path: { session_id: this.#state.session.session_id } }
      })) as { models: AIBuilderModel[]; default_model_id: string | null };
      if (!this.#ownsSession(owner)) return;
      this.#state.availableModels = result.models;
      this.#state.selectedModelId = result.default_model_id;
      this.#state.modelsLoaded = true;
      this.#notify();
    } catch {
      // Non-critical — model selector just won't appear
    }
  }

  #updateOrAddAssistantMessage(
    text: string,
    plan?: ProposedPlan,
    question?: StructuredQuestion,
    requirementsSummary?: RequirementsSummary
  ): void {
    const lastMsg = this.#state.messages[this.#state.messages.length - 1];
    if (lastMsg?.role === "assistant") {
      this.#state.messages = [
        ...this.#state.messages.slice(0, -1),
        {
          ...lastMsg,
          content: text,
          plan: plan ?? lastMsg.plan,
          question: question ?? lastMsg.question,
          requirementsSummary: requirementsSummary ?? lastMsg.requirementsSummary
        }
      ];
    } else {
      this.#state.messages = [
        ...this.#state.messages,
        {
          role: "assistant",
          content: text,
          plan,
          question,
          requirementsSummary,
          timestamp: Date.now()
        }
      ];
    }
    this.#notify();
  }

  #resetFlowState(): void {
    this.#sessionGeneration += 1;
    this.#pendingResumeOwner = null;
    this.#requiresAuthoritativeRefresh = false;
    this.#authoritativeRefreshError = false;
    this.#isRecoveringLatestTurn = false;
    this.#state = createInitialFlowAIBuilderState();
  }

  #updateSessionTelemetry(telemetry: AIBuilderUsageEventData): void {
    if (!this.#state.session) return;

    this.#state.session = {
      ...this.#state.session,
      telemetry
    };
    this.#notify();
  }

  #hydrateMessagesFromConversation(conversation: AIBuilderConversationMessage[]): void {
    const hydrated: ChatMessage[] = [];

    for (const message of conversation) {
      if (message.role === "user") {
        hydrated.push({
          role: "user",
          content: message.content ?? "",
          metadata: this.#metadataFromPublicUserMessage(message),
          timestamp: this.#parseTimestamp(message.timestamp)
        });
        continue;
      }

      if (message.role !== "assistant") {
        continue;
      }

      const assistantMessage: ChatMessage = {
        role: "assistant",
        content: message.content ?? "",
        timestamp: this.#parseTimestamp(message.timestamp)
      };

      if (message.requirements_summary) {
        assistantMessage.requirementsSummary = message.requirements_summary;
      }

      if (message.question) {
        assistantMessage.question = message.question;
      }

      hydrated.push(assistantMessage);
    }

    this.#state.messages = hydrated;
  }

  #metadataFromPublicUserMessage(
    message: AIBuilderConversationMessage
  ): ChatMessage["metadata"] | undefined {
    const metadata: Record<string, unknown> = {};

    if (message.question_answer?.kind === "structured_question_answer") {
      const questionAnswer = toPersistedQuestionAnswerMetadata(message.question_answer);
      if (questionAnswer) {
        metadata.question_answer = questionAnswer;
      }
    }

    if (message.requirements_confirmation?.requirements_confirmed === true) {
      metadata.requirements_confirmed = true;
      if (message.requirements_confirmation.requirements_version) {
        metadata.requirements_version = message.requirements_confirmation.requirements_version;
      }
    }

    return Object.keys(metadata).length > 0 ? metadata : undefined;
  }

  #parseTimestamp(timestamp?: string | null): number {
    if (!timestamp) return Date.now();
    const parsed = Date.parse(timestamp);
    return Number.isNaN(parsed) ? Date.now() : parsed;
  }

  #applyCommittedTurnOutcome(session: AIBuilderSession): void {
    const latestTurn = session.latest_turn;
    if (latestTurn?.state !== "committed") return;

    if (latestTurn.error === null || latestTurn.error === undefined) {
      this.#state.error = null;
      return;
    }

    const error = parseAIBuilderError({
      transport: "sse",
      payload: latestTurn.error,
      fallbackMessage: "The AI Builder turn failed. Please try again."
    });
    this.#state.error = isSoftBlockAIBuilderError(error) ? null : error;
  }

  #normalizePlan(plan: IncomingProposedPlan): ProposedPlan {
    return {
      ...plan,
      status: plan.status ?? "proposed"
    };
  }

  async #syncPlanFromSession(owner: SessionOperationOwner): Promise<boolean> {
    if (!this.#ownsSession(owner)) return false;
    const latestPlanId = this.#state.session?.latest_plan_id;
    if (!latestPlanId) {
      this.#state.currentPlan = null;
      this.#notify();
      return true;
    }

    try {
      const result = (await this.#transport.fetch(FLOW_AI_BUILDER_ROUTES.plan, {
        method: "get",
        params: { path: { plan_id: latestPlanId } }
      })) as ProposedPlan;
      if (!this.#ownsSession(owner) || this.#state.session?.latest_plan_id !== latestPlanId) {
        return false;
      }
      this.#state.currentPlan = this.#normalizePlan(result);
      this.#notify();
      return true;
    } catch {
      // Leave the current plan as-is if recovery fails.
      return this.#ownsSession(owner);
    }
  }

  #hasRecoverableCreateDraft(): boolean {
    return this.getRecoverableCreateDrafts().length > 0;
  }
}
