import { afterEach, describe, expect, test, vi } from "vitest";
import { API_BASE } from "@/lib/api/base";
import { EneoApiError } from "@/lib/api/errors";
import { startPromptGuideRun, updateHelperRunStatus, type HelperRun } from "./helper-runs";

// Reads the body it is handed, as a refusal owner may: the caller must still
// be able to read its own copy.
const rawRefusal = vi.hoisted(() =>
  vi.fn<(response: Response, url: string) => Promise<void>>(async (response) => {
    await response.text();
  })
);
vi.mock("@/lib/api/base", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/base")>()),
  onRawRefusal: rawRefusal
}));

function helperRun(overrides: Partial<HelperRun> = {}): HelperRun {
  return {
    id: "run-1",
    kind: "prompt_guide",
    assistant_id: "assistant-helper",
    target_type: "assistant",
    target_id: "assistant-target",
    session_id: "session-1",
    actor_user_id: "user-1",
    status: "in_progress",
    completed_at: null,
    created_at: null,
    updated_at: null,
    ...overrides
  };
}

function eventStream(events: unknown[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const event of events) {
        controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`));
      }
      controller.close();
    }
  });
}

describe("helper run transport", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    rawRefusal.mockClear();
  });

  test("starts a streamed prompt-guide run and accumulates answer chunks", async () => {
    const run = helperRun();
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        eventStream([
          { run, answer: "Hel", references: [] },
          { run, answer: "lo", references: [] }
        ]),
        { status: 200, headers: { "content-type": "text/event-stream" } }
      )
    );
    const chunks: string[] = [];

    const result = await startPromptGuideRun({
      targetId: "assistant-target",
      question: "Improve this prompt",
      onAnswer: (chunk) => chunks.push(chunk.answer)
    });

    expect(result.answer).toBe("Hello");
    expect(chunks).toEqual(["Hel", "lo"]);
    expect(fetchMock).toHaveBeenCalledWith(
      `${API_BASE}/api/v1/help-assistants/runs/`,
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ accept: "text/event-stream" }),
        body: JSON.stringify({
          kind: "prompt_guide",
          target_type: "assistant",
          target_id: "assistant-target",
          question: "Improve this prompt",
          stream: true
        })
      })
    );
  });

  test("updates a helper run status through the proxy", async () => {
    const completed = helperRun({ status: "completed" });
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(Response.json(completed, { status: 200 }));

    await expect(updateHelperRunStatus("run-1", "completed")).resolves.toEqual(completed);
    expect(fetchMock).toHaveBeenCalledWith(
      `${API_BASE}/api/v1/help-assistants/runs/run-1/`,
      expect.objectContaining({
        method: "PATCH",
        body: JSON.stringify({ status: "completed" })
      })
    );
  });

  const refusals = [
    [401, 9001],
    [403, 9070]
  ] as const;

  test.each(refusals)(
    "reports a refused %i run to the refusal owner once, then throws its own error",
    async (status, code) => {
      vi.spyOn(globalThis, "fetch").mockResolvedValue(
        Response.json({ message: "Refused", eneo_error_code: code }, { status })
      );

      const error = await startPromptGuideRun({
        targetId: "assistant-target",
        question: "Hi"
      }).then(
        () => null,
        (reason: unknown) => reason
      );

      expect(rawRefusal).toHaveBeenCalledTimes(1);
      expect(rawRefusal).toHaveBeenCalledWith(
        expect.any(Response),
        `${API_BASE}/api/v1/help-assistants/runs/`
      );
      expect(error).toBeInstanceOf(EneoApiError);
      expect(error).toMatchObject({ status, code, message: "Refused" });
    }
  );

  test.each(refusals)(
    "reports a refused %i status update to the refusal owner once, then throws its own error",
    async (status, code) => {
      vi.spyOn(globalThis, "fetch").mockResolvedValue(
        Response.json({ message: "Refused", eneo_error_code: code }, { status })
      );

      const error = await updateHelperRunStatus("run-1", "completed").then(
        () => null,
        (reason: unknown) => reason
      );

      expect(rawRefusal).toHaveBeenCalledTimes(1);
      expect(rawRefusal).toHaveBeenCalledWith(
        expect.any(Response),
        `${API_BASE}/api/v1/help-assistants/runs/run-1/`
      );
      expect(error).toBeInstanceOf(EneoApiError);
      expect(error).toMatchObject({ status, code, message: "Refused" });
    }
  );
});
