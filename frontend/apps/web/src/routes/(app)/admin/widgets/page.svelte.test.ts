/* eslint-disable eneo/no-raw-color -- fixtures use literal widget colours */
import { page, userEvent } from "vitest/browser";
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

import { beforeNavigate, goto, invalidateAll } from "$app/navigation";
import WidgetsAdminPage from "./+page.svelte";

/** Whether leaving the page right now would ask for confirmation. */
function leavingAsks(): boolean {
  const leave = vi.mocked(beforeNavigate).mock.lastCall![0];
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
  try {
    leave({ cancel: vi.fn() } as unknown as Parameters<typeof leave>[0]);
    return confirm.mock.calls.length > 0;
  } finally {
    confirm.mockRestore();
  }
}

function tpl(id: string, name: string, is_default = false) {
  return {
    id,
    name,
    description: "",
    theme: { primary_color: "#1F4E79", radius: 12 },
    language: "sv",
    is_default,
    locked_groups: [],
    linked_widgets: 0,
    published_at: "2026-09-21T10:00:00Z",
    has_unpublished_changes: false,
    created_at: "2026-09-21T10:00:00Z",
    updated_at: "2026-09-21T10:00:00Z"
  };
}

const policy: WidgetPolicy = {
  max_daily_token_budget: 1000,
  min_retention_days: 0,
  max_retention_days: 365,
  allow_bot_protection_none: false
};

