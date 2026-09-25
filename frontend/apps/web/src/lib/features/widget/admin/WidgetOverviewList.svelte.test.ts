import { page, userEvent } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import type { Eneo, WidgetOverview, WidgetOverviewItem } from "@eneo/eneo-js";
import axe from "axe-core";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import sv from "../../../../../messages/sv.json";
import "../../../../app.css";

const navigation = vi.hoisted(() => ({ invalidateAll: vi.fn() }));
// Messages read as their keys, or as the real Swedish text where length matters.
const i18n = vi.hoisted(() => ({ catalog: null as Record<string, string> | null }));

vi.mock("$app/navigation", () => ({
  afterNavigate: vi.fn(),
  beforeNavigate: vi.fn(),
  goto: vi.fn(),
  invalidate: vi.fn(),
  invalidateAll: navigation.invalidateAll,
  onNavigate: vi.fn(),
  preloadData: vi.fn(),
  pushState: vi.fn(),
  replaceState: vi.fn()
}));
vi.mock("$lib/paraglide/messages", () => ({
  m: new Proxy(
    {},
    {
      get: (_target, key) => (params?: Record<string, unknown>) => {
        const text = i18n.catalog?.[String(key)];
        if (text) return text.replace(/\{(\w+)\}/g, (_, name) => String(params?.[name] ?? ""));
        return params ? `${String(key)}(${Object.values(params).join("|")})` : String(key);
      }
    }
  )
}));
vi.mock("$lib/paraglide/runtime", () => ({
  getLocale: () => "sv",
  localizeHref: (href: string) => href
}));

import ActivationRequestsTable from "./ActivationRequestsTable.svelte";
import WidgetOverviewList from "./WidgetOverviewList.svelte";

function item(overrides: Partial<WidgetOverviewItem>): WidgetOverviewItem {
  return {
    id: "w1",
    name: "Kontaktchatt",
    status: "active",
    space_id: "s1",
    space_name: "Kundtjänst",
    space_kind: "shared",
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

function renderList(items: WidgetOverviewItem[], eneo: Partial<Eneo["widgets"]> = {}) {
  const overview = {
    totals: { widgets: items.length, active: 0, questions_30d: 0, tokens_30d: 0, blocked_30d: 0 },
    items
  } as unknown as WidgetOverview;
  render(WidgetOverviewList, { overview, eneo: { widgets: eneo } as unknown as Eneo });
}

const requestedBy = { id: "u2", name: "Anna Svensson", email: "anna@kommun.se" };

async function axeViolations(context: Element | Document = document) {
  await userEvent.unhover(document.body);
  await vi.waitFor(() => expect(document.getAnimations()).toHaveLength(0));
  const result = await axe.run(context, {
    runOnly: {
      type: "tag",
      values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22a", "wcag22aa"]
    },
    rules: { "landmark-one-main": { enabled: false }, region: { enabled: false } }
  });
  return result.violations.flatMap((violation) =>
    violation.nodes.map((node) => `${violation.id}: ${node.html}`)
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  i18n.catalog = null;
  document.body.classList.add("bg-primary");
});

afterEach(() => {
  document.body.classList.remove("bg-primary");
  delete document.documentElement.dataset.theme;
});

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

  test("each card links its review by a unique name that starts with the visible text", async () => {
    renderList([item({}), item({ id: "w2", name: "Bygglov", status: "draft" })]);
    const first = page.getByRole("link", {
      name: "widget_admin_overview_review_named(Kontaktchatt)"
    });
    await expect.element(first).toHaveAttribute("href", "/admin/widgets/w1");
    await expect.element(first).toHaveTextContent("widget_admin_overview_review");
    await expect
      .element(page.getByRole("link", { name: "widget_admin_overview_review_named(Bygglov)" }))
      .toHaveAttribute("href", "/admin/widgets/w2");
    await expect
      .element(page.getByRole("link", { name: "Kontaktchatt", exact: true }))
      .toHaveAttribute("href", "/admin/widgets/w1");
  });

  test("activating and resuming only happen after a review", async () => {
    renderList([
      item({ id: "w2", name: "Bygglov", status: "draft" }),
      item({ id: "w3", name: "Skola", status: "paused", activation_blockers: ["subtitle_empty"] })
    ]);
    await expect.element(page.getByRole("heading", { level: 2, name: /Skola/ })).toBeVisible();
    expect(
      page.getByRole("button", { name: /widget_admin_(activate|resume)/ }).elements()
    ).toHaveLength(0);
    // What blocks a paused widget is still said, without a button to hang it on.
    await expect
      .element(page.getByText("widget_admin_overview_blocked(widget_admin_blocker_subtitle_empty)"))
      .toBeVisible();
  });

  test("pausing a live widget still asks first", async () => {
    const pause = vi.fn(async () => ({}));
    renderList([item({})], { pause } as never);
    await userEvent.click(page.getByRole("button", { name: "widget_admin_pause" }));
    const dialog = page.getByRole("alertdialog");
    await expect.element(dialog).toBeVisible();
    expect(pause).not.toHaveBeenCalled();
    await userEvent.click(dialog.getByRole("button", { name: "widget_admin_pause" }));
    await vi.waitFor(() => expect(pause).toHaveBeenCalledWith({ id: "w1" }));
    expect(navigation.invalidateAll).toHaveBeenCalled();
  });

  test("after pausing, focus lands on the widget's review instead of the page", async () => {
    let paused!: () => void;
    const pause = vi.fn(() => new Promise<void>((resolve) => (paused = resolve)));
    renderList([item({}), item({ id: "w2", name: "Bygglov" })], { pause } as never);
    await userEvent.click(
      page
        .getByRole("group", { name: "widget_admin_overview_actions(Kontaktchatt)" })
        .getByRole("button")
    );
    const dialog = page.getByRole("alertdialog");
    const confirm = dialog.getByRole("button", { name: "widget_admin_pause" });
    await userEvent.click(confirm);

    // Still focused while it works: aria-disabled keeps the focus a disabled button would drop.
    const busy = dialog.getByRole("button", { name: "widget_review_pausing" });
    await expect.element(busy).toHaveAttribute("aria-disabled", "true");
    await expect.element(busy).toHaveFocus();
    expect((busy.element() as HTMLButtonElement).disabled).toBe(false);

    paused();
    await vi.waitFor(() => expect(navigation.invalidateAll).toHaveBeenCalled());
    await expect
      .element(page.getByRole("link", { name: "widget_admin_overview_review_named(Kontaktchatt)" }))
      .toHaveFocus();
    expect(document.querySelector('[role="alertdialog"]')).toBeNull();
  });

  test("a requested widget carries a badge and who asked when", async () => {
    renderList([
      item({
        status: "draft",
        activation_requested_at: "2026-09-24T08:30:00Z",
        activation_requested_by: requestedBy
      })
    ]);
    await expect
      .element(page.getByRole("heading", { level: 2, name: /widget_request_badge/ }))
      .toBeVisible();
    await expect
      .element(
        page.getByText(/^widget_admin_overview_awaiting_requested_line\(.*\|Anna Svensson\)$/)
      )
      .toBeVisible();
    expect(document.querySelector("time")?.getAttribute("datetime")).toBe("2026-09-24T08:30:00Z");
  });
});

