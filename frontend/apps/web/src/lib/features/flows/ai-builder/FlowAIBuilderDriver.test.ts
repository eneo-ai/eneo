import { describe, expect, it, vi } from "vitest";

import { FlowAIBuilderDriver, type AIBuilderClientTransport } from "./FlowAIBuilderDriver";
import { parseAIBuilderStreamEvent } from "./protocol";
import type {
  AIBuilderConversationMessage,
  AIBuilderDraftSession,
  AIBuilderError,
  AIBuilderSendMessageRequest,
  AIBuilderSession,
  ApplyResult,
  ProposedPlan
} from "./protocol";

function makeSession(overrides: Partial<AIBuilderSession> = {}): AIBuilderSession {
  return {
    session_id: "session-1",
    status: "chatting",
    target_kind: "edit",
    flow_id: "flow-1",
    latest_plan_id: null,
    conversation: [],
    ...overrides
  };
}

function makeRecoverableSession(
  state: "failed_before_provider" | "provider_outcome_unknown"
): AIBuilderSession {
  return makeSession({
    conversation: [
      {
        message_id: "user-turn-1",
        role: "user",
        content: "Build a flow",
        timestamp: "2026-07-10T20:00:00Z"
      }
    ],
    latest_turn: {
      client_turn_id: "11111111-1111-4111-8111-111111111111",
      state,
      user_message_id: "11111111-1111-4111-8111-111111111112",
      error: null,
      requires_duplicate_provider_spend_acknowledgement: state === "provider_outcome_unknown",
      retry_request: {
        client_turn_id: "11111111-1111-4111-8111-111111111111",
        message: "Build a flow",
        model_id: "11111111-1111-4111-8111-111111111113",
        ui_language: "sv",
        acknowledge_duplicate_provider_spend: false
      }
    }
  });
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
      risk_acknowledgments: [],
      description_override_manual: false,
      edit: null
    },
    ...overrides
  };
}

function makeEditApproval(): NonNullable<ProposedPlan["proposal"]["edit"]> {
  return {
    base_flow_revision: 7,
    removed_existing_step_refs: [],
    diff: {
      step_changes: [
        {
          kind: "modified",
          step_name: "Step A",
          step_ref: "existing_step_1",
          details: "output_type -> pdf"
        }
      ],
      net_steps_added: 0,
      net_steps_removed: 0,
      flow_property_changes: {}
    },
    warnings: ["Review before applying."],
    advisories: [
      {
        code: "flow_description_update_required",
        message: "The flow description should be checked.",
        severity: "warning",
        field: null
      }
    ],
    risk_flags: ["type_downgrade"],
    confidence: "needs_review"
  };
}

function makeAIBuilderError(overrides: Partial<AIBuilderError> = {}): AIBuilderError {
  return {
    schema_version: 2,
    code: "unknown",
    category: "internal",
    message: "AI Builder failed",
    phase: "client",
    request_id: null,
    eneo_error_code: null,
    diagnostic_context: null,
    details: {},
    ...overrides
  };
}

function makeDraft(overrides: Partial<AIBuilderDraftSession> = {}): AIBuilderDraftSession {
  return {
    session_id: "draft-1",
    space_id: "space-1",
    status: "chatting",
    target_kind: "edit",
    flow_id: "flow-1",
    latest_plan_id: null,
    draft_title: "Recovered draft",
    created_at: "2026-03-15T10:00:00Z",
    updated_at: "2026-03-15T10:05:00Z",
    ...overrides
  };
}

function makeDriver(
  options: {
    fetchImpl?: ReturnType<typeof vi.fn>;
    streamImpl?: ReturnType<typeof vi.fn>;
  } = {}
) {
  const fetch = options.fetchImpl ?? vi.fn();
  const stream = options.streamImpl ?? vi.fn();

  return {
    driver: new FlowAIBuilderDriver({ fetch, stream }, "space-1", "flow-1"),
    fetch,
    stream
  };
}

function completeStream(handlers: Parameters<AIBuilderClientTransport["stream"]>[2]): void {
  handlers.onMessage?.({ id: "", event: "done", data: "" }, new AbortController());
  handlers.onClose?.();
}

