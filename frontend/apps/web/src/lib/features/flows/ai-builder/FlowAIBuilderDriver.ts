import { m } from "$lib/paraglide/messages";
import { getLocale } from "$lib/paraglide/runtime";
import type { IntricFetchFunction, IntricStreamFunction } from "@intric/intric-js";
import type {
  PersistedStructuredQuestionAnswerMetadata,
  StructuredQuestion,
  StructuredQuestionAnswerMetadata
} from "./structuredQuestionAnswer";
import {
  buildClientAIBuilderError,
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
  AIBuilderSession,
  AIBuilderStreamEvent,
  AIBuilderUsageEventData,
  ApplyError,
  ApplyResult,
  ChatMessage,
  IncomingProposedPlan,
  PlanRevisionType,
  ProposedPlan,
  RequirementsSummary,
  TargetKind
} from "./protocol";

export interface AIBuilderClientTransport {
  fetch: IntricFetchFunction;
  stream: IntricStreamFunction;
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
  statusMessage: string | null;
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
  questionAnswer: StructuredQuestionAnswerMetadata
): PersistedStructuredQuestionAnswerMetadata | null {
  if (questionAnswer.kind !== "structured_question_answer") {
    return null;
  }
  const metadata: PersistedStructuredQuestionAnswerMetadata = {};
  if (questionAnswer.question_id !== undefined) {
    metadata.question_id = questionAnswer.question_id;
  }
  if (questionAnswer.selected_option_ids !== undefined) {
    metadata.selected_option_ids = questionAnswer.selected_option_ids;
  }
  if (questionAnswer.selected_values !== undefined) {
    metadata.selected_values = questionAnswer.selected_values;
  }
  if (questionAnswer.custom_value !== undefined) {
    metadata.custom_value = questionAnswer.custom_value;
  }
  return metadata;
}

function assertNever(value: never): never {
  throw new Error(`Unhandled AI Builder stream event: ${JSON.stringify(value)}`);
}

export class FlowAIBuilderDriver {
  readonly #transport: AIBuilderClientTransport;
  readonly #spaceId: string;
  #flowId: string | null;
  readonly #onChange?: FlowAIBuilderListener;

