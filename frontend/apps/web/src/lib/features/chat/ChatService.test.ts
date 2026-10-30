import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { ChatService, type ChatPartner } from "./ChatService.svelte";
import { projectTurnDebugDetails } from "./turnDebugProjection";
import {
  EneoError,
  type Conversation,
  type ConversationSparse,
  type ConversationSettings,
  type Eneo,
  type Paginated,
  type SSE,
  type UploadedFile
} from "@eneo/eneo-js";
import { m } from "$lib/paraglide/messages";
import { writable } from "svelte/store";
import { UploadsNotReadyError } from "$lib/features/attachments/AttachmentManager";

// Exercise the browser buffering path in Node when a test supplies an animation clock.
vi.mock("$app/environment", () => ({ browser: true }));

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
    get?: Mock<(conversation: Conversation) => Promise<Conversation>>;
    resolveSettings?: ReturnType<typeof vi.fn>;
    updateSettings?: ReturnType<typeof vi.fn>;
    getTurnDiagnostics?: ReturnType<typeof vi.fn>;
    initialConversation?: Conversation | null;
    partner?: ChatPartner;
    draftOwner?: { tenantId: string; userId: string };
    initialHistory?: Paginated<ConversationSparse>;
    missingConversation?: boolean;
  } = {}
) {
  return new ChatService({
    draftOwner: overrides.draftOwner,
    eneo: {
      conversations: {
        preflight,
        resolveSettings:
          overrides.resolveSettings ??
          vi.fn().mockImplementation(async ({ conversation, settings }) => {
            const saved =
              overrides.get && conversation.id ? await overrides.get(conversation) : conversation;
            const state = saved.settings;
            return {
              revision: state?.revision ?? 0,
              settings: state?.settings ??
                settings ?? { completion_model_id: "model-1", mcp_server_states: { tool: true } },
              effective_model: { id: "model-1", name: "model-1", token_limit: 128000 },
              available_models: [{ id: "model-1" }, { id: "model-2" }],
              model_unavailable: false
            };
          }),
        updateSettings:
          overrides.updateSettings ??
          vi.fn().mockImplementation(async (_conversation, settings, revision) => ({
            settings,
            revision: revision + 1
          })),
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
    chatPartner: overrides.partner ?? assistantPartner(),
    initialConversation: overrides.initialConversation ?? null,
    initialHistory: overrides.initialHistory ?? { items: [], count: 0, total_count: 0 },
    missingConversation: overrides.missingConversation
  });
}

describe("ChatService loaded page data", () => {
  it("makes the selected conversation and first history page available immediately", () => {
    const conversation = { id: "session-1", name: "Saved", messages: [] };
    const history = {
      items: [{ id: "session-1", name: "Saved" }],
      count: 1,
      total_count: 2,
      next_cursor: "next-page"
    };
    const chat = chatService(vi.fn(), {
      initialConversation: conversation,
      initialHistory: history
    });

    expect(chat.currentConversation).toEqual(conversation);
    expect(chat.loadedConversations).toEqual(history.items);
    expect(chat.totalConversations).toBe(2);
    expect(chat.hasMoreConversations).toBe(true);
  });

  it("clears the previous conversation, history and diagnostics on an empty context replacement", () => {
    const chat = chatService(vi.fn(), {
      initialConversation: { id: "session-1", name: "Saved", messages: [] },
      initialHistory: {
        items: [{ id: "session-1", name: "Saved" }],
        count: 1,
        total_count: 2,
        next_cursor: "next-page"
      }
    });
    chat.debugPanelOpen = true;
    chat.lockedInputTokens = 42;

    chat.init({ eneo: {} as never, chatPartner: assistantPartner({ id: "assistant-2" }) });

    expect(chat.partner.id).toBe("assistant-2");
    expect(chat.currentConversation.id).toBe("");
    expect(chat.currentConversation.messages).toEqual([]);
    expect(chat.loadedConversations).toEqual([]);
    expect(chat.totalConversations).toBe(0);
    expect(chat.hasMoreConversations).toBe(false);
    expect(chat.debugPanelOpen).toBe(false);
    expect(chat.lockedInputTokens).toBe(0);
  });

  it("keeps the missing-conversation notice until the user moves on", async () => {
    const conversation = { id: "session-2", name: "Other", messages: [] };
    const chat = chatService(vi.fn(), {
      get: vi.fn().mockResolvedValue(conversation),
      missingConversation: true
    });
    expect(chat.missingConversation).toBe(true);
    expect(chat.currentConversation.id).toBe("");

    chat.newConversation();
    expect(chat.missingConversation).toBe(false);

    chat.init({ eneo: {} as never, chatPartner: assistantPartner(), missingConversation: true });
    await chat.loadConversation({ id: conversation.id });
    expect(chat.missingConversation).toBe(false);
    expect(chat.currentConversation).toEqual(conversation);

    chat.init({ eneo: {} as never, chatPartner: assistantPartner(), missingConversation: true });
    chat.init({ eneo: {} as never, chatPartner: assistantPartner() });
    expect(chat.missingConversation).toBe(false);
  });
});

describe("ChatService missing-conversation recovery", () => {
  type AskRequest = Parameters<Eneo["conversations"]["ask"]>[0];
  const firstChunk: SSE.FirstChunk = {
    id: "message-1",
    session_id: "session-1",
    question: "Hello",
    answer: "Recovered",
    files: [],
    generated_files: [],
    references: [],
    tools: { assistants: [] }
  };

  beforeEach(() => {
    vi.spyOn(console, "error").mockImplementation(() => {});
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("clears the notice when a new session is confirmed, before the answer finishes", async () => {
    let finish!: () => void;
    const ask = vi.fn(async ({ callbacks }: AskRequest) => {
      await callbacks?.onOpen?.(new Response());
      callbacks?.onFirstChunk?.(firstChunk);
      await new Promise<void>((resolve) => {
        finish = resolve;
      });
    });
    const chat = chatService(vi.fn(), { ask, missingConversation: true });
    const request = chat.askQuestion("Hello");

    expect(chat.missingConversation).toBe(true);
    try {
      await vi.waitFor(() => expect(chat.currentConversation.id).toBe("session-1"));
      expect(chat.askQuestion.isLoading).toBe(true);
      expect(chat.missingConversation).toBe(false);
      expect(chat.currentConversation.messages[0].answer).toBe("Recovered");
    } finally {
      finish();
      await request;
    }
  });

  it.each([
    { outcome: "failed", failure: new EneoError("Unavailable", "SERVER", 503, 0) },
    { outcome: "cancelled", failure: new DOMException("Send cancelled", "AbortError") }
  ])(
    "keeps the notice after a $outcome send and clears it on a successful retry",
    async ({ failure }) => {
      const ask = vi
        .fn()
        .mockRejectedValueOnce(failure)
        .mockImplementationOnce(async ({ callbacks }: AskRequest) => {
          callbacks?.onFirstChunk?.(firstChunk);
        });
      const chat = chatService(vi.fn(), { ask, missingConversation: true });

      await expect(chat.askQuestion("Hello")).rejects.toBe(failure);
      expect(chat.currentConversation.id).toBe("");
      expect(chat.currentConversation.messages).toHaveLength(0);
      expect(chat.missingConversation).toBe(true);

      await chat.askQuestion("Hello");
      expect(chat.currentConversation.id).toBe("session-1");
      expect(chat.missingConversation).toBe(false);
    }
  );

  it("does not restore the notice if an answer fails after creating the new session", async () => {
    const ask = vi.fn(async ({ callbacks }: AskRequest) => {
      await callbacks?.onOpen?.(new Response());
      callbacks?.onFirstChunk?.(firstChunk);
      throw new EneoError("Answer failed", "SERVER", 200, 0);
    });
    const chat = chatService(vi.fn(), { ask, missingConversation: true });

    await chat.askQuestion("Hello");
    expect(chat.currentConversation.id).toBe("session-1");
    expect(chat.missingConversation).toBe(false);
  });

  it("ignores a late session confirmation after another missing conversation is opened", async () => {
    let confirm!: () => void;
    const ask = vi.fn(
      ({ callbacks }: AskRequest) =>
        new Promise<void>((resolve) => {
          confirm = () => {
            callbacks?.onFirstChunk?.(firstChunk);
            resolve();
          };
        })
    );
    const chat = chatService(vi.fn(), { ask, missingConversation: true });
    const request = chat.askQuestion("Hello");

    chat.init({
      eneo: {} as never,
      chatPartner: assistantPartner({ id: "assistant-2" }),
      missingConversation: true
    });
    confirm();
    await request;

    expect(chat.partner.id).toBe("assistant-2");
    expect(chat.currentConversation.id).toBe("");
    expect(chat.currentConversation.messages).toHaveLength(0);
    expect(chat.missingConversation).toBe(true);
  });
});

function completedAsk() {
  return vi.fn().mockImplementation(async ({ callbacks, settings }) => {
    callbacks.onFirstChunk({
      id: "message-1",
      session_id: "session-1",
      settings: settings ? { revision: 1, settings } : undefined,
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
      skill_context_tokens: 45,
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
      tools: undefined,
      settings: undefined,
      settingsRevision: undefined
    });
    expect(chat.assistantPromptTokens).toBe(125);
    expect(chat.assistantAttachmentTokens).toBe(3500);
    expect(chat.assistantSkillTokens).toBe(45);
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

describe("ChatService context usage", () => {
  it("uses the final provider request for headroom without changing cumulative cost", () => {
    const chat = chatService(vi.fn(), {
      initialConversation: {
        id: "session-1",
        name: "Skills",
        messages: [
          {
            id: "message-1",
            question: "Help",
            answer: "Done",
            num_tokens_question: 1020,
            num_tokens_answer: 60,
            context_prompt_tokens: 520,
            context_completion_tokens: 40,
            skill_context_tokens: 37
          }
        ]
      } as Conversation
    });

    expect(chat.lockedInputTokens).toBe(520);
    expect(chat.lockedOutputTokens).toBe(40);
    expect(chat.lockedSkillTokens).toBe(37);
    expect(chat.contextTokens).toBe(560);
    expect(chat.cumulativeTokens).toBe(1080);
  });

  it("falls back to cumulative fields for conversations saved before the new snapshot", () => {
    const chat = chatService(vi.fn(), {
      initialConversation: {
        id: "session-1",
        name: "Legacy",
        messages: [
          {
            id: "message-1",
            question: "Help",
            answer: "Done",
            num_tokens_question: 500,
            num_tokens_answer: 20
          }
        ]
      } as Conversation
    });

    expect(chat.lockedInputTokens).toBe(500);
    expect(chat.lockedOutputTokens).toBe(20);
    expect(chat.lockedSkillTokens).toBe(0);
    expect(chat.contextTokens).toBe(520);
  });

  it("applies streamed context usage without double-counting the Skill subset", async () => {
    const ask = vi.fn().mockImplementation(async ({ callbacks }) => {
      callbacks.onFirstChunk({
        id: "message-1",
        session_id: "session-1",
        answer: "",
        references: []
      });
      callbacks.onEneoEvent({
        session_id: "session-1",
        eneo_event_type: "token_usage",
        usage: {
          prompt_tokens: 1020,
          completion_tokens: 60,
          turn_tokens: 1080,
          context_prompt_tokens: 520,
          context_completion_tokens: 40,
          skill_context_tokens: 37
        }
      });
    });
    const chat = chatService(vi.fn(), { ask });

    await chat.askQuestion("Help");

    expect(chat.lockedInputTokens).toBe(520);
    expect(chat.lockedOutputTokens).toBe(40);
    expect(chat.lockedSkillTokens).toBe(37);
    expect(chat.contextTokens).toBe(560);
    expect(chat.cumulativeTokens).toBe(1080);
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
            tools: { assistants: [] }
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
        status: "complete",
        usage: null
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

describe("ChatService failed answers", () => {
  function failingAsk(code: string, partial: string) {
    return vi.fn().mockImplementation(async ({ callbacks }) => {
      await callbacks.onOpen();
      callbacks.onFirstChunk({
        id: "message-1",
        session_id: "session-1",
        answer: "",
        references: []
      });
      if (partial) callbacks.onText({ session_id: "session-1", answer: partial, references: [] });
      throw new EneoError("Backend fallback", "SERVER", 200, 0, { code, message: "x" });
    });
  }

  it("says whose side failed when an answer breaks off", async () => {
    const chat = chatService(vi.fn(), { ask: failingAsk("provider_connection_lost", "Hej") });

    await chat.askQuestion("Hello");

    expect(chat.currentConversation.messages.at(-1)?.answer).toBe(
      m.provider_failure_connection_lost()
    );
  });

  it("hands a failure before the first token to the input with its reason", async () => {
    const chat = chatService(vi.fn(), { ask: failingAsk("provider_unreachable", "") });

    await expect(chat.askQuestion("Hello")).rejects.toMatchObject({
      response: { code: "provider_unreachable" }
    });
    expect(chat.currentConversation.messages).toHaveLength(0);
  });

  describe("frame-buffered answers", () => {
    const requestFrame = vi.fn<(callback: FrameRequestCallback) => number>(() => 1);

    beforeEach(() => {
      requestFrame.mockClear();
      vi.stubGlobal("requestAnimationFrame", requestFrame);
      vi.stubGlobal("cancelAnimationFrame", vi.fn());
    });

    afterEach(() => vi.unstubAllGlobals());

    it.each([
      { scenario: "before the first frame", displayed: "", pending: "Partial answer" },
      { scenario: "between frames", displayed: "First part", pending: " tail<inref" },
      { scenario: "with only a pending citation", displayed: "", pending: "<inref" }
    ])("shows only the error $scenario", async ({ displayed, pending }) => {
      const ask = vi.fn().mockImplementation(async ({ callbacks }) => {
        await callbacks.onOpen();
        callbacks.onFirstChunk({
          id: "message-1",
          session_id: "session-1",
          answer: "",
          references: []
        });
        if (displayed) {
          callbacks.onText({ session_id: "session-1", answer: displayed, references: [] });
          requestFrame.mock.lastCall?.[0](performance.now() + 100);
        }
        callbacks.onText({ session_id: "session-1", answer: pending, references: [] });
        throw new EneoError("Failure", "SERVER", 200, 0, { code: "provider_connection_lost" });
      });
      const chat = chatService(vi.fn(), { ask });

      await chat.askQuestion("Hello");

      expect(chat.currentConversation.messages).toHaveLength(1);
      expect(chat.currentConversation.messages[0].answer).toBe(
        m.provider_failure_connection_lost()
      );
    });

    it.each(["completed", "aborted"])(
      "keeps pending text when the answer is %s",
      async (outcome) => {
        const ask = vi.fn().mockImplementation(async ({ callbacks }) => {
          await callbacks.onOpen();
          callbacks.onFirstChunk({
            id: "message-1",
            session_id: "session-1",
            answer: "",
            references: []
          });
          callbacks.onText({ session_id: "session-1", answer: "Text<inref", references: [] });
          callbacks.onReasoning({ session_id: "session-1", reasoning: "Thinking" });
          if (outcome === "aborted") throw new DOMException("Send cancelled", "AbortError");
        });
        const chat = chatService(vi.fn(), { ask });

        await chat.askQuestion("Hello");

        expect(chat.currentConversation.messages).toHaveLength(1);
        expect(chat.currentConversation.messages[0]).toMatchObject({
          answer: "Text<inref",
          reasoning: "Thinking"
        });
      }
    );

    it("does not flush a newer answer when an older request fails", async () => {
      let failOld!: (error: Error) => void;
      let finishNew!: () => void;
      const ask = vi
        .fn()
        .mockImplementationOnce(async ({ callbacks }) => {
          await callbacks.onOpen();
          callbacks.onFirstChunk({
            id: "message-1",
            session_id: "session-1",
            answer: "",
            references: []
          });
          callbacks.onText({ session_id: "session-1", answer: "Old", references: [] });
          await new Promise<void>((_, reject) => {
            failOld = reject;
          });
        })
        .mockImplementationOnce(async ({ callbacks }) => {
          await callbacks.onOpen();
          callbacks.onFirstChunk({
            id: "message-2",
            session_id: "session-1",
            answer: "",
            references: []
          });
          callbacks.onText({ session_id: "session-1", answer: "New<inref", references: [] });
          await new Promise<void>((resolve) => {
            finishNew = resolve;
          });
        });
      const chat = chatService(vi.fn(), { ask });
      const oldRequest = chat.askQuestion("First");
      await vi.waitFor(() => expect(chat.currentConversation.messages[0]?.id).toBe("message-1"));
      const newRequest = chat.askQuestion("Second");
      await vi.waitFor(() => expect(chat.currentConversation.messages[1]?.id).toBe("message-2"));

      failOld(new EneoError("Failure", "SERVER", 200, 0, { code: "provider_connection_lost" }));
      await oldRequest;
      expect(chat.currentConversation.messages[1].answer).toBe("");
      finishNew();
      await newRequest;

      expect(chat.currentConversation.messages.map(({ answer }) => answer)).toEqual([
        "Old",
        "New<inref"
      ]);
    });
  });
});

describe("ChatService independent capabilities", () => {
  it("sends capability opt-outs separately from external server IDs", async () => {
    const ask = completedAsk();
    const chat = chatService(vi.fn(), { ask });
    await chat.askQuestion("Hello", [], undefined, undefined, undefined, [
      "ordinary-server",
      "capability:image_generation"
    ]);
    expect(ask.mock.calls[0][0]).toMatchObject({
      disabledMcpServerIds: ["ordinary-server"],
      disabledCapabilities: ["image_generation"]
    });
  });

  it("refreshes a partner when only capability availability changes", () => {
    const chat = chatService();
    chat.changeChatPartner(
      assistantPartner({
        enabled_capabilities: ["image_generation"],
        available_capabilities: [
          { purpose: "image_generation", available: false, reason: "no_provider" }
        ]
      })
    );
    expect(chat.partner).toMatchObject({
      enabled_capabilities: ["image_generation"],
      available_capabilities: [{ available: false }]
    });
  });
});

describe("ChatService personal conversation model", () => {
  it("restores the saved model even when it differs from the last answer", () => {
    const partner = assistantPartner({ type: "default-assistant" });
    if (!("completion_model" in partner) || !partner.completion_model)
      throw new Error("missing model");
    const chat = chatService(vi.fn(), {
      partner,
      initialConversation: {
        id: "session-1",
        name: "Existing chat",
        settings: { revision: 3, settings: { completion_model_id: "model-1" } },
        messages: [
          {
            id: "message-1",
            question: "Hello",
            answer: "Hi",
            references: [],
            files: [],
            generated_files: [],
            tools: { assistants: [] },
            completion_model: {
              ...partner.completion_model,
              id: "model-2",
              name: "other-model",
              token_limit: 64000
            }
          }
        ]
      } as Conversation
    });

    expect(chat.selectedPersonalModel?.id).toBe("model-1");
    chat.newConversation();
    expect(chat.selectedPersonalModel).toBeNull();
  });

  it("sends the selected model to preflight and ask, then resets for a new conversation", async () => {
    vi.useFakeTimers();
    const preflight = vi.fn().mockResolvedValue({
      input_tokens: 0,
      file_tokens: 0,
      prompt_tokens: 0,
      assistant_attachment_tokens: 0,
      skill_context_tokens: 0,
      model_name: "other-model",
      context_window: 64000
    });
    const ask = completedAsk();
    const chat = chatService(preflight, { ask });
    chat.changeChatPartner(assistantPartner({ type: "default-assistant" }));
    const partner = chat.partner;
    if (!("completion_model" in partner) || !partner.completion_model)
      throw new Error("missing model");
    await chat.loadSettings();
    const chosenModel = {
      ...partner.completion_model,
      id: "model-2",
      name: "other-model",
      token_limit: 64000
    };
    chat.setModelCatalog([chosenModel]);
    await chat.selectPersonalModel(chosenModel);

    chat.requestPreflight("hello", [], undefined, 0);
    await vi.advanceTimersByTimeAsync(0);
    expect(preflight.mock.calls[0][0]).toMatchObject({
      settings: { completion_model_id: "model-2" }
    });

    await chat.askQuestion("hello");
    expect(ask.mock.calls[0][0]).toMatchObject({ settings: { completion_model_id: "model-2" } });
    expect(chat.currentConversation.settings?.revision).toBe(1);
    await chat.updateSettings({ require_tool_approval: true });
    expect(chat.currentConversation.settings?.revision).toBe(2);
    chat.newConversation();
    expect(chat.selectedPersonalModel).toBeNull();
    vi.useRealTimers();
  });
});

describe("ChatService saved conversation choices", () => {
  it("keeps history readable but blocks sends and edits for unsupported settings", async () => {
    const ask = completedAsk();
    const updateSettings = vi.fn();
    const chat = chatService(vi.fn(), {
      ask,
      updateSettings,
      resolveSettings: vi.fn().mockResolvedValue({
        revision: 2,
        settings: { require_tool_approval: false },
        settings_compatible: false
      }),
      initialConversation: {
        id: "saved",
        name: "Saved",
        messages: [],
        settings: { revision: 2, settings: {} }
      }
    });
    await chat.loadSettings();
    expect(chat.settingsError).toBeNull();
    expect(chat.currentConversation.id).toBe("saved");
    await expect(chat.askQuestion("Continue")).rejects.toThrow(
      m.conversation_settings_incompatible()
    );
    await chat.updateSettings({ require_tool_approval: false });
    expect(ask).not.toHaveBeenCalled();
    expect(updateSettings).not.toHaveBeenCalled();
  });
  it("blocks a removed model and recovers by selecting the only allowed replacement", async () => {
    const ask = completedAsk();
    const resolveSettings = vi.fn().mockImplementation(async ({ settings }) => ({
      revision: 0,
      settings: settings ?? { completion_model_id: "removed" },
      available_models: [{ id: "model-2" }],
      effective_model:
        settings?.completion_model_id === "model-2"
          ? { id: "model-2", name: "model-2", token_limit: 64000 }
          : null,
      model_unavailable: settings?.completion_model_id !== "model-2"
    }));
    const chat = chatService(vi.fn(), { ask, resolveSettings });
    await chat.loadSettings();
    await expect(chat.askQuestion("hello")).rejects.toThrow(
      m.conversation_settings_model_unavailable()
    );
    expect(ask).not.toHaveBeenCalled();
    await chat.updateSettings({ completion_model_id: "model-2" });
    expect(chat.settingsResolution?.model_unavailable).toBe(false);
    await chat.askQuestion("hello");
    expect(ask).toHaveBeenCalledWith(
      expect.objectContaining({ settings: { completion_model_id: "model-2" } })
    );
  });

  it("lets an older conversation replace an unavailable default before initializing settings", async () => {
    const updateSettings = vi.fn().mockResolvedValue({
      revision: 1,
      settings: { completion_model_id: "replacement" }
    });
    const resolveSettings = vi
      .fn()
      .mockResolvedValueOnce({
        revision: 0,
        settings: { completion_model_id: "removed" },
        model_unavailable: true,
        available_models: [{ id: "replacement" }]
      })
      .mockResolvedValue({
        revision: 1,
        settings: { completion_model_id: "replacement" },
        effective_model: { id: "replacement" }
      });
    const chat = chatService(vi.fn(), {
      initialConversation: { id: "legacy", name: "Legacy", messages: [] },
      resolveSettings,
      updateSettings
    });
    await chat.loadSettings();
    expect(updateSettings).not.toHaveBeenCalled();
    expect(chat.settingsError).toBeNull();
    expect(chat.settingsResolution?.available_models?.[0].id).toBe("replacement");
    await chat.updateSettings({ completion_model_id: "replacement" });
    expect(updateSettings.mock.lastCall?.[2]).toBe(0);
    expect(chat.currentConversation.settings?.revision).toBe(1);
    expect(chat.settings?.completion_model_id).toBe("replacement");
  });

  it("saves tools, approval and reasoning together, then reloads them in another client", async () => {
    const conversation: Conversation = {
      id: "saved",
      name: "Saved",
      messages: [],
      settings: { revision: 1, settings: {} }
    };
    const updateSettings = vi
      .fn()
      .mockImplementation(async (_id, settings: ConversationSettings, revision: number) => {
        conversation.settings = { settings, revision: revision + 1 };
        return conversation.settings;
      });
    const chat = chatService(vi.fn(), {
      initialConversation: structuredClone(conversation),
      updateSettings
    });
    await chat.loadSettings();
    await chat.updateSettings({
      mcp_server_states: { tool: false },
      require_tool_approval: true,
      reasoning_effort: "high"
    });
    expect(conversation.settings?.revision).toBe(2);
    const reopened = chatService(vi.fn(), { initialConversation: conversation });
    expect(reopened.settings).toEqual(chat.settings);
    chat.newConversation();
    await chat.loadSettings();
    expect(chat.settings?.mcp_server_states).toEqual({ tool: true });
    expect(reopened.settings?.mcp_server_states).toEqual({ tool: false });
  });

  it("adopts a newer revision saved elsewhere between its save and resolution", async () => {
    const latest = {
      revision: 3,
      settings: { require_tool_approval: true, mcp_server_states: { tool: false } },
      effective_model: { id: "model-1", name: "model-1", token_limit: 128000 }
    };
    const updateSettings = vi.fn().mockResolvedValue({ revision: 2, settings: {} });
    const chat = chatService(vi.fn(), {
      initialConversation: {
        id: "saved",
        name: "Saved",
        messages: [],
        settings: { revision: 1, settings: {} }
      },
      updateSettings,
      resolveSettings: vi.fn().mockResolvedValue(latest)
    });
    await chat.updateSettings({ reasoning_effort: "high" });
    expect(chat.currentConversation.settings?.revision).toBe(3);
    expect(chat.settings).toEqual(latest.settings);
    await chat.updateSettings({ require_tool_approval: false });
    expect(updateSettings.mock.lastCall?.[2]).toBe(3);
  });

  it("does not leak a late save into the next conversation", async () => {
    let finish!: (value: { revision: number; settings: ConversationSettings }) => void;
    const chat = chatService(vi.fn(), {
      initialConversation: {
        id: "old",
        name: "Old",
        messages: [],
        settings: { revision: 1, settings: {} }
      },
      updateSettings: vi.fn().mockImplementation(
        () =>
          new Promise((resolve) => {
            finish = resolve;
          })
      )
    });
    const save = chat.updateSettings({ require_tool_approval: true });
    chat.newConversation();
    await chat.loadSettings();
    finish({ revision: 2, settings: { require_tool_approval: true } });
    await save;
    expect(chat.currentConversation.id).toBe("");
    expect(chat.settings?.require_tool_approval).toBeUndefined();
  });

  it("reloads the saved choices after a rejected send instead of locking the composer", async () => {
    const rejected = new EneoError("Attachment too large", "RESPONSE", 400, 0);
    const ask = vi
      .fn()
      .mockRejectedValueOnce(rejected)
      .mockImplementation(async ({ callbacks }) => {
        callbacks.onFirstChunk({
          id: "message-2",
          session_id: "saved",
          answer: "",
          references: []
        });
      });
    const resolveSettings = vi.fn().mockResolvedValue({
      revision: 2,
      settings: { require_tool_approval: false },
      effective_model: { id: "model-1", name: "model-1", token_limit: 128000 },
      available_models: [],
      model_unavailable: false
    });
    const chat = chatService(vi.fn(), {
      ask,
      resolveSettings,
      initialConversation: {
        id: "saved",
        name: "Saved",
        messages: [],
        settings: { revision: 2, settings: {} }
      }
    });
    await chat.loadSettings();
    const resolved = resolveSettings.mock.calls.length;
    await expect(chat.askQuestion("hello")).rejects.toThrow("Attachment too large");
    // The failure belongs to the answer; the choices are re-read, not locked.
    expect(chat.settingsError).toBeNull();
    expect(resolveSettings.mock.calls.length).toBeGreaterThan(resolved);
    await vi.waitFor(() => expect(chat.settingsBusy).toBe(false));
    await chat.askQuestion("hello again");
    expect(ask).toHaveBeenCalledTimes(2);
  });

  it("keeps saved choices on a conflict and blocks send until the user reloads", async () => {
    const ask = completedAsk();
    const conflict = new EneoError("Changed elsewhere", "RESPONSE", 409, 0);
    const latest: Conversation = {
      id: "saved",
      name: "Saved",
      messages: [],
      settings: { revision: 3, settings: { require_tool_approval: true } }
    };
    const chat = chatService(vi.fn(), {
      ask,
      initialConversation: { ...latest, settings: { revision: 2, settings: {} } },
      updateSettings: vi.fn().mockRejectedValue(conflict),
      get: vi.fn().mockResolvedValue(latest)
    });
    await chat.loadSettings();
    await chat.updateSettings({ reasoning_effort: "high" });
    expect(chat.settingsError).toBe(conflict);
    expect(chat.settings?.reasoning_effort).toBeUndefined();
    await expect(chat.askQuestion("hello")).rejects.toThrow("Changed elsewhere");
    expect(ask).not.toHaveBeenCalled();
    const reload = chat.loadSettings(true);
    expect(chat.settingsError).toBe(conflict);
    await reload;
    expect(chat.settingsError).toBeNull();
    expect(chat.currentConversation.settings?.revision).toBe(3);
    expect(chat.settings?.require_tool_approval).toBe(true);
  });
});

describe("ChatService citation withholding", () => {
  it("shows a finished citation at once and holds only the unfinished one", async () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any -- test double for the stream callbacks
    let activeCallbacks: any;
    let finishStream: () => void = () => {};
    const ask = vi.fn().mockImplementationOnce(
      ({ callbacks }) =>
        new Promise<void>((resolve) => {
          activeCallbacks = callbacks;
          callbacks.onFirstChunk({
            id: "message-1",
            session_id: "session-1",
            answer: "",
            references: []
          });
          finishStream = resolve;
        })
    );
    const chat = chatService(vi.fn(), { ask });
    const request = chat.askQuestion("Hello");
    await vi.waitFor(() => expect(activeCallbacks).toBeDefined());
    const answer = () => chat.currentConversation.messages.at(-1)?.answer;

    // One provider chunk carries a complete citation and the start of the next.
    activeCallbacks.onText({
      session_id: "session-1",
      answer: 'Se <inref id="aaaaaaaa"/> och <inref id="bbbb',
      references: []
    });
    expect(answer()).toBe('Se <inref id="aaaaaaaa"/> och ');

    activeCallbacks.onText({ session_id: "session-1", answer: 'bbbb"/> för mer.', references: [] });
    expect(answer()).toBe('Se <inref id="aaaaaaaa"/> och <inref id="bbbbbbbb"/> för mer.');

    finishStream();
    await request;
    expect(answer()).toBe('Se <inref id="aaaaaaaa"/> och <inref id="bbbbbbbb"/> för mer.');
  });
});

describe("file creation streaming", () => {
  it.each(["docx", "pdf", "xlsx"])(
    "exposes the %s draft from call start through streamed arguments",
    async (format) => {
      let callbacks: Record<string, (event: unknown) => void>;
      let finish!: () => void;
      const ask = vi.fn().mockImplementation((request) => {
        callbacks = request.callbacks;
        callbacks.onFirstChunk({
          id: "message-1",
          session_id: "session-1",
          answer: "",
          files: [],
          generated_files: [],
          references: [],
          tools: { assistants: [] }
        });
        callbacks.onToolCall({
          session_id: "session-1",
          tools: [
            {
              tool_call_id: "create",
              server_name: "Documents",
              tool_name: "create",
              purpose: "file_creation",
              result_status: "pending"
            }
          ]
        });
        return new Promise<void>((resolve) => {
          finish = resolve;
        });
      });
      const chat = chatService(vi.fn(), { ask });
      const pending = chat.askQuestion("Create report");
      await vi.waitFor(() => expect(chat.writingDocument?.callId).toBe("create"));
      callbacks!.onToolCallDelta({
        session_id: "session-1",
        tool_call_id: "create",
        arguments_delta: `{"format":"${format}","title":"Report",`
      });
      callbacks!.onToolCallDelta({
        session_id: "session-1",
        tool_call_id: "create",
        arguments_delta:
          format === "xlsx"
            ? '"sheets":[{"name":"Costs","columns":["Budget"],"rows":[[123]]}]}'
            : '"content":"Actual report text"}'
      });
      expect(chat.writingDocument?.title).toBe("Report");
      if (format === "xlsx") expect(chat.writingDocument?.sheets?.[0].rows).toEqual([["123"]]);
      else expect(chat.writingDocument?.text).toContain("Actual report text");
      finish();
      await pending;
      expect(chat.writingDocument).toBeNull();
    }
  );
});

it("uses the available title and body when complete call metadata overtakes partial arguments", async () => {
  let callbacks!: Record<string, (event: unknown) => void>;
  let finish!: () => void;
  const call = {
    tool_call_id: "report",
    server_name: "Documents",
    tool_name: "create_document",
    purpose: "file_creation",
    result_status: "pending"
  };
  const ask = vi.fn().mockImplementation((request) => {
    callbacks = request.callbacks;
    callbacks.onFirstChunk({
      id: "message-1",
      session_id: "session-1",
      answer: "",
      files: [],
      generated_files: [],
      references: [],
      tools: { assistants: [] }
    });
    callbacks.onToolCall({ session_id: "session-1", tools: [call] });
    return new Promise<void>((resolve) => {
      finish = resolve;
    });
  });
  const chat = chatService(vi.fn(), { ask });
  const request = chat.askQuestion("Create a report");
  await vi.waitFor(() => expect(chat.writingDocument?.callId).toBe("report"));
  callbacks.onToolCallDelta({
    session_id: "session-1",
    tool_call_id: "report",
    arguments_delta: '{"format":"docx",'
  });
  expect(chat.writingDocument?.title).toBe("");
  const title = "Budgetuppföljning jan–aug 2025";
  callbacks.onToolCall({
    session_id: "session-1",
    tools: [
      {
        ...call,
        result_status: "approved",
        arguments: { format: "docx", title, content: "Rapportens innehåll" }
      }
    ]
  });
  expect(chat.writingDocument?.title).toBe(title);
  expect(chat.writingDocument?.text).toContain("Rapportens innehåll");
  // The file event can precede final metadata; an empty recorded list must
  // not bring the draft back over the saved document.
  callbacks.onToolCall({
    session_id: "session-1",
    tools: [{ ...call, result_status: "approved", generated_file_ids: [] }]
  });
  callbacks.onImage({
    session_id: "session-1",
    tool_call_id: "report",
    generated_files: [
      {
        id: "saved-report",
        name: "report.docx",
        mimetype: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        size: 100
      }
    ]
  });
  expect(chat.generatedFileIdsOf({ ...call, generated_file_ids: [] })).toEqual(["saved-report"]);
  expect(chat.writingDocument).toBeNull();
  finish();
  await request;
});

describe("pending question", () => {
  const question = (chat: ChatService) =>
    chat.currentConversation.messages.map((message) => message.question);

  it("shows the question before the backend has answered", async () => {
    let callbacks!: { onOpen: () => Promise<void>; onFirstChunk: (chunk: object) => void };
    let finish!: () => void;
    const ask = vi.fn().mockImplementation(
      ({ callbacks: received }) =>
        new Promise<void>((resolve) => {
          callbacks = received;
          finish = resolve;
        })
    );
    const chat = chatService(vi.fn(), { ask });

    const sending = chat.askQuestion("Hello");
    expect(question(chat)).toEqual(["Hello"]);
    expect(chat.askQuestion.isLoading).toBe(true);

    await callbacks.onOpen();
    callbacks.onFirstChunk({
      id: "message-1",
      session_id: "session-1",
      answer: "",
      references: []
    });
    expect(chat.currentConversation.messages[0].id).toBe("message-1");
    expect(chat.currentConversation.id).toBe("session-1");
    finish();
    await sending;
    expect(question(chat)).toEqual(["Hello"]);
  });

  it("takes the question back out when the request fails before the backend accepts it", async () => {
    const ask = vi.fn().mockRejectedValue(new Error("context window exceeded"));
    const chat = chatService(vi.fn(), { ask });

    await expect(chat.askQuestion("Too long")).rejects.toThrow("context window exceeded");
    expect(question(chat)).toEqual([]);
  });

  it("takes the question back out when the send is cancelled before it was accepted", async () => {
    const controller = new AbortController();
    const ask = vi.fn().mockImplementation(() => {
      controller.abort();
      return Promise.reject(new DOMException("The user aborted a request.", "AbortError"));
    });
    const chat = chatService(vi.fn(), { ask });

    await expect(chat.askQuestion("Hello", [], undefined, false, controller)).rejects.toThrow();
    expect(question(chat)).toEqual([]);
  });

  it("keeps the question when the stream is stopped after the backend accepted it", async () => {
    const controller = new AbortController();
    const ask = vi.fn().mockImplementation(async ({ callbacks }) => {
      await callbacks.onOpen();
      controller.abort();
      throw new Error("The operation was aborted");
    });
    const chat = chatService(vi.fn(), { ask });

    await chat.askQuestion("Hello", [], undefined, false, controller);
    expect(question(chat)).toEqual(["Hello"]);
  });

  it("does not send a question whose stop was pressed before its turn came", async () => {
    const controller = new AbortController();
    controller.abort();
    const ask = vi.fn();
    const chat = chatService(vi.fn(), { ask });

    await expect(chat.askQuestion("Hello", [], undefined, false, controller)).rejects.toThrow();
    expect(ask).not.toHaveBeenCalled();
    expect(question(chat)).toEqual([]);
  });

  it("removes a stale pending question that a newer request has already replaced", async () => {
    let failFirst!: (error: Error) => void;
    const ask = vi
      .fn()
      .mockImplementationOnce(
        () =>
          new Promise<void>((_, reject) => {
            failFirst = reject;
          })
      )
      .mockImplementationOnce(completedAsk());
    const chat = chatService(vi.fn(), { ask });

    const first = chat.askQuestion("First");
    await chat.askQuestion("Second");
    expect(question(chat)).toEqual(["First", "Second"]);

    failFirst(new Error("late failure"));
    await first;
    expect(question(chat)).toEqual(["Second"]);
  });

  it("merges first-chunk tool references with those that streamed ahead of it", async () => {
    const ask = vi.fn().mockImplementation(async ({ callbacks }) => {
      await callbacks.onOpen();
      callbacks.onToolCall({
        session_id: "",
        tools: [{ tool_call_id: "call-1", server_name: "warehouse", tool_name: "query" }],
        mcp_tool_references: [{ id: "ref-a" }]
      });
      callbacks.onFirstChunk({
        id: "message-1",
        session_id: "",
        answer: "",
        references: [],
        mcp_tool_references: [{ id: "ref-b" }]
      });
    });
    const chat = chatService(vi.fn(), { ask });

    await chat.askQuestion("Hello");
    expect(chat.currentConversation.messages[0].mcp_tool_references?.map((r) => r.id)).toEqual([
      "ref-a",
      "ref-b"
    ]);
  });

  describe("with attachments still uploading", () => {
    type Listed = {
      id: string;
      file: File;
      status: "queued" | "uploading" | "completed";
      progress: number;
      fileRef?: UploadedFile;
      remove: () => void;
    };
    const uploadedFile = (name: string) =>
      ({ id: `server-${name}`, name, mimetype: "text/plain", size: 3 }) as UploadedFile;

    function batch(ids: string[]) {
      const store = writable<Listed[]>(
        ids.map((id) => ({
          id,
          file: new File(["abc"], `${id}.txt`, { type: "text/plain" }),
          status: "uploading",
          progress: 0,
          remove: () => {}
        }))
      );
      let resolveReady!: (files: UploadedFile[]) => void;
      let rejectReady!: (error: Error) => void;
      const readyPromise = new Promise<UploadedFile[]>((resolve, reject) => {
        resolveReady = resolve;
        rejectReady = reject;
      });
      const ready = vi.fn(() => readyPromise);
      return {
        pending: { ids, subscribe: store.subscribe, ready },
        store,
        ready,
        complete: () => {
          store.update((list) =>
            list.map((item) => ({
              ...item,
              status: "completed" as const,
              progress: 100,
              fileRef: uploadedFile(item.id)
            }))
          );
          resolveReady(ids.map(uploadedFile));
        },
        fail: () => rejectReady(new UploadsNotReadyError("failed", "upload failed"))
      };
    }

    it("waits in the conversation, mirroring upload progress, and sends once they are ready", async () => {
      const ask = completedAsk();
      const chat = chatService(vi.fn(), { ask });
      const uploads = batch(["a", "b"]);

      const sending = chat.askQuestion("Read these", uploads.pending);
      const message = chat.currentConversation.messages[0] as {
        question: string;
        files: UploadedFile[];
        pending_uploads?: Array<{ id: string; progress: number; status: string }>;
      };
      expect(message.question).toBe("Read these");
      expect(message.pending_uploads?.map((upload) => upload.id)).toEqual(["a", "b"]);
      expect(ask).not.toHaveBeenCalled();

      uploads.store.update((list) =>
        list.map((item) => (item.id === "a" ? { ...item, progress: 40 } : item))
      );
      expect(message.pending_uploads?.[0].progress).toBe(40);

      uploads.complete();
      await sending;
      expect(ask).toHaveBeenCalledWith(
        expect.objectContaining({ files: [{ id: "server-a" }, { id: "server-b" }] })
      );
      expect(message.pending_uploads).toBeUndefined();
      expect(message.files.map((file) => file.id)).toEqual(["server-a", "server-b"]);
    });

    it("takes the question back out when an upload fails", async () => {
      const ask = vi.fn();
      const chat = chatService(vi.fn(), { ask });
      const uploads = batch(["a"]);

      const sending = chat.askQuestion("Read this", uploads.pending);
      expect(question(chat)).toEqual(["Read this"]);

      uploads.fail();
      await expect(sending).rejects.toBeInstanceOf(UploadsNotReadyError);
      expect(ask).not.toHaveBeenCalled();
      expect(question(chat)).toEqual([]);
      expect(chat.askQuestion.isLoading).toBe(false);
    });
  });
});

describe("ChatService browser start choices", () => {
  const owner = { tenantId: "tenant", userId: "user" };
  beforeEach(() => {
    const values = new Map<string, string>();
    vi.stubGlobal("localStorage", {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value),
      clear: () => values.clear()
    });
  });
  afterEach(() => vi.unstubAllGlobals());

  it("carries the setup into new chats and a fresh page without persisting a session", async () => {
    const updateSettings = vi.fn();
    const chat = chatService(vi.fn(), { draftOwner: owner, updateSettings });
    await chat.loadSettings();
    await chat.updateSettings({
      completion_model_id: "model-2",
      require_tool_approval: true,
      mcp_server_states: { tool: false },
      capability_states: { web_search: false }
    });
    chat.newConversation();
    await chat.loadSettings();
    expect(chat.settings).toMatchObject({
      completion_model_id: "model-2",
      require_tool_approval: true,
      mcp_server_states: { tool: false },
      capability_states: { web_search: false }
    });
    const fresh = chatService(vi.fn(), { draftOwner: owner });
    await fresh.loadSettings();
    expect(fresh.settings).toEqual(chat.settings);
    expect(updateSettings).not.toHaveBeenCalled();
    localStorage.clear();
    chat.newConversation();
    await chat.loadSettings();
    expect(chat.settings?.completion_model_id).toBe("model-1");
  });

  it("keeps saved choices and browser start choices apart when a conversation is opened", async () => {
    const draft = chatService(vi.fn(), { draftOwner: owner });
    await draft.loadSettings();
    await draft.updateSettings({ completion_model_id: "model-2" });
    const existing = chatService(vi.fn(), {
      draftOwner: owner,
      initialConversation: {
        id: "saved",
        name: "Saved",
        messages: [],
        settings: { revision: 3, settings: { completion_model_id: "model-1" } }
      }
    });
    await existing.loadSettings();
    expect(existing.settings?.completion_model_id).toBe("model-1");
    expect(existing.currentConversation.settings?.revision).toBe(3);
    // Reading the saved conversation did not replace the browser's start choices.
    const next = chatService(vi.fn(), { draftOwner: owner });
    await next.loadSettings();
    expect(next.settings?.completion_model_id).toBe("model-2");
    // A change made inside the saved conversation does become the next start choice.
    await existing.updateSettings({ require_tool_approval: true });
    const later = chatService(vi.fn(), { draftOwner: owner });
    await later.loadSettings();
    expect(later.settings).toMatchObject({
      completion_model_id: "model-1",
      require_tool_approval: true
    });
  });
});
