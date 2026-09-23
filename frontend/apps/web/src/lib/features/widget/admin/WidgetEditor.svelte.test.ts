/* eslint-disable eneo/no-raw-color -- fixtures use literal widget colours */
import { page, userEvent } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { EneoError, type Assistant, type Eneo, type Widget } from "@eneo/eneo-js";
import { describe, expect, test, vi } from "vitest";
import { beforeNavigate } from "$app/navigation";
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

function renderEditor(current: Widget, assistant: Partial<Assistant> = {}) {
  const update = vi.fn(async ({ update: patch }: { update: Partial<Widget> }) => ({
    ...current,
    ...patch
  }));
  const usage = vi.fn(() => new Promise(() => {}));
  const eneo = {
    widgets: {
      update,
      previewToken: vi.fn(() => new Promise(() => {})),
      usage
    }
  } as unknown as Eneo;
  render(WidgetEditor, {
    widget: current,
    assistant: {
      id: "a1",
      published: true,
      mcp_servers: [],
      ...assistant
    } as unknown as Assistant,
    eneo,
    isAdmin: true,
    policy: null,
    release: null
  });
  return { update, usage };
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

  test("a live widget's disclosure cannot be emptied: it stays in the field and is not sent", async () => {
    const { update } = renderEditor(widget());
    const subtitle = page.getByLabelText("widget_admin_text_subtitle", { exact: true });
    await userEvent.clear(subtitle);
    await expect.element(subtitle).toHaveAttribute("aria-invalid", "true");
    await expect
      .element(subtitle)
      .toHaveAccessibleDescription(/widget_admin_blocker_subtitle_empty/);
    await new Promise((resolve) => setTimeout(resolve, 800));
    expect(update).not.toHaveBeenCalled();
  });

  test("leaving with a live widget's disclosure emptied asks first", async () => {
    const { update } = renderEditor(widget());
    const subtitle = page.getByLabelText("widget_admin_text_subtitle", { exact: true });
    await userEvent.clear(subtitle);
    await expect.element(subtitle).toHaveAttribute("aria-invalid", "true");

    const leave = vi.mocked(beforeNavigate).mock.lastCall![0];
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    const cancel = vi.fn();
    try {
      leave({ cancel } as unknown as Parameters<typeof leave>[0]);
      expect(confirm).toHaveBeenCalledWith("widget_admin_unsaved_leave_confirm");
      expect(cancel).toHaveBeenCalled();
    } finally {
      confirm.mockRestore();
    }
    expect(update).not.toHaveBeenCalled();
  });

  test("a refusal of the whole texts group is tied to every text field", async () => {
    const { update } = renderEditor(widget());
    update.mockRejectedValueOnce(
      new EneoError("raw", "RESPONSE", 422, 0, {
        detail: [{ loc: ["body", "texts"], type: "value_error", msg: "Invalid" }]
      })
    );
    const title = page.getByLabelText("widget_admin_text_title", { exact: true });
    await userEvent.fill(title, "Hej");
    await vi.waitFor(() => expect(update).toHaveBeenCalledTimes(1), { timeout: 3000 });
    await expect.element(title).toHaveAccessibleDescription(/widget_admin_value_refused/);
    await expect
      .element(page.getByLabelText("widget_admin_text_footer", { exact: true }))
      .toHaveAccessibleDescription(/widget_admin_value_refused/);
  });

  test("the content cards are section headings", async () => {
    renderEditor(widget());
    await expect.element(page.getByRole("heading", { level: 2, name: "general" })).toBeVisible();
    await expect
      .element(page.getByRole("heading", { level: 2, name: "widget_admin_texts" }))
      .toBeVisible();
  });

  test("visitor access lists what visitors get and what they never get", async () => {
    renderEditor(widget(), {
      mcp_servers: [
        { id: "m1", name: "Kommunens ärenden", purpose: "general", is_enabled: true },
        { id: "m2", name: "Avstängd server", purpose: "general", is_enabled: false },
        { id: "m3", name: "Sökleverantören", purpose: "web_search", is_enabled: true }
      ],
      enabled_capabilities: ["web_search", "image_generation"]
    } as unknown as Partial<Assistant>);
    await userEvent.click(page.getByRole("tab", { name: /widget_admin_tab_publish/ }));
    const access = page.getByRole("region", { name: "widget_admin_visitor_access" });
    await expect.element(access).toBeVisible();
    expect(
      access
        .getByRole("listitem")
        .elements()
        .map((item) => item.textContent?.trim())
    ).toEqual([
      "widget_admin_visitor_access_knowledge",
      "Kommunens ärenden",
      "widget_admin_visitor_access_capability(web_search)"
    ]);
    await expect.element(access.getByText("widget_admin_visitor_access_never")).toBeVisible();
  });

  test("image generation alone is not reported as a hidden tool", async () => {
    renderEditor(widget({ show_tool_activity: false }), {
      enabled_capabilities: ["image_generation"]
    } as unknown as Partial<Assistant>);
    await userEvent.click(page.getByRole("tab", { name: /widget_admin_tab_publish/ }));
    const access = page.getByRole("region", { name: "widget_admin_visitor_access" });
    await expect.element(access).toBeVisible();
    expect(access.getByRole("listitem").elements()).toHaveLength(1);
    expect(access.getByText("widget_admin_visitor_access_hidden").elements()).toHaveLength(0);
  });

  test("tools that run with activity off are marked as not shown", async () => {
    renderEditor(widget({ show_tool_activity: false }), {
      enabled_capabilities: ["web_search"]
    } as unknown as Partial<Assistant>);
    await userEvent.click(page.getByRole("tab", { name: /widget_admin_tab_publish/ }));
    await expect
      .element(
        page
          .getByRole("region", { name: "widget_admin_visitor_access" })
          .getByText("widget_admin_visitor_access_hidden")
      )
      .toBeVisible();
  });

  test("usage is fetched when the Publish tab is opened, not while it is hidden", async () => {
    const { usage } = renderEditor(widget());
    await expect.element(page.getByRole("tab", { name: /widget_admin_tab_content/ })).toBeVisible();
    expect(usage).not.toHaveBeenCalled();
    await userEvent.click(page.getByRole("tab", { name: /widget_admin_tab_publish/ }));
    await vi.waitFor(() => expect(usage).toHaveBeenCalledTimes(1));
  });

  test("a linked template that locks nothing says so, not that nobody follows it", async () => {
    renderEditor(
      widget({
        template: { id: "t1", name: "Kommunblå", locked_groups: [] }
      } as unknown as Partial<Widget>)
    );
    await userEvent.click(page.getByRole("tab", { name: /widget_admin_tab_appearance/ }));
    await expect.element(page.getByText("widget_admin_template_locks_nothing")).toBeVisible();
    expect(document.body.textContent).not.toContain("widget_admin_template_linked_none");
  });

  test("detaching a template keeps a refused edit held at its field", async () => {
    const linked = widget({
      template: { id: "t1", name: "Kommunblå", locked_groups: [] }
    } as unknown as Partial<Widget>);
    const update = vi.fn(async () => {
      throw new EneoError("raw", "RESPONSE", 422, 0, {
        detail: [{ loc: ["body", "allowed_origins"], type: "value_error", msg: "Invalid" }]
      });
    });
    const detachTemplate = vi.fn(async () => ({ ...linked, template: null, revision: 1 }));
    const eneo = {
      widgets: {
        update,
        detachTemplate,
        previewToken: vi.fn(() => new Promise(() => {})),
        usage: vi.fn(() => new Promise(() => {}))
      }
    } as unknown as Eneo;
    render(WidgetEditor, {
      widget: linked,
      assistant: { id: "a1", published: true, mcp_servers: [] } as unknown as Assistant,
      eneo,
      isAdmin: true,
      policy: null,
      release: null
    });

    await userEvent.click(page.getByRole("tab", { name: /widget_admin_tab_rules/ }));
    const origins = page.getByLabelText("widget_admin_allowed_origins", { exact: true });
    await userEvent.fill(origins, "https://www.kommun.se\nhttps://ny.kommun.se");
    await userEvent.click(page.getByRole("tab", { name: /widget_admin_tab_appearance/ }));
    await vi.waitFor(() => expect(update).toHaveBeenCalledTimes(1), { timeout: 3000 });

    await userEvent.click(page.getByRole("button", { name: "widget_admin_template_detach" }));
    await userEvent.click(
      page.getByRole("alertdialog").getByRole("button", { name: "widget_admin_template_detach" })
    );
    await vi.waitFor(() => expect(detachTemplate).toHaveBeenCalledTimes(1));

    await userEvent.click(page.getByRole("tab", { name: /widget_admin_tab_rules/ }));
    const held = page.getByLabelText("widget_admin_allowed_origins", { exact: true });
    await expect.element(held).toHaveValue("https://www.kommun.se\nhttps://ny.kommun.se");
    await expect.element(held).toHaveAccessibleDescription(/widget_admin_origins_refused/);
  });
});
