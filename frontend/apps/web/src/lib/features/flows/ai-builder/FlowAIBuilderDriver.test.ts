import { readFileSync } from "node:fs";

import { describe, expect, it, vi } from "vitest";

import { FlowAIBuilderDriver } from "./FlowAIBuilderDriver";
import { parseAIBuilderStreamEvent } from "./protocol";
import type {
  AIBuilderDraftSession,
  AIBuilderError,
  AIBuilderSession,
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

describe("FlowAIBuilderDriver", () => {
  it("keeps stream event contracts derived from generated types", () => {
    const source = readFileSync(new URL("./protocol.ts", import.meta.url), "utf8");

    expect(source).toContain('operations["send_ai_builder_message"]');
    expect(source).toContain("parseAIBuilderStreamEvent");
    expect(source).toContain('AIBuilderEventType = AIBuilderParsedStreamEvent["event"]');
    expect(source).toMatch(/AIBuilderTextEventData = Extract<\s*AIBuilderParsedStreamEvent/s);
    expect(source).not.toMatch(/export type AIBuilderEventType\s*=\s*\|/);
    expect(source).not.toContain("export interface AIBuilderTextEventData");
    expect(source).not.toContain("export interface AIBuilderStatusEventData");
    expect(source).not.toContain("export interface KeyDecision");
    expect(source).not.toContain("export interface RequirementsSummary");
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
          metadata: {
            question_answer: {
              question_id: "input_mode",
              selected_option_ids: ["documents"]
            }
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
        handlers.onClose();
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
      statusMessage: "Old status",
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

  it("soft-block stream errors do not set visible error state", async () => {
    const { driver } = makeDriver({
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
        handlers.onClose();
      })
    });
    driver.seedState({ session: makeSession() });

    await driver.sendMessage("Build a flow");

    expect(driver.state.error).toBeNull();
  });

  it("stores structured stream errors", async () => {
    const { driver } = makeDriver({
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
        handlers.onClose();
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

  it("sends the current UI language with AI Builder messages", async () => {
    const { driver, stream } = makeDriver({
      streamImpl: vi.fn(async (_path, init, handlers) => {
        expect(init.requestBody["application/json"].ui_language).toBeTruthy();
        handlers.onClose();
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
            question_id: "mcp_resource_selection",
            question: "Should AI Builder use MCP tools?",
            selection_mode: "single",
            allow_custom: false,
            requires_confirm: true,
            options: [
              {
                id: "use_time",
                label: "Use Time MCP",
                value: "use_mcp_server:time-server"
              }
            ]
          })
        });
        handlers.onClose();
      })
    });
    driver.seedState({ session: makeSession() });

    await driver.sendMessage("Build a flow");

    expect(driver.state.messages[1]?.question).toMatchObject({
      question_id: "mcp_resource_selection",
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
        handlers.onClose();
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
        handlers.onClose();
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

  it("forwards file_ids with AI Builder messages", async () => {
    const { driver, stream } = makeDriver({
      streamImpl: vi.fn(async (_path, init, handlers) => {
        expect(init.requestBody["application/json"].file_ids).toEqual(["file-1", "file-2"]);
        handlers.onClose();
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
        handlers.onClose();
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
        handlers.onClose();
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
        makeSession({ latest_plan_id: "plan-77", status: "awaiting_approval" })
      )
      .mockResolvedValueOnce(makePlan({ plan_id: "plan-77", status: "approved" }));
    const { driver } = makeDriver({ fetchImpl: fetch });
    driver.seedState({ session: makeSession({ session_id: "session-9", latest_plan_id: null }) });

    await driver.refreshSession();

    expect(driver.state.session?.latest_plan_id).toBe("plan-77");
    expect(driver.state.currentPlan?.plan_id).toBe("plan-77");
    expect(driver.state.currentPlan?.status).toBe("approved");
  });

  it("hydrates stored conversation when resuming a draft session", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(
        makeSession({
          session_id: "session-2",
          status: "awaiting_approval",
          latest_plan_id: "plan-9",
          conversation: [
            {
              role: "user",
              content: "Bygg ett ljudflöde",
              timestamp: "2026-03-15T10:00:00Z"
            },
            {
              role: "assistant",
              content: "Jag behöver bekräfta kraven först.",
              timestamp: "2026-03-15T10:00:05Z",
              tool_calls: [{ id: "tool-1", name: "confirm_requirements", arguments: {} }]
            },
            {
              role: "tool",
              tool_call_id: "tool-1",
              metadata: {
                requirements_summary: {
                  summary: "Transkribera ljud och skriv rapport",
                  key_decisions: [{ topic: "Språk", decision: "Turkiska" }],
                  input_description: "Ljudfil",
                  output_description: "Text",
                  requirements_version: "req-1"
                }
              }
            }
          ]
        })
      )
      .mockResolvedValueOnce({ models: [], default_model_id: null })
      .mockResolvedValueOnce(makePlan({ plan_id: "plan-9", status: "approved" }))
      .mockResolvedValueOnce({ sessions: [] });
    const { driver } = makeDriver({ fetchImpl: fetch });

    await driver.resumeSession("session-2");

    expect(driver.state.messages[0]).toMatchObject({
      role: "user",
      content: "Bygg ett ljudflöde"
    });
    expect(driver.state.messages[1]?.requirementsSummary?.summary).toBe(
      "Transkribera ljud och skriv rapport"
    );
    expect(driver.state.currentPlan?.plan_id).toBe("plan-9");
  });

  it("hydrates requirements summary stored on assistant metadata", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(
        makeSession({
          session_id: "session-3",
          status: "chatting",
          conversation: [
            {
              role: "user",
              content: "Bygg ett dokumentflöde",
              timestamp: "2026-03-15T10:00:00Z"
            },
            {
              role: "assistant",
              content: "Jag har tillräckligt med information.",
              timestamp: "2026-03-15T10:00:05Z",
              metadata: {
                requirements_summary: {
                  summary: "Analysera dokument och skapa rapport",
                  key_decisions: [{ topic: "Indata", decision: "PDF-dokument" }],
                  input_description: "PDF-filer",
                  output_description: "DOCX-rapport"
                },
                requirements_version: "req-2"
              }
            }
          ]
        })
      )
      .mockResolvedValueOnce({ models: [], default_model_id: null })
      .mockResolvedValueOnce({ sessions: [] });
    const { driver } = makeDriver({ fetchImpl: fetch });

    await driver.resumeSession("session-3");

    expect(driver.state.messages[1]?.requirementsSummary?.summary).toBe(
      "Analysera dokument och skapa rapport"
    );
    expect(driver.state.messages[1]?.requirementsSummary?.requirements_version).toBe("req-2");
    expect(driver.derivePhase()).toBe("confirming");
  });
});
