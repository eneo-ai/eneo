import { describe, expect, it, vi } from "vitest";

vi.mock("$lib/paraglide/messages", () => ({
  m: new Proxy({}, { get: (_target, key) => () => String(key) })
}));

import { widgetStatusLabel } from "./status";

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
