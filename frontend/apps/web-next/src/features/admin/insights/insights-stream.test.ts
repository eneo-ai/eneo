import { describe, expect, it, vi } from "vitest";
import type { EneoClient } from "@/lib/api/browser";
import { EneoApiError } from "@/lib/api/errors";
import { askAssistantInsightQuestion } from "./insights";

const filters = {
  start: "2026-10-23T22:00:00.000Z",
  end: "2026-10-26T22:59:59.999999Z",
  includeFollowups: true
};
function client(data: ReadableStream<Uint8Array>) {
  const POST = vi.fn().mockResolvedValue({
    data,
    response: new Response(null, { headers: { "content-type": "text/event-stream" } })
  });
  return { api: { POST } as unknown as EneoClient, POST };
}

describe("assistant analysis stream", () => {
  it("publishes answer parts before the response closes and keeps typed request bounds", async () => {
    let controller!: ReadableStreamDefaultController<Uint8Array>;
    const body = new ReadableStream<Uint8Array>({
      start(value) {
        controller = value;
      }
    });
    const { api, POST } = client(body);
    const onAnswer = vi.fn();
    let first!: () => void;
    const received = new Promise<void>((resolve) => {
      first = resolve;
    });
    const signal = new AbortController().signal;
    const result = askAssistantInsightQuestion({
      api,
      assistantId: "assistant-1",
      filters,
      question: "What happened?",
      signal,
      onAnswer: (part: string) => {
        onAnswer(part);
        if (part) first();
      }
    });
    controller.enqueue(new TextEncoder().encode('data: {"answer":""}\r\n\r\n'));
    controller.enqueue(new TextEncoder().encode('data: {"answer":"Första"}\r\n\r\n'));
    await received;
    expect(onAnswer).toHaveBeenCalledWith("Första");
    controller.enqueue(new TextEncoder().encode('data: {"answer":" delen"}\r\n\r\n'));
    controller.close();
    expect(await result).toBe("Första delen");
    expect(POST).toHaveBeenCalledWith(
      "/api/v1/analysis/assistants/{assistant_id}/",
      expect.objectContaining({
        parseAs: "stream",
        signal,
        body: { question: "What happened?", stream: true },
        params: {
          path: { assistant_id: "assistant-1" },
          query: { from_date: filters.start, to_date: filters.end, include_followups: true }
        }
      })
    );
  });

  it.each(['{"answer":9}', '{"other":"ignored"}', "not json"])(
    "rejects invalid payload %s and cancels its unfinished stream",
    async (payload) => {
      const cancel = vi.fn();
      const body = new ReadableStream<Uint8Array>({
        start(controller) {
          controller.enqueue(new TextEncoder().encode(`data: ${payload}\n\n`));
        },
        cancel
      });
      const { api } = client(body);
      await expect(
        askAssistantInsightQuestion({ api, assistantId: "assistant-1", filters, question: "What?" })
      ).rejects.toThrow();
      expect(cancel).toHaveBeenCalledOnce();
    }
  );

  it("rejects an empty response and a reader error", async () => {
    const { api } = client(
      new ReadableStream({
        start(controller) {
          controller.close();
        }
      })
    );
    await expect(
      askAssistantInsightQuestion({ api, assistantId: "assistant-1", filters, question: "What?" })
    ).rejects.toThrow();
    const emptyAnswer = client(
      new ReadableStream({
        start(controller) {
          controller.enqueue(new TextEncoder().encode('data: {"answer":""}\n\n'));
          controller.close();
        }
      })
    );
    await expect(
      askAssistantInsightQuestion({
        api: emptyAnswer.api,
        assistantId: "assistant-1",
        filters,
        question: "What?"
      })
    ).rejects.toThrow();
    const broken = client(
      new ReadableStream({
        start(controller) {
          controller.error(new Error("dropped"));
        }
      })
    );
    await expect(
      askAssistantInsightQuestion({
        api: broken.api,
        assistantId: "assistant-1",
        filters,
        question: "What?"
      })
    ).rejects.toThrow("dropped");
  });

  it("preserves HTTP refusal metadata instead of treating it as an answer", async () => {
    const api = {
      POST: vi.fn().mockResolvedValue({
        error: { message: "Refused", eneo_error_code: 9070 },
        response: new Response(null, { status: 403 })
      })
    } as unknown as EneoClient;
    await expect(
      askAssistantInsightQuestion({ api, assistantId: "assistant-1", filters, question: "What?" })
    ).rejects.toMatchObject({
      status: 403,
      code: 9070,
      message: "Refused"
    } satisfies Partial<EneoApiError>);
  });
});