describe("FlowAIBuilderDriver", () => {
  it("keeps stream event contracts derived from generated types", () => {
    const publicRoles = {
      user: true,
      assistant: true
    } satisfies Record<AIBuilderConversationMessage["role"], true>;
    type InternalPublicField = Extract<
      keyof AIBuilderConversationMessage,
      "metadata" | "tool_calls" | "tool_call_id"
    >;
    const publicContractHasNoInternalFields: [InternalPublicField] extends [never] ? true : false =
      true;

    expect(Object.keys(publicRoles)).toEqual(["user", "assistant"]);
    expect(publicContractHasNoInternalFields).toBe(true);
  });

  it("rejects unknown raw stream event names", () => {
    expect(() => parseAIBuilderStreamEvent({ event: "garbage", data: "{}" })).toThrow(
      /Unknown AI Builder stream event/
    );
  });

  it("rejects malformed stream event JSON", () => {
    expect(() => parseAIBuilderStreamEvent({ event: "text", data: "{not json" })).toThrow();
  });

  it("rejects non-empty done event data frames", () => {
    expect(() => parseAIBuilderStreamEvent({ event: "done", data: "{}" })).toThrow(
      /empty data frame/
    );
  });

  it("resets confirmation phase when the user changes requirements after confirming", async () => {
    const { driver } = makeDriver();
    driver.seedState({
      messages: [
        {
          role: "assistant",
          content: "",
          requirementsSummary: {
            summary: "Build a DOCX flow",
            key_decisions: [{ topic: "DOCX", decision: "Without template" }],
            input_description: "PDF upload",
            output_description: "DOCX report",
            requirements_version: "req-v1"
          },
          timestamp: 1
        },
        {
          role: "user",
          content: "Ja, det stämmer. Bygg planen.",
          metadata: { requirements_confirmed: true, requirements_version: "req-v1" },
          timestamp: 2
        },
        {
          role: "user",
          content: "Jag vill ändra till en PDF i taget.",
          timestamp: 3
        }
      ]
    });

    expect(driver.derivePhase()).toBe("confirming");
  });

  it("tracks answered structured questions from question metadata instead of message position", async () => {
    const { driver } = makeDriver();
    const question = {
      question_id: "input_mode",
      question: "What input should the flow accept?",
      options: [{ label: "Documents", id: "documents" }],
      selection_mode: "single" as const,
      allow_custom: true
    };
    driver.seedState({
      messages: [
        {
          role: "assistant",
          content: "",
          question,
          timestamp: 1
        },
        {
          role: "user",
          content: "Documents",
          questionAnswer: {
            question_id: "input_mode",
            selected_option_ids: ["documents"]
          },
          timestamp: 2
        }
      ]
    });

    expect(driver.isQuestionAnswered("input_mode")).toBe(true);
    expect(driver.isQuestionAnswered("output_mode")).toBe(false);
  });

  it("only treats the latest requirements summary as active", async () => {
    const { driver } = makeDriver();
    const oldSummary = {
      summary: "Old summary",
      key_decisions: [],
      input_description: "Old input",
      output_description: "Old output",
      requirements_version: "req-old"
    };
    const newSummary = {
      summary: "New summary",
      key_decisions: [],
      input_description: "New input",
      output_description: "New output",
      requirements_version: "req-new"
    };

    driver.seedState({
      messages: [
        { role: "assistant", content: "", requirementsSummary: oldSummary, timestamp: 1 },
        { role: "assistant", content: "", requirementsSummary: newSummary, timestamp: 2 }
      ]
    });

    expect(driver.isLatestRequirementsSummary(oldSummary)).toBe(false);
    expect(driver.isLatestRequirementsSummary(newSummary)).toBe(true);
  });

  it("confirms a hydrated requirements summary whose version is stored on metadata", async () => {
    const { driver, stream } = makeDriver({
      streamImpl: vi.fn(async (_path, init, handlers) => {
        expect(init.requestBody["application/json"].question_answer).toEqual({
          kind: "requirements_confirmation",
          requirements_confirmed: true,
          requirements_version: "req-persisted"
        });
        completeStream(handlers);
      })
    });
    driver.seedState({
      session: makeSession(),
      messages: [
        {
          role: "assistant",
          content: "Jag har tillräckligt med information.",
          requirementsSummary: {
            summary: "Bygg ett dokumentflöde",
            key_decisions: [],
            input_description: "PDF-filer",
            output_description: "DOCX-rapport",
            requirements_version: "req-persisted"
          },
          timestamp: 1
        }
      ]
    });

    await driver.confirmRequirements();

    expect(stream).toHaveBeenCalledOnce();
    expect(driver.state.messages[1]).toMatchObject({
      role: "user",
      metadata: {
        requirements_confirmed: true,
        requirements_version: "req-persisted"
      }
    });
  });

  it("initializes create mode by waiting for an explicit choice when a matching draft exists", async () => {
    const draft = makeDraft({ target_kind: "create", flow_id: null });
    const fetch = vi.fn().mockResolvedValueOnce({ sessions: [draft] });
    const { driver } = makeDriver({ fetchImpl: fetch });

    await driver.initialize("create");

    expect(driver.state.session).toBeNull();
    expect(driver.state.draftSessions).toEqual([draft]);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch).toHaveBeenCalledWith("/api/v1/flows/ai-builder/sessions", {
      method: "get"
    });
  });

  it("initializes create mode by creating a fresh session when there is no matching draft", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce({ sessions: [] })
      .mockResolvedValueOnce(
        makeSession({ session_id: "create-1", target_kind: "create", flow_id: null })
      )
      .mockResolvedValueOnce({ models: [], default_model_id: null })
      .mockResolvedValueOnce(
        makeSession({ session_id: "create-1", target_kind: "create", flow_id: null })
      )
      .mockResolvedValueOnce({ sessions: [] });
    const { driver } = makeDriver({ fetchImpl: fetch });

    await driver.initialize("create");

    expect(driver.state.session?.session_id).toBe("create-1");
    expect(fetch.mock.calls[1]?.[0]).toBe("/api/v1/flows/ai-builder/sessions");
  });

  it("initializes edit mode by creating or resuming the session immediately", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce({ sessions: [makeDraft()] })
      .mockResolvedValueOnce(
        makeSession({
          session_id: "session-2",
          latest_plan_id: "plan-9",
          status: "awaiting_approval"
        })
      )
      .mockResolvedValueOnce({ models: [], default_model_id: null })
      .mockResolvedValueOnce(
        makeSession({
          session_id: "session-2",
          latest_plan_id: "plan-9",
          status: "awaiting_approval"
        })
      )
      .mockResolvedValueOnce(makePlan({ plan_id: "plan-9", status: "approved" }))
      .mockResolvedValueOnce({
        sessions: [makeDraft({ session_id: "session-2", latest_plan_id: "plan-9" })]
      });
    const { driver } = makeDriver({ fetchImpl: fetch });

    await driver.initialize("edit");

    expect(driver.state.session?.session_id).toBe("session-2");
    expect(driver.state.currentPlan?.plan_id).toBe("plan-9");
  });

  it("loads draft sessions and keeps them in state", async () => {
    const fetch = vi.fn().mockResolvedValueOnce({ sessions: [makeDraft()] });
    const { driver } = makeDriver({ fetchImpl: fetch });

    await driver.loadDraftSessions();

    expect(driver.state.draftSessions).toEqual([makeDraft()]);
  });

  it("reuses edit session creation as resume-first and refreshes recovered plan state", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(
        makeSession({
          session_id: "session-2",
          latest_plan_id: "plan-9",
          status: "awaiting_approval"
        })
      )
      .mockResolvedValueOnce({ models: [], default_model_id: null })
      .mockResolvedValueOnce(
        makeSession({
          session_id: "session-2",
          latest_plan_id: "plan-9",
          status: "awaiting_approval"
        })
      )
      .mockResolvedValueOnce(makePlan({ plan_id: "plan-9", status: "approved" }))
      .mockResolvedValueOnce({
        sessions: [makeDraft({ session_id: "session-2", latest_plan_id: "plan-9" })]
      });
    const { driver } = makeDriver({ fetchImpl: fetch });

    await driver.createSession("edit");

    expect(driver.state.session?.session_id).toBe("session-2");
    expect(driver.state.currentPlan?.plan_id).toBe("plan-9");
    expect(driver.state.draftSessions[0]?.session_id).toBe("session-2");
  });

  it("can discard a draft session and clears it from state", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(makeSession({ session_id: "draft-1", status: "cancelled" }))
      .mockResolvedValueOnce({ sessions: [] });
    const { driver } = makeDriver({ fetchImpl: fetch });
    driver.seedState({
      session: makeSession({ session_id: "draft-1" }),
      draftSessions: [makeDraft({ session_id: "draft-1" })]
    });

    await driver.discardSession("draft-1");

    expect(driver.state.session).toBeNull();
    expect(driver.state.draftSessions).toEqual([]);
  });

  it("starts a fresh session by forcing a new draft", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(makeSession({ session_id: "session-fresh", latest_plan_id: null }))
      .mockResolvedValueOnce({ models: [], default_model_id: null })
      .mockResolvedValueOnce(makeSession({ session_id: "session-fresh", latest_plan_id: null }))
      .mockResolvedValueOnce({ sessions: [makeDraft({ session_id: "session-fresh" })] });
    const { driver } = makeDriver({ fetchImpl: fetch });

    await driver.startFreshSession("edit");

    const createCall = fetch.mock.calls[0];
    expect(createCall?.[0]).toBe("/api/v1/flows/ai-builder/sessions");
    expect(createCall?.[1]?.requestBody["application/json"].force_new).toBe(true);
  });

  it("clears stale local chat and plan state when starting a fresh edit session", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(
        makeSession({
          session_id: "session-fresh",
          latest_plan_id: null,
          conversation: []
        })
      )
      .mockResolvedValueOnce({ models: [], default_model_id: null })
      .mockResolvedValueOnce(
        makeSession({
          session_id: "session-fresh",
          latest_plan_id: null,
          conversation: []
        })
      )
      .mockResolvedValueOnce({ sessions: [makeDraft({ session_id: "session-fresh" })] });
    const { driver } = makeDriver({ fetchImpl: fetch });
    driver.seedState({
      session: makeSession({ session_id: "session-old", latest_plan_id: "plan-old" }),
      messages: [{ role: "assistant", content: "Old conversation", timestamp: 1 }],
      currentPlan: makePlan({ plan_id: "plan-old" }),
      error: makeAIBuilderError({ message: "Old error" }),
      statusMessage: "architecture_revised",
      applyResult: {
        flow_id: "flow-1",
        flow_name: "Old flow",
        steps_created: 1,
        steps_updated: 0,
        steps_removed: 0
      }
    });

    await driver.startFreshSession("edit");

    expect(driver.state.session?.session_id).toBe("session-fresh");
    expect(driver.state.messages).toEqual([]);
    expect(driver.state.currentPlan).toBeNull();
    expect(driver.state.error).toBeNull();
    expect(driver.state.statusMessage).toBeNull();
    expect(driver.state.applyResult).toBeNull();
  });

  it("wires AbortController for streaming and treats abort as a non-error", async () => {
    let capturedAbortController: AbortController | undefined;
    const { driver, stream } = makeDriver({
      streamImpl: vi.fn((_path, _init, _handlers, abortController?: AbortController) => {
        capturedAbortController = abortController;
        return new Promise<void>((resolve) => {
          abortController?.signal.addEventListener("abort", () => resolve(), { once: true });
        });
      })
    });
    driver.seedState({ session: makeSession() });

    const pending = driver.sendMessage("Build a flow");
    expect(driver.state.isStreaming).toBe(true);

    driver.abort();
    await pending;

    expect(stream).toHaveBeenCalledOnce();
    expect(capturedAbortController).toBeInstanceOf(AbortController);
    expect(capturedAbortController?.signal.aborted).toBe(true);
    expect(driver.state.isStreaming).toBe(false);
    expect(driver.state.error).toBeNull();
  });

  it("retries a pre-provider failure with the exact persisted turn request", async () => {
    const session = makeRecoverableSession("failed_before_provider");
    const latestTurn = session.latest_turn;
    if (!latestTurn) throw new Error("Expected recoverable latest turn");
    const { driver, stream } = makeDriver({
      fetchImpl: vi.fn().mockResolvedValue({
        ...session,
        latest_turn: { ...latestTurn, state: "committed" }
      }),
      streamImpl: vi.fn(async (_path, _init, handlers) => {
        completeStream(handlers);
      })
    });
    driver.seedState({
      session,
      messages: [{ role: "user", content: "Build a flow", timestamp: 1 }]
    });

    await driver.retryLatestTurn();

    expect(driver.turnRecoveryState).toBeNull();
    expect(stream).toHaveBeenCalledWith(
      "/api/v1/flows/ai-builder/sessions/{session_id}/messages",
      expect.objectContaining({
        requestBody: {
          "application/json": {
            ...session.latest_turn?.retry_request,
            acknowledge_duplicate_provider_spend: false
          }
        }
      }),
      expect.any(Object),
      expect.any(AbortController)
    );
    expect(driver.state.messages).toHaveLength(1);
  });

  it("requires the named acknowledgement path for an unknown provider outcome", async () => {
    const session = makeRecoverableSession("provider_outcome_unknown");
    const { driver, stream } = makeDriver({
      streamImpl: vi.fn(async (_path, _init, handlers) => {
        completeStream(handlers);
      })
    });
    driver.seedState({
      session,
      messages: [{ role: "user", content: "Build a flow", timestamp: 1 }]
    });

    await driver.retryLatestTurn();
    expect(stream).not.toHaveBeenCalled();

    await driver.acknowledgeAndRetryLatestTurn();

    expect(stream).toHaveBeenCalledOnce();
    expect(stream.mock.calls[0]?.[1].requestBody["application/json"]).toEqual({
      ...session.latest_turn?.retry_request,
      acknowledge_duplicate_provider_spend: true
    });
    expect(driver.state.messages).toHaveLength(1);
  });

  it("prevents concurrent retry transport calls", async () => {
    let finishStream: (() => void) | undefined;
    const { driver, stream } = makeDriver({
      streamImpl: vi.fn(
        () =>
          new Promise<void>((resolve) => {
            finishStream = resolve;
          })
      )
    });
    driver.seedState({ session: makeRecoverableSession("failed_before_provider") });

    const firstRetry = driver.retryLatestTurn();
    const secondRetry = driver.retryLatestTurn();

    expect(stream).toHaveBeenCalledOnce();
    finishStream?.();
    await Promise.all([firstRetry, secondRetry]);
  });

  it("blocks another retry until the completed retry is authoritatively refreshed", async () => {
    const session = makeRecoverableSession("failed_before_provider");
    const latestTurn = session.latest_turn;
    if (!latestTurn) throw new Error("Expected recoverable latest turn");
    const fetchSession = vi
      .fn()
      .mockRejectedValueOnce(new Error("session refresh unavailable"))
      .mockResolvedValueOnce({
        ...session,
        latest_turn: { ...latestTurn, state: "committed" }
      });
    const { driver, stream } = makeDriver({
      fetchImpl: fetchSession,
      streamImpl: vi.fn(async (_path, _init, handlers) => {
        completeStream(handlers);
      })
    });
    driver.seedState({ session });

    await driver.retryLatestTurn();
    expect(driver.state.error).not.toBeNull();

    await driver.retryLatestTurn();

    expect(stream).toHaveBeenCalledOnce();
    expect(fetchSession).toHaveBeenCalledTimes(2);
    expect(driver.turnRecoveryState).toBeNull();
    expect(driver.state.error).toBeNull();
  });

  it("serializes a delayed recovery refresh before retrying provider work", async () => {
    const session = makeRecoverableSession("failed_before_provider");
    const latestTurn = session.latest_turn;
    if (!latestTurn) throw new Error("Expected recoverable latest turn");
    const delayedPreflight = Promise.withResolvers<AIBuilderSession>();
    const committedSession = {
      ...session,
      latest_turn: { ...latestTurn, state: "committed" as const }
    };
    const fetchSession = vi
      .fn()
      .mockRejectedValueOnce(new Error("session refresh unavailable"))
      .mockReturnValueOnce(delayedPreflight.promise)
      .mockResolvedValueOnce(committedSession);
    const { driver, stream } = makeDriver({
      fetchImpl: fetchSession,
      streamImpl: vi.fn(async (_path, _init, handlers) => {
        completeStream(handlers);
      })
    });
    driver.seedState({ session });

    await driver.retryLatestTurn();
    const firstRecovery = driver.retryLatestTurn();
    const concurrentRecovery = driver.retryLatestTurn();

    expect(fetchSession).toHaveBeenCalledTimes(2);
    expect(driver.isRecoveringLatestTurn).toBe(true);
    delayedPreflight.resolve(session);
    await Promise.all([firstRecovery, concurrentRecovery]);

    expect(fetchSession).toHaveBeenCalledTimes(3);
    expect(stream).toHaveBeenCalledTimes(2);
    expect(driver.latestTurnState).toBe("committed");
    expect(driver.isRecoveringLatestTurn).toBe(false);
  });

  it("keeps late stream callbacks and finalization owned by their original session", async () => {
    const oldSession = makeSession({ session_id: "session-old" });
    const newSession = makeSession({ session_id: "session-new" });
    const streamHandlers: Parameters<AIBuilderClientTransport["stream"]>[2][] = [];
    const streamControllers: AbortController[] = [];
    const finishStreams: Array<() => void> = [];
    const fetch = vi.fn(async (path: string, init?: { method?: string }) => {
      if (path === "/api/v1/flows/ai-builder/sessions/{session_id}") {
        return newSession;
      }
      if (path.endsWith("/models")) {
        return { models: [], default_model_id: null };
      }
      if (path === "/api/v1/flows/ai-builder/sessions" && init?.method === "get") {
        return { sessions: [] };
      }
      throw new Error(`Unexpected fetch: ${path}`);
    });
    const { driver, stream } = makeDriver({
      fetchImpl: fetch,
      streamImpl: vi.fn(
        (
          _path,
          _init,
          handlers: Parameters<AIBuilderClientTransport["stream"]>[2],
          abortController?: AbortController
        ) =>
          new Promise<void>((resolve) => {
            streamHandlers.push(handlers);
            if (abortController) {
              streamControllers.push(abortController);
            }
            finishStreams.push(resolve);
          })
      )
    });
    driver.seedState({ session: oldSession });

    const oldSend = driver.sendMessage("Old session request");
    await driver.resumeSession(newSession.session_id);
    const currentSend = driver.sendMessage("Current session request");
    const oldStreamHandlers = streamHandlers[0];
    const oldStreamController = streamControllers[0];
    const currentStreamHandlers = streamHandlers[1];
    const currentStreamController = streamControllers[1];
    if (
      !oldStreamHandlers?.onMessage ||
      !oldStreamHandlers.onClose ||
      !oldStreamController ||
      !currentStreamHandlers ||
      !currentStreamController
    ) {
      throw new Error("Expected controlled old and current stream operations");
    }

    oldStreamHandlers.onMessage(
      {
        id: "old-text",
        event: "text",
        data: JSON.stringify({ text: "Late old-session text" })
      },
      oldStreamController
    );
    oldStreamHandlers.onMessage(
      {
        id: "old-plan",
        event: "plan",
        data: JSON.stringify(makePlan({ plan_id: "plan-old" }))
      },
      oldStreamController
    );
    oldStreamHandlers.onMessage(
      {
        id: "old-usage",
        event: "usage",
        data: JSON.stringify({ total_tokens_total: 999 })
      },
      oldStreamController
    );
    oldStreamHandlers.onMessage(
      {
        id: "old-error",
        event: "error",
        data: JSON.stringify({
          schema_version: 2,
          code: "planner_stream_failed",
          category: "internal",
          message: "Late old-session error",
          phase: "router",
          request_id: "old-request",
          eneo_error_code: 9024
        })
      },
      oldStreamController
    );
    oldStreamHandlers.onMessage(
      {
        id: "old-status",
        event: "status",
        data: JSON.stringify({ status: "architecture_committed" })
      },
      oldStreamController
    );
    oldStreamHandlers.onClose();
    finishStreams[0]?.();
    await oldSend;

    const stateAfterOldStream = {
      sessionId: driver.state.session?.session_id,
      messages: driver.state.messages.map(({ role, content }) => ({ role, content })),
      planId: driver.state.currentPlan?.plan_id ?? null,
      statusMessage: driver.state.statusMessage,
      errorCode: driver.state.error?.code ?? null,
      totalTokens: driver.state.session?.telemetry?.total_tokens_total ?? null,
      isStreaming: driver.state.isStreaming,
      currentControllerAborted: currentStreamController.signal.aborted
    };

    const thirdSend = driver.sendMessage("Must stay blocked while session B streams");
    const streamCallsWhileCurrentSendIsActive = stream.mock.calls.length;

    if (streamHandlers[2]) {
      completeStream(streamHandlers[2]);
      finishStreams[2]?.();
    }
    await thirdSend;
    completeStream(currentStreamHandlers);
    finishStreams[1]?.();
    await currentSend;

    expect(stateAfterOldStream).toEqual({
      sessionId: "session-new",
      messages: [{ role: "user", content: "Current session request" }],
      planId: null,
      statusMessage: null,
      errorCode: null,
      totalTokens: null,
      isStreaming: true,
      currentControllerAborted: false
    });
    expect(streamCallsWhileCurrentSendIsActive).toBe(2);
  });

  it("ignores a delayed refresh response after the session is replaced", async () => {
    const oldSession = makeRecoverableSession("failed_before_provider");
    const newSession = makeSession({ session_id: "session-2" });
    const delayedOldRefresh = Promise.withResolvers<AIBuilderSession>();
    const fetchSession = vi
      .fn()
      .mockReturnValueOnce(delayedOldRefresh.promise)
      .mockResolvedValueOnce(newSession)
      .mockResolvedValueOnce({ models: [], default_model_id: null })
      .mockResolvedValueOnce({ sessions: [] });
    const { driver } = makeDriver({ fetchImpl: fetchSession });
    driver.seedState({ session: oldSession });

    const oldRefresh = driver.refreshSession();
    await driver.resumeSession(newSession.session_id);
    delayedOldRefresh.resolve(oldSession);

    expect(await oldRefresh).toBe(false);
    expect(driver.state.session?.session_id).toBe(newSession.session_id);
    expect(driver.latestTurnState).toBeNull();
  });

  it("ignores a delayed plan response after the session is replaced", async () => {
    const oldSession = makeSession({
      session_id: "session-old",
      latest_plan_id: "plan-old"
    });
    const newSession = makeSession({ session_id: "session-new", latest_plan_id: null });
    const delayedOldPlan = Promise.withResolvers<ProposedPlan>();
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(oldSession)
      .mockReturnValueOnce(delayedOldPlan.promise)
      .mockResolvedValueOnce(newSession)
      .mockResolvedValueOnce({ models: [], default_model_id: null })
      .mockResolvedValueOnce({ sessions: [] });
    const { driver } = makeDriver({ fetchImpl: fetch });
    driver.seedState({ session: oldSession });

    const oldRefresh = driver.refreshSession();
    await Promise.resolve();
    await Promise.resolve();
    expect(fetch).toHaveBeenCalledTimes(2);

    await driver.resumeSession(newSession.session_id);
    delayedOldPlan.resolve(makePlan({ plan_id: "plan-old" }));

    expect(await oldRefresh).toBe(false);
    expect(driver.state.session?.session_id).toBe(newSession.session_id);
    expect(driver.state.currentPlan).toBeNull();
  });

  it("lets only the newest overlapping resume install session state", async () => {
    const oldSession = makeSession({ session_id: "session-old" });
    const newSession = makeSession({ session_id: "session-new" });
    const delayedOldResume = Promise.withResolvers<AIBuilderSession>();
    const delayedNewResume = Promise.withResolvers<AIBuilderSession>();
    const fetch = vi
      .fn()
      .mockReturnValueOnce(delayedOldResume.promise)
      .mockReturnValueOnce(delayedNewResume.promise)
      .mockResolvedValueOnce({ models: [], default_model_id: null })
      .mockResolvedValueOnce({ sessions: [] })
      .mockResolvedValueOnce({ models: [], default_model_id: null })
      .mockResolvedValueOnce({ sessions: [] });
    const { driver } = makeDriver({ fetchImpl: fetch });

    const oldResume = driver.resumeSession(oldSession.session_id);
    const newResume = driver.resumeSession(newSession.session_id);
    delayedNewResume.resolve(newSession);
    await Promise.resolve();
    await Promise.resolve();
    delayedOldResume.resolve(oldSession);
    await Promise.all([oldResume, newResume]);

    expect(driver.state.session?.session_id).toBe(newSession.session_id);
    expect(fetch).toHaveBeenCalledTimes(4);
  });

  it("settles a failed resume quietly after a replacement session takes ownership", async () => {
    const oldSession = makeSession({ session_id: "session-old" });
    const replacementSession = makeSession({ session_id: "session-replacement" });
    const delayedOldResume = Promise.withResolvers<AIBuilderSession>();
    const delayedReplacementResume = Promise.withResolvers<AIBuilderSession>();
    const fetch = vi
      .fn()
      .mockReturnValueOnce(delayedOldResume.promise)
      .mockReturnValueOnce(delayedReplacementResume.promise)
      .mockResolvedValueOnce({ models: [], default_model_id: null })
      .mockResolvedValueOnce({ sessions: [] });
    const { driver } = makeDriver({ fetchImpl: fetch });

    const oldResume = driver.resumeSession(oldSession.session_id);
    const staleResumeSettlement = expect(oldResume).resolves.toBeUndefined();
    const replacementResume = driver.resumeSession(replacementSession.session_id);
    delayedReplacementResume.resolve(replacementSession);
    await replacementResume;
    delayedOldResume.reject(new Error("obsolete session unavailable"));

    await staleResumeSettlement;
    expect(driver.state.session).toEqual(replacementSession);
    expect(driver.state.error).toBeNull();
  });

  it("keeps a current resume failure explicit to its caller", async () => {
    const fetchError = new Error("current session unavailable");
    const { driver } = makeDriver({
      fetchImpl: vi.fn().mockRejectedValueOnce(fetchError)
    });

    await expect(driver.resumeSession("session-current")).rejects.toBe(fetchError);

    expect(driver.state.session).toBeNull();
    expect(driver.state.error).toBeNull();
  });

  it("does not let a delayed create replace a subsequently resumed session", async () => {
    const createdSession = makeSession({ session_id: "session-created" });
    const resumedSession = makeSession({ session_id: "session-resumed" });
    const delayedCreate = Promise.withResolvers<AIBuilderSession>();
    const delayedResume = Promise.withResolvers<AIBuilderSession>();
    const fetch = vi
      .fn()
      .mockReturnValueOnce(delayedCreate.promise)
      .mockReturnValueOnce(delayedResume.promise)
      .mockResolvedValueOnce({ models: [], default_model_id: null })
      .mockResolvedValueOnce({ sessions: [] })
      .mockResolvedValueOnce({ models: [], default_model_id: null })
      .mockResolvedValueOnce(createdSession)
      .mockResolvedValueOnce({ sessions: [] });
    const { driver } = makeDriver({ fetchImpl: fetch });

    const create = driver.createSession("create");
    const resume = driver.resumeSession(resumedSession.session_id);
    delayedResume.resolve(resumedSession);
    await Promise.resolve();
    await Promise.resolve();
    delayedCreate.resolve(createdSession);
    await Promise.all([create, resume]);

    expect(driver.state.session?.session_id).toBe(resumedSession.session_id);
    expect(fetch).toHaveBeenCalledTimes(4);
  });

  it("ignores a delayed draft list from the previous session generation", async () => {
    const resumedSession = makeSession({ session_id: "session-resumed" });
    const oldDraft = makeDraft({ session_id: "draft-old" });
    const currentDraft = makeDraft({ session_id: "draft-current" });
    const delayedOldDrafts = Promise.withResolvers<{ sessions: AIBuilderDraftSession[] }>();
    const fetch = vi
      .fn()
      .mockReturnValueOnce(delayedOldDrafts.promise)
      .mockResolvedValueOnce(resumedSession)
      .mockResolvedValueOnce({ models: [], default_model_id: null })
      .mockResolvedValueOnce({ sessions: [currentDraft] });
    const { driver } = makeDriver({ fetchImpl: fetch });

    const oldDraftLoad = driver.loadDraftSessions();
    await driver.resumeSession(resumedSession.session_id);
    delayedOldDrafts.resolve({ sessions: [oldDraft] });
    await oldDraftLoad;

    expect(driver.state.draftSessions).toEqual([currentDraft]);
  });

  it("does not apply a delayed approval result to a replacement session", async () => {
    const oldPlan = makePlan({ plan_id: "plan-old" });
    const currentPlan = makePlan({ plan_id: "plan-current" });
    const currentSession = makeSession({
      session_id: "session-current",
      latest_plan_id: currentPlan.plan_id
    });
    const delayedApproval = Promise.withResolvers<void>();
    const fetch = vi
      .fn()
      .mockReturnValueOnce(delayedApproval.promise)
      .mockResolvedValueOnce(currentSession)
      .mockResolvedValueOnce({ models: [], default_model_id: null })
      .mockResolvedValueOnce(currentPlan)
      .mockResolvedValueOnce({ sessions: [] });
    const { driver } = makeDriver({ fetchImpl: fetch });
    driver.seedState({
      session: makeSession({ session_id: "session-old", latest_plan_id: oldPlan.plan_id }),
      currentPlan: oldPlan
    });

    const approval = driver.approvePlan();
    await driver.resumeSession(currentSession.session_id);
    delayedApproval.resolve();
    await approval;

    expect(driver.state.session?.session_id).toBe(currentSession.session_id);
    expect(driver.state.currentPlan).toEqual(currentPlan);
    expect(driver.state.error).toBeNull();
  });

  it("does not return or apply a delayed apply result for a replacement session", async () => {
    const oldPlan = makePlan({ plan_id: "plan-old" });
    const currentPlan = makePlan({ plan_id: "plan-current" });
    const currentSession = makeSession({
      session_id: "session-current",
      flow_id: "flow-current",
      latest_plan_id: currentPlan.plan_id
    });
    const delayedApply = Promise.withResolvers<ApplyResult>();
    const fetch = vi
      .fn()
      .mockReturnValueOnce(delayedApply.promise)
      .mockResolvedValueOnce(currentSession)
      .mockResolvedValueOnce({ models: [], default_model_id: null })
      .mockResolvedValueOnce(currentPlan)
      .mockResolvedValueOnce({ sessions: [] })
      .mockResolvedValueOnce(currentSession)
      .mockResolvedValueOnce(currentPlan);
    const { driver } = makeDriver({ fetchImpl: fetch });
    driver.seedState({
      session: makeSession({ session_id: "session-old", latest_plan_id: oldPlan.plan_id }),
      currentPlan: oldPlan
    });

    const apply = driver.applyPlan();
    await driver.resumeSession(currentSession.session_id);
    delayedApply.resolve({
      flow_id: "flow-old",
      flow_name: "Old flow",
      steps_created: 1,
      steps_updated: 0,
      steps_removed: 0
    });

    await expect(apply).rejects.toMatchObject({ name: "AbortError" });
    expect(driver.state.session).toEqual(currentSession);
    expect(driver.state.currentPlan).toEqual(currentPlan);
    expect(driver.state.applyResult).toBeNull();
    expect(driver.state.applyError).toBeNull();
    expect(driver.state.error).toBeNull();
  });

  it("does not apply the replacement plan after a delayed unpublish", async () => {
    const oldPlan = makePlan({ plan_id: "plan-old" });
    const currentPlan = makePlan({ plan_id: "plan-current" });
    const currentSession = makeSession({
      session_id: "session-current",
      flow_id: "flow-current",
      latest_plan_id: currentPlan.plan_id
    });
    const delayedUnpublish = Promise.withResolvers<void>();
    const fetch = vi
      .fn()
      .mockReturnValueOnce(delayedUnpublish.promise)
      .mockResolvedValueOnce(currentSession)
      .mockResolvedValueOnce({ models: [], default_model_id: null })
      .mockResolvedValueOnce(currentPlan)
      .mockResolvedValueOnce({ sessions: [] })
      .mockResolvedValueOnce({ flow_id: "flow-current", revision: 3 })
      .mockResolvedValueOnce(currentSession)
      .mockResolvedValueOnce(currentPlan);
    const { driver } = makeDriver({ fetchImpl: fetch });
    driver.seedState({
      session: makeSession({
        session_id: "session-old",
        flow_id: "flow-old",
        latest_plan_id: oldPlan.plan_id
      }),
      currentPlan: oldPlan
    });

    const unpublishAndApply = driver.unpublishAndApplyPlan();
    await driver.resumeSession(currentSession.session_id);
    delayedUnpublish.resolve();

    await expect(unpublishAndApply).rejects.toMatchObject({ name: "AbortError" });
    expect(
      fetch.mock.calls.filter(([path]) => path === "/api/v1/flows/ai-builder/plans/{plan_id}/apply")
    ).toHaveLength(0);
    expect(driver.state.session).toEqual(currentSession);
    expect(driver.state.currentPlan).toEqual(currentPlan);
    expect(driver.state.applyError).toBeNull();
    expect(driver.state.error).toBeNull();
  });

  it("does not detach a same-id attachment from a replacement session", async () => {
    const sharedAttachment = {
      id: "file-shared",
      name: "shared.pdf",
      mimetype: "application/pdf",
      size: 123
    };
    const currentSession = makeSession({
      session_id: "session-current",
      attachments: [sharedAttachment]
    });
    const delayedDetach = Promise.withResolvers<void>();
    const fetch = vi
      .fn()
      .mockReturnValueOnce(delayedDetach.promise)
      .mockResolvedValueOnce(currentSession)
      .mockResolvedValueOnce({ models: [], default_model_id: null })
      .mockResolvedValueOnce({ sessions: [] });
    const { driver } = makeDriver({ fetchImpl: fetch });
    driver.seedState({
      session: makeSession({ session_id: "session-old", attachments: [sharedAttachment] })
    });

    const detach = driver.removeAttachment(sharedAttachment.id);
    await driver.resumeSession(currentSession.session_id);
    delayedDetach.resolve();
    await detach;

    expect(driver.state.session).toEqual(currentSession);
    expect(driver.state.session?.attachments).toEqual([sharedAttachment]);
  });

  it("does not install a delayed revision into a replacement session", async () => {
    const oldPlan = makePlan({ plan_id: "plan-old" });
    const currentPlan = makePlan({ plan_id: "plan-current" });
    const currentSession = makeSession({
      session_id: "session-current",
      latest_plan_id: currentPlan.plan_id
    });
    const delayedRevision = Promise.withResolvers<ProposedPlan>();
    const fetch = vi
      .fn()
      .mockReturnValueOnce(delayedRevision.promise)
      .mockResolvedValueOnce(currentSession)
      .mockResolvedValueOnce({ models: [], default_model_id: null })
      .mockResolvedValueOnce(currentPlan)
      .mockResolvedValueOnce({ sessions: [] });
    const { driver } = makeDriver({ fetchImpl: fetch });
    driver.seedState({
      session: makeSession({ session_id: "session-old", latest_plan_id: oldPlan.plan_id }),
      currentPlan: oldPlan
    });

    const revision = driver.revisePlan("keep_current_description");
    await driver.resumeSession(currentSession.session_id);
    delayedRevision.resolve(makePlan({ plan_id: "plan-old-revised" }));
    await revision;

    expect(driver.state.session).toEqual(currentSession);
    expect(driver.state.currentPlan).toEqual(currentPlan);
    expect(driver.state.error).toBeNull();
  });

  it("reconciles a successful delayed cancellation of the resumed same session", async () => {
    const sessionId = "session-shared";
    const resumedSession = makeSession({ session_id: sessionId });
    const resumedDraft = makeDraft({ session_id: sessionId });
    const delayedCancellation = Promise.withResolvers<void>();
    const fetch = vi
      .fn()
      .mockReturnValueOnce(delayedCancellation.promise)
      .mockResolvedValueOnce(resumedSession)
      .mockResolvedValueOnce({ models: [], default_model_id: null })
      .mockResolvedValueOnce({ sessions: [resumedDraft] })
      .mockResolvedValueOnce({ sessions: [] });
    const { driver } = makeDriver({ fetchImpl: fetch });
    driver.seedState({
      session: makeSession({ session_id: sessionId }),
      draftSessions: [resumedDraft]
    });

    const cancellation = driver.discardSession(sessionId);
    await driver.resumeSession(sessionId);
    delayedCancellation.resolve();
    await cancellation;

    expect(driver.state.session).toBeNull();
    expect(driver.state.draftSessions).toEqual([]);
  });

  it("keeps a successful cancellation authoritative over a pending same-session resume", async () => {
    const sessionId = "session-shared";
    const activeSnapshot = makeSession({ session_id: sessionId });
    const recoverableDraft = makeDraft({ session_id: sessionId });
    const delayedCancellation = Promise.withResolvers<void>();
    const delayedResume = Promise.withResolvers<AIBuilderSession>();
    const fetch = vi
      .fn()
      .mockReturnValueOnce(delayedCancellation.promise)
      .mockReturnValueOnce(delayedResume.promise)
      .mockResolvedValueOnce({ sessions: [] })
      .mockResolvedValueOnce({ models: [], default_model_id: null })
      .mockResolvedValueOnce({ sessions: [] });
    const { driver } = makeDriver({ fetchImpl: fetch });
    driver.seedState({
      session: activeSnapshot,
      draftSessions: [recoverableDraft]
    });

    const cancellation = driver.discardSession(sessionId);
    const resume = driver.resumeSession(sessionId);
    delayedCancellation.resolve();
    await cancellation;
    delayedResume.resolve(activeSnapshot);
    await resume;

    expect(driver.state.session).toBeNull();
    expect(driver.state.draftSessions).toEqual([]);
  });

  it("does not let cancellation invalidate a pending different-session resume", async () => {
    const cancelledSessionId = "session-cancelled";
    const replacementSession = makeSession({ session_id: "session-replacement" });
    const cancelledDraft = makeDraft({ session_id: cancelledSessionId });
    const replacementDraft = makeDraft({ session_id: replacementSession.session_id });
    const delayedCancellation = Promise.withResolvers<void>();
    const delayedResume = Promise.withResolvers<AIBuilderSession>();
    const fetch = vi
      .fn()
      .mockReturnValueOnce(delayedCancellation.promise)
      .mockReturnValueOnce(delayedResume.promise)
      .mockResolvedValueOnce({ sessions: [replacementDraft] })
      .mockResolvedValueOnce({ models: [], default_model_id: null })
      .mockResolvedValueOnce({ sessions: [replacementDraft] });
    const { driver } = makeDriver({ fetchImpl: fetch });
    driver.seedState({
      session: makeSession({ session_id: cancelledSessionId }),
      draftSessions: [cancelledDraft]
    });

    const cancellation = driver.discardSession(cancelledSessionId);
    const resume = driver.resumeSession(replacementSession.session_id);
    delayedCancellation.resolve();
    await cancellation;
    delayedResume.resolve(replacementSession);
    await resume;

    expect(driver.state.session).toEqual(replacementSession);
    expect(driver.state.draftSessions).toEqual([replacementDraft]);
  });

  it("keeps a newer cancellation draft list over an older same-generation resume load", async () => {
    const cancelledSessionId = "session-cancelled";
    const replacementSession = makeSession({ session_id: "session-replacement" });
    const cancelledDraft = makeDraft({ session_id: cancelledSessionId });
    const replacementDraft = makeDraft({ session_id: replacementSession.session_id });
    const delayedCancellation = Promise.withResolvers<void>();
    const delayedResumeDrafts = Promise.withResolvers<{ sessions: AIBuilderDraftSession[] }>();
    const resumeDraftLoadStarted = Promise.withResolvers<void>();
    const fetch = vi
      .fn()
      .mockReturnValueOnce(delayedCancellation.promise)
      .mockResolvedValueOnce(replacementSession)
      .mockResolvedValueOnce({ models: [], default_model_id: null })
      .mockImplementationOnce(() => {
        resumeDraftLoadStarted.resolve();
        return delayedResumeDrafts.promise;
      })
      .mockResolvedValueOnce({ sessions: [replacementDraft] });
    const { driver } = makeDriver({ fetchImpl: fetch });
    driver.seedState({
      session: makeSession({ session_id: cancelledSessionId }),
      draftSessions: [cancelledDraft]
    });

    const cancellation = driver.discardSession(cancelledSessionId);
    const resume = driver.resumeSession(replacementSession.session_id);
    await resumeDraftLoadStarted.promise;
    delayedCancellation.resolve();
    await cancellation;
    expect(driver.state.draftSessions).toEqual([replacementDraft]);

    delayedResumeDrafts.resolve({ sessions: [cancelledDraft, replacementDraft] });
    await resume;

    expect(driver.state.session).toEqual(replacementSession);
    expect(driver.state.draftSessions).toEqual([replacementDraft]);
  });

  it("preserves a different replacement session after delayed cancellation", async () => {
    const cancelledSessionId = "session-cancelled";
    const replacementSession = makeSession({ session_id: "session-replacement" });
    const cancelledDraft = makeDraft({ session_id: cancelledSessionId });
    const replacementDraft = makeDraft({ session_id: replacementSession.session_id });
    const delayedCancellation = Promise.withResolvers<void>();
    const fetch = vi
      .fn()
      .mockReturnValueOnce(delayedCancellation.promise)
      .mockResolvedValueOnce(replacementSession)
      .mockResolvedValueOnce({ models: [], default_model_id: null })
      .mockResolvedValueOnce({ sessions: [cancelledDraft, replacementDraft] })
      .mockResolvedValueOnce({ sessions: [replacementDraft] });
    const { driver } = makeDriver({ fetchImpl: fetch });
    driver.seedState({
      session: makeSession({ session_id: cancelledSessionId }),
      draftSessions: [cancelledDraft]
    });

    const cancellation = driver.discardSession(cancelledSessionId);
    await driver.resumeSession(replacementSession.session_id);
    delayedCancellation.resolve();
    await cancellation;

    expect(driver.state.session).toEqual(replacementSession);
    expect(driver.state.draftSessions).toEqual([replacementDraft]);
  });

  it("uses a new turn ID only for a distinct logical send", async () => {
    const bodies: AIBuilderSendMessageRequest[] = [];
    const { driver } = makeDriver({
      streamImpl: vi.fn(async (_path, init, handlers) => {
        bodies.push(init.requestBody["application/json"]);
        completeStream(handlers);
      })
    });
    driver.seedState({ session: makeSession() });

    await driver.sendMessage("First request");
    await driver.sendMessage("Second request");

    expect(bodies[0]?.client_turn_id).not.toBe(bodies[1]?.client_turn_id);
  });

  it.each(["open", "processing", "failed_before_provider", "provider_outcome_unknown"] as const)(
    "blocks a new logical send while the latest turn is %s",
    async (state) => {
      const recoverable = makeRecoverableSession(
        state === "provider_outcome_unknown" ? "provider_outcome_unknown" : "failed_before_provider"
      );
      const latestTurn = recoverable.latest_turn;
      if (!latestTurn) throw new Error("Expected latest turn");
      const { driver, stream } = makeDriver();
      driver.seedState({
        session: {
          ...recoverable,
          latest_turn: { ...latestTurn, state }
        }
      });

      await driver.sendMessage("Start a different turn");

      expect(driver.canStartNewTurn).toBe(false);
      expect(stream).not.toHaveBeenCalled();
    }
  );

  it("refreshes authoritative turn state when a stream closes without done", async () => {
    const activeSession = makeRecoverableSession("failed_before_provider");
    if (!activeSession.latest_turn) throw new Error("Expected latest turn");
    activeSession.latest_turn = { ...activeSession.latest_turn, state: "processing" };
    const fetch = vi.fn().mockResolvedValue(activeSession);
    const { driver } = makeDriver({
      fetchImpl: fetch,
      streamImpl: vi.fn(async (_path, _init, handlers) => {
        handlers.onClose();
      })
    });
    driver.seedState({ session: makeSession() });

    await driver.sendMessage("Build a flow");

    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/flows/ai-builder/sessions/{session_id}",
      expect.objectContaining({ method: "get" })
    );
    expect(driver.latestTurnState).toBe("processing");
    expect(driver.canStartNewTurn).toBe(false);
  });

  it("blocks new sends until an incomplete stream can be authoritatively refreshed", async () => {
    const fetch = vi.fn().mockRejectedValueOnce(new Error("refresh unavailable"));
    const stream = vi.fn(async (_path, _init, handlers) => {
      handlers.onClose();
    });
    const { driver } = makeDriver({ fetchImpl: fetch, streamImpl: stream });
    driver.seedState({ session: makeSession() });

    await driver.sendMessage("Build a flow");
    await driver.sendMessage("Do not send yet");

    expect(stream).toHaveBeenCalledOnce();
    expect(driver.canStartNewTurn).toBe(false);

    fetch.mockResolvedValueOnce(makeSession());
    expect(await driver.refreshSession()).toBe(true);
    expect(driver.canStartNewTurn).toBe(true);
  });

  it("does not carry an uncertain turn fence into a fresh authoritative session", async () => {
    const freshSession = makeSession({
      session_id: "session-fresh",
      target_kind: "create",
      flow_id: null
    });
    const fetch = vi.fn(async (path: string, init?: { method?: string }) => {
      if (path === "/api/v1/flows/ai-builder/sessions" && init?.method === "post") {
        return freshSession;
      }
      if (path === "/api/v1/flows/ai-builder/sessions" && init?.method === "get") {
        return { sessions: [] };
      }
      if (path.endsWith("/models")) {
        return { models: [], default_model_id: null };
      }
      if (path === "/api/v1/flows/ai-builder/sessions/{session_id}") {
        throw new Error("session refresh unavailable");
      }
      return {};
    });
    const { driver } = makeDriver({
      fetchImpl: fetch,
      streamImpl: vi.fn(async (_path, _init, handlers) => {
        handlers.onClose();
      })
    });
    driver.seedState({ session: makeSession() });

    await driver.sendMessage("Build a flow");
    expect(driver.canStartNewTurn).toBe(false);

    await driver.startFreshSession("create");

    expect(driver.state.session?.session_id).toBe("session-fresh");
    expect(driver.canStartNewTurn).toBe(true);
  });

  it("keeps an active turn fenced and reports an authoritative refresh failure", async () => {
    const activeSession = makeRecoverableSession("failed_before_provider");
    if (!activeSession.latest_turn) throw new Error("Expected latest turn");
    activeSession.latest_turn = { ...activeSession.latest_turn, state: "processing" };
    const { driver } = makeDriver({
      fetchImpl: vi.fn().mockRejectedValue(new Error("session refresh unavailable"))
    });
    driver.seedState({ session: activeSession });

    expect(await driver.refreshSession()).toBe(false);

    expect(driver.canStartNewTurn).toBe(false);
    expect(driver.state.error).not.toBeNull();
  });

  it("soft-block stream errors do not set visible error state", async () => {
    const { driver } = makeDriver({
      fetchImpl: vi.fn().mockResolvedValue(makeSession()),
      streamImpl: vi.fn(async (_path, _init, handlers) => {
        handlers.onMessage({
          event: "error",
          data: JSON.stringify({
            schema_version: 2,
            message: "More discovery is needed before confirming requirements.",
            code: "requirements_incomplete",
            category: "soft_block",
            phase: "requirements",
            request_id: "req-soft-block",
            eneo_error_code: 9007
          })
        });
        completeStream(handlers);
      })
    });
    driver.seedState({ session: makeSession() });

    await driver.sendMessage("Build a flow");

    expect(driver.state.error).toBeNull();
  });

  it("stores structured stream errors", async () => {
    const { driver } = makeDriver({
      fetchImpl: vi.fn().mockResolvedValue(makeSession()),
      streamImpl: vi.fn(async (_path, _init, handlers) => {
        handlers.onMessage({
          event: "error",
          data: JSON.stringify({
            schema_version: 2,
            code: "planner_stream_failed",
            category: "internal",
            message: "The AI Builder stream failed. Please try again.",
            phase: "router",
            request_id: "req-stream",
            eneo_error_code: 9024
          })
        });
        completeStream(handlers);
      })
    });
    driver.seedState({ session: makeSession() });

    await driver.sendMessage("Build a flow");

    expect(driver.state.error).toMatchObject({
      code: "planner_stream_failed",
      category: "internal",
      message: "The AI Builder stream failed. Please try again.",
      phase: "router",
      request_id: "req-stream"
    });
  });

  it("hydrates the exact committed turn error when a session is resumed", async () => {
    const recoverable = makeRecoverableSession("failed_before_provider");
    if (!recoverable.latest_turn) throw new Error("Expected latest turn");
    const committedError = {
      schema_version: 2 as const,
      code: "planner_stream_failed" as const,
      category: "internal" as const,
      message: "The persisted planner failure.",
      phase: "router" as const,
      request_id: "persisted-request",
      eneo_error_code: 9007 as const,
      diagnostic_context: { request_id: "persisted-request" },
      details: { quality_failure_codes: "missing_source_refs" }
    };
    const committedSession = {
      ...recoverable,
      latest_turn: {
        ...recoverable.latest_turn,
        state: "committed" as const,
        error: committedError
      }
    };
    const { driver } = makeDriver({
      fetchImpl: vi.fn(async (path: string) => {
        if (path === "/api/v1/flows/ai-builder/sessions/{session_id}") {
          return committedSession;
        }
        if (path.endsWith("/models")) return { models: [], default_model_id: null };
        if (path === "/api/v1/flows/ai-builder/sessions") return { sessions: [] };
        throw new Error(`Unexpected fetch: ${path}`);
      })
    });

    await driver.resumeSession(committedSession.session_id);

    expect(driver.state.error).toEqual(committedError);
  });

  it("replaces an ambiguous transport failure with the committed server error", async () => {
    const recoverable = makeRecoverableSession("failed_before_provider");
    if (!recoverable.latest_turn) throw new Error("Expected latest turn");
    const committedError = {
      schema_version: 2 as const,
      code: "planner_stream_failed" as const,
      category: "internal" as const,
      message: "The durable planner failure.",
      phase: "router" as const,
      request_id: "durable-request",
      eneo_error_code: 9007 as const,
      diagnostic_context: null,
      details: { stage: "proposal" }
    };
    const committedSession = {
      ...recoverable,
      latest_turn: {
        ...recoverable.latest_turn,
        state: "committed" as const,
        error: committedError
      }
    };
    const { driver } = makeDriver({
      fetchImpl: vi.fn().mockResolvedValue(committedSession),
      streamImpl: vi.fn().mockRejectedValue(new Error("connection lost"))
    });
    driver.seedState({ session: makeSession() });

    await driver.sendMessage("Build a flow");

    expect(driver.state.error).toEqual(committedError);
  });

  it("clears an ambiguous transport failure after committed success is reloaded", async () => {
    const recoverable = makeRecoverableSession("failed_before_provider");
    if (!recoverable.latest_turn) throw new Error("Expected latest turn");
    const committedSession = {
      ...recoverable,
      latest_turn: {
        ...recoverable.latest_turn,
        state: "committed" as const,
        error: null
      }
    };
    const { driver } = makeDriver({
      fetchImpl: vi.fn().mockResolvedValue(committedSession),
      streamImpl: vi.fn().mockRejectedValue(new Error("connection lost"))
    });
    driver.seedState({ session: makeSession() });

    await driver.sendMessage("Build a flow");

    expect(driver.state.error).toBeNull();
  });

  it("preserves structured transport errors and refreshes recovery state", async () => {
    const unknownSession = makeRecoverableSession("provider_outcome_unknown");
    const fetch = vi.fn().mockResolvedValueOnce(unknownSession);
    const transportError = {
      status: 409,
      response: {
        schema_version: 2,
        code: "session_turn_provider_outcome_unknown",
        category: "conflict",
        message: "The provider outcome is unknown.",
        phase: "router",
        request_id: "request-1",
        eneo_error_code: 9007,
        diagnostic_context: null,
        details: {}
      }
    };
    const { driver } = makeDriver({
      fetchImpl: fetch,
      streamImpl: vi.fn().mockRejectedValue(transportError)
    });
    driver.seedState({ session: makeSession() });

    await driver.sendMessage("Build a flow");

    expect(driver.state.error).toMatchObject({
      code: "session_turn_provider_outcome_unknown",
      category: "conflict",
      phase: "router",
      request_id: "request-1"
    });
    expect(driver.turnRecoveryState).toBe("provider_outcome_unknown");
    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/flows/ai-builder/sessions/{session_id}",
      expect.objectContaining({
        method: "get",
        params: { path: { session_id: "session-1" } }
      })
    );
  });

  it("sends the current UI language with AI Builder messages", async () => {
    const { driver, stream } = makeDriver({
      streamImpl: vi.fn(async (_path, init, handlers) => {
        expect(init.requestBody["application/json"].ui_language).toBeTruthy();
        completeStream(handlers);
      })
    });
    driver.seedState({ session: makeSession() });

    await driver.sendMessage("Build a flow");

    expect(stream).toHaveBeenCalledOnce();
  });

  it("preserves explicit-confirm structured question metadata from stream events", async () => {
    const { driver } = makeDriver({
      streamImpl: vi.fn(async (_path, _init, handlers) => {
        handlers.onMessage({
          event: "question",
          data: JSON.stringify({
            question_id: "report_disposition",
            question: "Should AI Builder create one combined report?",
            selection_mode: "single",
            allow_custom: false,
            requires_confirm: true,
            options: [
              {
                id: "combined_report",
                label: "Create one report",
                value: "report_disposition:combined"
              }
            ]
          })
        });
        completeStream(handlers);
      })
    });
    driver.seedState({ session: makeSession() });

    await driver.sendMessage("Build a flow");

    expect(driver.state.messages[1]?.question).toMatchObject({
      question_id: "report_disposition",
      requires_confirm: true
    });
  });

  it("updates session telemetry from usage stream events", async () => {
    const { driver } = makeDriver({
      streamImpl: vi.fn(async (_path, _init, handlers) => {
        handlers.onMessage({
          event: "usage",
          data: JSON.stringify({
            planner_request_count: 1,
            clarification_question_count: 0,
            prompt_tokens_total: 1200,
            completion_tokens_total: 300,
            total_tokens_total: 1500,
            tool_call_count_total: 1,
            auxiliary_llm_call_count: 0,
            architecture_commit_count: 0,
            repair_attempts_total: 1,
            parse_repair_attempts_total: 0,
            wall_clock_ms_total: 0,
            llm_calls_made_total: 2,
            token_usage_estimated: false,
            last_request_id: "request-1",
            last_model: "gpt-5.4-nano",
            last_finish_reason: "tool_calls",
            last_outcome_kind: "dispatched",
            last_token_usage_source: "provider",
            last_token_usage_estimated: false
          })
        });
        completeStream(handlers);
      })
    });
    driver.seedState({ session: makeSession() });

    await driver.sendMessage("Build a flow");

    expect(driver.state.session?.telemetry?.total_tokens_total).toBe(1500);
    expect(driver.state.session?.telemetry?.prompt_tokens_total).toBe(1200);
    expect(driver.state.session?.telemetry?.last_model).toBe("gpt-5.4-nano");
  });

  it("refreshes session telemetry after a plan stream without usage event", async () => {
    const plan = makePlan();
    const sessionWithTelemetry = makeSession({
      latest_plan_id: "plan-1",
      telemetry: {
        planner_request_count: 1,
        clarification_question_count: 0,
        prompt_tokens_total: 900,
        completion_tokens_total: 200,
        total_tokens_total: 1100,
        tool_call_count_total: 1,
        auxiliary_llm_call_count: 0,
        architecture_commit_count: 0,
        repair_attempts_total: 0,
        parse_repair_attempts_total: 0,
        wall_clock_ms_total: 0,
        llm_calls_made_total: 1,
        token_usage_estimated: false,
        last_request_id: "request-plan",
        last_model: "gpt-5.4-nano",
        last_finish_reason: "tool_calls",
        last_outcome_kind: "dispatched",
        last_token_usage_source: "provider",
        last_token_usage_estimated: false
      }
    });
    const fetch = vi.fn().mockResolvedValueOnce(sessionWithTelemetry).mockResolvedValueOnce(plan);
    const { driver } = makeDriver({
      fetchImpl: fetch,
      streamImpl: vi.fn(async (_path, _init, handlers) => {
        handlers.onMessage({
          event: "plan",
          data: JSON.stringify(plan)
        });
        completeStream(handlers);
      })
    });
    driver.seedState({ session: makeSession() });

    await driver.sendMessage("Build a flow");

    expect(driver.state.session?.telemetry?.total_tokens_total).toBe(1100);
    expect(driver.state.currentPlan?.plan_id).toBe("plan-1");
    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/flows/ai-builder/sessions/{session_id}",
      expect.objectContaining({
        method: "get",
        params: { path: { session_id: "session-1" } }
      })
    );
  });

  it("refreshes a structured-answer turn when the stream closes without a visible next action", async () => {
    const refreshedSession = makeSession({
      conversation: [
        {
          message_id: "assistant-source-question",
          role: "assistant",
          content: "Jag behöver förstå slutresultatet lite bättre.",
          timestamp: "2026-03-15T10:00:00Z",
          question: {
            question_id: "source_traceability",
            question: "Hur ska källor visas i slutresultatet?",
            options: [{ id: "none", label: "Inga källhänvisningar", value: "none" }],
            selection_mode: "single",
            allow_custom: true,
            requires_confirm: false
          }
        },
        {
          message_id: "user-source-answer",
          role: "user",
          content: "Inga källhänvisningar",
          timestamp: "2026-03-15T10:00:05Z",
          question_answer: {
            kind: "structured_question_answer",
            question_id: "source_traceability",
            selected_option_ids: ["none"],
            selected_values: ["none"]
          }
        },
        {
          message_id: "assistant-reading-question",
          role: "assistant",
          content: "Jag behöver förstå detaljnivån lite bättre.",
          timestamp: "2026-03-15T10:00:10Z",
          question: {
            question_id: "reading_depth",
            question: "Hur ska dokumentgranskningen tas fram?",
            options: [{ id: "overview", label: "Kort översikt", value: "overview" }],
            selection_mode: "single",
            allow_custom: true,
            requires_confirm: false
          }
        }
      ]
    });
    const fetch = vi.fn().mockResolvedValueOnce(refreshedSession);
    const { driver, stream } = makeDriver({
      fetchImpl: fetch,
      streamImpl: vi.fn(async (_path, init, handlers) => {
        expect(init.requestBody["application/json"].question_answer).toEqual({
          kind: "structured_question_answer",
          question_id: "source_traceability",
          selected_option_ids: ["none"],
          selected_values: ["none"]
        });
        completeStream(handlers);
      })
    });
    driver.seedState({ session: makeSession() });

    await driver.sendMessage("Inga källhänvisningar", {
      kind: "structured_question_answer",
      question_id: "source_traceability",
      selected_option_ids: ["none"],
      selected_values: ["none"]
    });

    expect(stream).toHaveBeenCalledOnce();
    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/flows/ai-builder/sessions/{session_id}",
      expect.objectContaining({
        method: "get",
        params: { path: { session_id: "session-1" } }
      })
    );
    expect(driver.state.messages.at(-1)?.question?.question_id).toBe("reading_depth");
    expect(driver.isQuestionAnswered("source_traceability")).toBe(true);
  });

  it("does not refresh a structured-answer turn when the stream already renders the next question", async () => {
    const fetch = vi.fn();
    const { driver } = makeDriver({
      fetchImpl: fetch,
      streamImpl: vi.fn(async (_path, _init, handlers) => {
        handlers.onMessage({
          event: "question",
          data: JSON.stringify({
            question_id: "reading_depth",
            question: "Hur ska dokumentgranskningen tas fram?",
            options: [{ id: "overview", label: "Kort översikt", value: "overview" }],
            selection_mode: "single",
            allow_custom: true,
            requires_confirm: false
          })
        });
        completeStream(handlers);
      })
    });
    driver.seedState({ session: makeSession() });

    await driver.sendMessage("Inga källhänvisningar", {
      kind: "structured_question_answer",
      question_id: "source_traceability",
      selected_option_ids: ["none"],
      selected_values: ["none"]
    });

    expect(fetch).not.toHaveBeenCalled();
    expect(driver.state.messages.at(-1)?.question?.question_id).toBe("reading_depth");
  });

  it("refreshes instead of rendering a repeated answered question from the stream", async () => {
    const refreshedSession = makeSession({
      conversation: [
        {
          message_id: "assistant-source-question",
          role: "assistant",
          content: "Jag behöver förstå slutresultatet lite bättre.",
          timestamp: "2026-03-15T10:00:00Z",
          question: {
            question_id: "source_traceability",
            question: "Hur ska källor visas i slutresultatet?",
            options: [{ id: "none", label: "Inga källhänvisningar", value: "none" }],
            selection_mode: "single",
            allow_custom: true,
            requires_confirm: false
          }
        },
        {
          message_id: "user-source-answer",
          role: "user",
          content: "Inga källhänvisningar",
          timestamp: "2026-03-15T10:00:05Z",
          question_answer: {
            kind: "structured_question_answer",
            question_id: "source_traceability",
            selected_option_ids: ["none"],
            selected_values: ["none"]
          }
        },
        {
          message_id: "assistant-summary",
          role: "assistant",
          content: "Jag har tillräckligt med information.",
          timestamp: "2026-03-15T10:00:10Z",
          requirements_summary: {
            summary: "Bygg ett PDF-flöde utan källhänvisningar.",
            key_decisions: [{ topic: "Källspårning", decision: "Inga källhänvisningar" }],
            input_description: "Uppladdade filer",
            output_description: "PDF",
            requirements_version: "req-after-source"
          }
        }
      ]
    });
    const fetch = vi.fn().mockResolvedValueOnce(refreshedSession);
    const { driver } = makeDriver({
      fetchImpl: fetch,
      streamImpl: vi.fn(async (_path, _init, handlers) => {
        handlers.onMessage({
          event: "question",
          data: JSON.stringify({
            question_id: "source_traceability",
            question: "Hur ska källor visas i slutresultatet?",
            options: [{ id: "none", label: "Inga källhänvisningar", value: "none" }],
            selection_mode: "single",
            allow_custom: true,
            requires_confirm: false
          })
        });
        completeStream(handlers);
      })
    });
    driver.seedState({ session: makeSession() });

    await driver.sendMessage("Inga källhänvisningar", {
      kind: "structured_question_answer",
      question_id: "source_traceability",
      selected_option_ids: ["none"],
      selected_values: ["none"]
    });

    expect(fetch).toHaveBeenCalledOnce();
    expect(driver.state.messages.at(-1)?.question?.question_id).not.toBe("source_traceability");
    expect(driver.state.messages.at(-1)?.requirementsSummary?.requirements_version).toBe(
      "req-after-source"
    );
  });

  it("forwards file_ids with AI Builder messages", async () => {
    const { driver, stream } = makeDriver({
      streamImpl: vi.fn(async (_path, init, handlers) => {
        expect(init.requestBody["application/json"].file_ids).toEqual(["file-1", "file-2"]);
        completeStream(handlers);
      })
    });
    driver.seedState({ session: makeSession() });

    await driver.sendMessage("Build a flow", undefined, ["file-1", "file-2"]);

    expect(stream).toHaveBeenCalledOnce();
  });

  it("forwards structured plan edit context with AI Builder messages", async () => {
    const editContext = {
      scope: "step" as const,
      plan_id: "plan-1",
      target_plan_step_ref: "step_f",
      target_step_name: "Create final result",
      target_step_number: 6
    };
    const { driver, stream } = makeDriver({
      streamImpl: vi.fn(async (_path, init, handlers) => {
        expect(init.requestBody["application/json"].edit_context).toEqual(editContext);
        completeStream(handlers);
      })
    });
    driver.seedState({ session: makeSession() });

    await driver.sendMessage("Change this to PDF", undefined, undefined, editContext);

    expect(stream).toHaveBeenCalledOnce();
    expect(driver.state.messages[0]?.metadata).toEqual({ edit_context: editContext });
  });

  it("refreshes the session after sending message attachments", async () => {
    const fetch = vi.fn().mockResolvedValue(makeSession({ attachments: [] }));
    const { driver, stream } = makeDriver({
      fetchImpl: fetch,
      streamImpl: vi.fn(async (_path, _init, handlers) => {
        completeStream(handlers);
      })
    });
    driver.seedState({ session: makeSession() });

    await driver.sendMessage("Build a flow", undefined, ["file-1"]);

    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/flows/ai-builder/sessions/{session_id}",
      expect.objectContaining({
        method: "get",
        params: { path: { session_id: "session-1" } }
      })
    );
    expect(stream).toHaveBeenCalledOnce();
  });

  it("removes persisted attachments from the session after detach", async () => {
    const fetch = vi.fn().mockResolvedValue(undefined);
    const { driver } = makeDriver({ fetchImpl: fetch });
    driver.seedState({
      session: makeSession({
        attachments: [
          {
            id: "file-1",
            name: "brief.pdf",
            mimetype: "application/pdf",
            size: 123
          }
        ]
      })
    });

    await driver.removeAttachment("file-1");

    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/flows/ai-builder/sessions/{session_id}/attachments/{file_id}",
      expect.objectContaining({
        method: "delete",
        params: { path: { session_id: "session-1", file_id: "file-1" } }
      })
    );
    expect(driver.state.session?.attachments).toEqual([]);
  });

  it("approves separately from apply and keeps session state aligned with backend refresh", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(undefined)
      .mockResolvedValueOnce({
        flow_id: "flow-1",
        flow_name: "Flow",
        steps_created: 1,
        steps_updated: 0,
        steps_removed: 0
      })
      .mockResolvedValueOnce(makeSession({ status: "applied", latest_plan_id: "plan-1" }))
      .mockResolvedValueOnce(makePlan({ status: "applied" }));
    const { driver } = makeDriver({ fetchImpl: fetch });
    driver.seedState({
      session: makeSession({ status: "awaiting_approval", latest_plan_id: "plan-1" }),
      currentPlan: makePlan()
    });

    await driver.approvePlan();
    expect(driver.state.currentPlan?.status).toBe("approved");
    expect(driver.state.session?.status).toBe("awaiting_approval");

    const result = await driver.applyPlan();
    expect(result.flow_id).toBe("flow-1");
    expect(driver.state.applyResult?.flow_id).toBe("flow-1");
    expect(driver.state.session?.status).toBe("applied");
    expect(driver.state.currentPlan?.status).toBe("applied");
  });

  it("keeps a published-flow apply error actionable after refreshing state", async () => {
    const publishedError = {
      body: {
        schema_version: 2,
        code: "flow_is_published",
        category: "bad_request",
        message: "Flow is published",
        phase: "router",
        request_id: "req-published",
        eneo_error_code: 9007,
        diagnostic_context: { flow_id: "flow-1" },
        details: { published_version: 3 }
      }
    };
    const fetch = vi
      .fn()
      .mockRejectedValueOnce(publishedError)
      .mockResolvedValueOnce(makeSession({ status: "awaiting_approval", latest_plan_id: "plan-1" }))
      .mockResolvedValueOnce(makePlan({ status: "approved" }));
    const { driver } = makeDriver({ fetchImpl: fetch });
    driver.seedState({
      session: makeSession({ status: "awaiting_approval", latest_plan_id: "plan-1" }),
      currentPlan: makePlan({ status: "approved" })
    });

    await expect(driver.applyPlan()).rejects.toBe(publishedError);

    expect(driver.state.applyError).toEqual({
      schema_version: 2,
      code: "flow_is_published",
      category: "bad_request",
      message: "Flow is published",
      phase: "router",
      request_id: "req-published",
      eneo_error_code: 9007,
      diagnostic_context: { flow_id: "flow-1" },
      details: { published_version: 3 }
    });
    expect(driver.state.currentPlan?.status).toBe("approved");
    expect(driver.state.session?.status).toBe("awaiting_approval");
  });

  it("stores unknown apply failures as typed errors and keeps the message visible", async () => {
    const unexpectedError = {
      status: 400,
      response: {
        code: "unexpected_backend_code",
        message: "Unexpected apply failure",
        details: { retryable: false }
      }
    };
    const fetch = vi
      .fn()
      .mockRejectedValueOnce(unexpectedError)
      .mockResolvedValueOnce(makeSession({ status: "awaiting_approval", latest_plan_id: "plan-1" }))
      .mockResolvedValueOnce(makePlan({ status: "approved" }));
    const { driver } = makeDriver({ fetchImpl: fetch });
    driver.seedState({
      session: makeSession({ status: "awaiting_approval", latest_plan_id: "plan-1" }),
      currentPlan: makePlan({ status: "approved" })
    });

    await expect(driver.applyPlan()).rejects.toBe(unexpectedError);

    expect(driver.state.applyError).toEqual({
      schema_version: 2,
      code: "unknown",
      category: "internal",
      message: "Unexpected apply failure",
      phase: "client",
      request_id: null,
      eneo_error_code: null,
      diagnostic_context: null,
      details: {
        retryable: false,
        status: 400,
        original_code: "unexpected_backend_code"
      }
    });
    expect(driver.state.error?.message).toBe("Unexpected apply failure");
    expect(driver.state.isConflict).toBe(false);
  });

  it("unpublishes a published flow before retrying plan apply", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce({ flow_id: "flow-1" })
      .mockResolvedValueOnce({
        flow_id: "flow-1",
        flow_name: "Flow",
        steps_created: 0,
        steps_updated: 2,
        steps_removed: 0
      })
      .mockResolvedValueOnce(makeSession({ status: "applied", latest_plan_id: "plan-1" }))
      .mockResolvedValueOnce(makePlan({ status: "applied" }));
    const { driver } = makeDriver({ fetchImpl: fetch });
    driver.seedState({
      session: makeSession({ status: "awaiting_approval", latest_plan_id: "plan-1" }),
      currentPlan: makePlan({ status: "approved" }),
      applyError: {
        schema_version: 2,
        code: "flow_is_published",
        category: "bad_request",
        message: "Flow is published",
        phase: "router",
        request_id: "req-published",
        eneo_error_code: 9007,
        diagnostic_context: { flow_id: "flow-1" },
        details: { published_version: 3 }
      }
    });

    const result = await driver.unpublishAndApplyPlan(12);

    expect(result.flow_id).toBe("flow-1");
    expect(fetch).toHaveBeenNthCalledWith(1, "/api/v1/flows/{id}/unpublish/", {
      method: "post",
      params: { path: { id: "flow-1" } }
    });
    expect(fetch).toHaveBeenNthCalledWith(
      2,
      "/api/v1/flows/ai-builder/plans/{plan_id}/apply",
      expect.objectContaining({
        method: "post",
        params: { path: { plan_id: "plan-1" } },
        requestBody: {
          "application/json": {
            expected_revision: 12
          }
        }
      })
    );
    expect(driver.state.applyError).toBeNull();
    expect(driver.state.applyResult?.steps_updated).toBe(2);
    expect(driver.state.session?.status).toBe("applied");
  });

  it("surfaces when apply fails after unpublishing succeeds", async () => {
    const staleError = {
      body: {
        schema_version: 2,
        code: "stale_revision",
        category: "conflict",
        message: "Flow was modified",
        phase: "router",
        request_id: "req-stale",
        eneo_error_code: 9007,
        details: { latest_revision: 9 }
      }
    };
    const fetch = vi
      .fn()
      .mockResolvedValueOnce({ flow_id: "flow-1" })
      .mockRejectedValueOnce(staleError)
      .mockResolvedValueOnce(makeSession({ status: "awaiting_approval", latest_plan_id: "plan-1" }))
      .mockResolvedValueOnce(makePlan({ status: "approved" }));
    const { driver } = makeDriver({ fetchImpl: fetch });
    driver.seedState({
      session: makeSession({ status: "awaiting_approval", latest_plan_id: "plan-1" }),
      currentPlan: makePlan({ status: "approved" }),
      applyError: {
        schema_version: 2,
        code: "flow_is_published",
        category: "bad_request",
        message: "Flow is published",
        phase: "router",
        request_id: "req-published",
        eneo_error_code: 9007,
        diagnostic_context: { flow_id: "flow-1" },
        details: { published_version: 3 }
      }
    });

    await expect(driver.unpublishAndApplyPlan()).rejects.toBe(staleError);

    expect(driver.state.applyError).toEqual({
      schema_version: 2,
      code: "flow_unpublished_apply_failed",
      category: "conflict",
      message: "Flow was modified",
      phase: "client",
      request_id: null,
      eneo_error_code: null,
      diagnostic_context: null,
      details: {
        flow_id: "flow-1",
        original_code: "stale_revision",
        original_details_latest_revision: 9
      }
    });
    expect(driver.state.isConflict).toBe(true);
    expect(driver.state.applyResult).toBeNull();
  });

  it("revises a plan with keep_current_description and refreshes current plan state", async () => {
    const editApproval = makeEditApproval();
    const revisedPlan = makePlan({ plan_id: "plan-2", status: "proposed" });
    revisedPlan.proposal.description_override_manual = true;
    revisedPlan.proposal.edit = editApproval;
    const fetch = vi.fn().mockResolvedValueOnce(revisedPlan);
    const { driver } = makeDriver({ fetchImpl: fetch });
    driver.seedState({
      session: makeSession({ latest_plan_id: "plan-1", status: "awaiting_approval" }),
      currentPlan: makePlan({ plan_id: "plan-1", status: "proposed" })
    });

    await driver.revisePlan("keep_current_description");

    expect(fetch).toHaveBeenCalledWith("/api/v1/flows/ai-builder/plans/{plan_id}/revise", {
      method: "post",
      params: { path: { plan_id: "plan-1" } },
      requestBody: {
        "application/json": {
          type: "keep_current_description"
        }
      }
    });
    expect(driver.state.currentPlan?.plan_id).toBe("plan-2");
    expect(driver.state.currentPlan?.proposal.description_override_manual).toBe(true);
    const currentEdit = driver.state.currentPlan?.proposal.edit;
    if (!currentEdit) {
      throw new Error("Expected revised plan to include nested edit approval metadata");
    }
    expect(currentEdit).toEqual(editApproval);
    expect(currentEdit.diff.step_changes[0]?.kind).toBe("modified");
    expect(currentEdit.confidence).toBe("needs_review");
    expect(currentEdit.advisories?.[0]?.code).toBe("flow_description_update_required");
  });

  it("starts a fresh edit session when continuing after apply", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(makeSession({ session_id: "session-2", latest_plan_id: null }))
      .mockResolvedValueOnce({ models: [], default_model_id: null })
      .mockResolvedValueOnce(makeSession({ session_id: "session-2", latest_plan_id: null }))
      .mockResolvedValueOnce({ sessions: [] });
    const { driver } = makeDriver({ fetchImpl: fetch });
    driver.seedState({
      session: makeSession({ status: "applied" }),
      currentPlan: makePlan({ status: "applied" }),
      applyResult: {
        flow_id: "flow-1",
        flow_name: "Flow",
        steps_created: 0,
        steps_updated: 1,
        steps_removed: 0
      },
      messages: [{ role: "assistant", content: "Applied", timestamp: Date.now() }],
      error: makeAIBuilderError({ message: "stale" }),
      isConflict: true,
      statusMessage: "repairing"
    });

    await driver.continueEditing();

    expect(driver.state.session?.session_id).toBe("session-2");
    expect(driver.state.session?.status).toBe("chatting");
    expect(driver.state.currentPlan).toBeNull();
    expect(driver.state.applyResult).toBeNull();
    expect(driver.state.messages).toEqual([]);
    expect(driver.state.isConflict).toBe(false);
    expect(driver.state.error).toBeNull();
    expect(driver.state.statusMessage).toBeNull();
  });

  it("can continue editing a newly created flow after apply", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(makeSession({ session_id: "edit-session-1", target_kind: "edit" }))
      .mockResolvedValueOnce({ models: [], default_model_id: null })
      .mockResolvedValueOnce(makeSession({ session_id: "edit-session-1", target_kind: "edit" }))
      .mockResolvedValueOnce({ sessions: [] });
    const { driver } = makeDriver({ fetchImpl: fetch });
    driver.seedState({
      session: makeSession({
        session_id: "create-session-1",
        target_kind: "create",
        flow_id: null,
        status: "applied"
      }),
      currentPlan: makePlan({ status: "applied" }),
      applyResult: {
        flow_id: "flow-created-1",
        flow_name: "Created flow",
        steps_created: 3,
        steps_updated: 0,
        steps_removed: 0
      }
    });

    await driver.continueEditing();

    expect(fetch.mock.calls[0]?.[0]).toBe("/api/v1/flows/ai-builder/sessions");
    expect(fetch.mock.calls[0]?.[1]?.requestBody["application/json"]).toMatchObject({
      target_kind: "edit",
      flow_id: "flow-created-1"
    });
    expect(driver.state.session?.target_kind).toBe("edit");
  });

  it("refreshes the latest plan so recovered sessions keep backend plan state", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(
        makeSession({
          session_id: "session-9",
          latest_plan_id: "plan-77",
          status: "awaiting_approval"
        })
      )
      .mockResolvedValueOnce(makePlan({ plan_id: "plan-77", status: "approved" }));
    const { driver } = makeDriver({ fetchImpl: fetch });
    driver.seedState({ session: makeSession({ session_id: "session-9", latest_plan_id: null }) });

    await driver.refreshSession();

    expect(driver.state.session?.latest_plan_id).toBe("plan-77");
    expect(driver.state.currentPlan?.plan_id).toBe("plan-77");
    expect(driver.state.currentPlan?.status).toBe("approved");
  });

  it("hydrates public conversation projection fields when resuming a draft session", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(
        makeSession({
          session_id: "session-public-conversation",
          status: "chatting",
          conversation: [
            {
              message_id: "assistant-question",
              role: "assistant",
              content: "Vilket slutformat vill du ha?",
              timestamp: "2026-03-15T10:00:00Z",
              question: {
                question_id: "terminal_output",
                question: "Vilket slutformat vill du ha?",
                options: [{ id: "pdf", label: "PDF" }],
                selection_mode: "single",
                allow_custom: false,
                requires_confirm: false
              }
            },
            {
              message_id: "user-answer",
              role: "user",
              content: "PDF",
              timestamp: "2026-03-15T10:00:05Z",
              question_answer: {
                kind: "structured_question_answer",
                question_id: "terminal_output",
                selected_option_ids: ["pdf"]
              }
            },
            {
              message_id: "assistant-summary",
              role: "assistant",
              content: "Jag har tillräckligt med information.",
              timestamp: "2026-03-15T10:00:10Z",
              requirements_summary: {
                summary: "Bygg ett PDF-flöde.",
                key_decisions: [{ topic: "Slutformat", decision: "PDF" }],
                input_description: "Uppladdade filer",
                output_description: "PDF",
                requirements_version: "req-public"
              }
            },
            {
              message_id: "user-confirmation",
              role: "user",
              content: "Ja, bygg planen.",
              timestamp: "2026-03-15T10:00:15Z",
              requirements_confirmation: {
                kind: "requirements_confirmation",
                requirements_confirmed: true,
                requirements_version: "req-public"
              }
            }
          ]
        })
      )
      .mockResolvedValueOnce({ models: [], default_model_id: null })
      .mockResolvedValueOnce({ sessions: [] });
    const { driver } = makeDriver({ fetchImpl: fetch });

    await driver.resumeSession("session-public-conversation");

    expect(driver.state.messages[0]?.question?.question_id).toBe("terminal_output");
    expect(driver.state.messages[1]?.questionAnswer).toEqual({
      question_id: "terminal_output",
      selected_option_ids: ["pdf"]
    });
    expect(driver.state.messages[1]?.metadata).toBeUndefined();
    expect(driver.state.messages[2]?.requirementsSummary?.summary).toBe("Bygg ett PDF-flöde.");
    expect(driver.state.messages[3]?.metadata).toEqual({
      requirements_confirmed: true,
      requirements_version: "req-public"
    });
  });
});

