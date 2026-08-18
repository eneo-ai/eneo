import { createClassContext } from "$lib/core/helpers/createClassContext";
import type { Eneo } from "@eneo/eneo-js";
import type { StructuredQuestionAnswerMetadata } from "./structuredQuestionAnswer";
import {
  FlowAIBuilderDriver,
  type AIBuilderClientTransport,
  type AIBuilderStreamState,
  type CreateFailureOutcome,
  type FlowAIBuilderState,
  type PendingPlanOperationKind
} from "./FlowAIBuilderDriver";
import { classifyAIBuilderConflict, type AIBuilderConflict } from "./aiBuilderConflict";
import type {
  AIBuilderDraftSession,
  AIBuilderError,
  AIBuilderModel,
  AIBuilderEditContext,
  AIBuilderPhase,
  AIBuilderSavedFlowStepScope,
  AIBuilderStepScopePresentation,
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
  #savedFlowStepScope = $state<AIBuilderSavedFlowStepScope | null>(null);
  #suppressedPlanStepScope = $state<{ sessionId: string; planId: string } | null>(null);

  hasSession = $derived(this.#state.session !== null);
  hasSeenPlanInSession = $derived(this.#hasSeenPlanInSession);
  /** True while an atomic plan operation (creation) is running. Every
   *  session-mutating control must render disabled while this holds; the
   *  driver enforces the same lock at its command boundaries. */
  isCreating = $derived(this.#state.pendingOperation?.kind === "creating");
  /** Any plan operation — create, approve, apply, unpublish-and-apply. */
  isBusy = $derived(this.#state.pendingOperation !== null);
  pendingOperationKind: PendingPlanOperationKind | null = $derived(
    this.#state.pendingOperation?.kind ?? null
  );
  /** A change request is rewriting a plan the user is already reviewing.
   *  The review screen dims the plan and locks approval while this holds. */
  isRevisingPlan = $derived(
    this.#state.streamState === "streaming" && this.#state.currentPlan !== null
  );
  /** One conflict classification for the whole builder, so the review screen
   *  renders a single card instead of guessing from raw error codes. */
  conflict: AIBuilderConflict | null = $derived(
    classifyAIBuilderConflict({
      applyError: this.#state.applyError,
      error: this.#state.error,
      isConflict: this.#state.isConflict
    })
  );
  canSendMessage = $derived(
    this.hasSession &&
      this.#state.streamState !== "streaming" &&
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

  get savedFlowStepScope(): AIBuilderSavedFlowStepScope | null {
    return this.#savedFlowStepScope;
  }

  get activeStepScope(): AIBuilderStepScopePresentation | null {
    const context = this.activeStepTransportContext;
    if (
      context?.kind === "proposed_plan" &&
      context.target_step_name &&
      context.target_step_number
    ) {
      return {
        stepName: context.target_step_name,
        stepNumber: context.target_step_number
      };
    }
    return this.#savedFlowStepScope;
  }

  get activeStepTransportContext(): AIBuilderEditContext | null {
    const scope = this.#savedFlowStepScope;
    const plan = this.#state.currentPlan;
    if (plan === null) return scope?.editContext ?? null;
    const suppressedScope = this.#suppressedPlanStepScope;
    if (
      suppressedScope !== null &&
      suppressedScope.sessionId === this.#state.session?.session_id &&
      suppressedScope.planId === plan.plan_id
    ) {
      return null;
    }

    const targetExistingStepRef = plan.proposal.edit?.scoped_target_existing_step_ref;
    const targetPlanStepRef = plan.proposal.edit?.scoped_target_plan_step_ref;
    if (!targetExistingStepRef && !targetPlanStepRef) return scope?.editContext ?? null;
    const targetPlanIndex = plan.proposal.spec.steps.findIndex(
      (step) =>
        (!targetPlanStepRef || step.plan_step_ref === targetPlanStepRef) &&
        (!targetExistingStepRef || step.existing_step_ref === targetExistingStepRef)
    );
    const targetStep = plan.proposal.spec.steps[targetPlanIndex];
    if (!targetStep?.plan_step_ref) {
      // Keep any launch scope rather than silently widening the edit. The
      // backend rejects stale saved-step identity against the current plan.
      return scope?.editContext ?? null;
    }

    return {
      kind: "proposed_plan",
      plan_id: plan.plan_id,
      scope: "step",
      target_existing_step_ref: targetExistingStepRef ?? null,
      target_plan_step_ref: targetPlanStepRef ?? null,
      target_step_name: targetStep.name,
      target_step_number: targetPlanIndex + 1
    };
  }

  setSavedFlowStepScope(scope: AIBuilderSavedFlowStepScope): void {
    this.#suppressedPlanStepScope = null;
    this.#savedFlowStepScope = scope;
  }

  clearSavedFlowStepScope(): void {
    this.#savedFlowStepScope = null;
  }

  clearActiveStepScope(): void {
    this.#savedFlowStepScope = null;
    const sessionId = this.#state.session?.session_id;
    const planId = this.#state.currentPlan?.plan_id;
    this.#suppressedPlanStepScope = sessionId && planId ? { sessionId, planId } : null;
  }

  resetStepScope(): void {
    this.#savedFlowStepScope = null;
    this.#suppressedPlanStepScope = null;
  }

  get isStreaming(): boolean {
    return this.#state.streamState === "streaming";
  }

  get streamState(): AIBuilderStreamState {
    return this.#state.streamState;
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

  /** Assistant prose from the last review turn that produced no new plan. */
  get latestReviewNote(): string | null {
    return this.#state.reviewNote;
  }

  dismissReviewNote(): void {
    this.#driver.dismissReviewNote();
  }

  get statusMessage(): AIBuilderStatus | null {
    return this.#state.statusMessage;
  }

  get availableModels(): AIBuilderModel[] {
    return this.#state.availableModels;
  }

  /** The model the next turn runs on — the override when set, else the server
   *  default. Null until the list arrives; the composer hides its controls
   *  rather than blocking on it. */
  get effectiveModel(): AIBuilderModel | null {
    void this.#state;
    return this.#driver.effectiveModel;
  }

  get hasModelOverride(): boolean {
    return this.#state.selectedModelId !== null;
  }

  get selectedReasoningEffort(): string | null {
    return this.#state.selectedReasoningEffort;
  }

  selectModel(modelId: string): void {
    this.#driver.selectModel(modelId);
  }

  selectReasoningEffort(reasoningEffort: string | null): void {
    this.#driver.selectReasoningEffort(reasoningEffort);
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
    this.clearSavedFlowStepScope();
    await this.#driver.startFreshSession(targetKind);
  }

  async loadDraftSessions(): Promise<void> {
    await this.#driver.loadDraftSessions();
  }

  async resumeSession(sessionId: string): Promise<void> {
    this.clearSavedFlowStepScope();
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
    editContext?: AIBuilderEditContext | null
  ): Promise<AIBuilderSendOutcome> {
    const outcome = await this.#driver.sendMessage(message, questionAnswer, fileIds, editContext);
    if (this.#state.error?.code === "invalid_existing_step_ref") {
      this.clearSavedFlowStepScope();
    }
    return outcome;
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

  async confirmRequirements(editContext?: AIBuilderEditContext | null): Promise<void> {
    await this.#driver.confirmRequirements(editContext ?? null);
  }

  async editNamedContentFields(requirementsVersion: string, fieldNames: string[]): Promise<void> {
    await this.#driver.editNamedContentFields(requirementsVersion, fieldNames);
  }

  async changeRequirements(feedback?: string, topic?: string | null): Promise<void> {
    await this.#driver.changeRequirements(feedback, null, topic);
  }

  async continueEditing(): Promise<void> {
    await this.#driver.continueEditing();
  }

  async removeAttachment(fileId: string): Promise<void> {
    await this.#driver.removeAttachment(fileId);
  }

  /** Whether the transcript replaces the phase screen. It lives here because
   *  the button that opens it can sit outside the builder, in the page header. */
  conversationOpen = $state(false);

  toggleConversation(): void {
    this.conversationOpen = !this.conversationOpen;
  }

  closeConversation(): void {
    this.conversationOpen = false;
  }

  /** Messages worth counting on the Samtal button: the ones a reader sees. */
  visibleMessageCount = $derived(
    this.messages.filter(
      (message) =>
        message.content.trim().length > 0 || message.question || message.requirementsSummary
    ).length
  );

  clearError(): void {
    this.#driver.clearError();
  }

  /** Reload session + plan; the conflict clears only when that succeeds. */
  async recoverFromConflict(): Promise<boolean> {
    return this.#driver.recoverFromConflict();
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
