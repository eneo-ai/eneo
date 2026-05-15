import { createClassContext } from "$lib/core/helpers/createClassContext";
import type { Intric } from "@intric/intric-js";
import type { StructuredQuestionAnswerMetadata } from "./structuredQuestionAnswer";
import {
  FlowAIBuilderDriver,
  type AIBuilderClientTransport,
  type FlowAIBuilderState
} from "./FlowAIBuilderDriver";
import type {
  AIBuilderDraftSession,
  AIBuilderModel,
  AIBuilderPlanEditContext,
  AIBuilderPhase,
  AIBuilderSession,
  ApplyError,
  ApplyResult,
  ChatMessage,
  PlanRevisionType,
  ProposedPlan,
  RequirementsSummary,
  SessionStatus,
  TargetKind
} from "./protocol";

export class FlowAIBuilderService {
  #driver: FlowAIBuilderDriver;
  #stateVersion = $state(0);
  #hasSeenPlanInSession = $state(false);

  hasSession = $derived(this.#state.session !== null);
  hasSeenPlanInSession = $derived(this.#hasSeenPlanInSession);
  canSendMessage = $derived(
    this.hasSession &&
      !this.#state.isStreaming &&
      (this.#state.session?.status === "chatting" ||
        this.#state.session?.status === "awaiting_approval")
  );
  canApprove = $derived(
    this.#state.currentPlan?.status === "proposed" &&
      this.#state.session?.status === "awaiting_approval"
  );
  canApply = $derived(
    this.#state.currentPlan?.status === "approved" &&
      this.#state.session?.status === "awaiting_approval"
  );
  isApplied = $derived(this.#state.session?.status === "applied");
  canContinueEditing = $derived(
    this.#state.applyResult?.flow_id !== undefined ||
      (this.#state.session?.status === "applied" && this.#state.session?.flow_id !== null)
  );

  constructor(intric: Intric, spaceId: string, flowId: string | null) {
    const transport: AIBuilderClientTransport = {
      fetch: intric.client.fetch as AIBuilderClientTransport["fetch"],
      stream: intric.client.stream as AIBuilderClientTransport["stream"]
    };
    this.#driver = new FlowAIBuilderDriver(transport, spaceId, flowId, (state) => {
      this.#stateVersion += 1;
      this.#updatePlanSeenLatch(state);
    });
  }

  get #state(): Readonly<FlowAIBuilderState> {
    // Svelte tracks Driver updates through this read; Service getters must use this accessor.
    void this.#stateVersion;
    return this.#driver.state;
  }

  // Keep "updating plan" copy stable while a re-plan stream briefly clears currentPlan.
  #updatePlanSeenLatch(state: Readonly<FlowAIBuilderState>): void {
    if (state.session === null) {
      this.#hasSeenPlanInSession = false;
      return;
    }
    if (state.currentPlan !== null) {
      this.#hasSeenPlanInSession = true;
    }
  }

  get session(): AIBuilderSession | null {
    return this.#state.session;
  }

  get messages(): ChatMessage[] {
    return this.#state.messages;
  }

  get currentPlan(): ProposedPlan | null {
    return this.#state.currentPlan;
  }

  get isStreaming(): boolean {
    return this.#state.isStreaming;
  }

  get isInitializing(): boolean {
    return this.#state.isInitializing;
  }

  get error(): string | null {
    return this.#state.error;
  }

  get applyError(): ApplyError | null {
    return this.#state.applyError;
  }

  get applyResult(): ApplyResult | null {
    return this.#state.applyResult;
  }

  get isConflict(): boolean {
    return this.#state.isConflict;
  }

  get statusMessage(): string | null {
    return this.#state.statusMessage;
  }

  get availableModels(): AIBuilderModel[] {
    return this.#state.availableModels;
  }

  get selectedModelId(): string | null {
    return this.#state.selectedModelId;
  }

  get modelsLoaded(): boolean {
    return this.#state.modelsLoaded;
  }

  get draftSessions(): AIBuilderDraftSession[] {
    return this.#state.draftSessions;
  }

  get hasRecoverableCreateDraft(): boolean {
    return this.recoverableCreateDrafts.length > 0;
  }

  get recoverableCreateDrafts(): AIBuilderDraftSession[] {
    void this.#state;
    return this.#driver.getRecoverableCreateDrafts();
  }

  get sessionStatus(): SessionStatus | undefined {
    return this.#state.session?.status;
  }

  phase: AIBuilderPhase = $derived.by(() => {
    void this.#state;
    return this.#driver.derivePhase();
  });

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
    questionAnswer?: StructuredQuestionAnswerMetadata,
    fileIds?: string[],
    editContext?: AIBuilderPlanEditContext | null
  ): Promise<void> {
    await this.#driver.sendMessage(message, questionAnswer, fileIds, editContext);
  }

  async approvePlan(): Promise<void> {
    await this.#driver.approvePlan();
  }

  async applyPlan(expectedRevision?: number): Promise<ApplyResult> {
    return await this.#driver.applyPlan(expectedRevision);
  }

  async unpublishAndApplyPlan(expectedRevision?: number): Promise<ApplyResult> {
    return await this.#driver.unpublishAndApplyPlan(expectedRevision);
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

  async removeAttachment(fileId: string): Promise<void> {
    await this.#driver.removeAttachment(fileId);
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

  async revisePlan(type: PlanRevisionType): Promise<void> {
    await this.#driver.revisePlan(type);
  }

  dismissApplyError(): void {
    this.#driver.dismissApplyError();
  }

  abort(): void {
    this.#driver.abort();
  }

  destroy(): void {
    this.abort();
  }
}

export const [getAIBuilderService, initAIBuilderService] = createClassContext(
  "FlowAIBuilderService",
  FlowAIBuilderService
);
