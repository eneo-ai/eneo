import { afterEach, describe, expect, it, vi } from "vitest";
import { passwordChangeUrl } from "@/lib/auth/password-change-path";
import { API_BASE, CHAT_API, JOB_EVENTS_PATH, onBrowserApiResponse, onRawRefusal } from "./base";

// Literal values: the Vite build swaps this module for base.vite.ts, so
// these pin what the Next build sends where.
it("sends the browser's requests through the Next proxies", () => {
  expect(API_BASE).toBe("/api/eneo");
  expect(CHAT_API).toBe("/api/chat");
  expect(JOB_EVENTS_PATH).toBe("/api/jobs/events");
});

function stubWindow() {
  const location = {
    pathname: "/spaces/x",
    search: "?a=1",
    assign: vi.fn(),
    reload: vi.fn()
  };
  vi.stubGlobal("window", { location });
  return location;
}

function refusal(status: number, code?: number) {
  return Response.json({ message: "Refused", eneo_error_code: code }, { status });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("onBrowserApiResponse", () => {
  const request = (path: string) => new Request(`http://localhost${API_BASE}${path}`);

  it("reloads on a 401, so the proxy sends the browser to the login page", async () => {
    const location = stubWindow();
    await onBrowserApiResponse({ request: request("/api/v1/spaces/"), response: refusal(401) });
    expect(location.reload).toHaveBeenCalledTimes(1);
    expect(location.assign).not.toHaveBeenCalled();
  });

  it("leaves an audit 401 to the audit page's access gate", async () => {
    const location = stubWindow();
    await onBrowserApiResponse({ request: request("/api/v1/audit/logs/"), response: refusal(401) });
    expect(location.reload).not.toHaveBeenCalled();
  });

  it("sends a 403 that requires a password change to the password page", async () => {
    const location = stubWindow();
    await onBrowserApiResponse({
      request: request("/api/v1/spaces/"),
      response: refusal(403, 9070)
    });
    expect(location.assign).toHaveBeenCalledWith(passwordChangeUrl("/spaces/x?a=1"));
    expect(location.reload).not.toHaveBeenCalled();
  });

  it("ignores other refusals and successes", async () => {
    const location = stubWindow();
    for (const response of [refusal(403, 9025), refusal(403), new Response("{}")]) {
      await onBrowserApiResponse({ request: request("/api/v1/spaces/"), response });
    }
    expect(location.assign).not.toHaveBeenCalled();
    expect(location.reload).not.toHaveBeenCalled();
  });
});

describe("onRawRefusal", () => {
  it("does nothing in Next: raw callers report refusals themselves", async () => {
    const location = stubWindow();
    const response = refusal(401);
    await onRawRefusal(response, `${API_BASE}/api/v1/icons/`);
    await onRawRefusal(refusal(403, 9070), `${API_BASE}/api/v1/icons/`);
    expect(location.reload).not.toHaveBeenCalled();
    expect(location.assign).not.toHaveBeenCalled();
    expect(response.bodyUsed).toBe(false);
  });
});
