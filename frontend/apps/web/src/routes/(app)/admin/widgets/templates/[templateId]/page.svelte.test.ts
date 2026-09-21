/* eslint-disable eneo/no-raw-color -- fixtures use literal widget colours */
import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import type { WidgetTemplate } from "@eneo/eneo-js";
import { describe, expect, test, vi } from "vitest";
import "../../../../../../app.css";

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
  page: { url: new URL("http://localhost/admin/widgets/templates/t1"), state: {} }
}));
vi.mock("$lib/paraglide/messages", () => ({
  m: new Proxy<Record<string, () => string>>({}, { get: (_target, key) => () => String(key) })
}));
vi.mock("$lib/paraglide/runtime", () => ({
  getLocale: () => "sv",
  localizeHref: (href: string) => href
}));

import TemplatePage from "./+page.svelte";

function template(overrides: Partial<WidgetTemplate> = {}): WidgetTemplate {
  return {
    id: "t1",
    name: "Kommunblå",
    description: "",
    texts: { title: "", welcome: "", placeholder: "", suggested_questions: [], subtitle: "AI" },
    theme: { primary_color: "#1F4E79", radius: 12 },
    language: "sv",
    is_default: false,
    locked_groups: ["appearance", "language"],
    linked_widgets: 3,
    created_at: "2026-09-21T10:00:00Z",
    updated_at: "2026-09-21T10:00:00Z",
    ...overrides
  } as unknown as WidgetTemplate;
}

function renderPage(current: WidgetTemplate) {
  const update = vi.fn(async ({ update: patch }: { update: Partial<WidgetTemplate> }) => ({
    ...current,
    ...patch
  }));
  render(TemplatePage, {
    data: { template: current, eneo: { widgets: { templates: { update } } } } as never
  });
  return update;
}

describe("widget template page locks", () => {
  test("locking a part with followers asks first, then saves the canonical lock list", async () => {
    const update = renderPage(template());
    await expect.element(page.getByText("widget_admin_template_linked_count")).toBeVisible();

    const wording = page.getByRole("switch", { name: "widget_admin_template_lock_wording" });
    await expect.element(wording).not.toBeChecked();
    (wording.element() as HTMLElement).click();
    const confirm = page.getByRole("button", { name: "widget_admin_template_lock_confirm_action" });
    await expect.element(confirm).toBeVisible();
    expect(update).not.toHaveBeenCalled();
    (confirm.element() as HTMLElement).click();

    await vi.waitFor(() => expect(update).toHaveBeenCalledTimes(1), { timeout: 3000 });
    expect(update).toHaveBeenLastCalledWith({
      template: { id: "t1" },
      update: { locked_groups: ["appearance", "language", "wording"] }
    });
    await expect.element(wording).toBeChecked();
  });

  test("unlocking never asks and drops only that part", async () => {
    const update = renderPage(template());
    (
      page
        .getByRole("switch", { name: "widget_admin_template_lock_language" })
        .element() as HTMLElement
    ).click();
    await vi.waitFor(() => expect(update).toHaveBeenCalledTimes(1), { timeout: 3000 });
    expect(update).toHaveBeenLastCalledWith({
      template: { id: "t1" },
      update: { locked_groups: ["appearance"] }
    });
  });

  test("a template nobody follows locks without a question", async () => {
    const update = renderPage(template({ linked_widgets: 0, locked_groups: [] }));
    await expect.element(page.getByText("widget_admin_template_linked_none")).toBeVisible();
    (
      page
        .getByRole("switch", { name: "widget_admin_template_lock_appearance" })
        .element() as HTMLElement
    ).click();
    await vi.waitFor(() => expect(update).toHaveBeenCalledTimes(1), { timeout: 3000 });
    expect(update).toHaveBeenLastCalledWith({
      template: { id: "t1" },
      update: { locked_groups: ["appearance"] }
    });
  });
});