function renderPage(
  update: (patch: Partial<WidgetPolicy>) => Promise<WidgetPolicy>,
  totals = { widgets: 0, active: 0, questions_30d: 0, tokens_30d: 0, blocked_30d: 0 },
  create: () => Promise<unknown> = vi.fn(),
  templates: { items?: unknown[]; update?: (args: unknown) => Promise<unknown> } = {}
) {
  return render(WidgetsAdminPage, {
    data: {
      policy,
      templates: templates.items ?? [],
      overview: { totals, items: [] },
      eneo: {
        widgets: {
          policy: { update },
          templates: { create, update: templates.update ?? vi.fn(), delete: vi.fn() },
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

  test("a saved policy reloads the overview, whose blockers fold the policy in", async () => {
    vi.mocked(invalidateAll).mockClear();
    const update = vi.fn(async (patch: Partial<WidgetPolicy>) => ({ ...policy, ...patch }));
    renderPage(update);
    (
      page.getByRole("switch", { name: "widget_admin_policy_allow_none" }).element() as HTMLElement
    ).click();
    await vi.waitFor(() => expect(update).toHaveBeenCalledTimes(1), { timeout: 3000 });
    expect(update).toHaveBeenCalledWith({ allow_bot_protection_none: true });
    await vi.waitFor(() => expect(invalidateAll).toHaveBeenCalledTimes(1));
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
    renderPage(vi.fn(), {
      widgets: 3,
      active: 1,
      questions_30d: 0,
      tokens_30d: 0,
      blocked_30d: 0
    });
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
        overview: {
          totals: { widgets: 0, active: 0, questions_30d: 0, tokens_30d: 0, blocked_30d: 0 },
          items: []
        },
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

  test("a budget typed but not yet committed counts as unsaved", async () => {
    const update = vi.fn(async (patch: Partial<WidgetPolicy>) => ({ ...policy, ...patch }));
    renderPage(update);
    const budget = page.getByLabelText("widget_admin_policy_max_budget");
    await userEvent.fill(budget, "5000");
    expect(leavingAsks()).toBe(true);
    expect(update).not.toHaveBeenCalled();
    await userEvent.tab();
    await vi.waitFor(() => expect(update).toHaveBeenCalledTimes(1), { timeout: 3000 });
    expect(update).toHaveBeenCalledWith({ max_daily_token_budget: 5000 });
    await vi.waitFor(() => expect(leavingAsks()).toBe(false));
    // Typing the saved value back is not an edit.
    await userEvent.fill(budget, "5000");
    expect(leavingAsks()).toBe(false);
  });

  test("the policy card title is a section heading", async () => {
    renderPage(vi.fn());
    await expect
      .element(page.getByRole("heading", { level: 2, name: "widget_admin_policy" }))
      .toBeVisible();
  });
});

describe("widget templates", () => {
  test("a created template is listed even when leaving the page is declined", async () => {
    const created = {
      id: "t9",
      name: "Ny mall",
      description: "",
      theme: { primary_color: "#1F4E79", radius: 12 },
      language: "sv",
      is_default: false,
      locked_groups: [],
      linked_widgets: 0,
      published_at: null,
      has_unpublished_changes: true,
      created_at: "2026-11-05T08:00:00Z",
      updated_at: "2026-11-05T08:00:00Z"
    };
    const create = vi.fn(async () => created);
    renderPage(vi.fn(), undefined, create);

    // A policy edit the page cannot save makes the leave guard ask; here the
    // navigation is a stub, which is what a declined leave looks like.
    const min = page.getByLabelText("widget_admin_policy_retention_min");
    await userEvent.fill(min, "400");
    await userEvent.tab();
    await expect.element(min).toHaveAttribute("aria-invalid", "true");

    // bits-ui tabs and buttons answer a DOM click; the pointer path is flaky here.
    const press = (locator: { element: () => Element }) =>
      (locator.element() as HTMLElement).click();
    press(page.getByRole("tab", { name: /widget_admin_templates/ }));
    await expect
      .element(page.getByRole("button", { name: "widget_admin_template_new" }))
      .toBeVisible();
    press(page.getByRole("button", { name: "widget_admin_template_new" }));
    await vi.waitFor(() => expect(create).toHaveBeenCalledTimes(1));
    await vi.waitFor(() => expect(goto).toHaveBeenCalledWith("/admin/widgets/templates/t9"));

    const list = page.getByRole("list", { name: "widget_admin_templates" });
    await expect.element(list.getByRole("link", { name: "Ny mall" }).first()).toBeVisible();
    await expect
      .element(page.getByRole("button", { name: "widget_admin_template_new" }))
      .toBeEnabled();
  });
});

describe("widget templates default", () => {
  const row = (name: string) =>
    [...document.querySelectorAll("li")].find((li) => li.textContent?.includes(name))!;
  const defaultButton = (name: string) =>
    [...row(name).querySelectorAll("button")].find((button) =>
      /widget_admin_template_(set|unset)_default/.test(button.textContent ?? "")
    )!;
  const isDefault = (name: string) =>
    row(name).textContent?.includes("widget_admin_template_default") ?? false;

  test("default changes are taken one at a time, so a late answer cannot undo a newer choice", async () => {
    let answerFirst!: (template: unknown) => void;
    const update = vi
      .fn<
        (args: { template: { id: string }; update: { is_default: boolean } }) => Promise<unknown>
      >()
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            answerFirst = resolve;
          })
      )
      .mockImplementation(async ({ template, update: patch }) =>
        tpl(template.id, template.id === "t1" ? "Alfa" : "Beta", patch.is_default)
      );
    renderPage(vi.fn(), undefined, vi.fn(), {
      items: [tpl("t1", "Alfa"), tpl("t2", "Beta")],
      update: update as (args: unknown) => Promise<unknown>
    });
    (page.getByRole("tab", { name: /widget_admin_templates/ }).element() as HTMLElement).click();
    await expect.element(page.getByRole("list", { name: "widget_admin_templates" })).toBeVisible();

    defaultButton("Alfa").click();
    await vi.waitFor(() => expect(update).toHaveBeenCalledTimes(1));
    // While Alfa's answer is on its way, no other default can be chosen.
    await vi.waitFor(() => expect(defaultButton("Beta").disabled).toBe(true));
    defaultButton("Beta").click();
    expect(update).toHaveBeenCalledTimes(1);

    answerFirst(tpl("t1", "Alfa", true));
    await vi.waitFor(() => expect(isDefault("Alfa")).toBe(true));
    await vi.waitFor(() => expect(defaultButton("Beta").disabled).toBe(false));

    defaultButton("Beta").click();
    await vi.waitFor(() => expect(update).toHaveBeenCalledTimes(2));
    await vi.waitFor(() => expect(isDefault("Beta")).toBe(true));
    expect(isDefault("Alfa")).toBe(false);
  });
});
