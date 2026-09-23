import { describe, expect, it, vi } from "vitest";
import { EneoError } from "@eneo/eneo-js";
import {
  describeWidgetError,
  isSessionError,
  retryAfterSeconds,
  widgetErrorCode
} from "./widgetErrors";

vi.mock("$lib/paraglide/messages", () => ({
  m: new Proxy<Record<string, (params?: Record<string, unknown>) => string>>(
    {},
    {
      get: (_target, key) => (params?: Record<string, unknown>) =>
        `${String(key)}${params ? " " + JSON.stringify(params) : ""}`
    }
  )
}));

function error(status: number, code?: string, headers?: Record<string, string>) {
  return new EneoError(
    "failed",
    "SERVER",
    status,
    0,
    code ? { detail: { code } } : undefined,
    { endpoint: "/x" },
    headers ? new Headers(headers) : undefined
  );
}

describe("widget errors", () => {
  it("reads the backend code and the session ownership case", () => {
    expect(widgetErrorCode(error(404, "session_not_owned"))).toBe("session_not_owned");
    expect(widgetErrorCode(new Error("plain"))).toBeNull();
    expect(isSessionError(error(404, "session_not_owned"))).toBe(true);
    expect(isSessionError(error(404, "widget_not_active"))).toBe(false);
  });

  it("only trusts a positive Retry-After on a 429", () => {
    expect(retryAfterSeconds(error(429, "rate_limited_ip", { "retry-after": "30" }))).toBe(30);
    expect(retryAfterSeconds(error(429, "rate_limited_ip", { "retry-after": "soon" }))).toBeNull();
    expect(retryAfterSeconds(error(503, "x", { "retry-after": "30" }))).toBeNull();
  });

  it("maps codes to visitor wording and falls back to the generic message", () => {
    expect(describeWidgetError(error(429, "rate_limited_ip", { "retry-after": "30" }))).toBe(
      'widget_error_rate_limited_wait {"seconds":"30"}'
    );
    // A wait longer than the composer will sit out is not promised as a countdown.
    expect(describeWidgetError(error(429, "rate_limited_ip", { "retry-after": "3600" }))).toBe(
      "widget_error_rate_limited"
    );
    expect(describeWidgetError(error(402, "budget_exhausted"))).toBe("widget_error_budget");
    expect(describeWidgetError(error(404, "widget_not_active"))).toBe("widget_error_unavailable");
    expect(describeWidgetError(error(400, "challenge_expired"))).toBe("widget_error_verification");
    // Retrying the same conversation can never succeed; the visitor must start a new one.
    expect(describeWidgetError(error(400, "session_turns_exceeded"))).toBe(
      "widget_error_session_limit"
    );
    expect(describeWidgetError(new Error("boom"))).toBe("widget_error_generic");
  });
});
