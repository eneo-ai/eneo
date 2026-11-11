/**
 * Every failed question becomes one human sentence (UX review A1: the chat
 * showed the backend's raw JSON), with the technical facts kept for the
 * details disclosure.
 */
import { describe, expect, it } from "vitest";
import { apiErrorFromResponse, EneoApiError } from "@/lib/api/errors";
import en from "@/lib/i18n/messages/en.json";
import sv from "@/lib/i18n/messages/sv.json";
import { testTranslator } from "@/test/i18n";
import { describeChatFailure, getContextErrorInfo } from "./chat-error";
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
      [429, "request_rate_limited"],
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
    expect(describeChatFailure(refused, { code: 9033 }, t).message).toBe("eneo_error_9033");
    expect(describeChatFailure(new Error("boom"), { code: 9024 }, t).message).toBe(
      "eneo_error_9024"
    );
  });

  it("uses the same provider and quota reasons for HTTP and JSON failures", () => {
    for (const [reason, key] of [
      ["provider_timeout", "provider_failure_timeout"],
      ["tenant_quota_exceeded", "job_failure_tenant_quota_exceeded"],
      ["user_quota_exceeded", "job_failure_user_quota_exceeded"]
    ]) {
      const error = new EneoApiError("Refused", { status: 503, code: 9008, reason });
      expect(describeChatFailure(error, null, t).message).toBe(key);
      const json = new Error(
        JSON.stringify({ message: "Refused", eneo_error_code: 9008, code: reason })
      );
      expect(describeChatFailure(json, null, t).message).toBe(key);
    }
  });

  it("asks to wait on a rate-limited question in both languages, as every 429 does", () => {
    const body = {
      code: "rate_limit_exceeded",
      message: "Too many requests",
      retry_after_seconds: 12,
      eneo_error_code: 9008,
      request_id: "req-1",
      detail: { code: "rate_limit_exceeded", message: "Too many requests", retry_after_seconds: 12 }
    };
    const refused = apiErrorFromResponse(new Response(null, { status: 429 }), body);
    const sdkStyle = new Error(JSON.stringify(body));
    for (const [locale, messages, sentence] of [
      ["sv", sv, "För många förfrågningar just nu. Vänta en stund och försök igen."],
      ["en", en, "Too many requests right now. Wait a moment and try again."]
    ] as const) {
      const translate = testTranslator(locale, messages);
      expect(describeChatFailure(refused, null, translate).message).toBe(sentence);
      expect(describeChatFailure(sdkStyle, null, translate).message).toBe(sentence);
      // A 429 without a reason reaches the same sentence through its status.
      expect(
        describeChatFailure(new EneoApiError("Too many", { status: 429 }), null, translate).message
      ).toBe(sentence);
    }
  });

  it("keeps an unknown reason behind details and falls back to the numeric code", () => {
    const error = new EneoApiError("Refused", { status: 503, code: 9010, reason: "future_reason" });
    expect(describeChatFailure(error, null, t).message).toBe("eneo_error_9010");
    expect(describeChatFailure(error, null, t).details).toContain(
      "chat_error_detail_code 9010 (future_reason)"
    );
  });

  it("keeps status, code, the backend's message and the support references as details", () => {
    const error = new EneoApiError("Model not available", {
      status: 403,
      code: 9033,
      reason: "model_not_available",
      errorId: "8bc91e0a",
      traceId: "trace-1"
    });
    expect(describeChatFailure(error, null, t).details).toEqual([
      "chat_error_detail_status 403",
      "chat_error_detail_code 9033 (model_not_available)",
      "Model not available",
      "error_id: 8bc91e0a",
      "trace_id: trace-1"
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

describe("context rejection facts", () => {
  it("reads real HTTP9003 details and the SDK JSON error body", () => {
    const details = { tokens_used: 12000, token_limit: 10000 };
    expect(
      getContextErrorInfo(new EneoApiError("Too large", { status: 400, code: 9003, details }), null)
    ).toEqual({ used: 12000, limit: 10000 });
    expect(
      getContextErrorInfo(
        new Error(JSON.stringify({ eneo_error_code: 9003, message: "Too large", details })),
        null
      )
    ).toEqual({ used: 12000, limit: 10000 });
  });
  it("recognizes the real SSE shape and keeps absent or invalid counts absent", () => {
    expect(getContextErrorInfo(new Error("Context window exceeded"), { code: 9003 })).toEqual({});
    expect(
      getContextErrorInfo(new Error("12,000 tokens used, limit is 10,000 tokens"), null)
    ).toEqual({ used: 12000, limit: 10000 });
    for (const details of [
      { tokens_used: -1, token_limit: 100 },
      { tokens_used: 120, token_limit: 0 },
      { tokens_used: "120", token_limit: 100 },
      { tokens_used: 80, token_limit: 100 }
    ]) {
      expect(
        getContextErrorInfo(
          new EneoApiError("Too large", { status: 400, code: 9003, details }),
          null
        )
      ).toEqual({});
    }
    expect(getContextErrorInfo(new Error("Provider unavailable"), { code: 9003 })).toEqual({});
    expect(getContextErrorInfo(new Error("Provider unavailable"), { code: 9008 })).toBeNull();
  });
});