describe("ActivationRequestsTable", () => {
  const requests = [
    item({
      id: "w-new",
      name: "Bygglov",
      status: "draft",
      space_id: "s2",
      space_name: "Samhällsbyggnad",
      activation_requested_at: "2026-09-24T08:30:00Z",
      activation_requested_by: requestedBy,
      activation_blockers: ["subtitle_empty"]
    }),
    item({ id: "w-live", name: "Kontaktchatt" }),
    item({
      id: "w-old",
      name: "Skolskjuts",
      status: "paused",
      activation_requested_at: "2026-09-20T12:00:00Z",
      activation_requested_by: null
    })
  ];

  test("lists only requests, oldest first, with a captioned table", async () => {
    await page.viewport(1440, 900);
    render(ActivationRequestsTable, { items: requests });
    const table = page.getByRole("table", { name: "widget_admin_overview_awaiting_caption" });
    await expect.element(table).toBeVisible();
    const rows = page.getByRole("rowheader").elements();
    expect(rows.map((row) => row.querySelector("span")?.textContent)).toEqual([
      "Skolskjuts",
      "Bygglov"
    ]);
    await expect
      .element(page.getByRole("link", { name: "widget_admin_overview_review_named(Bygglov)" }))
      .toHaveAttribute("href", "/admin/widgets/w-new");
    await expect
      .element(page.getByRole("link", { name: "Samhällsbyggnad" }))
      .toHaveAttribute("href", "/admin/spaces/s2");
  });

  test("names the organisation space without linking to a page it does not have", async () => {
    await page.viewport(1440, 900);
    render(ActivationRequestsTable, {
      items: [
        item({
          status: "draft",
          space_id: "org",
          space_name: "Organisationens yta",
          space_kind: "organization",
          activation_requested_at: "2026-09-24T08:30:00Z"
        })
      ]
    });
    await expect
      .element(page.getByRole("cell").filter({ hasText: "Organisationens yta" }))
      .toBeVisible();
    expect(page.getByRole("link", { name: "Organisationens yta" }).query()).toBeNull();
  });

  test("says whether each request is ready or what blocks it, in text", async () => {
    await page.viewport(1440, 900);
    render(ActivationRequestsTable, { items: requests });
    await expect
      .element(
        page.getByRole("cell").filter({
          hasText: "widget_admin_overview_awaiting_blocked(widget_admin_blocker_subtitle_empty)"
        })
      )
      .toBeVisible();
    await expect
      .element(page.getByRole("cell").filter({ hasText: "widget_admin_overview_awaiting_ready" }))
      .toBeVisible();
  });

  test.each(["light", "dark"])(
    "has no violations and no sideways scroll at 320 px (%s)",
    async (theme) => {
      document.documentElement.dataset.theme = theme;
      i18n.catalog = sv;
      await page.viewport(320, 720);
      try {
        render(ActivationRequestsTable, { items: requests });
        await expect.element(page.getByRole("table")).toBeVisible();
        expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(320);
        const container = document.querySelector<HTMLElement>('[data-slot="table-container"]');
        expect(container!.scrollWidth).toBeLessThanOrEqual(container!.clientWidth);
        expect(await axeViolations()).toEqual([]);
      } finally {
        await page.viewport(1440, 900);
      }
    }
  );
});
