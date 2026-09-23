/* eslint-disable eneo/no-raw-color -- fixtures use literal widget colours */
import { page, userEvent } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import type { Assistant, Eneo, Widget } from "@eneo/eneo-js";
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
  page: { url: new URL("http://localhost/spaces/s1/assistants/a1/widget"), state: {} }
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

import WidgetEditor from "./WidgetEditor.svelte";

function widget(overrides: Partial<Widget> = {}): Widget {
  return {
    id: "11111111-1111-4111-8111-111111111111",
    public_id: "wgt_test",
    name: "Kontaktchatt",
    status: "active",
    activated_at: "2026-09-01T00:00:00Z",
    revision: 0,
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
    updated_at: "2026-09-21T10:00:00Z",
    ...overrides
  } as unknown as Widget;
}

function renderEditor(current: Widget) {
  const update = vi.fn(async ({ update: patch }: { update: Partial<Widget> }) => ({
    ...current,
    ...patch
  }));
  const eneo = {
    widgets: {
      update,
      previewToken: vi.fn(() => new Promise(() => {})),
      usage: vi.fn(() => new Promise(() => {}))
    }
  } as unknown as Eneo;
  render(WidgetEditor, {
    widget: current,
    assistant: { id: "a1", published: true, mcp_servers: [] } as unknown as Assistant,
    eneo,
    isAdmin: true,
    policy: null,
    release: null
  });
  return { update };
}

describe("WidgetEditor", () => {
  test("an active widget with something to fix says so on the Publish tab", async () => {
    renderEditor(widget({ activation_blockers: ["target_not_published"] }));
    await expect
      .element(
        page.getByRole("tab", { name: /widget_admin_tab_publish.*widget_admin_tab_issues_one/ })
      )
      .toBeVisible();
    await expect.element(page.getByText("widget_admin_active_issues_title")).toBeVisible();
  });

  test("a healthy active widget has no badge", async () => {
    renderEditor(widget());
    await expect
      .element(page.getByRole("tab", { name: "widget_admin_tab_publish", exact: true }))
      .toBeVisible();
  });

  test("a blank name is flagged at the field and never sent", async () => {
    const { update } = renderEditor(widget());
    const name = page.getByLabelText("name", { exact: true });
    await userEvent.fill(name, "  ");
    await expect.element(name).toHaveAttribute("aria-invalid", "true");
    await expect.element(name).toHaveAccessibleDescription(/widget_admin_name_required/);
    await new Promise((resolve) => setTimeout(resolve, 800));
    expect(update).not.toHaveBeenCalled();
  });

  test("the content cards are section headings", async () => {
    renderEditor(widget());
    await expect.element(page.getByRole("heading", { level: 2, name: "general" })).toBeVisible();
    await expect
      .element(page.getByRole("heading", { level: 2, name: "widget_admin_texts" }))
      .toBeVisible();
  });
});
