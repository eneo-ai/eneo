import { describe, expect, it, vi } from "vitest";

import { FlowAIBuilderService } from "./FlowAIBuilderService.svelte.ts";
import type {
  AIBuilderDraftSession,
  AIBuilderError,
  AIBuilderModel,
  AIBuilderSession,
  ApplyError,
  ApplyResult,
  ChatMessage,
  ProposedPlan
} from "./protocol";

function makeSession(overrides: Partial<AIBuilderSession> = {}): AIBuilderSession {
  return {
    session_id: "session-1",
    status: "chatting",
    target_kind: "create",
    flow_id: null,
    latest_plan_id: null,
    conversation: [],
    ...overrides
  };
}

function makeDraft(overrides: Partial<AIBuilderDraftSession> = {}): AIBuilderDraftSession {
  return {
    session_id: "draft-1",
    space_id: "space-1",
    status: "chatting",
    target_kind: "create",
    flow_id: null,
    latest_plan_id: null,
    draft_title: "Recovered draft",
    created_at: "2026-03-15T10:00:00Z",
    updated_at: "2026-03-15T10:05:00Z",
    ...overrides
  };
}

function makePlan(overrides: Partial<ProposedPlan> = {}): ProposedPlan {
  return {
    plan_id: "plan-1",
    status: "proposed",
    proposal: {
      spec: {
        flow_name: "Flow",
        flow_description: "",
        steps: [],
        form_fields: null
      },
      assumptions: [],
      lint_warnings: [],
      execution_shape: {
        completion_model_step_count: 0,
        transcription_model_step_count: 0,
        deterministic_step_count: 0,
        schema_constrained_step_count: 0,
        mapped_step_upper_bounds: []
      }
    },
    ...overrides
  };
}

function makeScopedEdit(
  targetExistingStepRef: string | null,
  targetPlanStepRef: string | null = null
): NonNullable<ProposedPlan["proposal"]["edit"]> {
  return {
    base_flow_revision: 1,
    scoped_target_existing_step_ref: targetExistingStepRef,
    scoped_target_plan_step_ref: targetPlanStepRef,
    removed_existing_step_refs: [],
    diff: {
      step_changes: [],
      net_steps_added: 0,
      net_steps_removed: 0,
      flow_property_changes: {}
    }
  };
}

function makeExistingStep(
  stepNumber: number,
  name: string
): ProposedPlan["proposal"]["spec"]["steps"][number] {
  return {
    plan_step_ref: `step_${stepNumber}`,
    existing_step_ref: `existing_step_${stepNumber}`,
    name,
    assistant_spec: {
      instructions: `Instructions for ${name}`,
      model_ref: null,
      knowledge_refs: []
    },
    input_source: stepNumber === 1 ? "flow_input" : "previous_step",
    input_type: "text",
    output_mode: "compose_text",
    output_type: "text",
    input_bindings: null,
    input_contract: null,
    output_contract: null,
    input_config: null,
    output_config: null,
    review_policy: null
  };
}

function makeAIBuilderError(overrides: Partial<AIBuilderError> = {}): AIBuilderError {
  return {
    schema_version: 2,
    code: "invalid_existing_step_ref",
    category: "bad_request",
    message: "Plan changed",
    phase: "router",
    request_id: "req-test",
    eneo_error_code: 9007,
    diagnostic_context: null,
    details: {},
    ...overrides
  };
}

function makeService() {
  return new FlowAIBuilderService(
    {
      client: {
        fetch: vi.fn(),
        stream: vi.fn()
      }
    } as never,
    "space-1",
    null
  );
}

