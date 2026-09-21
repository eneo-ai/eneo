import { page, userEvent } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import type { WidgetPolicy } from "@eneo/eneo-js";
import { describe, expect, test, vi } from "vitest";
import "../../../../app.css";

vi.mock("$app/navigation", () => ({
  afterNavigate: vi.fn(),
  beforeNavigate: vi.fn(),
  goto: vi.fn(),
  invalidate: vi.fn(),
  invalidateAll: vi.fn(),
  onNavigate: vi.fn(),
  preloadData: vi.fn(),
  pushState: vi.fn(),
  replaceState: vi.fn()
}));
vi.mock("$app/state", () => ({
  page: { url: new URL("http://localhost/admin/widgets?tab=policy"), state: {} }
}));
vi.mock("$lib/paraglide/messages", () => ({
  m: new Proxy<Record<string, () => string>>({}, { get: (_target, key) => () => String(key) })
}));
vi.mock("$lib/paraglide/runtime", () => ({
  getLocale: () => "sv",
  localizeHref: (href: string) => href
}));

import WidgetsAdminPage from "./+page.svelte";

const policy: WidgetPolicy = {
  max_daily_token_budget: 1000,
  min_retention_days: 0,
  max_retention_days: 365,
  allow_bot_protection_none: false
};

function renderPage(update: (patch: Partial<WidgetPolicy>) => Promise<WidgetPolicy>) {
  return render(WidgetsAdminPage, {
    data: {
      policy,
      templates: [],
      overview: {
        totals: { widgets: 0, active: 0, questions_30d: 0, tokens_30d: 0, blocked_30d: 0 },
        items: []
      },
      eneo: {
        widgets: {
          policy: { update },
          templates: { create: vi.fn(), update: vi.fn(), delete: vi.fn() },
          pause: vi.fn(),
          activate: vi.fn()
        }
      }
    } as never
  });
}

describe("widget policy page", () => {
  test("keeps an edit made during a slow save and saves it afterwards", async () => {
    let resolveFirst!: (value: WidgetPolicy) => void;
    const update = vi
      .fn<(patch: Partial<WidgetPolicy>) => Promise<WidgetPolicy>>()
      .mockImplementationOnce(() => new Promise((resolve) => (resolveFirst = resolve)))
      .mockImplementationOnce(async (patch) => ({
        ...policy,
        max_daily_token_budget: 2000,
        ...patch
      }));
    renderPage(update);

    const budget = page.getByLabelText("widget_admin_policy_max_budget");
    const retention = page.getByLabelText("widget_admin_policy_retention_min");
    // Numbers are committed when the field is left, never per keystroke.
    await userEvent.fill(budget, "2000");
    await userEvent.tab();
    await vi.waitFor(() => expect(update).toHaveBeenCalledTimes(1), { timeout: 3000 });
    expect(update).toHaveBeenNthCalledWith(1, { max_daily_token_budget: 2000 });

    // Edited while the first save is still pending: stays visible, not sent yet.
    await userEvent.fill(retention, "5");
    await userEvent.tab();
    await expect.element(retention).toHaveValue(5);
    expect(update).toHaveBeenCalledTimes(1);

    // The server echoes the policy as of the first patch only.
    resolveFirst({ ...policy, max_daily_token_budget: 2000 });
    await vi.waitFor(() => expect(update).toHaveBeenCalledTimes(2), { timeout: 3000 });
    expect(update).toHaveBeenNthCalledWith(2, { min_retention_days: 5 });
    await expect.element(retention).toHaveValue(5);
    await expect.element(budget).toHaveValue(2000);
    await expect.element(page.getByText("widget_admin_saved")).toBeVisible();
  });

  test("keeps an out-of-range number in the field with an error instead of saving it", async () => {
    const update = vi.fn<(patch: Partial<WidgetPolicy>) => Promise<WidgetPolicy>>();
    renderPage(update);

    const budget = page.getByLabelText("widget_admin_policy_max_budget");
    await userEvent.fill(budget, "5");
    await userEvent.tab();
    await expect.element(page.getByText("widget_admin_value_out_of_range")).toBeVisible();
    await expect.element(budget).toHaveAttribute("aria-invalid", "true");
    expect(update).not.toHaveBeenCalled();

    await userEvent.fill(budget, "3000");
    await userEvent.tab();
    await vi.waitFor(() => expect(update).toHaveBeenCalledTimes(1), { timeout: 3000 });
    expect(update).toHaveBeenCalledWith({ max_daily_token_budget: 3000 });
  });
});
