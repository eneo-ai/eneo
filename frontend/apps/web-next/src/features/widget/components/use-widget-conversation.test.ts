// @vitest-environment jsdom
import type { WidgetClient } from "@eneo/eneo-js";
import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { type AskResult, useWidgetConversation } from "./use-widget-conversation";

const SESSION = "11111111-2222-4333-8444-555555555555";

type Callbacks = NonNullable<Parameters<WidgetClient["conversations"]["ask"]>[0]["callbacks"]>;

/**
 * A client whose stream delivers the first chunk and one piece of text at
 * once, then stays open until the test finishes or fails it.
 */
function streamingClient() {
  const stream: { finish: () => void; fail: (error: unknown) => void } = {
    finish: () => {},
    fail: () => {}
  };
  const ask = vi.fn(({ question, callbacks }: { question: string; callbacks?: Callbacks }) => {
    const message = {
      id: "m1",
      session_id: SESSION,
      question,
      answer: "",
      files: [],
      generated_files: [],
      references: [],
      tools: { assistants: [] },
      mcp_tool_references: []
    };
    callbacks?.onFirstChunk?.(message as never);
    callbacks?.onText?.({ answer: "Pour over:", references: [] } as never);
    return new Promise<typeof message>((resolve, reject) => {
      stream.finish = () => resolve({ ...message, answer: "Pour over: 15 g kaffe." });
      stream.fail = reject;
    });
  });
  const client = {
    conversations: { ask, get: vi.fn(), leaveFeedback: vi.fn() }
  } as unknown as WidgetClient;
  return { client, ask, stream };
}

describe("useWidgetConversation", () => {
  it("answers done with the conversation when the stream finishes", async () => {
    const { client, stream } = streamingClient();
    const { result } = renderHook(() => useWidgetConversation(client));
    let asked!: Promise<AskResult>;
    act(() => {
      asked = result.current.ask("Hur brygger jag?");
    });
    expect(result.current.asking).toBe(true);
    await act(async () => stream.finish());
    await expect(asked).resolves.toEqual({
      status: "done",
      sessionId: SESSION,
      answer: "Pour over: 15 g kaffe."
    });
    expect(result.current.asking).toBe(false);
    expect(result.current.conversation.id).toBe(SESSION);
  });

  it.each([
    ["finishes", (stream: { finish: () => void }) => stream.finish()],
    ["fails", (stream: { fail: (error: unknown) => void }) => stream.fail(new Error("aborted"))]
  ])(
    "answers cancelled, keeping nothing, when the question was reset before its stream %s",
    async (_outcome, settle) => {
      const { client, stream } = streamingClient();
      const { result } = renderHook(() => useWidgetConversation(client));
      let asked!: Promise<AskResult>;
      act(() => {
        asked = result.current.ask("Hur brygger jag?");
      });
      expect(result.current.conversation.id).toBe(SESSION);

      act(() => result.current.reset());
      expect(result.current.conversation).toEqual({ id: null, messages: [], feedback: null });
      expect(result.current.asking).toBe(false);

      await act(async () => settle(stream));
      await expect(asked).resolves.toEqual({ status: "cancelled" });
      // Neither the finished answer nor the failure reaches the new conversation.
      expect(result.current.conversation).toEqual({ id: null, messages: [], feedback: null });
      expect(result.current.asking).toBe(false);
    }
  );
});