describe("FlowAIBuilderDriver conversation hydration", () => {
  it("hydrates a public question_answer into the typed ChatMessage field", async () => {
    const { driver } = makeDriver({
      fetchImpl: vi.fn(async (path: string) => {
        if (path.endsWith("/models")) return { models: [], default_model_id: null };
        return makeSession({
          conversation: [
            {
              message_id: "u1",
              role: "user",
              content: "Avsnitt per k\u00e4lla",
              timestamp: "2026-07-12T09:00:10Z",
              question_answer: {
                kind: "structured_question_answer",
                question_id: "report_layout",
                selected_option_ids: ["per_source"]
              }
            }
          ]
        });
      })
    });

    await driver.resumeSession("session-1");

    const hydrated = driver.state.messages[0];
    expect(hydrated?.questionAnswer).toEqual({
      question_id: "report_layout",
      selected_option_ids: ["per_source"]
    });
    // Single owner: structured answers never appear in the metadata dict.
    expect(hydrated?.metadata?.question_answer).toBeUndefined();
  });
});

describe("FlowAIBuilderDriver send outcome contract", () => {
  // "delivered" authorizes irreversible draft deletion in the composer, so
  // every branch of the outcome is pinned here.
  const publicError = JSON.stringify({
    schema_version: 2,
    code: "internal_error",
    category: "internal",
    message: "boom",
    phase: "planner",
    request_id: null,
    diagnostic_context: null,
    details: {}
  });

  function seeded(streamImpl: ReturnType<typeof vi.fn>) {
    const made = makeDriver({
      streamImpl,
      fetchImpl: vi.fn(async () => makeSession())
    });
    made.driver.seedState({ session: makeSession() });
    return made;
  }

  it("returns 'not_started' when the turn guards reject the send", async () => {
    const { driver } = makeDriver();
    expect(await driver.sendMessage("Hej")).toBe("not_started");
  });

  it("returns 'delivered' only for done without a preceding error event", async () => {
    const { driver } = seeded(
      vi.fn(async (_path, _init, handlers) => {
        completeStream(handlers);
      })
    );
    expect(await driver.sendMessage("Hej")).toBe("delivered");
  });

  it("returns 'failed' when an error event arrives even if done follows", async () => {
    const { driver } = seeded(
      vi.fn(async (_path, _init, handlers) => {
        handlers.onMessage?.({ id: "", event: "error", data: publicError }, new AbortController());
        completeStream(handlers);
      })
    );
    expect(await driver.sendMessage("Hej")).toBe("failed");
  });

  it("returns 'failed' when the transport throws", async () => {
    const { driver } = seeded(
      vi.fn(async () => {
        throw new Error("transport down");
      })
    );
    expect(await driver.sendMessage("Hej")).toBe("failed");
  });

  it("returns 'failed' when stream ownership is lost mid-flight", async () => {
    let release!: () => void;
    const gate = new Promise<void>((resolve) => (release = resolve));
    const { driver } = seeded(
      vi.fn(async (_path, _init, handlers) => {
        await gate;
        completeStream(handlers);
      })
    );
    const pending = driver.sendMessage("Hej");
    // A fresh session supersedes the in-flight stream; its outcome is
    // unknowable for the original caller.
    await driver.startFreshSession("edit");
    release();
    expect(await pending).toBe("failed");
  });
});

