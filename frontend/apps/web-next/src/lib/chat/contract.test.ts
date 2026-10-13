/**
 * The chat stream contract, client side (CONTRACT.md): every shared fixture
 * is fed through the pinned `ai` / `@ai-sdk/react` versions by way of the
 * app's own transport, and the settled request must match the projection
 * the fixture declares. The backend suite asserts the encoder produces the
 * same fixtures (backend/tests/unittests/conversations/test_ui_message_stream_fixtures.py).
 */
import { Chat } from "@ai-sdk/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { loadFixtures, sseResponse, toSseBody, type StreamFixture } from "./contract-fixtures";
import { createChatTransport } from "./transport";
import type { EneoUIMessage } from "./types";

type FinishArgs = { isAbort: boolean; isError: boolean; isDisconnect: boolean };
type DataPart = { type: string; data: unknown };

const fetchMock = vi.fn<typeof fetch>();
vi.stubGlobal("fetch", fetchMock);

afterEach(() => {
  fetchMock.mockReset();
});

/** A chat wired like chat-view.tsx: our transport, callbacks, no automation. */
function createHarness() {
  const data: DataPart[] = [];
  const errors: Error[] = [];
  let finish: FinishArgs | null = null;
  const chat = new Chat<EneoUIMessage>({
    transport: createChatTransport(),
    // The SDK keeps the first chunk of a reconciled data part as the part and
    // overwrites its `data` on every update, so snapshot what arrived.
    onData: (part) => data.push({ type: part.type, data: structuredClone(part.data) }),
    onError: (error) => errors.push(error),
    onFinish: (args) => {
      finish = args;
    }
  });
  const send = () =>
    chat.sendMessage(
      { text: "What is in a.txt?" },
      { body: { session_id: null, assistant_id: "assistant-1", files: [] } }
    );
  return { chat, data, errors, send, finish: () => finish };
}

async function settle(fixture: StreamFixture) {
  fetchMock.mockResolvedValueOnce(
    sseResponse(toSseBody(fixture.events, { done: fixture.terminal !== "truncated" }))
  );
  const harness = createHarness();
  await harness.send();
  return harness;
}

const fixtures = loadFixtures();

it("covers every fixture the backend ships", () => {
  expect(fixtures.map((fixture) => fixture.name)).toEqual([
    "backend-error",
    "cancelled-mid-stream",
    "file-part",
    "plain-text",
    "reasoning-and-text",
    "sources",
    "tool-approval-approved",
    "tool-approval-denied",
    "tool-approval-timeout",
    "tool-call-with-output",
    "tool-failure"
  ]);
});

describe.each(fixtures)("$name", (fixture) => {
  it("settles with the declared status and message parts", async () => {
    const { chat, finish } = await settle(fixture);

    expect(chat.status).toBe(fixture.ui.status);
    const answer = chat.lastMessage;
    expect(answer?.id).toBe(fixture.ui.message.id);
    expect(answer?.role).toBe("assistant");
    expect(answer?.parts).toEqual(fixture.ui.message.parts);

    const finished = finish();
    expect(finished).not.toBeNull();
    expect(finished!.isAbort).toBe(false);
    expect(finished!.isError).toBe(fixture.ui.status === "error");
  });

  it("sends exactly one request and never resubmits", async () => {
    await settle(fixture);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("keeps transient parts out of the message", async () => {
    const { chat, data } = await settle(fixture);
    const transientTypes = fixture.events
      .filter((event) => event.transient === true)
      .map((event) => event.type);
    for (const type of transientTypes) {
      expect(data.map((part) => part.type)).toContain(type);
      expect(chat.lastMessage?.parts.map((part) => part.type)).not.toContain(type);
    }
  });

  if (fixture.terminal === "error") {
    it("fails with the backend's error text and code", async () => {
      const { chat, errors, data } = await settle(fixture);
      expect(chat.error?.message).toBe(fixture.ui.error!.message);
      expect(errors.map((error) => error.message)).toEqual([fixture.ui.error!.message]);
      expect(data.find((part) => part.type === "data-error")?.data).toEqual({
        code: fixture.ui.error!.code
      });
    });
  }
});

describe("request body", () => {
  it("sends the ConversationBody (latest question only, stream: true)", async () => {
    await settle(fixtures.find((fixture) => fixture.name === "plain-text")!);

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe("/api/chat");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(init?.body as string)).toEqual({
      question: "What is in a.txt?",
      session_id: null,
      assistant_id: "assistant-1",
      files: [],
      stream: true
    });
  });
});

describe("tool approval", () => {
  const approved = fixtures.find((fixture) => fixture.name === "tool-approval-approved")!;

  it("resolves the pending approval part in place and runs the call on the same stream", async () => {
    const { chat, data } = await settle(approved);

    const approvalUpdates = data.filter((part) => part.type === "data-tool-approval");
    expect(approvalUpdates.map((part) => (part.data as { status: string }).status)).toEqual([
      "pending",
      "approved"
    ]);
    const approvalParts = chat.lastMessage!.parts.filter(
      (part) => part.type === "data-tool-approval"
    );
    expect(approvalParts).toHaveLength(1);
    expect(approvalParts[0]).toMatchObject({ id: "approval-1", data: { status: "approved" } });
    expect(chat.lastMessage!.parts).toContainEqual(
      expect.objectContaining({
        type: "dynamic-tool",
        toolCallId: "call-1",
        state: "output-available"
      })
    );
  });

  it("never asks the SDK to execute or resubmit tools", async () => {
    const { chat } = await settle(approved);
    // No onToolCall, no sendAutomaticallyWhen: one request, no tool output added client-side.
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(chat.lastMessage!.parts.filter((part) => part.type === "dynamic-tool")).toEqual([
      expect.objectContaining({ output: { status: "succeeded" } })
    ]);
  });
});

describe("cancelled mid-stream", () => {
  const cancelled = fixtures.find((fixture) => fixture.name === "cancelled-mid-stream")!;

  it("is an abort, not an error, when the user stops the answer", async () => {
    const encoder = new TextEncoder();
    let controller!: ReadableStreamDefaultController<Uint8Array>;
    const body = new ReadableStream<Uint8Array>({
      start(c) {
        controller = c;
      }
    });
    fetchMock.mockResolvedValueOnce(sseResponse(body));
    const harness = createHarness();

    const pending = harness.send();
    controller.enqueue(encoder.encode(toSseBody(cancelled.events, { done: false })));
    await vi.waitFor(() => {
      const text = harness.chat.lastMessage?.parts.find((part) => part.type === "text");
      expect(text).toMatchObject({ text: "Hello" });
    });

    await harness.chat.stop();
    await pending;

    expect(harness.chat.status).toBe("ready");
    expect(harness.chat.error).toBeUndefined();
    expect(harness.finish()).toMatchObject({ isAbort: true, isError: false });
    // The partial answer stays on screen (the backend persists it too).
    expect(harness.chat.lastMessage?.parts).toEqual(cancelled.ui.message.parts);
    expect(harness.errors).toEqual([]);
  });

  it("is a failure when the connection closes without the user asking", async () => {
    const { chat, finish, errors } = await settle(cancelled);

    expect(chat.status).toBe("error");
    expect(chat.error?.name).toBe("StreamContractError");
    expect(finish()).toMatchObject({ isAbort: false, isError: true });
    expect(errors).toHaveLength(1);
    expect(chat.lastMessage?.parts).toEqual(cancelled.ui.message.parts);
  });
});
