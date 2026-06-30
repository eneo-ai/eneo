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

function chatService(preflight = vi.fn()) {
  return new ChatService({
    eneo: {
      conversations: {
        preflight,
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
