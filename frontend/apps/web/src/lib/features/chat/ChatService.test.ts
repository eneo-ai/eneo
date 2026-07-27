import { afterEach, describe, expect, it, vi } from "vitest";
import { ChatService, type ChatPartner } from "./ChatService.svelte";

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
  ])("rehydrates a completed live turn $scenario", async ({ panelOpenDuringStream }) => {
    let finishStream!: () => void;
    const ask = vi.fn().mockImplementation(
      ({ callbacks }) =>
        new Promise<void>((resolve) => {
          callbacks.onFirstChunk({
            id: "message-1",
            session_id: "session-1",
            question: "Hello",
            answer: "",
            files: [],
            generated_files: [],
            references: [],
            tools: { assistants: [] },
            web_search_references: []
          });
          finishStream = resolve;
        })
    );
    const get = vi.fn().mockResolvedValue({
      id: "session-1",
      name: "Hello",
      messages: [
        {
          id: "message-1",
          question: "Hello",
          answer: "Answer",
          completion_model: {
            id: "model-1",
            name: "gpt-4o",
            token_limit: 128000
          },
          references: [],
          files: [],
          generated_files: [],
          web_search_references: [],
          mcp_tool_references: [],
          tool_calls: [
            {
              server_name: "warehouse",
              tool_name: "query",
              result_status: "complete"
            }
          ],
          tools: { assistants: [] }
        }
      ]
    });
    const chat = chatService(vi.fn(), { ask, get });
    if (panelOpenDuringStream) chat.setDebugPanelOpen(true);

    const request = chat.askQuestion("Hello");
    await vi.waitFor(() => expect(chat.pendingDiagnosticsMessageIds).toEqual(["message-1"]));

    finishStream();
    await request;
    if (!panelOpenDuringStream) {
      expect(chat.pendingDiagnosticsMessageIds).toEqual(["message-1"]);
      chat.setDebugPanelOpen(true);
    }
    await vi.waitFor(() => expect(get).toHaveBeenCalledWith({ id: "session-1" }));

    expect(chat.pendingDiagnosticsMessageIds).toEqual([]);
    expect(chat.currentConversation.messages[0].completion_model?.name).toBe("gpt-4o");
    expect(chat.currentConversation.messages[0].tool_calls).toEqual([
      {
        server_name: "warehouse",
        tool_name: "query",
        result_status: "complete"
      }
    ]);
  });
});
