import type { FlowRunFailureRepairTarget } from "$lib/features/flows/flowRunFailureRepair";

/** The composer's scope with what a send needs and what the chip shows. */
interface AIBuilderStepScopeState extends AIBuilderStepScopePresentation {
  editContext: AIBuilderEditContext | null;
  locked: boolean;
}

/** One identity per projected scope, so a dismissal outlives re-renders of
 *  the same snapshot but not a newer accepted turn. */
function scopeKey(context: AIBuilderEditContext): string {
  return JSON.stringify(context);
}
import { m } from "$lib/paraglide/messages";
import { createClassContext } from "$lib/core/helpers/createClassContext";
import type { Eneo } from "@eneo/eneo-js";
import type { StructuredQuestionAnswerMetadata } from "./structuredQuestionAnswer";
import {
  FlowAIBuilderDriver,
  type AIBuilderClientTransport,
  type AIBuilderModelSendBlock,
  type AIBuilderStreamState,
  type CreateFailureOutcome,
  type FlowAIBuilderState,
  type ModelLoadStatus,
  type PendingPlanOperationKind
} from "./FlowAIBuilderDriver";
import { classifyAIBuilderConflict, type AIBuilderConflict } from "./aiBuilderConflict";
import { parseAIBuilderError } from "./aiBuilderError";
import type { FailureRecoveryCapabilities } from "./aiBuilderFailurePresentation";
import type {
  AIBuilderClientErrorFirstAction,
  AIBuilderClientErrorPresentation,
  AIBuilderClientErrorSurface,
  AIBuilderDraftSession,
  AIBuilderError,
  AIBuilderLatestTurn,
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
  TargetKind,
  AIBuilderFlowReviewState,
  AIBuilderFailureRepairState,
  AIBuilderReviewReference,
  AIBuilderFlowReviewSuggestionsState
} from "./protocol";

