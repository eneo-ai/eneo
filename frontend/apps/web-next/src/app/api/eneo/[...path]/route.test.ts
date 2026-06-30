import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { getAccessTokenOrNull } from "@/lib/auth/session";
import { DELETE, GET, POST } from "./route";

vi.mock("@/lib/auth/session", () => ({
  getAccessTokenOrNull: vi.fn()
}));

const mockToken = vi.mocked(getAccessTokenOrNull);
const fetchMock = vi.fn();
vi.stubGlobal("fetch", fetchMock);

function backendResponse(init: ResponseInit = {}) {
  return new Response(JSON.stringify({ ok: true }), {
    status: 200,
    headers: { "content-type": "application/json" },
    ...init
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  mockToken.mockResolvedValue("test-token");
  fetchMock.mockResolvedValue(backendResponse());
});

describe("/api/eneo proxy", () => {
  it("returns 401 JSON without touching the backend when there is no session", async () => {
    mockToken.mockResolvedValue(null);

    const response = await GET(new NextRequest("http://localhost:3100/api/eneo/api/v1/spaces/"));

    expect(response.status).toBe(401);
    expect(response.headers.get("content-type")).toContain("application/json");
    await expect(response.json()).resolves.toEqual({ message: "Not authenticated" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("returns 404 for paths outside api/v1", async () => {
    const response = await GET(new NextRequest("http://localhost:3100/api/eneo/spaces/"));

    expect(response.status).toBe(404);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("forwards the path (trailing slash intact), query string and bearer token", async () => {
    await GET(
      new NextRequest("http://localhost:3100/api/eneo/api/v1/spaces/?limit=5&cursor=abc", {
        headers: { cookie: "eneo_session=secret", accept: "application/json" }
      })
    );

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8123/api/v1/spaces/?limit=5&cursor=abc");
    expect(init.method).toBe("GET");

    const headers = init.headers as Headers;
    expect(headers.get("authorization")).toBe("Bearer test-token");
    expect(headers.get("accept")).toBe("application/json");
    // The session cookie must never reach the backend.
    expect(headers.get("cookie")).toBeNull();
  });

  it("forwards method and body for mutating requests", async () => {
    await POST(
      new NextRequest("http://localhost:3100/api/eneo/api/v1/spaces/", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ name: "New space" })
      })
    );

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit & { duplex?: string }];
    expect(init.method).toBe("POST");
    expect(init.duplex).toBe("half");
    expect((init.headers as Headers).get("content-type")).toBe("application/json");
    await expect(new Response(init.body).text()).resolves.toBe('{"name":"New space"}');
  });

  it("does not attach a body to bodyless methods", async () => {
    await DELETE(
      new NextRequest("http://localhost:3100/api/eneo/api/v1/spaces/some-id/", {
        method: "DELETE"
      })
    );

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.method).toBe("DELETE");
    expect(init.body).toBeNull();
  });

  it("passes through status, body and trace headers, filtering the rest", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ message: "Not found", eneo_error_code: 9000 }), {
        status: 404,
        headers: {
          "content-type": "application/json",
          "x-trace-id": "trace-1",
          "x-correlation-id": "corr-1",
          "set-cookie": "backend=leak",
          "content-encoding": "gzip"
        }
      })
    );

    const response = await GET(
      new NextRequest("http://localhost:3100/api/eneo/api/v1/spaces/nope/")
    );

    expect(response.status).toBe(404);
    expect(response.headers.get("x-trace-id")).toBe("trace-1");
    expect(response.headers.get("x-correlation-id")).toBe("corr-1");
    expect(response.headers.get("set-cookie")).toBeNull();
    expect(response.headers.get("content-encoding")).toBeNull();
    await expect(response.json()).resolves.toEqual({
      message: "Not found",
      eneo_error_code: 9000
    });
  });
});
