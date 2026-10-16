import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { getAccessTokenOrNull } from "@/lib/auth/session";
import { GET } from "./route";

vi.mock("@/lib/auth/session", () => ({
  getAccessTokenOrNull: vi.fn()
}));

const mockToken = vi.mocked(getAccessTokenOrNull);
const fetchMock = vi.fn();
vi.stubGlobal("fetch", fetchMock);

beforeEach(() => {
  vi.clearAllMocks();
  mockToken.mockResolvedValue("test-token");
  fetchMock.mockResolvedValue(
    new Response('event: job\ndata: {"id":"job-1"}\n\n', {
      status: 200,
      headers: { "content-type": "text/event-stream; charset=utf-8" }
    })
  );
});

describe("/api/jobs/events", () => {
  it("returns 401 JSON without a session", async () => {
    mockToken.mockResolvedValue(null);
    const response = await GET(new NextRequest("http://localhost:3100/api/jobs/events"));
    expect(response.status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("streams the backend's job events through with the bearer token", async () => {
    const response = await GET(new NextRequest("http://localhost:3100/api/jobs/events"));

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8123/api/v1/jobs/events/");
    expect((init.headers as Record<string, string>).authorization).toBe("Bearer test-token");
    expect(init.signal).toBeInstanceOf(AbortSignal);

    expect(response.status).toBe(200);
    expect(response.headers.get("content-type")).toContain("text/event-stream");
    expect(response.headers.get("cache-control")).toBe("no-store");
    await expect(response.text()).resolves.toContain('"id":"job-1"');
  });

  it("passes an upstream refusal through so the browser stops retrying", async () => {
    fetchMock.mockResolvedValue(new Response("", { status: 401 }));
    const response = await GET(new NextRequest("http://localhost:3100/api/jobs/events"));
    expect(response.status).toBe(401);
  });
});
