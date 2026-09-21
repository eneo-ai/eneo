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
    published_at: "2026-09-21T10:00:00Z",
    published_by_user_id: null,
    has_unpublished_changes: false,
    created_at: "2026-09-21T10:00:00Z",
    updated_at: "2026-09-21T10:00:00Z",
    ...overrides
  } as unknown as WidgetTemplate;
}

function renderPage(current: WidgetTemplate) {
  const update = vi.fn(async ({ update: patch }: { update: Partial<WidgetTemplate> }) => ({
    ...current,
    ...patch,
    has_unpublished_changes: true
  }));
  const publish = vi.fn(async () => ({
    ...current,
    has_unpublished_changes: false,
    published_at: "2026-09-21T12:00:00Z"
  }));
  render(TemplatePage, {
    data: { template: current, eneo: { widgets: { templates: { update, publish } } } } as never
  });
  return { update, publish };
}

const click = (locator: { element: () => Element }) => (locator.element() as HTMLElement).click();

describe("widget template page", () => {
  test("a lock toggle only edits the draft and marks it unpublished", async () => {
    const { update, publish } = renderPage(template());
    await expect.element(page.getByText("widget_admin_template_linked_count")).toBeVisible();
    const publishButton = page.getByRole("button", { name: "widget_admin_template_publish" });
    await expect.element(publishButton).toBeDisabled();

    click(page.getByRole("switch", { name: "widget_admin_template_lock_wording" }));
    await vi.waitFor(() => expect(update).toHaveBeenCalledTimes(1), { timeout: 3000 });
    expect(update).toHaveBeenLastCalledWith({
      template: { id: "t1" },
      update: { locked_groups: ["appearance", "language", "wording"] }
    });
    expect(publish).not.toHaveBeenCalled();
    await expect.element(page.getByText("widget_admin_template_unpublished_changes")).toBeVisible();
    await expect.element(publishButton).toBeEnabled();
  });

  test("publishing to followers asks first and then shows the release as current", async () => {
    const { publish } = renderPage(template({ has_unpublished_changes: true }));
    click(page.getByRole("button", { name: "widget_admin_template_publish" }));
    await expect
      .element(page.getByText("widget_admin_template_publish_confirm_title"))
      .toBeVisible();
    expect(publish).not.toHaveBeenCalled();
    const dialogButtons = page.getByRole("button", { name: "widget_admin_template_publish" });
    click(dialogButtons.nth(1));
    await vi.waitFor(() => expect(publish).toHaveBeenCalledTimes(1), { timeout: 3000 });
    await expect.element(page.getByText("widget_admin_template_published_at")).toBeVisible();
  });

  test("a template nobody follows publishes without a question", async () => {
    const { publish } = renderPage(
      template({ linked_widgets: 0, published_at: null, has_unpublished_changes: true })
    );
    await expect.element(page.getByText("widget_admin_template_unpublished")).toBeVisible();
    click(page.getByRole("button", { name: "widget_admin_template_publish" }));
    await vi.waitFor(() => expect(publish).toHaveBeenCalledTimes(1), { timeout: 3000 });
    expect(document.querySelector('[role="alertdialog"]')).toBeNull();
  });
});
