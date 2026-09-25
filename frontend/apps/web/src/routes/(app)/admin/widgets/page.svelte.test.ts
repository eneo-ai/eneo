import { page, userEvent } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import type { WidgetOverviewItem, WidgetPolicy } from "@eneo/eneo-js";
import axe from "axe-core";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import "../../../../app.css";

const state = vi.hoisted(() => ({ url: "http://localhost/admin/widgets?tab=policy" }));

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
  page: {
    get url() {
      return new URL(state.url);
    },
    state: {}
  }
}));
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

import WidgetsAdminPage from "./+page.svelte";

const policy: WidgetPolicy = {
  max_daily_token_budget: 1000,
  min_retention_days: 0,
  max_retention_days: 365,
  allow_bot_protection_none: false
};

const emptyTotals = {
  widgets: 0,
  active: 0,
  awaiting_activation: 0,
  questions_30d: 0,
  tokens_30d: 0,
  blocked_30d: 0
};

/** Page.Main sizes itself to its container, which the app shell normally gives a height. */
function shell(): HTMLElement {
  const target = document.createElement("div");
  target.className = "flex h-[900px] flex-col";
  document.body.append(target);
  return target;
}

function renderPage(
  update: (patch: Partial<WidgetPolicy>) => Promise<WidgetPolicy>,
  totals = emptyTotals,
  items: WidgetOverviewItem[] = []
) {
  return render(WidgetsAdminPage, {
    target: shell(),
    props: {
      data: {
        policy,
        templates: [],
        overview: { totals, items },
        eneo: {
          widgets: {
            policy: { update },
            templates: { create: vi.fn(), update: vi.fn(), delete: vi.fn() },
            pause: vi.fn(),
            activate: vi.fn()
          }
        }
      } as never
    }
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

  test("the maximum budget may reach the API's ceiling but not pass it", async () => {
    const update = vi.fn(async (patch: Partial<WidgetPolicy>) => ({ ...policy, ...patch }));
    renderPage(update);
    const budget = page.getByLabelText("widget_admin_policy_max_budget");
    await userEvent.fill(budget, "2000000001");
    await userEvent.tab();
    await expect.element(budget).toHaveAttribute("aria-invalid", "true");
    expect(update).not.toHaveBeenCalled();

    await userEvent.fill(budget, "2000000000");
    await userEvent.tab();
    await vi.waitFor(() => expect(update).toHaveBeenCalledTimes(1), { timeout: 3000 });
    expect(update).toHaveBeenCalledWith({ max_daily_token_budget: 2_000_000_000 });
    await expect.element(budget).toHaveAttribute("aria-invalid", "false");
  });

  test("keeps an out-of-range number in the field with an error instead of saving it", async () => {
    const update = vi.fn<(patch: Partial<WidgetPolicy>) => Promise<WidgetPolicy>>();
    renderPage(update);

    const budget = page.getByLabelText("widget_admin_policy_max_budget");
    await userEvent.fill(budget, "5");
    await userEvent.tab();
    await expect.element(page.getByText(/^widget_admin_value_out_of_range/)).toBeVisible();
    await expect.element(budget).toHaveAttribute("aria-invalid", "true");
    expect(update).not.toHaveBeenCalled();

    await userEvent.fill(budget, "3000");
    await userEvent.tab();
    await vi.waitFor(() => expect(update).toHaveBeenCalledTimes(1), { timeout: 3000 });
    expect(update).toHaveBeenCalledWith({ max_daily_token_budget: 3000 });
  });
});

describe("widget overview totals", () => {
  test("one active widget is counted in the singular", async () => {
    renderPage(vi.fn(), { ...emptyTotals, widgets: 3, active: 1 });
    await vi.waitFor(() =>
      expect(document.body.textContent).toContain("widget_admin_stat_active_one")
    );
    expect(document.body.textContent).not.toContain("widget_admin_stat_active(");
  });
});

describe("widget policy retention window", () => {
  test("a minimum above the maximum stays in the field instead of failing the save", async () => {
    const update = vi.fn<(patch: Partial<WidgetPolicy>) => Promise<WidgetPolicy>>();
    renderPage(update);

    const min = page.getByLabelText("widget_admin_policy_retention_min");
    await userEvent.fill(min, "400");
    await userEvent.tab();
    await expect.element(page.getByText("widget_admin_retention_window_min(365)")).toBeVisible();
    await expect.element(min).toHaveAttribute("aria-invalid", "true");

    // Raising the maximum makes the typed minimum valid: the pair is saved
    // together and neither field keeps a stale error.
    const max = page.getByLabelText("widget_admin_policy_retention_max");
    await userEvent.fill(max, "500");
    await userEvent.tab();
    await vi.waitFor(() => expect(update).toHaveBeenCalledTimes(1), { timeout: 3000 });
    expect(update).toHaveBeenCalledWith({ min_retention_days: 400, max_retention_days: 500 });
    await expect.element(min).toHaveAttribute("aria-invalid", "false");
    expect(page.getByText(/widget_admin_retention_window/).elements()).toHaveLength(0);
  });

  test("a maximum below the minimum waits for the minimum to follow", async () => {
    const update = vi.fn(async (patch: Partial<WidgetPolicy>) => ({ ...policy, ...patch }));
    render(WidgetsAdminPage, {
      data: {
        policy: { ...policy, min_retention_days: 30 },
        templates: [],
        overview: { totals: emptyTotals, items: [] },
        eneo: { widgets: { policy: { update }, templates: {}, pause: vi.fn() } }
      } as never
    });

    const max = page.getByLabelText("widget_admin_policy_retention_max");
    await userEvent.fill(max, "20");
    await userEvent.tab();
    await expect.element(page.getByText("widget_admin_retention_window_max(30)")).toBeVisible();

    const min = page.getByLabelText("widget_admin_policy_retention_min");
    await userEvent.fill(min, "10");
    await userEvent.tab();
    await vi.waitFor(() => expect(update).toHaveBeenCalledTimes(1), { timeout: 3000 });
    expect(update).toHaveBeenCalledWith({ min_retention_days: 10, max_retention_days: 20 });
    await expect.element(max).toHaveAttribute("aria-invalid", "false");
  });

  test("the policy card title is a section heading", async () => {
    renderPage(vi.fn());
    await expect
      .element(page.getByRole("heading", { level: 2, name: "widget_admin_policy" }))
      .toBeVisible();
  });
});

describe("widget activation requests", () => {
  const requested = {
    id: "w1",
    name: "Bygglovschatt",
    status: "draft",
    space_id: "s1",
    space_name: "Samhällsbyggnad",
    target_id: "a1",
    assistant_name: "Bygglov",
    allowed_origins: ["https://www.kommun.se"],
    activation_blockers: [],
    activation_requested_at: "2026-09-24T08:30:00Z",
    activation_requested_by: { id: "u2", name: "Anna Svensson", email: "anna@kommun.se" },
    daily_token_budget: 1000,
    budget_used_today: 0,
    questions_7d: 0,
    questions_30d: 0,
    input_tokens_30d: 0,
    output_tokens_30d: 0,
    blocked_30d: 0,
    helpful_30d: 0,
    unhelpful_30d: 0,
    last_activity: null
  } as unknown as WidgetOverviewItem;

  beforeEach(() => {
    state.url = "http://localhost/admin/widgets";
  });

  afterEach(() => {
    state.url = "http://localhost/admin/widgets?tab=policy";
    document.body.classList.remove("bg-primary");
    delete document.documentElement.dataset.theme;
  });

  test("a waiting request gets its own headed section and a tile", async () => {
    renderPage(vi.fn(), { ...emptyTotals, widgets: 1, awaiting_activation: 1 }, [requested]);
    const heading = page.getByRole("heading", {
      level: 2,
      name: "widget_admin_overview_awaiting_title"
    });
    await expect.element(heading).toBeVisible();
    const section = heading.element().closest("section");
    expect(section?.id).toBe("activation-requests");
    expect(section?.getAttribute("aria-labelledby")).toBe(heading.element().id);
    await expect
      .element(page.getByRole("table", { name: "widget_admin_overview_awaiting_caption" }))
      .toBeVisible();

    const tile = page
      .getByRole("listitem")
      .filter({ hasText: "widget_admin_overview_awaiting_title" })
      .filter({ hasNotText: "widget_admin_overview_awaiting_help" });
    await expect.element(tile).toHaveTextContent(/1$/);
  });

  test("without requests the section is left out and the tile says 0", async () => {
    renderPage(vi.fn(), { ...emptyTotals, widgets: 1 }, [
      { ...requested, activation_requested_at: null }
    ]);
    await expect.element(page.getByText("widget_admin_overview_awaiting_title")).toBeVisible();
    expect(document.getElementById("activation-requests")).toBeNull();
  });

  test.each(["light", "dark"])("the widgets tab has no violations (%s)", async (theme) => {
    document.documentElement.dataset.theme = theme;
    document.body.classList.add("bg-primary");
    renderPage(vi.fn(), { ...emptyTotals, widgets: 1, awaiting_activation: 1 }, [requested]);
    await expect.element(page.getByRole("table")).toBeVisible();
    await userEvent.unhover(document.body);
    await vi.waitFor(() => expect(document.getAnimations()).toHaveLength(0));
    const result = await axe.run(document.body, {
      runOnly: {
        type: "tag",
        values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22a", "wcag22aa"]
      },
      rules: { "landmark-one-main": { enabled: false }, region: { enabled: false } }
    });
    expect(
      result.violations.flatMap((violation) =>
        violation.nodes.map((node) => `${violation.id}: ${node.html}`)
      )
    ).toEqual([]);
  });
});
