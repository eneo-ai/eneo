import { describe, expect, it, vi } from "vitest";
import { EneoError } from "@eneo/eneo-js";
import { m } from "$lib/paraglide/messages";
import { ChatService, type ChatPartner } from "./ChatService.svelte";

// Runs in the browser project on purpose: the frame-aligned answer buffer only
// exists where requestAnimationFrame does, and that is where the ordering
// between buffered text and a withheld "<inref" prefix matters.
function chatService(
  ask: ReturnType<typeof vi.fn>,
  options: { inlineStreamErrors?: boolean } = {}
) {
  return new ChatService({
    ...options,
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

describe("ChatService answers that break off mid-stream", () => {
  // Some text arrives and is rendered, then the stream fails.
  const brokenOff = () =>
    vi.fn().mockImplementation(async ({ callbacks }) => {
      callbacks.onFirstChunk({
        id: "message-1",
        session_id: "session-1",
        answer: "",
        references: []
      });
      callbacks.onText({
        session_id: "session-1",
        answer: "Biblioteket har öppet ",
        references: []
      });
      await new Promise((resolve) => setTimeout(resolve, 100));
      throw new EneoError("The AI response stream ended unexpectedly.", "SERVER", 200, 0);
    });

  it("writes the failure into the answer in the signed-in chat", async () => {
    const chat = chatService(brokenOff());

    await chat.askQuestion("När har biblioteket öppet?");

    const answer = chat.currentConversation.messages.at(-1)?.answer ?? "";
    expect(answer.startsWith(m.chat_stream_error_inline())).toBe(true);
  });

  it("keeps the partial answer and hands the failure to a caller that reports it itself", async () => {
    const chat = chatService(brokenOff(), { inlineStreamErrors: false });

    await expect(chat.askQuestion("När har biblioteket öppet?")).rejects.toBeInstanceOf(EneoError);

    expect(chat.currentConversation.messages).toHaveLength(1);
    expect(chat.currentConversation.messages.at(-1)?.answer).toBe("Biblioteket har öppet ");
  });
});
