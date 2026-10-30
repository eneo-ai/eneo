import { describe, expect, it, vi } from "vitest";

import { readEvents } from "./stream";

describe("readEvents", () => {
  it("ignores comment-only SSE heartbeat frames", async () => {
    const onMessage = vi.fn();
    const response = eventStreamResponse(": ping\n\n");

    await readEvents(response, { onMessage });

    expect(onMessage).not.toHaveBeenCalled();
  });

  it("preserves named events with empty data", async () => {
    const onMessage = vi.fn();
    const response = eventStreamResponse("event: done\n\n");

    await readEvents(response, { onMessage });

    expect(onMessage).toHaveBeenCalledTimes(1);
    expect(onMessage).toHaveBeenCalledWith({
      data: "",
      event: "done",
      id: "",
      retry: undefined
    });
  });

  it("forwards unknown named events so endpoint protocols can reject them", async () => {
    const onMessage = vi.fn();
    const response = eventStreamResponse("event: mystery\n\n");

    await readEvents(response, { onMessage });

    expect(onMessage).toHaveBeenCalledTimes(1);
    expect(onMessage).toHaveBeenCalledWith({
      data: "",
      event: "mystery",
      id: "",
      retry: undefined
    });
  });
});

function eventStreamResponse(body) {
  return new Response(body, {
    headers: { "Content-Type": "text/event-stream" },
    status: 200
  });
}
