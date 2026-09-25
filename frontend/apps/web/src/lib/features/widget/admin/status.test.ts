import { describe, expect, it, vi } from "vitest";

vi.mock("$lib/paraglide/messages", () => ({
  m: new Proxy({}, { get: (_target, key) => () => String(key) })
}));

import { activationRequestState, widgetStatusLabel } from "./status";

describe("widgetStatusLabel", () => {
  it("names every lifecycle status with its own message", () => {
    expect(
      (["draft", "active", "paused", "archived"] as const).map((status) =>
        widgetStatusLabel(status)
      )
    ).toEqual([
      "widget_admin_status_draft",
      "widget_admin_status_active",
      "widget_admin_status_paused",
      "widget_admin_status_archived"
    ]);
  });

  it("shows a status this build does not know as it came", () => {
    expect(widgetStatusLabel("retired" as never)).toBe("retired");
  });
});

describe("activationRequestState", () => {
  const at = "2026-09-21T08:00:00Z";

  it("has no request for a live or archived widget, whatever the timestamps say", () => {
    for (const status of ["active", "archived"] as const) {
      expect(
        activationRequestState({
          status,
          activation_requested_at: at,
          activation_declined_at: at
        })
      ).toEqual({ kind: "not_applicable" });
    }
  });

  it("tells a waiting request from one sent back, and from none", () => {
    for (const status of ["draft", "paused"] as const) {
      expect(activationRequestState({ status, activation_requested_at: at })).toEqual({
        kind: "requested",
        at
      });
      expect(
        activationRequestState({
          status,
          activation_requested_at: null,
          activation_declined_at: at
        })
      ).toEqual({ kind: "returned", at });
      expect(activationRequestState({ status })).toEqual({ kind: "none" });
    }
    // A new request clears the send-back, so the request wins.
    expect(
      activationRequestState({
        status: "draft",
        activation_requested_at: at,
        activation_declined_at: "2026-09-01T08:00:00Z"
      })
    ).toEqual({ kind: "requested", at });
  });
});