export class FlowAIBuilderService {
  #driver: FlowAIBuilderDriver;
  #stateVersion = $state(0);
  #hasSeenPlanInSession = $state(false);
  /** The step the flow editor launched, before its first message is sent.
   *  Bound to the session snapshot it was made against: the next committed
   *  snapshot (a delivered turn read back, a retry reconciled, a plan
   *  operation) retires it in favour of the server's projection. */
  #savedFlowStepScope = $state<{
    sessionId: string | null;
    snapshotVersion: number;
    scope: AIBuilderSavedFlowStepScope;
  } | null>(null);
  /** A dismissed projected scope, for one snapshot of the current session. */
  #dismissedScope = $state<{
    sessionId: string;
    snapshotVersion: number;
    key: string;
  } | null>(null);

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

  get #replayModel(): string | "previous" | null {
    return this.#driver.replayModel;
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

  /** The launch scope, and only while the session it was opened from is the
   *  one on screen.
   *
   *  A scope that outlived its own session would otherwise be sent with the
   *  first message of the session that replaced it. Binding it to the session also means a
   *  replacement that was refused gets its scope back with the session it
   *  never left. */
  get savedFlowStepScope(): AIBuilderSavedFlowStepScope | null {
    const owned = this.#savedFlowStepScope;
    if (owned === null) return null;
    const sessionId = this.#state.session?.session_id ?? null;
    return owned.sessionId === sessionId && owned.snapshotVersion === this.#state.snapshotVersion
      ? owned.scope
      : null;
  }

  /** The scope the server projected from the newest accepted turn, unless
   *  the user dismissed exactly that one. The projection names the step as
   *  it is now and carries the repair restriction; it is what a reload
   *  restores, so nothing here is a second copy of it. */
  get #projectedScope(): AIBuilderStepScopeState | null {
    const session = this.#state.session;
    const projected = session?.edit_scope ?? null;
    if (!session || !projected) return null;
    const dismissed = this.#dismissedScope;
    if (
      dismissed !== null &&
      dismissed.sessionId === session.session_id &&
      dismissed.snapshotVersion === this.#state.snapshotVersion &&
      dismissed.key === scopeKey(projected.context)
    ) {
      return null;
    }
    return {
      editContext: projected.context,
      stepName: projected.step_name?.trim() || m.flow_step_unnamed(),
      stepNumber: projected.step_number,
      locked: projected.preserves_output_contract
    };
  }

  /** The step the next message edits: the editor's unsent launch first, then
   *  the server's projection. The launch is bound to the snapshot it was made
   *  against, so the read-back a scoped turn forces (or any later snapshot)
   *  retires it and the projection names the step as the server resolved it. */
  get #activeScope(): AIBuilderStepScopeState | null {
    const launched = this.savedFlowStepScope;
    if (launched) return { ...launched, locked: false };
    return this.#projectedScope;
  }

  get activeStepScope(): AIBuilderStepScopePresentation | null {
    const scope = this.#activeScope;
    return scope ? { stepName: scope.stepName, stepNumber: scope.stepNumber } : null;
  }

  /** A failure repair keeps the failed step's output contract on every later
   *  turn whatever the composer shows, so its scope cannot be dismissed. */
  get activeStepScopeLocked(): boolean {
    return this.#activeScope?.locked ?? false;
  }

  get activeStepTransportContext(): AIBuilderEditContext | null {
    return this.#activeScope?.editContext ?? null;
  }

  setSavedFlowStepScope(scope: AIBuilderSavedFlowStepScope): void {
    this.#dismissedScope = null;
    this.#savedFlowStepScope = {
      sessionId: this.#state.session?.session_id ?? null,
      snapshotVersion: this.#state.snapshotVersion,
      scope
    };
  }

  clearSavedFlowStepScope(): void {
    this.#savedFlowStepScope = null;
  }

  clearActiveStepScope(): void {
    if (this.activeStepScopeLocked) return;
    this.#savedFlowStepScope = null;
    const session = this.#state.session;
    const projected = session?.edit_scope ?? null;
    this.#dismissedScope =
      session && projected
        ? {
            sessionId: session.session_id,
            snapshotVersion: this.#state.snapshotVersion,
            key: scopeKey(projected.context)
          }
        : null;
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

  /** The model the composer names and a turn runs — the user's choice when
   *  set, else the advertised default. Null when neither is known. */
  get effectiveModel(): AIBuilderModel | null {
    void this.#state;
    return this.#driver.effectiveModel;
  }

  /** Why no turn may start on the model the composer shows, or null. Separate
   *  from `canSendMessage`: typing, attachments and the picker stay usable. */
  get modelSendBlock(): AIBuilderModelSendBlock | null {
    void this.#state;
    return this.#driver.modelSendBlock;
  }

  /** The sentence shown wherever a turn would start, or null when one may. */
  get modelSendBlockMessage(): string | null {
    switch (this.modelSendBlock) {
      case "models_loading":
        return m.ai_builder_models_loading();
      case "models_failed":
        return m.failed_to_load_models();
      case "model_not_listed":
        return m.ai_builder_model_not_listed();
      case "model_capacity_undeclared":
        return m.ai_builder_model_capacity_undeclared();
      case "model_capacity_too_small":
        return m.ai_builder_model_capacity_too_small();
      case "no_ready_model":
        return this.#state.availableModels.length === 0
          ? m.no_completion_model_description()
          : m.ai_builder_no_ready_model();
      case null:
        return null;
    }
  }

  get modelLoadStatus(): ModelLoadStatus {
    return this.#state.modelLoadStatus;
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

  async retryModelLoad(): Promise<void> {
    await this.#driver.retryModelLoad();
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

  forcedCreateRefusedFor(targetKind: TargetKind): boolean {
    void this.#state;
    return this.#driver.forcedCreateRefusedFor(targetKind);
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

  async createSession(targetKind: TargetKind, options?: { forceNew?: boolean }): Promise<boolean> {
    return this.#driver.createSession(targetKind, options);
  }

  async startFreshSession(targetKind: TargetKind): Promise<boolean> {
    return this.#driver.startFreshSession(targetKind);
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

  /** The flow review the user opened from the task screen or run history:
   *  closed, loading, the packet, or the load failure. */
  review: AIBuilderFlowReviewState = $state({ status: "closed" });

  /** Which opened review a pending request belongs to. Opening or closing
   *  starts a new one, so a response that arrives late finds its review gone
   *  and is dropped instead of repopulating a closed or different review. */
  #reviewGeneration = 0;

  async openReview(): Promise<void> {
    const generation = ++this.#reviewGeneration;
    this.review = { status: "loading" };
    this.suggestions = { status: "closed" };
    this.failureRepair = { status: "closed" };
    try {
      const packet = await this.#driver.fetchFlowReviewPacket();
      if (generation !== this.#reviewGeneration) return;
      await this.#driver.openReviewListing(packet.evidence_classification_level);
      if (generation !== this.#reviewGeneration) return;
      this.review = { status: "ready", packet };
    } catch (error) {
      if (generation !== this.#reviewGeneration) return;
      this.review = {
        status: "failed",
        error: parseAIBuilderError({
          transport: "apply",
          payload: error,
          fallbackMessage: m.ai_builder_review_load_failed()
        })
      };
    }
  }

  closeReview(): void {
    this.#reviewGeneration += 1;
    this.review = { status: "closed" };
    this.suggestions = { status: "closed" };
    void this.#driver.closeReviewListing();
  }

  /** The failed step handed over from the run history. It shares the
   *  review's generation: opening either closes the other, and an answer that
   *  arrives after its launch closed is dropped rather than shown. */
  failureRepair: AIBuilderFailureRepairState = $state({ status: "closed" });

  async openFailureRepair(target: FlowRunFailureRepairTarget): Promise<void> {
    const generation = ++this.#reviewGeneration;
    this.review = { status: "closed" };
    this.suggestions = { status: "closed" };
    this.failureRepair = { status: "loading", target };
    try {
      const launch = await this.#driver.fetchRunFailureLaunch(target);
      if (generation !== this.#reviewGeneration) return;
      await this.#driver.openReviewListing(launch.evidence_classification_level);
      if (generation !== this.#reviewGeneration) return;
      this.failureRepair = { status: "ready", launch };
    } catch (error) {
      if (generation !== this.#reviewGeneration) return;
      this.failureRepair = {
        status: "failed",
        target,
        error: parseAIBuilderError({
          transport: "apply",
          payload: error,
          fallbackMessage: m.ai_builder_repair_load_failed()
        })
      };
    }
  }

  closeFailureRepair(): void {
    if (this.failureRepair.status === "closed") return;
    this.#reviewGeneration += 1;
    this.failureRepair = { status: "closed" };
    void this.#driver.closeReviewListing();
  }

  /** The model's judgement over the same runs, asked for on demand from the
   *  review screen; closed with it, never persisted. */
  suggestions: AIBuilderFlowReviewSuggestionsState = $state({ status: "closed" });

  async requestSuggestions(): Promise<void> {
    if (this.modelSendBlock !== null) return;
    const generation = this.#reviewGeneration;
    this.suggestions = { status: "loading" };
    try {
      const suggestions = await this.#driver.fetchFlowReviewSuggestions();
      if (generation !== this.#reviewGeneration) return;
      this.suggestions = { status: "ready", suggestions };
    } catch (error) {
      if (generation !== this.#reviewGeneration) return;
      this.suggestions = {
        status: "failed",
        error: parseAIBuilderError({
          transport: "apply",
          payload: error,
          fallbackMessage: m.ai_builder_review_suggestions_failed()
        })
      };
    }
  }

  async sendMessage(
    message: string,
    questionAnswer?: StructuredQuestionAnswerMetadata,
    fileIds?: string[],
    editContext?: AIBuilderEditContext | null,
    reviewContext?: AIBuilderReviewReference | null
  ): Promise<AIBuilderSendOutcome> {
    const outcome = await this.#driver.sendMessage(
      message,
      questionAnswer,
      fileIds,
      editContext,
      reviewContext
    );
    if (outcome !== "not_started" && reviewContext) {
      if (reviewContext.kind === "run_failure") {
        if (outcome === "delivered") this.closeFailureRepair();
      } else {
        this.closeReview();
      }
    }
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

  async resendLatestTurn(): Promise<AIBuilderSendOutcome> {
    return await this.#driver.resendLatestTurn();
  }

  get latestTurn(): AIBuilderLatestTurn | null {
    return this.#state.session?.latest_turn ?? null;
  }

  /** What the driver allows for the failure on screen. The presentation
   *  owner reads this instead of judging the turn on its own. */
  failureRecoveryCapabilities: FailureRecoveryCapabilities = $derived({
    replay: this.turnRecoveryState,
    canResend:
      this.latestTurn?.retry_request != null &&
      (this.latestTurnState === "committed" || this.latestTurnState === null),
    canStartNewTurn:
      this.#canStartNewTurn &&
      this.#state.streamState !== "streaming" &&
      this.#state.pendingOperation === null,
    turnActive: this.latestTurnState === "open" || this.latestTurnState === "processing",
    replayModel: this.#replayModel
  });

  /** The failure on screen (or the one given) was displayed here. */
  reportFailureDisplayed(
    facts: {
      surface: AIBuilderClientErrorSurface | null;
      presentedAs: AIBuilderClientErrorPresentation | null;
    },
    error?: AIBuilderError
  ): void {
    this.#driver.reportFailureDisplayed(facts, error);
  }

  reportFailureAction(action: AIBuilderClientErrorFirstAction, error?: AIBuilderError): void {
    this.#driver.reportFailureAction(action, error);
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

  async editNamedContentFields(
    requirementsVersion: string,
    fieldNames: string[],
    addedFieldPlacements?: Record<string, string>
  ): Promise<void> {
    await this.#driver.editNamedContentFields(
      requirementsVersion,
      fieldNames,
      addedFieldPlacements
    );
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
  #conversationOpen = $state(false);

  get conversationOpen(): boolean {
    return this.#conversationOpen;
  }

  set conversationOpen(open: boolean) {
    // Opening the transcript while a failure is on screen is the user's way
    // back; the surface that presented the failure records it as such.
    if (open && !this.#conversationOpen) {
      this.#driver.reportFailureAction("conversation_opened");
    }
    this.#conversationOpen = open;
  }

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
