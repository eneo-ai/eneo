/* eslint-disable eneo/no-raw-color -- fixtures use literal widget colours */
import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { readable } from "svelte/store";
import type { Widget } from "@eneo/eneo-js";
import { describe, expect, test, vi } from "vitest";

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
  page: { url: new URL("http://localhost/spaces/s1/assistants/a1/widget"), state: {} }
}));
vi.mock("$lib/paraglide/messages", () => ({
  m: new Proxy<Record<string, () => string>>({}, { get: (_target, key) => () => String(key) })
}));
vi.mock("$lib/paraglide/runtime", () => ({
  getLocale: () => "sv",
  localizeHref: (href: string) => href
}));
vi.mock("$lib/features/spaces/SpacesManager.js", () => ({
  getSpacesManager: () => ({ state: { currentSpace: readable({ id: "s1", routeId: "s1" }) } })
}));

import WidgetPage from "./+page.svelte";

const widget = {
  id: "11111111-1111-4111-8111-111111111111",
  public_id: "wgt_test",
  name: "Kontaktchatt",
  status: "paused",
  activated_at: "2026-09-01T00:00:00Z",
  revision: 2,
  token_generation: 1,
  language: "sv",
  texts: { title: "", welcome: "", suggested_questions: [], subtitle: "AI" },
  theme: { primary_color: "#1F4E79", radius: 12, color_scheme: "auto" },
  limits: { daily_token_budget: 4000, max_question_chars: 2000 },
  privacy: { retention_days: 30 },
  allowed_origins: ["https://www.kommun.se"],
  bot_protection: "altcha",
  show_sources: true,
  show_tool_activity: true,
  activation_blockers: [],
  updated_at: "2026-09-21T10:00:00Z"
} as unknown as Widget;

const click = (locator: { element: () => Element }) => (locator.element() as HTMLElement).click();

describe("assistant widget page", () => {
  test("archiving the widget takes the editor away and offers a new widget", async () => {
    const archive = vi.fn(async () => ({ ...widget, status: "archived", revision: 3 }));
    const update = vi.fn();
    const pending = () => new Promise(() => {});
    render(WidgetPage, {
      data: {
        widget,
        assistant: { id: "a1", name: "Kontakt", published: true, mcp_servers: [] },
        currentSpace: { id: "s1" },
        eneo: { widgets: { archive, update, previewToken: pending, usage: pending } },
        isAdmin: true,
        user: { id: "u1" },
        policy: null,
        release: null,
        templates: []
      } as never
    });

    click(page.getByRole("button", { name: "widget_admin_archive" }));
    const dialog = page.getByRole("alertdialog");
    // Settled like a person's click would find it: focus moved into the dialog.
    await vi.waitFor(() => expect(dialog.element().contains(document.activeElement)).toBe(true));
    click(dialog.getByRole("button", { name: "widget_admin_archive" }));
    await vi.waitFor(() => expect(archive).toHaveBeenCalledTimes(1));

    await expect
      .element(page.getByRole("heading", { name: "widget_admin_create_title" }))
      .toBeVisible();
    await expect.element(page.getByText("widget_admin_archived_note")).toHaveFocus();
    expect(page.getByLabelText("name", { exact: true }).elements()).toHaveLength(1);
    expect(page.getByLabelText("widget_admin_text_subtitle").query()).toBeNull();
    expect(document.querySelector('[role="alertdialog"]')).toBeNull();
    expect(update).not.toHaveBeenCalled();
  });
});
