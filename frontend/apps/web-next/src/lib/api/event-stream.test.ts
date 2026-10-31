import { describe, expect, it, vi } from "vitest";
import { readEventStream } from "./event-stream";

describe("SSE data framing", () => {
  it("preserves split UTF8, CRLF and multiline data across arbitrary byte chunks", async () => {
    const bytes = new TextEncoder().encode(
      ': ping\r\ndata: {"answer":\r\ndata: "åäö"}\r\n\r\ndata: last\n\n'
    );
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        for (const byte of bytes) controller.enqueue(Uint8Array.of(byte));
        controller.close();
      }
    });
    const messages: string[] = [];
    await readEventStream(body, (message) => messages.push(message));
    expect(messages).toEqual(['{"answer":\n"åäö"}', "last"]);
    expect(body.locked).toBe(false);
  });

  it("cancels an unfinished response when its payload consumer throws", async () => {
    const cancel = vi.fn();
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new TextEncoder().encode("data: broken\n\n"));
      },
      cancel
    });
    await expect(
      readEventStream(body, () => {
        throw new Error("invalid payload");
      })
    ).rejects.toThrow("invalid payload");
    expect(cancel).toHaveBeenCalledOnce();
    expect(body.locked).toBe(false);
  });

  it("propagates reader failures and releases its reader", async () => {
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.error(new Error("connection dropped"));
      }
    });
    await expect(readEventStream(body, () => {})).rejects.toThrow("connection dropped");
    expect(body.locked).toBe(false);
  });
});
