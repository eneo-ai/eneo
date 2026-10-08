import { beforeEach, describe, expect, test, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  fetch: vi.fn<typeof fetch>(),
  getBackendUrl: vi.fn(() => "https://eneo.example"),
  setFrontendAuthCookie: vi.fn()
}));

vi.mock("$app/server", () => ({
  getRequestEvent: () => ({ fetch: mocks.fetch })
}));

vi.mock("$lib/core/environment.server", () => ({
  getBackendUrl: mocks.getBackendUrl
}));

vi.mock("./auth.server", () => ({
  setFrontendAuthCookie: mocks.setFrontendAuthCookie
}));

import { loginWithEneo } from "./eneo.server";

function jsonResponse(status: number, body: unknown, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers }
  });
}

describe("loginWithEneo", () => {
  let consoleError: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    vi.clearAllMocks();
    consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
  });

  test("posts the credentials through the request event's fetch and sets the cookie", async () => {
    mocks.fetch.mockResolvedValue(
      jsonResponse(200, { access_token: "eneo-token" }, { "X-Trace-Id": "trace-1" })
    );

    const result = await loginWithEneo("user@example.com", "secret");

    expect(result).toEqual({ success: true, traceId: "trace-1", correlationId: "trace-1" });
    const [url, init] = mocks.fetch.mock.calls[0];
    expect(url).toBe("https://eneo.example/api/v1/users/login/token/");
    expect(init?.method).toBe("POST");
    expect(String(init?.body)).toBe("username=user%40example.com&password=secret");
    expect(mocks.setFrontendAuthCookie).toHaveBeenCalledWith({ id_token: "eneo-token" });
    expect(consoleError).not.toHaveBeenCalled();
  });

  test("reports the attempt limit after wrong credentials", async () => {
    mocks.fetch.mockResolvedValue(
      jsonResponse(
        401,
        { code: "invalid_credentials", message: "Invalid credentials", attempts_remaining: 2 },
        { "X-Trace-Id": "trace-2" }
      )
    );

    const result = await loginWithEneo("user@example.com", "wrong");

    expect(result).toEqual({
      success: false,
      traceId: "trace-2",
      correlationId: "trace-2",
      attemptsRemaining: 2,
      retryAfterSeconds: null
    });
    expect(mocks.setFrontendAuthCookie).not.toHaveBeenCalled();
    expect(consoleError).toHaveBeenCalledWith(
      expect.stringContaining("Code: %s"),
      401,
      "invalid_credentials",
      "trace-2"
    );
  });

  test("logs the backend's error code so a misconfiguration is not read as wrong credentials", async () => {
    mocks.fetch.mockResolvedValue(
      jsonResponse(400, { code: "disallowed_cors_origin", message: "Origin is not allowed." })
    );

    const result = await loginWithEneo("user@example.com", "secret");

    expect(result.success).toBe(false);
    expect(consoleError).toHaveBeenCalledWith(
      expect.stringContaining("Code: %s"),
      400,
      "disallowed_cors_origin",
      "none"
    );
  });

  test("reads the code from FastAPI's detail envelope as well", async () => {
    mocks.fetch.mockResolvedValue(jsonResponse(401, { detail: { code: "invalid_credentials" } }));

    await loginWithEneo("user@example.com", "wrong");

    expect(consoleError).toHaveBeenCalledWith(
      expect.stringContaining("Code: %s"),
      401,
      "invalid_credentials",
      "none"
    );
  });

  test("fails without throwing when the backend cannot be reached", async () => {
    mocks.fetch.mockRejectedValue(new TypeError("fetch failed"));

    const result = await loginWithEneo("user@example.com", "secret");

    expect(result).toEqual({ success: false, traceId: null, correlationId: null });
    expect(mocks.setFrontendAuthCookie).not.toHaveBeenCalled();
    expect(consoleError).toHaveBeenCalledWith(
      expect.stringContaining("before reaching the backend"),
      "fetch failed"
    );
  });
});
