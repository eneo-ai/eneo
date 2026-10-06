import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { getAccessTokenOrNull } from "@/lib/auth/session";
import { GET, HEAD } from "./route";

vi.mock("@/lib/auth/session", () => ({
  getAccessTokenOrNull: vi.fn(),
  SESSION_COOKIE: "eneo_session"
}));

const mockToken = vi.mocked(getAccessTokenOrNull);
const fetchMock = vi.fn();
vi.stubGlobal("fetch", fetchMock);

const TOKEN = "session-access-token";
const TARGET = "https://reports.example.se/cb?ticket=one%20time&state=abc";
const QUERY = "module_key=reports&redirect_uri=https%3A%2F%2Freports.example.se%2Fcb&state=abc";

function request(query = QUERY) {
  return new NextRequest(`http://localhost:3100/module-login?${query}`);
}

function ticketResponse(status = 201, body: unknown = { redirect_target: TARGET }) {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" }
  });
}

function expectSecurityHeaders(response: Response) {
  expect(response.headers.get("cache-control")).toBe("private, no-store, max-age=0");
  expect(response.headers.get("referrer-policy")).toBe("no-referrer");
  expect(response.headers.get("x-robots-tag")).toBe("noindex, nofollow, noarchive");
}

beforeEach(() => {
  vi.clearAllMocks();
  mockToken.mockResolvedValue(TOKEN);
  fetchMock.mockResolvedValue(ticketResponse());
});

describe("GET /module-login", () => {
  it("issues a ticket and sends the browser to the module's redirect_target as is", async () => {
    const response = await GET(request());

    expect(response.status).toBe(303);
    expect(response.headers.get("location")).toBe(TARGET);
    expectSecurityHeaders(response);

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8123/api/v1/module-auth/tickets/");
    expect(init.method).toBe("POST");
    expect((init.headers as Record<string, string>).authorization).toBe(`Bearer ${TOKEN}`);
    expect(JSON.parse(init.body as string)).toEqual({
      module_key: "reports",
      redirect_uri: "https://reports.example.se/cb",
      state: "abc"
    });
  });

  it("sends a signed-out visitor to /login with the hand-off as next, without a cookie", async () => {
    mockToken.mockResolvedValue(null);

    const response = await GET(request());

    expect(response.status).toBe(303);
    const location = new URL(response.headers.get("location")!);
    expect(location.origin).toBe("http://localhost:3100");
    expect(location.pathname).toBe("/login");
    expect(location.searchParams.get("next")).toBe(`/module-login?${QUERY}`);
    expect(response.headers.get("set-cookie")).toMatch(/^eneo_session=;/);
    expectSecurityHeaders(response);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("treats a backend 401 as a session to renew", async () => {
    fetchMock.mockResolvedValue(ticketResponse(401, { message: "expired" }));

    const response = await GET(request());

    const location = new URL(response.headers.get("location")!);
    expect(location.pathname).toBe("/login");
    expect(location.searchParams.get("next")).toBe(`/module-login?${QUERY}`);
    expect(response.headers.get("set-cookie")).toMatch(/^eneo_session=;/);
  });

  it.each([
    ["a missing parameter", "module_key=reports&state=abc"],
    ["a repeated parameter", `${QUERY}&state=other`],
    ["an unknown parameter", `${QUERY}&extra=1`]
  ])("rejects %s before touching the session or the backend", async (_, query) => {
    const response = await GET(request(query));

    expect(response.status).toBe(303);
    expect(response.headers.get("location")).toBe(
      "http://localhost:3100/module-login/failed?reason=invalid_request"
    );
    expectSecurityHeaders(response);
    expect(mockToken).not.toHaveBeenCalled();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it.each([
    [422, "invalid_request"],
    [400, "module_unavailable"],
    [403, "module_unavailable"],
    [404, "module_unavailable"],
    [500, "service_unavailable"]
  ])("maps a backend %i to the %s failure", async (status, reason) => {
    fetchMock.mockResolvedValue(ticketResponse(status, { message: "no" }));

    const response = await GET(request());

    expect(response.headers.get("location")).toBe(
      `http://localhost:3100/module-login/failed?reason=${reason}`
    );
    expectSecurityHeaders(response);
  });

  it("fails as service_unavailable when the backend is unreachable", async () => {
    fetchMock.mockRejectedValue(new TypeError("fetch failed"));

    const response = await GET(request());

    expect(response.headers.get("location")).toBe(
      "http://localhost:3100/module-login/failed?reason=service_unavailable"
    );
  });

  it.each([
    ["an unparsable body", new Response("not json", { status: 201 })],
    ["a body without redirect_target", ticketResponse(201, {})],
    [
      "a redirect_target that is not http(s)",
      ticketResponse(201, { redirect_target: "javascript:1" })
    ],
    [
      "a redirect_target with credentials",
      ticketResponse(201, { redirect_target: "https://u:p@reports.example.se/cb" })
    ]
  ])("fails as service_unavailable on %s", async (_, backendResponse) => {
    fetchMock.mockResolvedValue(backendResponse);

    const response = await GET(request());

    expect(response.headers.get("location")).toBe(
      "http://localhost:3100/module-login/failed?reason=service_unavailable"
    );
  });

  it("never puts the access token in a response", async () => {
    for (const backendResponse of [ticketResponse(), ticketResponse(401), ticketResponse(500)]) {
      fetchMock.mockResolvedValue(backendResponse);
      const response = await GET(request());
      for (const [, value] of response.headers) expect(value).not.toContain(TOKEN);
      expect(await response.text()).not.toContain(TOKEN);
    }
  });
});

describe("HEAD /module-login", () => {
  it("is not allowed: a HEAD must not issue a ticket", () => {
    const response = HEAD();
    expect(response.status).toBe(405);
    expect(response.headers.get("allow")).toBe("GET");
    expectSecurityHeaders(response);
  });
});
