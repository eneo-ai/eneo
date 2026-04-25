import { describe, expect, it, vi } from "vitest";

import { FlowAIBuilderDriver } from "./FlowAIBuilderDriver";
import type { AIBuilderDraftSession, AIBuilderSession, ProposedPlan } from "./protocol";

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
    expect(driver.getQuestionAnswerText(question)).toBe("Documents");
  });

  it("renders custom structured question answers for collapsed answered questions", async () => {
    const { driver } = makeDriver();
    const question = {
      question_id: "output_mode",
      question: "What should the flow produce?",
      options: [{ label: "DOCX document", id: "docx", value: "docx_document" }],
      selection_mode: "single" as const,
      allow_custom: true
    };
    driver.seedState({
      messages: [
        { role: "assistant", content: "", question, timestamp: 1 },
        {
          role: "user",
          content: "PowerPoint deck",
          metadata: {
            question_answer: {
              question_id: "output_mode",
              custom_value: "PowerPoint deck"
            }
          },
          timestamp: 2
        }
      ]
    });

    expect(driver.getQuestionAnswerText(question)).toBe("PowerPoint deck");
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

  it("initializes create mode by waiting for an explicit choice when a matching draft exists", async () => {
    const draft = makeDraft({ target_kind: "create", flow_id: null });
    const fetch = vi.fn().mockResolvedValueOnce({ sessions: [draft] });
    const { driver } = makeDriver({ fetchImpl: fetch });

    await driver.initialize("create");

    expect(driver.state.session).toBeNull();
    expect(driver.state.draftSessions).toEqual([draft]);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch).toHaveBeenCalledWith("/api/v1/flows/ai-builder/sessions", {
      method: "get",
      params: {}
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
      error: "Old error",
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

  it("suppresses raw discovery gate errors if they leak from the backend", async () => {
    const { driver } = makeDriver({
      streamImpl: vi.fn(async (_path, _init, handlers) => {
        handlers.onMessage({
          event: "error",
          data: JSON.stringify({
            error: "More discovery is needed before confirming requirements.",
            message: "More discovery is needed before confirming requirements.",
            code: "requirements_incomplete",
            phase: "requirements"
          })
        });
        handlers.onClose();
      })
    });
    driver.seedState({ session: makeSession() });

    await driver.sendMessage("Build a flow");

    expect(driver.state.error).toBeNull();
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
      "/api/v1/flows/ai-builder/sessions/session-1",
      expect.objectContaining({ method: "get" })
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
      "/api/v1/flows/ai-builder/sessions/session-1/attachments/file-1",
      expect.objectContaining({ method: "delete" })
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

  it("revises a plan with keep_current_description and refreshes current plan state", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(makePlan({ plan_id: "plan-2", status: "proposed" }));
    const { driver } = makeDriver({ fetchImpl: fetch });
    driver.seedState({
      session: makeSession({ latest_plan_id: "plan-1", status: "awaiting_approval" }),
      currentPlan: makePlan({ plan_id: "plan-1", status: "proposed" })
    });

    await driver.revisePlan("keep_current_description");

    expect(fetch).toHaveBeenCalledWith("/api/v1/flows/ai-builder/plans/plan-1/revise", {
      method: "post",
      body: JSON.stringify({ type: "keep_current_description" }),
      headers: { "Content-Type": "application/json" }
    });
    expect(driver.state.currentPlan?.plan_id).toBe("plan-2");
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
      error: "stale",
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
                  output_description: "DOCX-rapport",
                  requirements_version: "req-2"
                }
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
    expect(driver.derivePhase()).toBe("confirming");
  });
});