describe("FlowAIBuilderService", () => {
  it("owns and clears the saved-step launch scope", () => {
    const service = makeService();
    const scope = {
      editContext: { kind: "saved_flow_step" as const, flow_step_id: "step-1" },
      stepName: "Extract facts",
      stepNumber: 2
    };

    service.setSavedFlowStepScope(scope);
    expect(service.savedFlowStepScope).toEqual(scope);

    service.clearSavedFlowStepScope();
    expect(service.savedFlowStepScope).toBeNull();
  });

  it("keeps the saved-step scope while its plan is reviewed", () => {
    const service = makeService();
    const scope = {
      editContext: { kind: "saved_flow_step" as const, flow_step_id: "step-1" },
      stepName: "Extract facts",
      stepNumber: 2
    };
    service.setSavedFlowStepScope(scope);

    expect(service.activeStepTransportContext).toEqual(scope.editContext);

    service.seedState({
      currentPlan: makePlan({
        status: "proposed",
        proposal: {
          ...makePlan().proposal,
          edit: makeScopedEdit("existing_step_2", "step_2"),
          spec: {
            ...makePlan().proposal.spec,
            steps: [
              makeExistingStep(1, "Collect source"),
              makeExistingStep(2, "Extract facts"),
              makeExistingStep(3, "Write report")
            ]
          }
        }
      })
    });

    expect(service.savedFlowStepScope).toEqual(scope);
    expect(service.activeStepTransportContext).toEqual({
      kind: "proposed_plan",
      plan_id: "plan-1",
      scope: "step",
      target_existing_step_ref: "existing_step_2",
      target_plan_step_ref: "step_2",
      target_step_name: "Extract facts",
      target_step_number: 2
    });
  });

  it("uses the backend-resolved step identity when order changed before planning", () => {
    const service = makeService();
    service.setSavedFlowStepScope({
      editContext: { kind: "saved_flow_step", flow_step_id: "selected-step-id" },
      stepName: "Originally second",
      stepNumber: 2
    });
    service.seedState({
      currentPlan: makePlan({
        proposal: {
          ...makePlan().proposal,
          edit: makeScopedEdit("existing_step_3", "step_3"),
          spec: {
            ...makePlan().proposal.spec,
            steps: [
              makeExistingStep(1, "First"),
              makeExistingStep(3, "Selected after reorder"),
              makeExistingStep(2, "Moved step")
            ]
          }
        }
      })
    });

    expect(service.activeStepScope).toEqual({
      stepName: "Selected after reorder",
      stepNumber: 2
    });
    expect(service.activeStepTransportContext).toMatchObject({
      kind: "proposed_plan",
      target_existing_step_ref: "existing_step_3",
      target_step_name: "Selected after reorder",
      target_step_number: 2
    });
  });

  it("restores scoped plan transport after a page reload without browser-only scope", () => {
    const service = makeService();
    service.seedState({
      currentPlan: makePlan({
        proposal: {
          ...makePlan().proposal,
          edit: makeScopedEdit("existing_step_2", "step_2"),
          spec: {
            ...makePlan().proposal.spec,
            steps: [makeExistingStep(1, "First"), makeExistingStep(2, "Selected")]
          }
        }
      })
    });

    expect(service.activeStepScope).toEqual({ stepName: "Selected", stepNumber: 2 });
    expect(service.activeStepTransportContext).toMatchObject({
      kind: "proposed_plan",
      target_existing_step_ref: "existing_step_2"
    });
  });

  it("restores proposal-only step scope after reload", () => {
    const service = makeService();
    const addedStep = {
      ...makeExistingStep(2, "New report"),
      existing_step_ref: null
    };
    service.seedState({
      currentPlan: makePlan({
        plan_id: "replacement-plan",
        proposal: {
          ...makePlan().proposal,
          edit: makeScopedEdit(null, "step_2"),
          spec: {
            ...makePlan().proposal.spec,
            steps: [makeExistingStep(1, "First"), addedStep]
          }
        }
      })
    });

    expect(service.activeStepScope).toEqual({ stepName: "New report", stepNumber: 2 });
    expect(service.activeStepTransportContext).toEqual({
      kind: "proposed_plan",
      plan_id: "replacement-plan",
      scope: "step",
      target_existing_step_ref: null,
      target_plan_step_ref: "step_2",
      target_step_name: "New report",
      target_step_number: 2
    });
  });

  it("suppresses persisted step scope only for the current plan", () => {
    const service = makeService();
    const scopedProposal = {
      ...makePlan().proposal,
      edit: makeScopedEdit(null, "step_2"),
      spec: {
        ...makePlan().proposal.spec,
        steps: [
          makeExistingStep(1, "First"),
          { ...makeExistingStep(2, "New report"), existing_step_ref: null }
        ]
      }
    };
    service.seedState({
      session: makeSession({ session_id: "session-1" }),
      currentPlan: makePlan({ plan_id: "plan-1", proposal: scopedProposal })
    });

    service.clearActiveStepScope();
    expect(service.activeStepTransportContext).toBeNull();
    expect(service.activeStepScope).toBeNull();

    service.seedState({
      currentPlan: makePlan({ plan_id: "plan-2", proposal: scopedProposal })
    });
    expect(service.activeStepTransportContext).toMatchObject({
      kind: "proposed_plan",
      plan_id: "plan-2",
      target_plan_step_ref: "step_2"
    });

    service.seedState({
      session: makeSession({ session_id: "session-2" }),
      currentPlan: makePlan({ plan_id: "plan-1", proposal: scopedProposal })
    });
    expect(service.activeStepTransportContext).toMatchObject({
      kind: "proposed_plan",
      plan_id: "plan-1",
      target_plan_step_ref: "step_2"
    });
  });

  it("passes Driver-owned field getters through the reactive facade", () => {
    const service = makeService();
    const session = makeSession({ session_id: "session-2", status: "awaiting_approval" });
    const messages: ChatMessage[] = [
      {
        role: "user",
        content: "Build a summary flow",
        timestamp: 10
      }
    ];
    const currentPlan = makePlan({ status: "approved" });
    const applyError: ApplyError = makeAIBuilderError();
    const error = makeAIBuilderError({
      code: "unknown",
      category: "internal",
      message: "Something failed",
      phase: "client",
      request_id: null,
      eneo_error_code: null
    });
    const applyResult: ApplyResult = {
      flow_id: "flow-1",
      flow_name: "Flow",
      steps_created: 1,
      steps_updated: 2,
      steps_removed: 0
    };
    const availableModels: AIBuilderModel[] = [
      {
        id: "model-1",
        name: "Model",
        provider: "openai"
      }
    ];
    const draftSessions = [makeDraft({ session_id: "draft-2" })];

    service.seedState({
      session,
      messages,
      currentPlan,
      streamState: "streaming",
      isInitializing: true,
      error,
      applyError,
      applyResult,
      isConflict: true,
      statusMessage: "repairing",
      availableModels,
      draftSessions
    });

    expect(service.session).toBe(session);
    expect(service.messages).toBe(messages);
    expect(service.currentPlan).toBe(currentPlan);
    expect(service.isStreaming).toBe(true);
    expect(service.isInitializing).toBe(true);
    expect(service.error).toBe(error);
    expect(service.applyError).toBe(applyError);
    expect(service.applyResult).toBe(applyResult);
    expect(service.isConflict).toBe(true);
    expect(service.statusMessage).toBe("repairing");
    expect(service.availableModels).toBe(availableModels);
    expect(service.draftSessions).toBe(draftSessions);
    expect(service.sessionStatus).toBe("awaiting_approval");
  });

  it("exposes Driver-owned state through reactive facade getters", () => {
    const service = makeService();

    expect(service.session).toBeNull();
    expect(service.canSendMessage).toBe(false);

    service.seedState({
      session: makeSession({ status: "chatting" }),
      streamState: "idle"
    });

    expect(service.session?.session_id).toBe("session-1");
    // The planner model is the server's default; a slow or failed model-name
    // request must never block the first message.
    expect(service.canSendMessage).toBe(true);

    service.seedState({ streamState: "streaming" });

    expect(service.isStreaming).toBe(true);
    expect(service.canSendMessage).toBe(false);
  });

  it("delegates recoverable draft filtering to the Driver state owner", () => {
    const service = makeService();

    service.seedState({
      draftSessions: [
        makeDraft({ session_id: "recoverable" }),
        makeDraft({ session_id: "wrong-space", space_id: "space-2" }),
        makeDraft({ session_id: "applied", status: "applied" }),
        makeDraft({ session_id: "cancelled", status: "cancelled" }),
        makeDraft({ session_id: "edit", target_kind: "edit", flow_id: "flow-1" })
      ]
    });

    expect(service.recoverableCreateDrafts.map((draft) => draft.session_id)).toEqual([
      "recoverable"
    ]);
    expect(service.hasRecoverableCreateDraft).toBe(true);
  });

  it("updates derived phase from Driver-owned messages and plan state", () => {
    const service = makeService();

    expect(service.phase).toBe("discovering");

    service.seedState({
      messages: [
        {
          role: "assistant",
          content: "",
          requirementsSummary: {
            summary: "Build a flow",
            key_decisions: [],
            input_description: "Uploaded files",
            output_description: "Summary",
            requirements_version: "req-1"
          },
          timestamp: 1
        }
      ]
    });

    expect(service.phase).toBe("confirming");

    // A plan can only be reviewed against a confirmed disclosure; an
    // unconfirmed one keeps the builder in confirming even with a plan loaded.
    service.seedState({ currentPlan: makePlan() });
    expect(service.phase).toBe("confirming");

    service.seedState({
      messages: [
        ...service.messages,
        {
          role: "user",
          content: "",
          metadata: { requirements_confirmed: true, requirements_version: "req-1" },
          timestamp: 2
        }
      ]
    });

    expect(service.phase).toBe("reviewing");
  });

  describe("review lifetime", () => {
    function deferred<T>() {
      let resolve!: (value: T) => void;
      let reject!: (reason: unknown) => void;
      const promise = new Promise<T>((res, rej) => {
        resolve = res;
        reject = rej;
      });
      return { promise, resolve, reject };
    }
    const packet = (version: number) => ({
      flow_version: version,
      definition_checksum: `sum-${version}`
    });
    const judged = (version: number) => ({
      flow_version: version,
      definition_checksum: `sum-${version}`,
      suggestions: []
    });
    function makeReviewService() {
      const fetch = vi.fn();
      const service = new FlowAIBuilderService(
        { client: { fetch, stream: vi.fn() } } as never,
        "space-1",
        "flow-1"
      );
      return { service, fetch };
    }

    it("drops a review packet that arrives after the review closed", async () => {
      const { service, fetch } = makeReviewService();
      const pending = deferred<object>();
      fetch.mockReturnValueOnce(pending.promise);

      const opened = service.openReview();
      expect(service.review.status).toBe("loading");
      service.closeReview();
      pending.resolve(packet(1));
      await opened;

      expect(service.review).toEqual({ status: "closed" });
    });

    it("drops suggestions that answer a review that was reopened on another version", async () => {
      const { service, fetch } = makeReviewService();
      const pendingSuggestions = deferred<object>();
      fetch
        .mockResolvedValueOnce(packet(1))
        .mockReturnValueOnce(pendingSuggestions.promise)
        .mockResolvedValueOnce(packet(2));

      await service.openReview();
      const requested = service.requestSuggestions();
      await service.openReview();
      pendingSuggestions.resolve(judged(1));
      await requested;

      expect(service.review).toEqual({ status: "ready", packet: packet(2) });
      expect(service.suggestions).toEqual({ status: "closed" });
    });

    it("drops a suggestions failure that arrives after the review closed", async () => {
      const { service, fetch } = makeReviewService();
      const pendingSuggestions = deferred<object>();
      fetch.mockResolvedValueOnce(packet(1)).mockReturnValueOnce(pendingSuggestions.promise);

      await service.openReview();
      const requested = service.requestSuggestions();
      service.closeReview();
      pendingSuggestions.reject(new Error("late"));
      await requested;

      expect(service.suggestions).toEqual({ status: "closed" });
    });

    it("keeps suggestions that answer the review still open", async () => {
      const { service, fetch } = makeReviewService();
      fetch.mockResolvedValueOnce(packet(1)).mockResolvedValueOnce(judged(1));

      await service.openReview();
      await service.requestSuggestions();

      expect(service.suggestions).toEqual({ status: "ready", suggestions: judged(1) });
    });
  });

  it("keeps the plan-seen latch for transient re-plan streams", () => {
    const service = makeService();

    expect(service.hasSeenPlanInSession).toBe(false);

    service.seedState({
      session: makeSession(),
      currentPlan: makePlan()
    });

    expect(service.hasSeenPlanInSession).toBe(true);

    service.seedState({
      currentPlan: null,
      streamState: "streaming"
    });

    expect(service.hasSeenPlanInSession).toBe(true);
    expect(service.currentPlan).toBeNull();
    expect(service.isStreaming).toBe(true);
  });

  it("resets and re-engages the plan-seen latch across sessions", () => {
    const service = makeService();

    service.seedState({
      session: makeSession(),
      currentPlan: makePlan()
    });

    expect(service.hasSeenPlanInSession).toBe(true);

    service.seedState({
      session: null,
      currentPlan: makePlan()
    });

    expect(service.hasSeenPlanInSession).toBe(false);

    service.seedState({
      session: makeSession({ session_id: "session-2" }),
      currentPlan: makePlan({ plan_id: "plan-2" })
    });

    expect(service.hasSeenPlanInSession).toBe(true);
  });
});
