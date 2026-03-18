import { createClassContext } from "$lib/core/helpers/createClassContext";
import type { Intric } from "@intric/intric-js";
import type { StructuredQuestionAnswerMetadata } from "./structuredQuestionAnswer";
import {
  createInitialFlowAIBuilderState,
  FlowAIBuilderDriver,
  type AIBuilderClientTransport,
  type FlowAIBuilderState
} from "./FlowAIBuilderDriver";
import type {
  AIBuilderDraftSession,
  AIBuilderModel,
  AIBuilderPhase,
  AIBuilderSession,
  ApplyResult,
  ChatMessage,
  ProposedPlan,
  RequirementsSummary,
  SessionStatus,
  TargetKind
} from "./protocol";

export class FlowAIBuilderService {
  #driver: FlowAIBuilderDriver;
  #spaceId: string;

  #session = $state<AIBuilderSession | null>(null);
  #messages = $state<ChatMessage[]>([]);
  #currentPlan = $state<ProposedPlan | null>(null);
  #isStreaming = $state(false);
  #isInitializing = $state(false);
  #error = $state<string | null>(null);
  #applyResult = $state<ApplyResult | null>(null);
  #isConflict = $state(false);
  #statusMessage = $state<string | null>(null);
  #availableModels = $state<AIBuilderModel[]>([]);
  #selectedModelId = $state<string | null>(null);
  #modelsLoaded = $state(false);
  #draftSessions = $state<AIBuilderDraftSession[]>([]);

  hasSession = $derived(this.#session !== null);
  canSendMessage = $derived(
    this.hasSession &&
      !this.#isStreaming &&
      (this.#session?.status === "chatting" || this.#session?.status === "awaiting_approval")
  );
  canApprove = $derived(
    this.#currentPlan?.status === "proposed" && this.#session?.status === "awaiting_approval"
  );
  canApply = $derived(
    this.#currentPlan?.status === "approved" && this.#session?.status === "awaiting_approval"
  );
  isApplied = $derived(this.#session?.status === "applied");
  canContinueEditing = $derived(
    this.#applyResult?.flow_id !== undefined ||
      (this.#session?.status === "applied" && this.#session?.flow_id !== null)
  );

  constructor(intric: Intric, spaceId: string, flowId: string | null) {
    this.#spaceId = spaceId;
    const transport = intric.client as unknown as AIBuilderClientTransport;
    this.#driver = new FlowAIBuilderDriver(transport, spaceId, flowId, (state) => {
      this.#applyState(state);
    });
    this.#applyState(createInitialFlowAIBuilderState());
  }

  get session(): AIBuilderSession | null {
    return this.#session;
  }

  get messages(): ChatMessage[] {
    return this.#messages;
  }

  get currentPlan(): ProposedPlan | null {
    return this.#currentPlan;
  }

  get isStreaming(): boolean {
    return this.#isStreaming;
  }

  get isInitializing(): boolean {
    return this.#isInitializing;
  }

  get error(): string | null {
    return this.#error;
  }

  get applyResult(): ApplyResult | null {
    return this.#applyResult;
  }

  get isConflict(): boolean {
    return this.#isConflict;
  }

  get statusMessage(): string | null {
    return this.#statusMessage;
  }

  get availableModels(): AIBuilderModel[] {
    return this.#availableModels;
  }

  get selectedModelId(): string | null {
    return this.#selectedModelId;
  }

  get modelsLoaded(): boolean {
    return this.#modelsLoaded;
  }

  get draftSessions(): AIBuilderDraftSession[] {
    return this.#draftSessions;
  }

  get hasRecoverableCreateDraft(): boolean {
    return this.recoverableCreateDrafts.length > 0;
  }

  get recoverableCreateDrafts(): AIBuilderDraftSession[] {
    return this.#draftSessions.filter(
      (session) =>
        session.space_id === this.#spaceId &&
        session.target_kind === "create" &&
        session.flow_id === null &&
        session.status !== "applied" &&
        session.status !== "cancelled"
    );
  }

  get sessionStatus(): SessionStatus | undefined {
    return this.#session?.status;
  }

  get phase(): AIBuilderPhase {
    return this.#driver.derivePhase();
  }

  isRequirementsSummaryConfirmed(summary: RequirementsSummary): boolean {
    return this.#driver.isRequirementsSummaryConfirmed(summary);
  }

  isLatestRequirementsSummary(summary: RequirementsSummary): boolean {
    return this.#driver.isLatestRequirementsSummary(summary);
  }

  isQuestionAnswered(questionId: string): boolean {
    return this.#driver.isQuestionAnswered(questionId);
  }

  seedState(partial: Partial<FlowAIBuilderState>): void {
    this.#driver.seedState(partial);
  }

  async initialize(targetKind: TargetKind): Promise<void> {
    await this.#driver.initialize(targetKind);
  }

  async createSession(targetKind: TargetKind, options?: { forceNew?: boolean }): Promise<void> {
    await this.#driver.createSession(targetKind, options);
  }

  async startFreshSession(targetKind: TargetKind): Promise<void> {
    await this.#driver.startFreshSession(targetKind);
  }

  async loadDraftSessions(): Promise<void> {
    await this.#driver.loadDraftSessions();
  }

  async resumeSession(sessionId: string): Promise<void> {
    await this.#driver.resumeSession(sessionId);
  }

  async discardSession(sessionId: string): Promise<void> {
    await this.#driver.discardSession(sessionId);
  }

  async refreshSession(): Promise<void> {
    await this.#driver.refreshSession();
  }

  async sendMessage(
    message: string,
    questionAnswer?: StructuredQuestionAnswerMetadata
  ): Promise<void> {
    await this.#driver.sendMessage(message, questionAnswer);
  }

  async approvePlan(): Promise<void> {
    await this.#driver.approvePlan();
  }

  async applyPlan(expectedRevision?: number): Promise<ApplyResult> {
    return await this.#driver.applyPlan(expectedRevision);
  }

  async confirmRequirements(): Promise<void> {
    await this.#driver.confirmRequirements();
  }

  async changeRequirements(feedback?: string): Promise<void> {
    await this.#driver.changeRequirements(feedback);
  }

  async continueEditing(): Promise<void> {
    await this.#driver.continueEditing();
  }

  selectModel(modelId: string): void {
    this.#driver.selectModel(modelId);
  }

  clearError(): void {
    this.#driver.clearError();
  }

  dismissConflict(): void {
    this.#driver.dismissConflict();
  }

  dismissPlanPane(): void {
    this.#driver.dismissPlanPane();
  }

  abort(): void {
    this.#driver.abort();
  }

  destroy(): void {
    this.abort();
  }

  #applyState(state: Readonly<FlowAIBuilderState>): void {
    this.#session = state.session;
    this.#messages = state.messages;
    this.#currentPlan = state.currentPlan;
    this.#isStreaming = state.isStreaming;
    this.#isInitializing = state.isInitializing;
    this.#error = state.error;
    this.#applyResult = state.applyResult;
    this.#isConflict = state.isConflict;
    this.#statusMessage = state.statusMessage;
    this.#availableModels = state.availableModels;
    this.#selectedModelId = state.selectedModelId;
    this.#modelsLoaded = state.modelsLoaded;
    this.#draftSessions = state.draftSessions;
  }
}

export const [getAIBuilderService, initAIBuilderService] = createClassContext(
  "FlowAIBuilderService",
  FlowAIBuilderService
);
