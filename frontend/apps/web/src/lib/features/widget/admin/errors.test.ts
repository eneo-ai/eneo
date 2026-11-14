import { describe, expect, it, vi } from "vitest";

vi.mock("$lib/components/toast", () => ({ toast: { error: vi.fn() } }));
vi.mock("$lib/core/errors", () => ({ toastError: vi.fn() }));
vi.mock("$lib/paraglide/messages", () => ({
  m: new Proxy<Record<string, (params?: Record<string, string>) => string>>(
    {
      widget_admin_error_field_locked: () => "locked",
      widget_admin_error_template_not_published: () => "unpublished",
      widget_admin_template_in_use: () => "in use",
      widget_admin_save_conflict: () => "conflict"
    },
    {
      get: (target, key: string) =>
        target[key] ??
        ((params?: Record<string, string>) =>
          params ? `${key}(${Object.values(params).join("|")})` : key)
    }
  )
}));

import { EneoError } from "@eneo/eneo-js";
import {
  currentExternalTools,
  isStaleEditorError,
  widgetErrorCode,
  widgetErrorMessage,
  widgetFieldErrors
} from "./errors";

function apiError(status: number, code: string) {
  return new EneoError("raw", "RESPONSE", status, 0, { detail: { code, message: "raw" } });
}

describe("widget admin errors", () => {
  it("reads the widget API's string codes", () => {
    expect(widgetErrorCode(apiError(400, "field_locked_by_template"))).toBe(
      "field_locked_by_template"
    );
    expect(widgetErrorCode(new Error("x"))).toBeNull();
    expect(widgetErrorCode(new EneoError("x", "RESPONSE", 400, 0, { detail: "text" }))).toBeNull();
  });

  it("translates the codes the editor can run into", () => {
    expect(widgetErrorMessage(apiError(400, "field_locked_by_template"))).toBe("locked");
    expect(widgetErrorMessage(apiError(400, "template_not_published"))).toBe("unpublished");
    expect(widgetErrorMessage(apiError(409, "template_in_use"))).toBe("in use");
    expect(widgetErrorMessage(apiError(409, "widget_revision_conflict"))).toBe("conflict");
    expect(widgetErrorMessage(apiError(500, "other"))).toBeNull();
  });

  it("names the template when leaving it is what a live widget needs an admin for", () => {
    const refusal = (fields: string[]) =>
      new EneoError("raw", "RESPONSE", 403, 0, {
        detail: { code: "admin_required_while_active", message: "raw", fields }
      });
    expect(widgetErrorMessage(refusal(["template"]))).toBe(
      "widget_admin_template_detach_admin_only"
    );
    expect(widgetErrorMessage(refusal(["allowed_origins"]))).toBe(
      "widget_admin_error_admin_required_while_active"
    );
  });

  it("pins a live widget's admin-only settings to the fields that hold them", () => {
    const refusal = new EneoError("raw", "RESPONSE", 403, 0, {
      detail: {
        code: "admin_required_while_active",
        message: "raw",
        fields: ["allowed_origins", "privacy", "bot_protection", "template"]
      }
    });
    // The template has no field of its own: leaving it is refused in the picker.
    expect(widgetFieldErrors(refusal)).toEqual({
      allowed_origins: "widget_admin_error_admin_required_while_active",
      "privacy.retention_days": "widget_admin_error_admin_required_while_active",
      bot_protection: "widget_admin_error_admin_required_while_active"
    });
  });

  it("hands back the current external tools when the admin saw another list", () => {
    const servers = [{ id: "m1", name: "Ärenden", tools: [{ id: "t1", name: "Sök" }] }];
    const refusal = (status: number, code: string) =>
      new EneoError("raw", "RESPONSE", status, 0, { detail: { code, message: "raw", servers } });
    expect(currentExternalTools(refusal(409, "external_tools_changed"))).toEqual(servers);
    expect(currentExternalTools(refusal(400, "external_tools_unacknowledged"))).toEqual(servers);
    expect(currentExternalTools(refusal(400, "widget_serving_blocked"))).toBeNull();
    expect(currentExternalTools(new Error("x"))).toBeNull();
  });

  it("treats a published lock like a revision conflict", () => {
    expect(isStaleEditorError(apiError(409, "widget_revision_conflict"))).toBe(true);
    expect(isStaleEditorError(apiError(400, "field_locked_by_template"))).toBe(true);
    expect(isStaleEditorError(apiError(422, "validation"))).toBe(false);
  });
});

describe("refused values", () => {
  const policyViolation = new EneoError("raw", "RESPONSE", 400, 0, {
    detail: {
      code: "widget_policy_violation",
      message: "raw",
      violations: ["daily_token_budget_exceeds_policy", "bot_protection_none_not_allowed"]
    }
  });
  const servingBlocked = new EneoError("raw", "RESPONSE", 400, 0, {
    detail: {
      code: "widget_serving_blocked",
      message: "raw",
      blockers: ["allowed_origins_empty", "target_not_published"]
    }
  });
  const invalid = new EneoError("raw", "RESPONSE", 422, 0, {
    detail: [
      { loc: ["body", "texts", "suggested_questions"], type: "value_error", msg: "Invalid value" },
      { loc: ["body", "allowed_origins", 0], type: "value_error", msg: "Invalid value" },
      { loc: ["body", "revision"], type: "missing", msg: "Field required" }
    ]
  });

  it("pins policy violations and blockers to the fields they are about", () => {
    expect(widgetFieldErrors(policyViolation)).toEqual({
      "limits.daily_token_budget": "widget_admin_blocker_budget_policy",
      bot_protection: "widget_admin_blocker_bot_protection"
    });
    // An unpublished assistant is not something the widget form can fix.
    expect(widgetFieldErrors(servingBlocked)).toEqual({
      allowed_origins: "widget_admin_blocker_allowed_origins_empty"
    });
  });

  it("pins request validation errors by their location", () => {
    expect(widgetFieldErrors(invalid)).toEqual({
      "texts.suggested_questions": "widget_admin_questions_refused",
      allowed_origins: "widget_admin_origins_refused"
    });
    expect(widgetFieldErrors(new EneoError("x", "RESPONSE", 503, 0))).toEqual({});
    expect(widgetFieldErrors(new Error("offline"))).toEqual({});
  });

  it("pins a template lock that cannot be kept to the subtitle", () => {
    const locks = new EneoError("raw", "RESPONSE", 400, 0, {
      detail: {
        code: "template_locks_unenforceable",
        message: "raw",
        violations: ["subtitle_required_for_legal_texts_lock"]
      }
    });
    expect(widgetFieldErrors(locks)).toEqual({
      "texts.subtitle": "widget_admin_blocker_legal_texts_lock_subtitle"
    });
    expect(widgetErrorMessage(locks)).toBe(
      "widget_admin_error_template_locks(widget_admin_blocker_legal_texts_lock_subtitle)"
    );
  });

  it("explains a refusal in the editor's language instead of the raw English", () => {
    expect(widgetErrorMessage(policyViolation)).toBe(
      "widget_admin_error_policy_violation(widget_admin_blocker_budget_policy widget_admin_blocker_bot_protection)"
    );
    expect(widgetErrorMessage(servingBlocked)).toBe(
      "widget_admin_error_serving_blocked(widget_admin_blocker_allowed_origins_empty widget_admin_blocker_target_not_published)"
    );
    expect(widgetErrorMessage(invalid)).toBe("widget_admin_error_values_refused");
  });
});
