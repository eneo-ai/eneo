import { afterEach, describe, expect, test, vi } from "vitest";
import { startPromptGuideRun, updateHelperRunStatus, type HelperRun } from "./helper-runs";

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
      "/api/eneo/api/v1/help-assistants/runs/",
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
      "/api/eneo/api/v1/help-assistants/runs/run-1/",
      expect.objectContaining({
        method: "PATCH",
        body: JSON.stringify({ status: "completed" })
      })
    );
  });
});
