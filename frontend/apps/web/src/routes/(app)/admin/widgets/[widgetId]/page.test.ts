import { EneoError } from "@eneo/eneo-js";
import { describe, expect, test, vi } from "vitest";
import { load } from "./+page";

const policy = {
  max_daily_token_budget: 1000,
  min_retention_days: 0,
  max_retention_days: 90,
  allow_bot_protection_none: false
};

function event(review: (args: { id: string }) => Promise<unknown>) {
  return {
    parent: async () => ({
      eneo: { widgets: { review, policy: { get: async () => policy } } }
    }),
    depends: vi.fn(),
    params: { widgetId: "widget-1" }
  };
}

describe("loading a widget review in Admin → Webbwidgetar", () => {
  test("loads the review the URL names, with the policy", async () => {
    const review = vi.fn(async () => ({ widget: { id: "widget-1" } }));
    const loadEvent = event(review);
    await expect(load(loadEvent as never)).resolves.toEqual({
      review: { widget: { id: "widget-1" } },
      policy
    });
    expect(review).toHaveBeenCalledWith({ id: "widget-1" });
    expect(loadEvent.depends).toHaveBeenCalledWith("admin:widget-review");
  });

  test("a widget that is not there renders the page's own not-found state", async () => {
    const missing = event(() => Promise.reject(new EneoError("Not found", "RESPONSE", 404, 0, {})));
    await expect(load(missing as never)).resolves.toEqual({ review: null, policy: null });
  });

  test("a truncated or mistyped id is not found either, not an error page", async () => {
    const malformed = event(() =>
      Promise.reject(new EneoError("Validation error", "RESPONSE", 422, 9012, {}))
    );
    await expect(load(malformed as never)).resolves.toEqual({ review: null, policy: null });
  });

  test("other failures still reach the error page", async () => {
    const failed = event(() => Promise.reject(new EneoError("Down", "SERVER", 502, 0, {})));
    await expect(load(failed as never)).rejects.toMatchObject({ status: 502 });
  });
});