  #abortController: AbortController | null = null;
  #state: FlowAIBuilderState = createInitialFlowAIBuilderState();
  #initGeneration = 0;

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
    this.abort();
    this.#resetFlowState();
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
      this.#state.session = result;
      this.#hydrateMessagesFromConversation(result.conversation ?? []);
      this.#notify();
      await this.#fetchModels();
      await this.refreshSession();
      await this.loadDraftSessions();
    } catch (e) {
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

  async loadDraftSessions(): Promise<void> {
    try {
      const result = (await this.#transport.fetch(FLOW_AI_BUILDER_ROUTES.sessions, {
        method: "get"
      })) as { sessions: AIBuilderDraftSession[] };
      this.#state.draftSessions = result.sessions;
      this.#notify();
    } catch {
      // Non-critical — recovery affordances just won't render
    }
  }

  hasRecoverableCreateDraft(): boolean {
    return this.getRecoverableCreateDrafts().length > 0;
  }

  getRecoverableCreateDrafts(): AIBuilderDraftSession[] {
    return this.#state.draftSessions.filter(
      (session) =>
        session.space_id === this.#spaceId &&
        session.target_kind === "create" &&
        session.flow_id === null &&
        session.status !== "applied" &&
        session.status !== "cancelled"
    );
  }

  async resumeSession(sessionId: string): Promise<void> {
    ++this.#initGeneration;
    this.abort();
    this.#resetFlowState();
    this.#state.error = null;
    this.#notify();

    const result = (await this.#transport.fetch(FLOW_AI_BUILDER_ROUTES.session, {
      method: "get",
      params: { path: { session_id: sessionId } }
    })) as AIBuilderSession;
    this.#state.session = result;
    this.#hydrateMessagesFromConversation(result.conversation ?? []);
    this.#notify();
    await this.#fetchModels();
    await this.#syncPlanFromSession();
    await this.loadDraftSessions();
  }

  async discardSession(sessionId: string): Promise<void> {
    await this.#transport.fetch(FLOW_AI_BUILDER_ROUTES.sessionCancel, {
      method: "post",
      params: { path: { session_id: sessionId } }
    });

    this.#state.draftSessions = this.#state.draftSessions.filter(
      (session) => session.session_id !== sessionId
    );
    if (this.#state.session?.session_id === sessionId) {
      this.#state.session = null;
      this.#state.messages = [];
      this.#state.currentPlan = null;
      this.#state.applyResult = null;
      this.#state.isConflict = false;
      this.#state.statusMessage = null;
    }
    this.#notify();
    await this.loadDraftSessions();
  }

  async refreshSession(): Promise<void> {
    if (!this.#state.session) return;

    try {
      const result = (await this.#transport.fetch(FLOW_AI_BUILDER_ROUTES.session, {
        method: "get",
        params: { path: { session_id: this.#state.session.session_id } }
      })) as AIBuilderSession;
      this.#state.session = result;
      this.#hydrateMessagesFromConversation(result.conversation ?? []);
      this.#notify();
      await this.#syncPlanFromSession();
    } catch {
      // Silently fail on refresh
    }
  }

  async sendMessage(
    message: string,
    questionAnswer?: StructuredQuestionAnswerMetadata,
    fileIds?: string[],
    editContext?: AIBuilderPlanEditContext | null
  ): Promise<void> {
    if (!this.#state.session || this.#state.isStreaming) return;

    this.#state.error = null;
    this.#state.isConflict = false;
    this.#state.isStreaming = true;
    this.#abortController = new AbortController();
    const abortController = this.#abortController;

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
    this.#state.messages = [...this.#state.messages, userMsg];

    if (this.#state.currentPlan) {
      this.#state.currentPlan = null;
      this.#state.applyResult = null;
    }

    this.#notify();

    let assistantText = "";
    let receivedUsageEvent = false;

    try {
      const requestBody: {
        message: string;
        model_id?: string;
        file_ids?: string[];
        question_answer?: StructuredQuestionAnswerMetadata;
        edit_context?: AIBuilderPlanEditContext;
        ui_language?: string;
      } = { message };

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
      requestBody.ui_language = getLocale();

      await this.#transport.stream(
        FLOW_AI_BUILDER_ROUTES.sessionMessages,
        {
          params: { path: { session_id: this.#state.session.session_id } },
          requestBody: {
            "application/json": requestBody
          }
        },
        {
          onMessage: (rawEvent: AIBuilderStreamEvent) => {
            const event = parseAIBuilderStreamEvent(rawEvent);
            switch (event.event) {
              case "text": {
                assistantText += event.data.text;
                this.#updateOrAddAssistantMessage(assistantText);
                return;
              }
              case "plan": {
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
                this.#updateOrAddAssistantMessage(assistantText, undefined, event.data);
                return;
              }
              case "requirements_summary": {
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
                const data = parseAIBuilderError({
                  transport: "sse",
                  payload: event.data,
                  fallbackMessage: "The AI Builder stream failed. Please try again."
                });
                this.#state.error = isSoftBlockAIBuilderError(data) ? null : data;
                this.#state.statusMessage = null;
                this.#notify();
                return;
              }
              case "done": {
                this.#state.isStreaming = false;
                this.#state.statusMessage = null;
                this.#notify();
                return;
              }
            }
            assertNever(event);
          },
          onClose: () => {
            this.#state.isStreaming = false;
            this.#notify();
          }
        },
        abortController
      );

      const shouldRefreshAfterStream =
        (fileIds && fileIds.length > 0) ||
        (!receivedUsageEvent && this.#state.currentPlan !== null);
      if (shouldRefreshAfterStream && !abortController.signal.aborted) {
        await this.refreshSession();
      }
    } catch (e) {
      if (!abortController.signal.aborted) {
        this.#state.error = buildClientAIBuilderError(
          e instanceof Error ? e.message : "Stream failed",
          { code: "stream_failed" }
        );
        this.#notify();
      }
    } finally {
      this.#state.isStreaming = false;
      if (this.#abortController === abortController) {
        this.#abortController = null;
      }
      this.#notify();
    }
  }

  async approvePlan(): Promise<void> {
    if (!this.#state.currentPlan) return;
    this.#state.error = null;
    this.#notify();

    try {
      await this.#transport.fetch(FLOW_AI_BUILDER_ROUTES.planApprove, {
        method: "post",
        params: { path: { plan_id: this.#state.currentPlan.plan_id } }
      });
      this.#state.currentPlan = { ...this.#state.currentPlan, status: "approved" };
      this.#notify();
    } catch (e) {
      this.#state.error = parseAIBuilderError({
        transport: "apply",
        payload: e,
        fallbackMessage: "Failed to approve plan"
      });
      this.#notify();
      throw e;
    }
  }

  async applyPlan(expectedRevision?: number): Promise<ApplyResult> {
    if (!this.#state.currentPlan) throw new Error("No plan to apply");

    this.#state.error = null;
    this.#state.applyError = null;
    this.#state.isConflict = false;
    if (this.#state.session) {
      this.#state.session = { ...this.#state.session, status: "applying" };
    }
    this.#notify();

    try {
      const result = (await this.#transport.fetch(FLOW_AI_BUILDER_ROUTES.planApply, {
        method: "post",
        params: { path: { plan_id: this.#state.currentPlan.plan_id } },
        requestBody: {
          "application/json": {
            expected_revision: expectedRevision ?? null
          }
        }
      })) as ApplyResult;
      this.#flowId = result.flow_id;
      this.#state.applyResult = result;
      this.#state.applyError = null;
      this.#state.currentPlan = { ...this.#state.currentPlan, status: "applied" };
      if (this.#state.session) {
        this.#state.session = {
          ...this.#state.session,
          flow_id: result.flow_id
        };
      }
      this.#notify();
      await this.refreshSession();
      return result;
    } catch (e: unknown) {
      const parsed = parseAIBuilderError({
        transport: "apply",
        payload: e,
        fallbackMessage: "Failed to apply plan"
      });
      this.#state.applyError = parsed;
      this.#state.isConflict = isStaleApplyError(parsed);
      this.#state.error = parsed.code === "unknown" || parsed.code === "network" ? parsed : null;
      this.#notify();
      await this.refreshSession();
      throw e;
    }
  }

  async unpublishAndApplyPlan(expectedRevision?: number): Promise<ApplyResult> {
    if (!this.#state.currentPlan) throw new Error("No plan to apply");
    const flowId = this.#publishedApplyFlowId();
    if (!flowId) throw new Error("No published flow to unpublish");

    this.#state.error = null;
    this.#notify();

    try {
      await this.#transport.fetch(FLOW_AI_BUILDER_ROUTES.flowUnpublish, {
        method: "post",
        params: { path: { id: flowId } }
      });
      this.#state.applyError = null;
      this.#state.isConflict = false;
      this.#notify();
    } catch (e) {
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
    if (!this.#state.session) return;

    await this.#transport.fetch(FLOW_AI_BUILDER_ROUTES.sessionAttachments, {
      method: "delete",
      params: { path: { session_id: this.#state.session.session_id, file_id: fileId } }
    });

    if (this.#state.session.attachments) {
      this.#state.session.attachments = this.#state.session.attachments.filter(
        (attachment) => attachment.id !== fileId
      );
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
    if (!this.#state.currentPlan) return;

    try {
      const result = (await this.#transport.fetch(FLOW_AI_BUILDER_ROUTES.planRevise, {
        method: "post",
        params: { path: { plan_id: this.#state.currentPlan.plan_id } },
        requestBody: {
          "application/json": { type }
        }
      })) as IncomingProposedPlan;

      this.#state.currentPlan = this.#normalizePlan(result);
      this.#notify();
    } catch (e) {
      this.#state.error = parseAIBuilderError({
        transport: "apply",
        payload: e,
        fallbackMessage: "Failed to revise plan"
      });
      this.#notify();
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

  #getLatestRequirementsSummary(): RequirementsSummary | null {
    for (let index = this.#state.messages.length - 1; index >= 0; index -= 1) {
      const summary = this.#state.messages[index]?.requirementsSummary;
      if (summary) {
        return summary;
      }
    }
    return null;
  }

  async #fetchModels(): Promise<void> {
    if (!this.#state.session) return;

    try {
      const result = (await this.#transport.fetch(FLOW_AI_BUILDER_ROUTES.sessionModels, {
        method: "get",
        params: { path: { session_id: this.#state.session.session_id } }
      })) as { models: AIBuilderModel[]; default_model_id: string | null };
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

    for (let index = 0; index < conversation.length; index += 1) {
      const message = conversation[index];
      if (!message) continue;

      if (message.role === "user") {
        hydrated.push({
          role: "user",
          content: message.content ?? "",
          metadata: message.metadata ?? undefined,
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

      const metadataRequirementsSummary = this.#parseRequirementsSummaryFromMetadata(
        message.metadata
      );
      if (metadataRequirementsSummary) {
        assistantMessage.requirementsSummary = metadataRequirementsSummary;
      }

      const toolCalls = Array.isArray(message.tool_calls) ? message.tool_calls : [];
      const structuredQuestionToolCall = toolCalls.find(
        (toolCall) => toolCall?.name === "ask_structured_question"
      );
      const requirementsToolCall = toolCalls.find(
        (toolCall) => toolCall?.name === "confirm_requirements"
      );

      const structuredQuestion = this.#parseStructuredQuestion(
        structuredQuestionToolCall?.arguments
      );
      if (structuredQuestion) {
        assistantMessage.question = structuredQuestion;
      }

      for (let toolIndex = index + 1; toolIndex < conversation.length; toolIndex += 1) {
        const toolMessage = conversation[toolIndex];
        if (toolMessage?.role !== "tool") {
          break;
        }

        if (requirementsToolCall?.id && toolMessage.tool_call_id === requirementsToolCall.id) {
          const requirementsSummary = this.#parseRequirementsSummaryFromMetadata(
            toolMessage.metadata
          );
          if (requirementsSummary) {
            assistantMessage.requirementsSummary = requirementsSummary;
          }
        }

        index = toolIndex;
      }

      hydrated.push(assistantMessage);
    }

    this.#state.messages = hydrated;
  }

  #parseStructuredQuestion(payload: unknown): StructuredQuestion | undefined {
    if (!payload || typeof payload !== "object") return undefined;

    const question = payload as Record<string, unknown>;
    if (
      typeof question.question_id !== "string" ||
      typeof question.question !== "string" ||
      !Array.isArray(question.options) ||
      (question.selection_mode !== "single" && question.selection_mode !== "multi") ||
      typeof question.allow_custom !== "boolean"
    ) {
      return undefined;
    }

    return {
      question_id: question.question_id,
      question: question.question,
      options: question.options.filter(
        (option): option is StructuredQuestion["options"][number] => {
          return typeof option === "object" && option !== null && typeof option.label === "string";
        }
      ),
      selection_mode: question.selection_mode,
      allow_custom: question.allow_custom,
      requires_confirm: question.requires_confirm === true
    };
  }

  #parseRequirementsSummary(payload: unknown): RequirementsSummary | undefined {
    if (!payload || typeof payload !== "object") return undefined;

    const summary = payload as Record<string, unknown>;
    if (
      typeof summary.summary !== "string" ||
      !Array.isArray(summary.key_decisions) ||
      typeof summary.input_description !== "string" ||
      typeof summary.output_description !== "string"
    ) {
      return undefined;
    }

    return {
      requirements_version:
        typeof summary.requirements_version === "string" ? summary.requirements_version : null,
      summary: summary.summary,
      key_decisions: summary.key_decisions.filter(
        (decision): decision is RequirementsSummary["key_decisions"][number] => {
          return (
            typeof decision === "object" &&
            decision !== null &&
            typeof decision.topic === "string" &&
            typeof decision.decision === "string"
          );
        }
      ),
      input_description: summary.input_description,
      output_description: summary.output_description,
      assumptions: Array.isArray(summary.assumptions)
        ? summary.assumptions.filter(
            (assumption): assumption is string => typeof assumption === "string"
          )
        : [],
      manual_setup_notes: Array.isArray(summary.manual_setup_notes)
        ? summary.manual_setup_notes.filter((note): note is string => typeof note === "string")
        : []
    };
  }

  #parseRequirementsSummaryFromMetadata(
    metadata: AIBuilderConversationMessage["metadata"] | undefined | null
  ): RequirementsSummary | undefined {
    if (!metadata || typeof metadata !== "object") return undefined;
    const summaryPayload = metadata.requirements_summary;
    if (!summaryPayload || typeof summaryPayload !== "object") {
      return undefined;
    }
    const version = metadata.requirements_version;
    const payload =
      typeof version === "string" && !("requirements_version" in summaryPayload)
        ? { ...summaryPayload, requirements_version: version }
        : summaryPayload;
    return this.#parseRequirementsSummary(payload);
  }

  #parseTimestamp(timestamp?: string | null): number {
    if (!timestamp) return Date.now();
    const parsed = Date.parse(timestamp);
    return Number.isNaN(parsed) ? Date.now() : parsed;
  }

  #normalizePlan(plan: IncomingProposedPlan): ProposedPlan {
    const edit = plan.proposal.edit ?? null;
    return {
      ...plan,
      status: plan.status ?? "proposed",
      edit_diff: plan.edit_diff ?? edit?.diff ?? null,
      edit_confidence: plan.edit_confidence ?? edit?.confidence ?? null,
      edit_warnings: plan.edit_warnings ?? edit?.warnings ?? null,
      edit_advisories: plan.edit_advisories ?? edit?.advisories ?? null,
      edit_risk_flags: plan.edit_risk_flags ?? edit?.risk_flags ?? null
    };
  }

  async #syncPlanFromSession(): Promise<void> {
    const latestPlanId = this.#state.session?.latest_plan_id;
    if (!latestPlanId) {
      this.#state.currentPlan = null;
      this.#notify();
      return;
    }

    try {
      const result = (await this.#transport.fetch(FLOW_AI_BUILDER_ROUTES.plan, {
        method: "get",
        params: { path: { plan_id: latestPlanId } }
      })) as ProposedPlan;
      this.#state.currentPlan = this.#normalizePlan(result);
      this.#notify();
    } catch {
      // Leave the current plan as-is if recovery fails.
    }
  }

  #hasRecoverableCreateDraft(): boolean {
    return this.getRecoverableCreateDrafts().length > 0;
  }
}
