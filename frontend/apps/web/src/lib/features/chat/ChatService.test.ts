import { afterEach, describe, expect, it, vi } from "vitest";
import { ChatService, type ChatPartner } from "./ChatService.svelte";
import { projectTurnDebugDetails } from "./turnDebugProjection";

function assistantPartner(overrides: Partial<ChatPartner> = {}): ChatPartner {
  return {
    id: "assistant-1",
    type: "assistant",
    name: "Assistant",
    completion_model: {
      id: "model-1",
      name: "gpt-4o",
      token_limit: 128000
    },
    effective_config: null,
    tools: { assistants: [] },
    attachments: [{ id: "attachment-1" }],
    ...overrides
  } as ChatPartner;
}

function chatService(
  preflight = vi.fn(),
  overrides: {
    ask?: ReturnType<typeof vi.fn>;
    get?: ReturnType<typeof vi.fn>;
    getTurnDiagnostics?: ReturnType<typeof vi.fn>;
  } = {}
) {
  return new ChatService({
    eneo: {
      conversations: {
        preflight,
        ask: overrides.ask ?? vi.fn(),
        get: overrides.get ?? vi.fn(),
        getTurnDiagnostics: overrides.getTurnDiagnostics ?? vi.fn(),
        list: vi.fn().mockResolvedValue({
          items: [],
          count: 0,
          total_count: 0,
          next_cursor: null
        })
      }
    } as never,
    chatPartner: assistantPartner(),
    initialConversation: null,
    initialHistory: { items: [], count: 0, total_count: 0 }
  });
}

function completedAsk() {
  return vi.fn().mockImplementation(async ({ callbacks }) => {
    callbacks.onFirstChunk({
      id: "message-1",
      session_id: "session-1",
      answer: "",
      references: []
    });
  });
}

describe("ChatService assistant baseline preflight", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows prompt and fixed attachment tokens before the user writes", async () => {
    vi.useFakeTimers();
    const preflight = vi.fn().mockResolvedValue({
      input_tokens: 0,
      file_tokens: 0,
      prompt_tokens: 125,
      assistant_attachment_tokens: 3500,
      model_name: "gpt-4o",
      context_window: 128000
    });
    const chat = chatService(preflight);

    chat.requestPreflight("", [], undefined, 400);
    await vi.advanceTimersByTimeAsync(400);

    expect(preflight).toHaveBeenCalledWith({
      chatPartner: chat.partner,
      conversation: undefined,
      question: "",
      files: [],
      tools: undefined
    });
    expect(chat.assistantPromptTokens).toBe(125);
    expect(chat.assistantAttachmentTokens).toBe(3500);
    expect(chat.contextTokens).toBe(3625);
  });

  it("does not baseline-preflight an existing conversation", async () => {
    vi.useFakeTimers();
    const preflight = vi.fn();
    const chat = chatService(preflight);
    chat.currentConversation = { id: "session-1", name: "Existing", messages: [] };

    chat.requestPreflight("", [], undefined, 400);
    await vi.advanceTimersByTimeAsync(400);

    expect(preflight).not.toHaveBeenCalled();
    expect(chat.assistantAttachmentTokens).toBe(0);
  });
});

