import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import type { WidgetOverview, WidgetOverviewItem } from "@eneo/eneo-js";
import { describe, expect, test, vi } from "vitest";
import "../../../../app.css";

vi.mock("$app/navigation", () => ({ invalidateAll: vi.fn() }));
vi.mock("$lib/paraglide/messages", () => ({
  m: new Proxy<Record<string, (params?: Record<string, string>) => string>>(
    {},
    {
      get: (_target, key) => (params?: Record<string, string>) =>
        params ? `${String(key)}(${Object.values(params).join("|")})` : String(key)
    }
  )
}));
vi.mock("$lib/paraglide/runtime", () => ({
  getLocale: () => "sv",
  localizeHref: (href: string) => href
}));

import WidgetOverviewList from "./WidgetOverviewList.svelte";

function item(overrides: Partial<WidgetOverviewItem>): WidgetOverviewItem {
  return {
    id: "w1",
    name: "Kontaktchatt",
    status: "active",
    space_id: "s1",
    space_name: "Kundtjänst",
    target_id: "a1",
    assistant_name: "Kontakt",
    allowed_origins: ["https://www.kommun.se"],
    activation_blockers: [],
    daily_token_budget: 1000,
    budget_used_today: 0,
    questions_7d: 0,
    questions_30d: 0,
    input_tokens_30d: 0,
    output_tokens_30d: 0,
    blocked_30d: 0,
    helpful_30d: 0,
    unhelpful_30d: 0,
    last_activity: null,
    ...overrides
  } as WidgetOverviewItem;
}

function renderList(items: WidgetOverviewItem[]) {
  const overview = {
    totals: { widgets: items.length, active: 0, questions_30d: 0, tokens_30d: 0, blocked_30d: 0 },
    items
  } as unknown as WidgetOverview;
  render(WidgetOverviewList, { overview, eneo: {} as never });
}

describe("WidgetOverviewList", () => {
  test("an active widget that is not serving as configured is flagged on its card", async () => {
    renderList([item({ activation_blockers: ["target_not_published"] })]);
    await expect
      .element(
        page.getByText(
          "widget_admin_overview_active_issues(widget_admin_blocker_target_not_published)"
        )
      )
      .toBeVisible();
    await expect.element(page.getByRole("button", { name: "widget_admin_pause" })).toBeEnabled();
  });

  test("one allowed site is counted in the singular", async () => {
    renderList([
      item({}),
      item({ id: "w2", name: "Bygglov", allowed_origins: ["https://a.se", "https://b.se"] })
    ]);
    await expect.element(page.getByText(/widget_admin_overview_origins_one/)).toBeVisible();
    await expect.element(page.getByText(/widget_admin_overview_origins\(2\)/)).toBeVisible();
  });

  test("a healthy active widget has no warning, and each card is a heading", async () => {
    renderList([item({}), item({ id: "w2", name: "Bygglov", status: "paused" })]);
    expect(document.body.textContent).not.toContain("widget_admin_overview_active_issues");
    await expect
      .element(page.getByRole("heading", { level: 2, name: /Kontaktchatt/ }))
      .toBeVisible();
    await expect.element(page.getByRole("heading", { level: 2, name: /Bygglov/ })).toBeVisible();
  });
});
