import { describe, expect, it } from "vitest";
import { apiErrorFromResponse } from "@/lib/api/errors";
import {
  isStaleEditorError,
  widgetErrorCode,
  widgetErrorMessage,
  widgetFieldErrors
} from "./errors";

/** Keys and their parameters as text, so a test pins which message is chosen. */
const NAMED: Record<string, string> = {
  widget_admin_error_field_locked: "locked",
  widget_admin_error_template_not_published: "unpublished",
  widget_admin_template_in_use: "in use",
  widget_admin_save_conflict: "conflict"
};
const t = (key: string, params?: Record<string, string | number>) =>
  NAMED[key] ?? (params ? `${key}(${Object.values(params).join("|")})` : key);

/** An error as the widget API answers, with its string code in the detail. */
function refusal(status: number, detail: unknown) {
  return apiErrorFromResponse(new Response(null, { status }), { detail });
}

function apiError(status: number, code: string) {
  return refusal(status, { code, message: "raw" });
}

describe("widget admin errors", () => {
  it("reads the widget API's string codes", () => {
    expect(widgetErrorCode(apiError(400, "field_locked_by_template"))).toBe(
      "field_locked_by_template"
    );
    expect(widgetErrorCode(new Error("x"))).toBeNull();
    expect(widgetErrorCode(refusal(400, "text"))).toBeNull();
  });

  it("translates the codes the editor can run into", () => {
    expect(widgetErrorMessage(apiError(400, "field_locked_by_template"), t)).toBe("locked");
    expect(widgetErrorMessage(apiError(400, "template_not_published"), t)).toBe("unpublished");
    expect(widgetErrorMessage(apiError(409, "template_in_use"), t)).toBe("in use");
    expect(widgetErrorMessage(apiError(409, "widget_revision_conflict"), t)).toBe("conflict");
    expect(widgetErrorMessage(apiError(500, "other"), t)).toBeNull();
  });

  it("treats a published lock like a revision conflict", () => {
    expect(isStaleEditorError(apiError(409, "widget_revision_conflict"))).toBe(true);
    expect(isStaleEditorError(apiError(400, "field_locked_by_template"))).toBe(true);
    expect(isStaleEditorError(apiError(422, "validation"))).toBe(false);
  });
});

describe("refused values", () => {
  const policyViolation = refusal(400, {
    code: "widget_policy_violation",
    message: "raw",
    violations: ["daily_token_budget_exceeds_policy", "bot_protection_none_not_allowed"]
  });
  const servingBlocked = refusal(400, {
    code: "widget_serving_blocked",
    message: "raw",
    blockers: ["allowed_origins_empty", "target_not_published"]
  });
  const invalid = refusal(422, [
    { loc: ["body", "texts", "suggested_questions"], type: "value_error", msg: "Invalid value" },
    { loc: ["body", "allowed_origins", 0], type: "value_error", msg: "Invalid value" },
    { loc: ["body", "revision"], type: "missing", msg: "Field required" }
  ]);

  it("pins policy violations and blockers to the fields they are about", () => {
    expect(widgetFieldErrors(policyViolation, t)).toEqual({
      "limits.daily_token_budget": "widget_admin_blocker_budget_policy",
      bot_protection: "widget_admin_blocker_bot_protection"
    });
    // An unpublished assistant is not something the widget form can fix.
    expect(widgetFieldErrors(servingBlocked, t)).toEqual({
      allowed_origins: "widget_admin_blocker_allowed_origins_empty"
    });
  });

  it("pins request validation errors by their location", () => {
    expect(widgetFieldErrors(invalid, t)).toEqual({
      "texts.suggested_questions": "widget_admin_questions_refused",
      allowed_origins: "widget_admin_origins_refused"
    });
    expect(widgetFieldErrors(refusal(503, "down"), t)).toEqual({});
    expect(widgetFieldErrors(new Error("offline"), t)).toEqual({});
  });

  it("pins a template lock that cannot be kept to the subtitle", () => {
    const locks = refusal(400, {
      code: "template_locks_unenforceable",
      message: "raw",
      violations: ["subtitle_required_for_legal_texts_lock"]
    });
    expect(widgetFieldErrors(locks, t)).toEqual({
      "texts.subtitle": "widget_admin_blocker_legal_texts_lock_subtitle"
    });
    expect(widgetErrorMessage(locks, t)).toBe(
      "widget_admin_error_template_locks(widget_admin_blocker_legal_texts_lock_subtitle)"
    );
  });

  it("explains a refusal in the editor's language instead of the raw English", () => {
    expect(widgetErrorMessage(policyViolation, t)).toBe(
      "widget_admin_error_policy_violation(widget_admin_blocker_budget_policy widget_admin_blocker_bot_protection)"
    );
    expect(widgetErrorMessage(servingBlocked, t)).toBe(
      "widget_admin_error_serving_blocked(widget_admin_blocker_allowed_origins_empty widget_admin_blocker_target_not_published)"
    );
    expect(widgetErrorMessage(invalid, t)).toBe("widget_admin_error_values_refused");
  });
});
