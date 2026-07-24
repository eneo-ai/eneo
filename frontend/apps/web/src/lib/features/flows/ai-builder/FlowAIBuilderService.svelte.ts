import { createClassContext } from "$lib/core/helpers/createClassContext";
import type { Eneo } from "@eneo/eneo-js";
import type { StructuredQuestionAnswerMetadata } from "./structuredQuestionAnswer";
import {
  FlowAIBuilderDriver,
  type AIBuilderClientTransport,
  type CreateFailureOutcome,
  type FlowAIBuilderState,
  type ModelLoadStatus
} from "./FlowAIBuilderDriver";
import type {
  AIBuilderDraftSession,
  AIBuilderError,
  AIBuilderModel,
  AIBuilderPlanEditContext,
  AIBuilderPhase,
  AIBuilderSendOutcome,
  AIBuilderSession,
  AIBuilderStatus,
  AIBuilderTurnState,
  AIBuilderTurnRecoveryState,
  ApplyError,
  ApplyResult,
  ChatMessage,
  PlanRevisionType,
  ProposedPlan,
  RecoverableAIBuilderDraftSession,
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
  /** True while an atomic plan operation (creation) is running. Every
   *  session-mutating control must render disabled while this holds; the
   *  driver enforces the same lock at its command boundaries. */
  isCreating = $derived(this.#state.pendingOperation?.kind === "creating");
  canSendMessage = $derived(
    this.hasSession &&
      !this.#state.isStreaming &&
      this.#state.pendingOperation === null &&
      this.#canStartNewTurn &&
      (this.#state.session?.status === "chatting" ||
        this.#state.session?.status === "awaiting_approval")
  );
  canApprove = $derived(
    this.#state.pendingOperation === null &&
      this.#state.currentPlan?.status === "proposed" &&
      this.#state.session?.status === "awaiting_approval"
  );
  canApply = $derived(
    this.#state.pendingOperation === null &&
      this.#state.currentPlan?.status === "approved" &&
      this.#state.session?.status === "awaiting_approval"
  );
  isApplied = $derived(this.#state.session?.status === "applied");
  canContinueEditing = $derived(
    this.#state.applyResult?.flow_id !== undefined ||
      (this.#state.session?.status === "applied" && this.#state.session?.flow_id !== null)
  );

  constructor(eneo: Eneo, spaceId: string, flowId: string | null) {
    const transport: AIBuilderClientTransport = {
      fetch: eneo.client.fetch,
      stream: eneo.client.stream
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

  get #canStartNewTurn(): boolean {
    return this.#driver.canStartNewTurn;
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

  get error(): AIBuilderError | null {
    return this.#state.error;
  }

  get applyError(): ApplyError | null {
    return this.#state.applyError;
  }

  get applyResult(): ApplyResult | null {
    return this.#state.applyResult;
  }

  get createFailureOutcome(): CreateFailureOutcome | null {
    return this.#state.createFailureOutcome;
  }

  get isConflict(): boolean {
    return this.#state.isConflict;
  }

  get statusMessage(): AIBuilderStatus | null {
    return this.#state.statusMessage;
  }

  get availableModels(): AIBuilderModel[] {
    return this.#state.availableModels;
  }

  get selectedModelId(): string | null {
    return this.#state.selectedModelId;
  }

  get modelLoadStatus(): ModelLoadStatus {
    return this.#state.modelLoadStatus;
  }

  get modelsLoaded(): boolean {
    return this.#state.modelLoadStatus === "loaded";
  }

  get draftSessions(): AIBuilderDraftSession[] {
    return this.#state.draftSessions;
  }

  get hasRecoverableCreateDraft(): boolean {
    return this.recoverableCreateDrafts.length > 0;
  }

  get recoverableCreateDrafts(): RecoverableAIBuilderDraftSession[] {
    void this.#state;
    return this.#driver.getRecoverableCreateDrafts();
  }

  get sessionStatus(): SessionStatus | undefined {
    return this.#state.session?.status;
  }

  get turnRecoveryState(): AIBuilderTurnRecoveryState | null {
    void this.#state;
    return this.#driver.turnRecoveryState;
  }

  get latestTurnState(): AIBuilderTurnState | null {
    void this.#state;
    return this.#driver.latestTurnState;
  }

  get authoritativeRefreshFailed(): boolean {
    void this.#state;
    return this.#driver.authoritativeRefreshFailed;
  }

  get isRecoveringLatestTurn(): boolean {
    void this.#state;
    return this.#driver.isRecoveringLatestTurn;
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
  ): Promise<AIBuilderSendOutcome> {
    return await this.#driver.sendMessage(message, questionAnswer, fileIds, editContext);
  }

  async retryLatestTurn(): Promise<void> {
    await this.#driver.retryLatestTurn();
  }

  async acknowledgeAndRetryLatestTurn(): Promise<void> {
    await this.#driver.acknowledgeAndRetryLatestTurn();
  }

  async approvePlan(): Promise<void> {
    await this.#driver.approvePlan();
  }

  async applyPlan(): Promise<ApplyResult> {
    return await this.#driver.applyPlan();
  }

  async createFlowFromPlan(): Promise<ApplyResult> {
    return await this.#driver.createFlowFromPlan();
  }

  async unpublishAndApplyPlan(): Promise<ApplyResult> {
    return await this.#driver.unpublishAndApplyPlan();
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

  async retryModelLoad(): Promise<void> {
    await this.#driver.retryModelLoad();
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