describe("FlowAIBuilderDriver.createFlowFromPlan", () => {
  const CREATE_ROUTE = "/api/v1/flows/ai-builder/plans/{plan_id}/create";

  function seedCreateSession(driver: ReturnType<typeof makeDriver>["driver"]) {
    driver.seedState({
      session: makeSession({
        status: "awaiting_approval",
        target_kind: "create",
        flow_id: null,
        latest_plan_id: "plan-1"
      }),
      currentPlan: makePlan({ status: "proposed" })
    });
  }

  it("creates the flow with a single atomic call and no approve/apply requests", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce({
        flow_id: "flow-1",
        flow_name: "Flow",
        steps_created: 1,
        steps_updated: 0,
        steps_removed: 0
      })
      .mockResolvedValueOnce(
        makeSession({
          status: "applied",
          target_kind: "create",
          flow_id: "flow-1",
          latest_plan_id: "plan-1"
        })
      )
      .mockResolvedValueOnce(makePlan({ status: "applied" }));
    const { driver } = makeDriver({ fetchImpl: fetch });
    seedCreateSession(driver);

    const result = await driver.createFlowFromPlan();

    expect(result.flow_id).toBe("flow-1");
    expect(driver.state.applyResult?.flow_id).toBe("flow-1");
    expect(driver.state.pendingOperation).toBeNull();
    expect(driver.state.createFailureOutcome).toBeNull();
    const calledRoutes = fetch.mock.calls.map((call) => call[0]);
    expect(calledRoutes.filter((route) => route === CREATE_ROUTE)).toHaveLength(1);
    expect(calledRoutes).not.toContain("/api/v1/flows/ai-builder/plans/{plan_id}/approve");
    expect(calledRoutes).not.toContain("/api/v1/flows/ai-builder/plans/{plan_id}/apply");
  });

  it("recovers a committed-but-lost response by replaying the applied plan", async () => {
    const fetch = vi
      .fn()
      .mockRejectedValueOnce(new Error("response lost"))
      .mockResolvedValueOnce(
        makeSession({
          status: "applied",
          target_kind: "create",
          flow_id: "flow-1",
          latest_plan_id: "plan-1"
        })
      )
      .mockResolvedValueOnce(makePlan({ status: "applied" }))
      .mockResolvedValueOnce({
        flow_id: "flow-1",
        flow_name: "Flow",
        steps_created: 1,
        steps_updated: 0,
        steps_removed: 0
      })
      .mockResolvedValueOnce(
        makeSession({
          status: "applied",
          target_kind: "create",
          flow_id: "flow-1",
          latest_plan_id: "plan-1"
        })
      )
      .mockResolvedValueOnce(makePlan({ status: "applied" }));
    const { driver } = makeDriver({ fetchImpl: fetch });
    seedCreateSession(driver);

    const result = await driver.createFlowFromPlan();

    expect(result.flow_id).toBe("flow-1");
    expect(driver.state.applyResult?.flow_id).toBe("flow-1");
    expect(driver.state.applyError).toBeNull();
    expect(driver.state.createFailureOutcome).toBeNull();
    expect(driver.state.pendingOperation).toBeNull();
    const createCalls = fetch.mock.calls.filter((call) => call[0] === CREATE_ROUTE);
    expect(createCalls).toHaveLength(2);
  });

  it("confirms nothing was applied before allowing the truthful failure banner", async () => {
    const fetch = vi
      .fn()
      .mockRejectedValueOnce({
        status: 400,
        response: { code: "architecture_materialization_failed", message: "boom" }
      })
      .mockResolvedValueOnce(
        makeSession({
          status: "awaiting_approval",
          target_kind: "create",
          flow_id: null,
          latest_plan_id: "plan-1"
        })
      )
      .mockResolvedValueOnce(makePlan({ status: "proposed" }));
    const { driver } = makeDriver({ fetchImpl: fetch });
    seedCreateSession(driver);

    await expect(driver.createFlowFromPlan()).rejects.toBeTruthy();

    expect(driver.state.applyError).not.toBeNull();
    expect(driver.state.createFailureOutcome).toBe("confirmed_not_applied");
    expect(driver.state.pendingOperation).toBeNull();
    expect(driver.state.applyResult).toBeNull();
    const createCalls = fetch.mock.calls.filter((call) => call[0] === CREATE_ROUTE);
    expect(createCalls).toHaveLength(1);
  });

  it("keeps recovery possible when refresh proves applied but the replay call fails", async () => {
    const appliedSession = makeSession({
      status: "applied",
      target_kind: "create",
      flow_id: "flow-1",
      latest_plan_id: "plan-1"
    });
    const fetch = vi
      .fn()
      // first attempt: response lost
      .mockRejectedValueOnce(new Error("response lost"))
      // authoritative refresh: the flow exists
      .mockResolvedValueOnce(appliedSession)
      .mockResolvedValueOnce(makePlan({ status: "applied" }))
      // automatic replay also fails
      .mockRejectedValueOnce(new Error("still flaky"))
      // manual retry: replay returns the original outcome
      .mockResolvedValueOnce({
        flow_id: "flow-1",
        flow_name: "Flow",
        steps_created: 1,
        steps_updated: 0,
        steps_removed: 0
      })
      .mockResolvedValueOnce(appliedSession)
      .mockResolvedValueOnce(makePlan({ status: "applied" }));
    const { driver } = makeDriver({ fetchImpl: fetch });
    seedCreateSession(driver);

    await expect(driver.createFlowFromPlan()).rejects.toBeTruthy();
    expect(driver.state.createFailureOutcome).toBe("unknown");
    expect(driver.state.pendingOperation).toBeNull();

    // The user must still have a working retry: the same command reconciles
    // through the idempotent replay endpoint.
    const result = await driver.createFlowFromPlan();
    expect(result.flow_id).toBe("flow-1");
    expect(driver.state.applyResult?.flow_id).toBe("flow-1");
    expect(driver.state.createFailureOutcome).toBeNull();
    expect(driver.state.applyError).toBeNull();
  });

  it("reports an unknown outcome when the authoritative refresh also fails", async () => {
    const fetch = vi
      .fn()
      .mockRejectedValueOnce(new Error("network down"))
      .mockRejectedValueOnce(new Error("still down"));
    const { driver } = makeDriver({ fetchImpl: fetch });
    seedCreateSession(driver);

    await expect(driver.createFlowFromPlan()).rejects.toBeTruthy();

    expect(driver.state.createFailureOutcome).toBe("unknown");
    expect(driver.state.pendingOperation).toBeNull();
  });

  it("locks every session-mutating command while creation is pending", async () => {
    let resolveCreate: (value: unknown) => void = () => {};
    const fetch = vi.fn().mockImplementation((route: string) => {
      if (route === CREATE_ROUTE) {
        return new Promise((resolve) => {
          resolveCreate = resolve;
        });
      }
      return Promise.resolve(
        makeSession({
          status: "applied",
          target_kind: "create",
          flow_id: "flow-1",
          latest_plan_id: null
        })
      );
    });
    const { driver } = makeDriver({ fetchImpl: fetch });
    seedCreateSession(driver);

    const creating = driver.createFlowFromPlan();
    expect(driver.state.pendingOperation?.kind).toBe("creating");

    await driver.sendMessage("should be ignored");
    await driver.confirmRequirements();
    await driver.changeRequirements();
    await driver.removeAttachment("file-1");
    await driver.startFreshSession("create");
    await driver.resumeSession("session-2");
    await driver.discardSession("session-1");
    await driver.createSession("create");
    await driver.revisePlan("keep_current_description");
    await driver.retryLatestTurn();
    await driver.acknowledgeAndRetryLatestTurn();
    await driver.approvePlan();
    await expect(driver.applyPlan()).rejects.toThrow(/already in progress/);
    await expect(driver.createFlowFromPlan()).rejects.toThrow(/already in progress/);
    // The pending creation is the only request that ever reached the transport.
    expect(fetch.mock.calls.filter((call) => call[0] === CREATE_ROUTE)).toHaveLength(1);
    expect(fetch.mock.calls).toHaveLength(1);

    resolveCreate({
      flow_id: "flow-1",
      flow_name: "Flow",
      steps_created: 1,
      steps_updated: 0,
      steps_removed: 0
    });
    await creating;
    expect(driver.state.pendingOperation).toBeNull();
  });
});
