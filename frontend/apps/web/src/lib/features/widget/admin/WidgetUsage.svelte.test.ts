import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import type { Eneo, Widget, WidgetUsage as Usage } from "@eneo/eneo-js";
import { describe, expect, test, vi } from "vitest";

vi.mock("$lib/paraglide/messages", () => ({
  m: new Proxy<Record<string, (params?: Record<string, string>) => string>>(
    {},
    {
      get: (_target, key) => (params?: Record<string, string>) =>
        params ? `${String(key)}(${Object.values(params).join("|")})` : String(key)
    }
  )
}));
vi.mock("$lib/paraglide/runtime", () => ({ getLocale: () => "sv" }));

import WidgetUsage from "./WidgetUsage.svelte";

const widget = {
  id: "w1",
  limits: { daily_token_budget: 4000 },
  updated_at: "2026-09-21T10:00:00Z"
} as unknown as Widget;

function usage(overrides: Partial<Usage> = {}): Usage {
  return {
    daily_token_budget: 4000,
    budget_used_today: 0,
    days: [],
    ...overrides
  } as Usage;
}

function day(overrides: Partial<Usage["days"][number]> = {}) {
  return {
    day: "2026-09-21",
    questions: 0,
    input_tokens: 0,
    output_tokens: 0,
    blocked_budget: 0,
    blocked_rate: 0,
    helpful: 0,
    unhelpful: 0,
    ...overrides
  };
}

function renderUsage(answer: Usage) {
  const fetchUsage = vi.fn(async () => answer);
  const eneo = { widgets: { usage: fetchUsage } } as unknown as Eneo;
  const screen = render(WidgetUsage, { widget, eneo });
  return { screen, fetchUsage };
}

describe("WidgetUsage totals", () => {
  test("a count of one is written in the singular", async () => {
    renderUsage(usage({ days: [day({ questions: 1, blocked_rate: 1, unhelpful: 1 })] }));
    await expect
      .element(
        page.getByText(
          "widget_admin_usage_totals(widget_admin_usage_questions_total_one|widget_admin_usage_blocked_total_one)"
        )
      )
      .toBeVisible();
    await expect.element(page.getByText(/widget_admin_usage_unhelpful_total_one/)).toBeVisible();
  });

  test("other counts keep the plural", async () => {
    renderUsage(usage({ days: [day({ questions: 2, unhelpful: 0 })] }));
    await expect
      .element(
        page.getByText(
          "widget_admin_usage_totals(widget_admin_usage_questions_total(2)|widget_admin_usage_blocked_total(0))"
        )
      )
      .toBeVisible();
    await expect.element(page.getByText(/widget_admin_usage_unhelpful_total\(0\)/)).toBeVisible();
  });
});

describe("WidgetUsage freshness", () => {
  test("a hidden card is fetched when it comes into view, and again each time", async () => {
    const fetchUsage = vi.fn(async () => usage());
    const eneo = { widgets: { usage: fetchUsage } } as unknown as Eneo;
    const screen = render(WidgetUsage, { widget, eneo, visible: false });
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(fetchUsage).not.toHaveBeenCalled();

    await screen.rerender({ visible: true });
    await vi.waitFor(() => expect(fetchUsage).toHaveBeenCalledTimes(1));
    await screen.rerender({ visible: false });
    await screen.rerender({ visible: true });
    await vi.waitFor(() => expect(fetchUsage).toHaveBeenCalledTimes(2));
  });

  test("a saved budget change shows the budget in force, not the old one", async () => {
    const fetchUsage = vi
      .fn()
      .mockResolvedValueOnce(usage({ daily_token_budget: 4000 }))
      .mockResolvedValueOnce(usage({ daily_token_budget: 8000 }));
    const eneo = { widgets: { usage: fetchUsage } } as unknown as Eneo;
    const screen = render(WidgetUsage, { widget, eneo });
    await expect.element(page.getByText(/widget_admin_budget_used\(0\|4\s000\)/)).toBeVisible();

    // A new copy of the same saved widget is not news.
    await screen.rerender({ widget: { ...widget } });
    await screen.rerender({
      widget: {
        ...widget,
        limits: { daily_token_budget: 8000 },
        updated_at: "2026-09-21T10:05:00Z"
      } as unknown as Widget
    });
    await expect.element(page.getByText(/widget_admin_budget_used\(0\|8\s000\)/)).toBeVisible();
    expect(fetchUsage).toHaveBeenCalledTimes(2);
  });
});
