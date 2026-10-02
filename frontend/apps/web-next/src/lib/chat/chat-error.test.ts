/**
 * Every failed question becomes one human sentence (UX review A1: the chat
 * showed the backend's raw JSON), with the technical facts kept for the
 * details disclosure.
 */
import { describe, expect, it } from "vitest";
import { EneoApiError } from "@/lib/api/errors";
import { describeChatFailure } from "./chat-error";
import { StreamContractError } from "./transport";

const t = (key: string, values?: Record<string, string | number>) =>
  values ? `${key} ${Object.values(values).join(" ")}` : key;

describe("describeChatFailure", () => {
  it("maps a refused response by its HTTP status", () => {
    const cases: [number, string][] = [
      [401, "session_expired_please_login_again"],
      [403, "chat_error_forbidden"],
      [404, "chat_error_not_found"],
      [413, "chat_error_too_large"],
      [400, "chat_error_invalid"],
      [422, "chat_error_invalid"],
      [429, "chat_error_rate_limited"],
      [500, "chat_error_server"],
      [503, "chat_error_server"],
      [418, "request_failed"]
    ];
    for (const [status, key] of cases) {
      const error = new EneoApiError("Not authenticated", { status });
      expect(describeChatFailure(error, null, t).message, `status ${status}`).toBe(key);
    }
  });

  it("prefers the catalog sentence of a known backend code over the status", () => {
    const refused = new EneoApiError("Quota exceeded", { status: 403, code: 9008 });
    expect(describeChatFailure(refused, null, t).message).toBe("eneo_error_9008");
    // The stream's data-error code wins over the response's code.
    expect(describeChatFailure(refused, 9033, t).message).toBe("eneo_error_9033");
    expect(describeChatFailure(new Error("boom"), 9024, t).message).toBe("eneo_error_9024");
  });

  it("keeps status, code, the backend's message and trace id as details", () => {
    const error = new EneoApiError("Model not available", {
      status: 403,
      code: 9033,
      reason: "model_not_available",
      traceId: "trace-1"
    });
    expect(describeChatFailure(error, null, t).details).toEqual([
      "chat_error_detail_status 403",
      "chat_error_detail_code 9033 (model_not_available)",
      "Model not available",
      "chat_error_detail_trace trace-1"
    ]);
  });

  it("never shows a JSON body, not even in the details", () => {
    const sdkStyle = new Error('{"message":"Not authenticated","eneo_error_code":9001}');
    const failure = describeChatFailure(sdkStyle, null, t);
    expect(failure.message).toBe("eneo_error_9001");
    expect(failure.details).toEqual(["chat_error_detail_code 9001", "Not authenticated"]);
    for (const line of [failure.message, ...failure.details]) expect(line).not.toContain("{");

    const detailOnly = new Error('{"detail":"Session not found"}');
    expect(describeChatFailure(detailOnly, null, t)).toEqual({
      message: "request_failed",
      details: ["Session not found"]
    });
  });

  it("calls a broken stream or a lost network a lost connection", () => {
    const broken = new StreamContractError("The answer stream closed before it finished");
    expect(describeChatFailure(broken, null, t)).toEqual({
      message: "chat_error_connection_lost",
      details: ["StreamContractError: The answer stream closed before it finished"]
    });
    expect(describeChatFailure(new TypeError("Failed to fetch"), null, t).message).toBe(
      "chat_error_connection_lost"
    );
    expect(describeChatFailure(new DOMException("Aborted", "AbortError"), null, t).message).toBe(
      "chat_error_connection_lost"
    );
  });

  it("falls back to the generic sentence and keeps the original text for support", () => {
    expect(describeChatFailure(new Error("Tjänsten svarar inte"), null, t)).toEqual({
      message: "request_failed",
      details: ["Tjänsten svarar inte"]
    });
    expect(describeChatFailure("unknown", null, t)).toEqual({
      message: "request_failed",
      details: ["unknown"]
    });
    expect(describeChatFailure(undefined, null, t)).toEqual({
      message: "request_failed",
      details: []
    });
  });

  it("cuts a long backend text (an HTML error page, a stack trace) to one line", () => {
    const long = new Error(`<html>\n${"x".repeat(500)}\n</html>`);
    const [detail] = describeChatFailure(long, null, t).details;
    expect(detail!.length).toBeLessThanOrEqual(301);
    expect(detail).not.toContain("\n");
    expect(detail!.endsWith("…")).toBe(true);
  });
});
