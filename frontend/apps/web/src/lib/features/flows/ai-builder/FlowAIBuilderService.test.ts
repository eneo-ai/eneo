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
    envelope: {
      spec: {
        flow_name: "Flow",
        flow_description: "",
        steps: [],
        form_fields: null
      },
      assumptions: [],
      lint_warnings: [],
      risk_acknowledgments: []
    },
    ...overrides
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
    intric_error_code: 9007,
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
      intric_error_code: null
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
      isStreaming: true,
      isInitializing: true,
      error,
      applyError,
      applyResult,
      isConflict: true,
      statusMessage: "Working",
      availableModels,
      selectedModelId: "model-1",
      modelsLoaded: true,
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
    expect(service.statusMessage).toBe("Working");
    expect(service.availableModels).toBe(availableModels);
    expect(service.selectedModelId).toBe("model-1");
    expect(service.modelsLoaded).toBe(true);
    expect(service.draftSessions).toBe(draftSessions);
    expect(service.sessionStatus).toBe("awaiting_approval");
  });

  it("exposes Driver-owned state through reactive facade getters", () => {
    const service = makeService();

    expect(service.session).toBeNull();
    expect(service.canSendMessage).toBe(false);

    service.seedState({
      session: makeSession({ status: "chatting" }),
      isStreaming: false
    });

    expect(service.session?.session_id).toBe("session-1");
    expect(service.canSendMessage).toBe(true);

    service.seedState({ isStreaming: true });

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

    service.seedState({ currentPlan: makePlan() });

    expect(service.phase).toBe("reviewing");
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
      isStreaming: true
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
