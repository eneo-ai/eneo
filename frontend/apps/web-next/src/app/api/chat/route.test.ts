import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { getAccessTokenOrNull } from "@/lib/auth/session";
import { POST } from "./route";

vi.mock("@/lib/auth/session", () => ({
  getAccessTokenOrNull: vi.fn()
}));

const mockToken = vi.mocked(getAccessTokenOrNull);
const fetchMock = vi.fn();
vi.stubGlobal("fetch", fetchMock);

function streamResponse() {
  return new Response('data: {"type":"start"}\n\ndata: [DONE]\n\n', {
    status: 200,
    headers: {
      "content-type": "text/event-stream; charset=utf-8",
      "x-vercel-ai-ui-message-stream": "v1",
      "x-trace-id": "trace-9"
    }
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  mockToken.mockResolvedValue("test-token");
  fetchMock.mockResolvedValue(streamResponse());
});

describe("/api/chat", () => {
  it("returns 401 JSON without a session", async () => {
    mockToken.mockResolvedValue(null);
    const response = await POST(
      new NextRequest("http://localhost:3100/api/chat", { method: "POST", body: "{}" })
    );
    expect(response.status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("forwards to the v3 endpoint with the bearer token and streams back", async () => {
    const body = JSON.stringify({ question: "hi", stream: true, files: [] });
    const response = await POST(
      new NextRequest("http://localhost:3100/api/chat", { method: "POST", body })
    );

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit & { duplex?: string }];
    expect(url).toBe("http://localhost:8123/api/v1/conversations/?version=3");
    expect((init.headers as Record<string, string>).authorization).toBe("Bearer test-token");
    expect(init.duplex).toBe("half");
    expect(init.signal).toBeInstanceOf(AbortSignal);

    expect(response.status).toBe(200);
    // The protocol marker header must survive the proxy.
    expect(response.headers.get("x-vercel-ai-ui-message-stream")).toBe("v1");
    expect(response.headers.get("content-type")).toContain("text/event-stream");
    expect(response.headers.get("x-trace-id")).toBe("trace-9");
    await expect(response.text()).resolves.toContain("data: [DONE]");
  });

  it("passes upstream error statuses through", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ message: "Not found", intric_error_code: 9000 }), {
        status: 404,
        headers: { "content-type": "application/json" }
      })
    );

    const response = await POST(
      new NextRequest("http://localhost:3100/api/chat", { method: "POST", body: "{}" })
    );
    expect(response.status).toBe(404);
  });
});
