import { describe, expect, it, vi } from "vitest";

vi.mock("$lib/components/toast", () => ({ toast: { error: vi.fn() } }));
vi.mock("$lib/core/errors", () => ({ toastError: vi.fn() }));
vi.mock("$lib/paraglide/messages", () => ({
  m: {
    widget_admin_error_field_locked: () => "locked",
    widget_admin_error_template_not_published: () => "unpublished",
    widget_admin_template_in_use: () => "in use",
    widget_admin_save_conflict: () => "conflict"
  }
}));

import { EneoError } from "@eneo/eneo-js";
import { isStaleEditorError, widgetErrorCode, widgetErrorMessage } from "./errors";

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

  it("treats a published lock like a revision conflict", () => {
    expect(isStaleEditorError(apiError(409, "widget_revision_conflict"))).toBe(true);
    expect(isStaleEditorError(apiError(400, "field_locked_by_template"))).toBe(true);
    expect(isStaleEditorError(apiError(422, "validation"))).toBe(false);
  });
});
