import { describe, expect, it, vi } from "vitest";
import { EneoError } from "@eneo/eneo-js";
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

  it("keeps the specialist steps when the turn fails before any synthesis text", async () => {
    const consultation = {
      id: "consultation-1",
      ordinal: 1,
      assistant_id: "specialist-1",
      assistant_name: "HR",
      question: "Vacation days?",
      answer: "25 days.",
      status: "complete",
      tool_calls: []
    };
    const ask = vi.fn().mockImplementation(async ({ callbacks }) => {
      await callbacks.onOpen();
      callbacks.onFirstChunk({
        id: "message-1",
        session_id: "session-1",
        answer: "",
        references: []
      });
      callbacks.onEneoEvent({
        eneo_event_type: "consultation",
        session_id: "session-1",
        consultations: [consultation]
      });
      // The parent's own budget runs out before it streams a single token.
      throw new EneoError("limit", "SERVER", 422, 0, { code: "execution_limit_duration" });
    });
    const chat = chatService(ask);

    await chat.askQuestion("Plan the meeting");

    const message = chat.currentConversation.messages.at(-1);
    expect(chat.currentConversation.messages).toHaveLength(1);
    expect(message?.consultations?.map((item) => item.id)).toEqual(["consultation-1"]);
    expect(message?.answer).not.toBe("");
  });
});