describe("ChatService turn diagnostics", () => {
  it("does not add a debug field to ordinary chat requests", async () => {
    const ask = completedAsk();
    const chat = chatService(vi.fn(), { ask });

    await chat.askQuestion("Hello");

    expect(ask).toHaveBeenCalledOnce();
    expect(ask.mock.calls[0][0]).not.toHaveProperty("debug");
  });

  it("delegates one persisted turn to the strict diagnostics endpoint", async () => {
    const details = {
      session_id: "session-1",
      message_id: "message-1",
      skill_activation: null
    };
    const getTurnDiagnostics = vi.fn().mockResolvedValue(details);
    const chat = chatService(vi.fn(), { getTurnDiagnostics });

    await expect(chat.getTurnDiagnostics("session-1", "message-1")).resolves.toBe(details);

    expect(getTurnDiagnostics).toHaveBeenCalledWith({
      sessionId: "session-1",
      messageId: "message-1"
    });
  });

  it.each([
    { panelOpenDuringStream: true, scenario: "when the panel is already open" },
    { panelOpenDuringStream: false, scenario: "when the panel opens after completion" }
  ])("confirms a completed live turn $scenario", async ({ panelOpenDuringStream }) => {
    let finishStream!: () => void;
    const ask = vi.fn().mockImplementation(
      ({ callbacks }) =>
        new Promise<void>((resolve) => {
          callbacks.onFirstChunk({
            id: "message-1",
            session_id: "session-1",
            question: "Hello",
            answer: "",
            completion_model: {
              id: "model-1",
              name: "gpt-4o",
              token_limit: 128_000
            },
            files: [],
            generated_files: [],
            references: [],
            tools: { assistants: [] },
            web_search_references: []
          });
          callbacks.onToolCall({
            session_id: "session-1",
            eneo_event_type: "tool_call",
            tools: [
              {
                server_name: "warehouse",
                tool_name: "query",
                result_status: "complete"
              }
            ]
          });
          finishStream = resolve;
        })
    );
    const get = vi.fn();
    const getTurnDiagnostics = vi.fn().mockResolvedValue({
      session_id: "session-1",
      message_id: "message-1",
      skill_activation: null
    });
    const chat = chatService(vi.fn(), { ask, get, getTurnDiagnostics });
    if (panelOpenDuringStream) chat.setDebugPanelOpen(true);

    const request = chat.askQuestion("Hello");
    await vi.waitFor(() => expect(chat.pendingDiagnosticsMessageIds).toEqual(["message-1"]));

    finishStream();
    await request;
    if (!panelOpenDuringStream) {
      expect(chat.pendingDiagnosticsMessageIds).toEqual(["message-1"]);
      chat.setDebugPanelOpen(true);
    }
    await vi.waitFor(() =>
      expect(getTurnDiagnostics).toHaveBeenCalledWith({
        sessionId: "session-1",
        messageId: "message-1"
      })
    );

    await vi.waitFor(() => expect(chat.pendingDiagnosticsMessageIds).toEqual([]));
    expect(get).not.toHaveBeenCalled();
    expect(chat.currentConversation.messages[0].completion_model?.name).toBe("gpt-4o");
    expect(projectTurnDebugDetails(chat.currentConversation.messages[0]).tools).toEqual([
      {
        order: 1,
        serverName: "warehouse",
        toolName: "query",
        status: "complete"
      }
    ]);
  });

  it("rehydrates pending diagnostics when the next request fails before streaming", async () => {
    const diagnostics = {
      session_id: "session-1",
      message_id: "message-1",
      skill_activation: null
    };
    let resolveStaleHydration!: (value: typeof diagnostics) => void;
    const staleHydration = new Promise<typeof diagnostics>((resolve) => {
      resolveStaleHydration = resolve;
    });
    const getTurnDiagnostics = vi
      .fn()
      .mockReturnValueOnce(staleHydration)
      .mockResolvedValueOnce(diagnostics);
    const ask = completedAsk();
    const chat = chatService(vi.fn(), { ask, getTurnDiagnostics });
    chat.setDebugPanelOpen(true);

    await chat.askQuestion("Hello");
    await vi.waitFor(() => expect(getTurnDiagnostics).toHaveBeenCalledTimes(1));
    expect(chat.pendingDiagnosticsMessageIds).toEqual(["message-1"]);

    ask.mockRejectedValueOnce(new Error("request failed before streaming"));
    await expect(chat.askQuestion("Try again")).rejects.toThrow("request failed before streaming");
    await vi.waitFor(() => expect(getTurnDiagnostics).toHaveBeenCalledTimes(2));
    expect(chat.pendingDiagnosticsMessageIds).toEqual([]);

    resolveStaleHydration(diagnostics);
  });

  it("queues a manual metadata retry until the active stream completes", async () => {
    let activeCallbacks!: {
      onFirstChunk: (chunk: object) => void;
      onText: (event: object) => void;
    };
    let finishStream!: () => void;
    const ask = vi
      .fn()
      .mockImplementationOnce(async ({ callbacks }) => {
        callbacks.onFirstChunk({
          id: "message-1",
          session_id: "session-1",
          answer: "",
          references: []
        });
      })
      .mockImplementationOnce(
        ({ callbacks }) =>
          new Promise<void>((resolve) => {
            activeCallbacks = callbacks;
            callbacks.onFirstChunk({
              id: "message-2",
              session_id: "session-1",
              answer: "",
              references: []
            });
            finishStream = resolve;
          })
      );
    const get = vi.fn();
    const getTurnDiagnostics = vi
      .fn()
      .mockRejectedValueOnce(new Error("temporary"))
      .mockResolvedValue({
        session_id: "session-1",
        message_id: "message-1",
        skill_activation: null
      });
    const chat = chatService(vi.fn(), { ask, get, getTurnDiagnostics });
    chat.setDebugPanelOpen(true);

    await chat.askQuestion("First");
    await vi.waitFor(() => expect(getTurnDiagnostics).toHaveBeenCalledTimes(1));
    expect(chat.pendingDiagnosticsRefreshFailed).toBe(true);

    const request = chat.askQuestion("Second");
    await vi.waitFor(() => expect(chat.pendingDiagnosticsMessageIds).toContain("message-2"));
    await chat.retryPendingDiagnosticsMetadata();

    expect(getTurnDiagnostics).toHaveBeenCalledTimes(1);
    expect(get).not.toHaveBeenCalled();

    activeCallbacks.onText({
      session_id: "session-1",
      answer: "Live answer",
      references: []
    });
    finishStream();
    await request;

    await vi.waitFor(() => expect(chat.pendingDiagnosticsMessageIds).toEqual([]));
    expect(chat.currentConversation.messages.at(-1)?.answer).toBe("Live answer");
    expect(get).not.toHaveBeenCalled();
  });
});
