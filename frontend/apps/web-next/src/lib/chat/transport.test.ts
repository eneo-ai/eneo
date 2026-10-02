/**
 * Malformed and interrupted streams (CONTRACT.md → What the client treats as
 * failure): none of them may settle as a finished answer.
 */
import { Chat } from "@ai-sdk/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { sseResponse, toSseBody } from "./contract-fixtures";
import { createChatTransport, enforceStreamContract } from "./transport";
import type { EneoUIMessage } from "./types";

const fetchMock = vi.fn<typeof fetch>();
vi.stubGlobal("fetch", fetchMock);

afterEach(() => {
  fetchMock.mockReset();
});

const start = { type: "start", messageId: "q-1" };
const session = {
  type: "data-session",
  data: {
    session_id: "s-1",
    completion_model: null,
    files: [],
    web_search_references: [],
    mcp_tool_references: [],
    answering_assistant: null
  }
};
const textStart = { type: "text-start", id: "text-0" };
const textDelta = { type: "text-delta", id: "text-0", delta: "Hello" };
const textEnd = { type: "text-end", id: "text-0" };
const finish = { type: "finish" };

async function run(body: string) {
  fetchMock.mockResolvedValueOnce(sseResponse(body));
  let finished: { isAbort: boolean; isError: boolean } | null = null;
  const chat = new Chat<EneoUIMessage>({
    transport: createChatTransport(),
    onFinish: (args) => {
      finished = args;
    },
    onError: () => {}
  });
  await chat.sendMessage({ text: "Hi" }, { body: { files: [] } });
  return { chat, finished: finished as { isAbort: boolean; isError: boolean } | null };
}

function expectFailed(result: Awaited<ReturnType<typeof run>>) {
  expect(result.chat.status).toBe("error");
  expect(result.chat.error).toBeInstanceOf(Error);
  expect(result.finished).toMatchObject({ isAbort: false, isError: true });
}

/** The text that arrived is still shown, but never as a finished part. */
function expectPartialText(result: Awaited<ReturnType<typeof run>>, text: string) {
  expect(result.chat.lastMessage?.parts.find((part) => part.type === "text")).toMatchObject({
    text,
    state: "streaming"
  });
}

describe("a well-formed stream", () => {
  it("settles as ready", async () => {
    const result = await run(toSseBody([start, session, textStart, textDelta, textEnd, finish]));
    expect(result.chat.status).toBe("ready");
    expect(result.finished).toMatchObject({ isAbort: false, isError: false });
    expect(result.chat.lastMessage?.parts).toContainEqual({
      type: "text",
      text: "Hello",
      state: "done"
    });
  });
});

describe("a broken stream", () => {
  it("fails when the connection closes before finish", async () => {
    const result = await run(toSseBody([start, session, textStart, textDelta], { done: false }));
    expectFailed(result);
    expectPartialText(result, "Hello");
    expect(result.chat.error?.name).toBe("StreamContractError");
  });

  it("fails when [DONE] arrives without a finish part", async () => {
    const result = await run(toSseBody([start, session, textStart, textDelta, textEnd]));
    expectFailed(result);
    expect(result.chat.error?.name).toBe("StreamContractError");
  });

  it("fails on an invalid JSON event", async () => {
    const body =
      toSseBody([start, session, textStart, textDelta], { done: false }) + "data: {not json\n\n";
    const result = await run(body);
    expectFailed(result);
    expectPartialText(result, "Hello");
    expect(result.chat.error?.name).not.toBe("StreamContractError");
  });

  it("fails on an unknown part type", async () => {
    const result = await run(
      toSseBody([start, session, textStart, { type: "bogus-part", id: "x" }, textEnd, finish])
    );
    expectFailed(result);
  });

  it("fails on an unknown data part", async () => {
    const result = await run(
      toSseBody([start, session, { type: "data-unknown", data: {} }, textStart, textEnd, finish])
    );
    expectFailed(result);
    expect(result.chat.error?.message).toContain('Unknown stream part type "data-unknown"');
  });

  it("fails on a delta for a part that was never started", async () => {
    const result = await run(toSseBody([start, session, textDelta, finish]));
    expectFailed(result);
  });

  it("fails on an output for a tool call that was never announced", async () => {
    const result = await run(
      toSseBody([
        start,
        session,
        { type: "tool-output-error", toolCallId: "call-9", errorText: "denied", dynamic: true },
        finish
      ])
    );
    expectFailed(result);
  });

  it("fails on an error part even though finish follows it", async () => {
    const result = await run(
      toSseBody([
        start,
        session,
        textStart,
        textDelta,
        { type: "data-error", data: { code: 500 }, transient: true },
        { type: "error", errorText: "Model exploded" },
        textEnd,
        finish
      ])
    );
    expectFailed(result);
    expectPartialText(result, "Hello");
    expect(result.chat.error?.message).toBe("Model exploded");
  });

  it("fails on a non-2xx response", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ message: "Not found" }), {
        status: 404,
        headers: { "content-type": "application/json" }
      })
    );
    const chat = new Chat<EneoUIMessage>({ transport: createChatTransport(), onError: () => {} });
    await chat.sendMessage({ text: "Hi" }, { body: { files: [] } });
    expect(chat.status).toBe("error");
  });
});

describe("enforceStreamContract", () => {
  async function pipe(chunks: { type: string }[]) {
    const source = new ReadableStream<{ type: string }>({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(chunk);
        controller.close();
      }
    });
    const out: { type: string }[] = [];
    const reader = source
      .pipeThrough(enforceStreamContract() as unknown as TransformStream<{ type: string }>)
      .getReader();
    for (;;) {
      const { done, value } = await reader.read();
      if (done) return out;
      out.push(value);
    }
  }

  it("passes a finished stream through unchanged", async () => {
    const chunks = [start, session, textStart, textDelta, textEnd, finish];
    await expect(pipe(chunks)).resolves.toEqual(chunks);
  });

  it("accepts the error part as a terminal part", async () => {
    const chunks = [start, { type: "error", errorText: "x" }];
    await expect(pipe(chunks)).resolves.toEqual(chunks);
  });

  it("rejects a stream without a terminal part", async () => {
    await expect(pipe([start, session])).rejects.toThrow("closed before it finished");
  });
});
