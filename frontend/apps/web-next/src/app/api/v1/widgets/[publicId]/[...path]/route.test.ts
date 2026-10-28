import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { GET, POST, visitorEndpoint } from "./route";

const ID = "wgt_aaaaaaaaaaaaaaaaaaaaaa";
const SESSION = "11111111-2222-4333-8444-555555555555";

const fetchMock = vi.fn();
vi.stubGlobal("fetch", fetchMock);
afterEach(() => fetchMock.mockReset());

function request(path: string, init: ConstructorParameters<typeof NextRequest>[1] = {}) {
  return new NextRequest(`http://localhost:3100${path}`, init);
}

describe("visitorEndpoint", () => {
  it("forwards the visitor endpoints only, each with its one method", () => {
    expect(visitorEndpoint(`/api/v1/widgets/${ID}/config/`)).toMatchObject({ method: "GET" });
    expect(visitorEndpoint(`/api/v1/widgets/${ID}/ask/`)).toMatchObject({ method: "POST" });
    expect(visitorEndpoint(`/api/v1/widgets/${ID}/sessions/${SESSION}/feedback/`)).toMatchObject({
      method: "POST"
    });
    // Without the trailing slash the backend would redirect, and that is not a visitor path.
    expect(visitorEndpoint(`/api/v1/widgets/${ID}/config`)).toBeNull();
    expect(visitorEndpoint(`/api/v1/widgets/${ID}/sessions/`)).toBeNull();
    expect(visitorEndpoint(`/api/v1/widgets/not-an-id/config/`)).toBeNull();
    expect(visitorEndpoint(`/api/v1/widgets/${ID}/../../users/me/`)).toBeNull();
  });
});

describe("the visitor proxy", () => {
  it("passes the visitor's token and address on, and nothing from the browser's cookies", async () => {
    fetchMock.mockResolvedValue(
      new Response("event: text\ndata: {}\n\n", {
        status: 200,
        headers: { "content-type": "text/event-stream", "x-trace-id": "trace-1" }
      })
    );
    const response = await POST(
      request(`/api/v1/widgets/${ID}/ask/`, {
        method: "POST",
        headers: {
          "content-type": "application/json",
          authorization: "Bearer visitor-token",
          cookie: "eneo_session=secret",
          "x-forwarded-for": "203.0.113.5, 10.0.0.2"
        },
        body: JSON.stringify({ question: "Hej" })
      })
    );
    expect(response.status).toBe(200);
    expect(response.headers.get("content-type")).toBe("text/event-stream");
    expect(response.headers.get("x-trace-id")).toBe("trace-1");
    expect(response.headers.get("cache-control")).toBe("no-store");

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`http://localhost:8123/api/v1/widgets/${ID}/ask/`);
    const headers = new Headers(init.headers);
    expect(headers.get("authorization")).toBe("Bearer visitor-token");
    expect(headers.get("x-forwarded-for")).toBe("203.0.113.5, 10.0.0.2");
    expect(headers.get("cookie")).toBeNull();
    expect(init.method).toBe("POST");
  });

  it("hands a rate limit back with its Retry-After", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ detail: { code: "rate_limited_ip" } }), {
        status: 429,
        headers: { "content-type": "application/json", "retry-after": "30" }
      })
    );
    const response = await GET(request(`/api/v1/widgets/${ID}/config/`));
    expect(response.status).toBe(429);
    expect(response.headers.get("retry-after")).toBe("30");
  });

  it("refuses paths and methods a visitor never uses without asking the backend", async () => {
    fetchMock.mockResolvedValue(new Response("{}", { status: 200 }));
    expect((await POST(request(`/api/v1/widgets/${ID}/config/`, { method: "POST" }))).status).toBe(
      405
    );
    expect((await GET(request(`/api/v1/widgets/${ID}/secrets/`))).status).toBe(404);
    expect((await GET(request(`/api/v1/widgets/${ID}/sessions/${SESSION}/`))).status).not.toBe(404);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
