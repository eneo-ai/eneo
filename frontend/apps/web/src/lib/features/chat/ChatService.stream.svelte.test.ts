import { describe, expect, it, vi } from "vitest";
import { ChatService, type ChatPartner } from "./ChatService.svelte";

// Runs in the browser project on purpose: the frame-aligned answer buffer only
// exists where requestAnimationFrame does, and that is where the ordering
// between buffered text and a withheld "<inref" prefix matters.
function chatService(ask: ReturnType<typeof vi.fn>) {
  return new ChatService({
    eneo: {
      conversations: {
        preflight: vi.fn(),
        ask,
        get: vi.fn(),
        getTurnDiagnostics: vi.fn(),
        list: vi.fn().mockResolvedValue({ items: [], count: 0, total_count: 0, next_cursor: null })
      }
    } as never,
    chatPartner: {
      id: "assistant-1",
      type: "assistant",
      name: "Assistant",
      completion_model: { id: "model-1", name: "gpt-4o", token_limit: 128000 },
      effective_config: null,
      tools: { assistants: [] },
      attachments: []
    } as unknown as ChatPartner,
    initialConversation: null,
    initialHistory: { items: [], count: 0, total_count: 0 }
  });
}

describe("ChatService stream finalization", () => {
  it("keeps arrival order when the stream ends with a withheld citation prefix", async () => {
    const ask = vi.fn().mockImplementation(async ({ callbacks }) => {
      callbacks.onFirstChunk({
        id: "message-1",
        session_id: "session-1",
        answer: "",
        references: []
      });
      // "Hello " waits for the next animation frame; "<inref" is held back as a
      // possible citation. The stream ends before either is flushed.
      callbacks.onText({ session_id: "session-1", answer: "Hello ", references: [] });
      callbacks.onText({ session_id: "session-1", answer: "<inref", references: [] });
    });
    const chat = chatService(ask);

    await chat.askQuestion("Hi");

    expect(chat.currentConversation.messages.at(-1)?.answer).toBe("Hello <inref");
  });
});
