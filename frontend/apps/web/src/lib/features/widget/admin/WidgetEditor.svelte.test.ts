/* eslint-disable eneo/no-raw-color -- fixtures use literal widget colours */
import { page, userEvent } from "vitest/browser";
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
vi.mock("$lib/paraglide/messages", () => {
  const message = (key: string | symbol) => (params?: Record<string, string>) =>
    params ? `${String(key)}(${Object.values(params).join("|")})` : String(key);
  // The persona's avatar upload imports the module namespace (`import * as m`),
  // so the messages it reads are named exports here, beside `m`.
  const avatarUploadKeys = [
    "avatar_current",
    "avatar_invalid_type",
    "avatar_too_large",
    "avatar_upload",
    "avatar_uploading",
    "close",
    "delete",
    "download",
    "upload_avatar_alt",
    "upload_avatar_preview_alt",
    "upload_view_avatar"
  ];
  return {
    ...Object.fromEntries(avatarUploadKeys.map((key) => [key, message(key)])),
    m: new Proxy<Record<string, (params?: Record<string, string>) => string>>(
      {},
      { get: (_target, key) => message(key) }
    )
  };
});
vi.mock("$lib/paraglide/runtime", () => ({
  getLocale: () => "sv",
  localizeHref: (href: string) => href
}));

const icons = vi.hoisted(() => ({
  upload: vi.fn<() => Promise<{ id: string }>>(),
  delete: vi.fn(async () => {}),
  url: () => "data:image/png;base64,AA=="
}));
vi.mock("$lib/core/Eneo", () => ({ getEneo: () => ({ icons }) }));

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
    persona: { name: "", avatar_icon_id: null, avatar_in_launcher: false },
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

function renderEditor(
  current: Widget,
  assistant: Partial<Assistant> = {},
  widgets: Record<string, unknown> = {}
) {
  const update = vi.fn(async ({ update: patch }: { update: Partial<Widget> }) => ({
    ...current,
    ...patch
  }));
  const usage = vi.fn(() => new Promise(() => {}));
  const eneo = {
    widgets: {
      update,
      previewToken: vi.fn(() => new Promise(() => {})),
      usage,
      ...widgets
    }
  } as unknown as Eneo;
  render(WidgetEditor, {
    onReloaded: vi.fn(),
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

const click = (locator: { element: () => Element }) => (locator.element() as HTMLElement).click();

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

describe("WidgetEditor", () => {
  test("an edit made while the widget pauses is saved with the revision the pause returned", async () => {
    const current = widget({ revision: 3 });
    let finishPause!: (paused: Widget) => void;
    const pause = vi.fn(() => new Promise<Widget>((resolve) => (finishPause = resolve)));
    const { update } = renderEditor(current, {}, { pause });
    click(page.getByRole("button", { name: "widget_admin_pause" }));
    await vi.waitFor(() => expect(pause).toHaveBeenCalledTimes(1));

    // Typed while the pause is still in flight: it waits for the new revision.
    await userEvent.fill(page.getByLabelText("name", { exact: true }), "Kaffe och te");
    await new Promise((resolve) => setTimeout(resolve, 1500));
    expect(update).not.toHaveBeenCalled();

    finishPause({ ...current, status: "paused", revision: 7 });
    await vi.waitFor(() => expect(update).toHaveBeenCalledTimes(1), { timeout: 3000 });
    expect(update).toHaveBeenLastCalledWith({
      widget: { id: current.id },
      update: { name: "Kaffe och te", revision: 7 }
    });
    await expect.element(page.getByLabelText("name", { exact: true })).toHaveValue("Kaffe och te");
  });

  test.each(["upload", "copy"])("clearing a persona releases a late avatar %s", async (source) => {
    let complete!: (icon: { id: string }) => void;
    icons.upload.mockClear().mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          complete = resolve;
        })
    );
    icons.delete.mockClear();
    const { update } = renderEditor(
      widget({ persona: { name: "Robo", avatar_icon_id: null, avatar_in_launcher: false } }),
      { icon_id: "assistant-icon" }
    );
    if (source === "copy") {
      await userEvent.click(
        page.getByRole("button", { name: "widget_admin_persona_use_assistant_icon" })
      );
    } else {
      const file = document.querySelector<HTMLInputElement>("#widget-persona-avatar-input")!;
      const transfer = new DataTransfer();
      transfer.items.add(new File(["x"], "avatar.png", { type: "image/png" }));
      file.files = transfer.files;
      file.dispatchEvent(new Event("change", { bubbles: true }));
    }
    await vi.waitFor(() => expect(icons.upload).toHaveBeenCalledTimes(1));
    await userEvent.fill(page.getByLabelText("widget_admin_persona_name", { exact: true }), "");
    complete({ id: "unused-icon" });
    await vi.waitFor(() => expect(icons.delete).toHaveBeenCalledWith({ id: "unused-icon" }));
    await vi.waitFor(() => expect(update).toHaveBeenCalledTimes(1), { timeout: 3000 });
    expect(update.mock.calls[0][0].update.persona).toMatchObject({
      name: "",
      avatar_icon_id: null
    });
  });

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

  // Required texts retain their invalid draft; leaving treats them alike.
  test("an incomplete colour counts as unsaved until it is corrected", async () => {
    const { update } = renderEditor(widget());
    click(page.getByRole("tab", { name: "widget_admin_tab_appearance" }));
    const colour = page.getByRole("textbox", { name: "widget_admin_primary_color", exact: true });
    await userEvent.fill(colour, "#12");
    await expect.element(colour).toHaveAttribute("aria-invalid", "true");
    expect(leavingAsks()).toBe(true);
    // Cleared is held too: the primary colour has no empty value to save.
    await userEvent.clear(colour);
    await expect.element(colour).toHaveAttribute("aria-invalid", "true");
    expect(leavingAsks()).toBe(true);

    await userEvent.fill(colour, "#123456");
    await vi.waitFor(() => expect(update).toHaveBeenCalledTimes(1), { timeout: 3000 });
    await vi.waitFor(() => expect(leavingAsks()).toBe(false));
  });

  test("a blank name, a held disclosure and a bad persona name all count as unsaved", async () => {
    renderEditor(widget());
    const name = page.getByLabelText("name", { exact: true });
    await userEvent.clear(name);
    await expect.element(name).toHaveAttribute("aria-invalid", "true");
    expect(leavingAsks()).toBe(true);
    await userEvent.fill(name, "Kontaktchatt");
    await expect.element(name).toHaveAttribute("aria-invalid", "false");
    await vi.waitFor(() => expect(leavingAsks()).toBe(false));

    // A live widget keeps its disclosure, so a blank one is held, not sent.
    const subtitle = page.getByLabelText("widget_admin_text_subtitle", { exact: true });
    await userEvent.clear(subtitle);
    await expect.element(subtitle).toHaveAttribute("aria-invalid", "true");
    expect(leavingAsks()).toBe(true);
    await userEvent.fill(subtitle, "AI");
    await vi.waitFor(() => expect(leavingAsks()).toBe(false));

    const persona = page.getByLabelText("widget_admin_persona_name", { exact: true });
    await userEvent.fill(persona, "1Robo");
    await expect.element(persona).toHaveAttribute("aria-invalid", "true");
    expect(leavingAsks()).toBe(true);
    await userEvent.fill(persona, "Robo");
    await vi.waitFor(() => expect(leavingAsks()).toBe(false), { timeout: 3000 });
  });

  test("a link or a question typed but not yet committed counts as unsaved", async () => {
    const { update } = renderEditor(widget());
    const link = page.getByLabelText("widget_admin_text_footer_link_url", { exact: true });
    await userEvent.fill(link, "https://www.kommun.se/personuppgifter");
    expect(leavingAsks()).toBe(true);
    expect(update).not.toHaveBeenCalled();
    await userEvent.tab();
    await vi.waitFor(() => expect(update).toHaveBeenCalledTimes(1), { timeout: 3000 });
    expect(update.mock.lastCall![0].update).toMatchObject({
      texts: expect.objectContaining({ footer_link_url: "https://www.kommun.se/personuppgifter" })
    });
    await vi.waitFor(() => expect(leavingAsks()).toBe(false));

    await userEvent.click(page.getByRole("button", { name: "widget_admin_questions_add" }));
    const question = page.getByRole("textbox", { name: "widget_admin_questions_label" });
    // An empty new row is not an edit yet.
    expect(leavingAsks()).toBe(false);
    await userEvent.type(question, "Kontakt?");
    expect(leavingAsks()).toBe(true);
    await userEvent.tab();
    await vi.waitFor(() => expect(update).toHaveBeenCalledTimes(2), { timeout: 3000 });
    expect(update.mock.lastCall![0].update).toMatchObject({
      texts: expect.objectContaining({ suggested_questions: ["Kontakt?"] })
    });
    await vi.waitFor(() => expect(leavingAsks()).toBe(false));
  });

  test("a website or a number typed but not yet committed counts as unsaved", async () => {
    const { update } = renderEditor(widget());
    click(page.getByRole("tab", { name: /widget_admin_tab_rules/ }));
    const origins = page.getByLabelText("widget_admin_allowed_origins", { exact: true });
    await userEvent.fill(origins, "https://www.kommun.se\nhttps://ny.kommun.se");
    expect(leavingAsks()).toBe(true);
    expect(update).not.toHaveBeenCalled();
    await userEvent.tab();
    await vi.waitFor(() => expect(update).toHaveBeenCalledTimes(1), { timeout: 3000 });
    expect(update.mock.lastCall![0].update).toMatchObject({
      allowed_origins: ["https://www.kommun.se", "https://ny.kommun.se"]
    });
    await vi.waitFor(() => expect(leavingAsks()).toBe(false));

    const budget = page.getByLabelText("widget_admin_daily_budget", { exact: true });
    await userEvent.fill(budget, "5000");
    expect(leavingAsks()).toBe(true);
    await userEvent.tab();
    await vi.waitFor(() => expect(update).toHaveBeenCalledTimes(2), { timeout: 3000 });
    expect(update.mock.lastCall![0].update).toMatchObject({
      limits: expect.objectContaining({ daily_token_budget: 5000 })
    });
    await vi.waitFor(() => expect(leavingAsks()).toBe(false));
    // Typing the saved value back is not an edit.
    await userEvent.fill(budget, "5000");
    expect(leavingAsks()).toBe(false);
  });

  test("a template taking the persona over releases a late avatar upload", async () => {
    let complete!: (icon: { id: string }) => void;
    icons.upload.mockClear().mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          complete = resolve;
        })
    );
    icons.delete.mockClear();
    const linked = widget({
      persona: { name: "Robo", avatar_icon_id: null, avatar_in_launcher: false },
      template: { id: "t1", name: "Kommunblå", locked_groups: [] }
    } as unknown as Partial<Widget>);
    const update = vi.fn(async ({ update: patch }: { update: Partial<Widget> }) => ({
      ...linked,
      ...patch
    }));
    const linkTemplate = vi.fn(async () => ({
      ...linked,
      persona: { name: "Kommunboten", avatar_icon_id: null, avatar_in_launcher: false },
      template: { id: "t1", name: "Kommunblå", locked_groups: ["persona"] },
      revision: 1
    }));
    const eneo = {
      widgets: {
        update,
        linkTemplate,
        previewToken: vi.fn(() => new Promise(() => {})),
        usage: vi.fn(() => new Promise(() => {}))
      }
    } as unknown as Eneo;
    render(WidgetEditor, {
      onReloaded: vi.fn(),
      widget: linked,
      assistant: {
        id: "a1",
        published: true,
        mcp_servers: [],
        icon_id: "assistant-icon"
      } as unknown as Assistant,
      eneo,
      isAdmin: true,
      policy: null,
      release: null
    });

    await userEvent.click(
      page.getByRole("button", { name: "widget_admin_persona_use_assistant_icon" })
    );
    await vi.waitFor(() => expect(icons.upload).toHaveBeenCalledTimes(1));

    // The template takes the persona over while the copy is still uploading.
    await userEvent.click(page.getByRole("tab", { name: /widget_admin_tab_appearance/ }));
    await userEvent.click(page.getByRole("button", { name: "widget_admin_template_reapply" }));
    await userEvent.click(
      page.getByRole("alertdialog").getByRole("button", { name: "widget_admin_template_reapply" })
    );
    await vi.waitFor(() => expect(linkTemplate).toHaveBeenCalledTimes(1));
    await userEvent.click(page.getByRole("tab", { name: /widget_admin_tab_content/ }));
    await expect
      .element(page.getByLabelText("widget_admin_persona_name", { exact: true }))
      .toBeDisabled();

    complete({ id: "unused-icon" });
    await vi.waitFor(() => expect(icons.delete).toHaveBeenCalledWith({ id: "unused-icon" }));
    await new Promise((resolve) => setTimeout(resolve, 800));
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
      onReloaded: vi.fn(),
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

  // Linking copies the persona too, so a refused persona is moot afterwards;
  // a refused edit the release does not touch stays held.
  test("applying a template that locks the persona drops a refused persona but keeps other held edits", async () => {
    const linked = widget({
      template: { id: "t1", name: "Kommunblå", locked_groups: [] }
    } as unknown as Partial<Widget>);
    const refuse = (...loc: string[]) => ({
      loc: ["body", ...loc],
      type: "value_error",
      msg: "Invalid"
    });
    const update = vi.fn(async ({ update: patch }: { update: Partial<Widget> }) => {
      const detail = [
        ...("persona" in patch ? [refuse("persona", "name")] : []),
        ...("allowed_origins" in patch ? [refuse("allowed_origins")] : [])
      ];
      if (detail.length > 0) throw new EneoError("raw", "RESPONSE", 422, 0, { detail });
      return { ...linked, ...patch };
    });
    const linkTemplate = vi.fn(async () => ({
      ...linked,
      persona: { name: "Kommunboten", avatar_icon_id: null, avatar_in_launcher: false },
      template: { id: "t1", name: "Kommunblå", locked_groups: ["persona"] },
      revision: 1
    }));
    const eneo = {
      widgets: {
        update,
        linkTemplate,
        previewToken: vi.fn(() => new Promise(() => {})),
        usage: vi.fn(() => new Promise(() => {}))
      }
    } as unknown as Eneo;
    render(WidgetEditor, {
      onReloaded: vi.fn(),
      widget: linked,
      assistant: { id: "a1", published: true, mcp_servers: [] } as unknown as Assistant,
      eneo,
      isAdmin: true,
      policy: null,
      release: null
    });

    const personaName = page.getByLabelText("widget_admin_persona_name", { exact: true });
    await userEvent.fill(personaName, "Robo");
    await vi.waitFor(() => expect(update).toHaveBeenCalledTimes(1), { timeout: 3000 });
    await expect.element(personaName).toHaveAccessibleDescription(/widget_admin_value_refused/);

    await userEvent.click(page.getByRole("tab", { name: /widget_admin_tab_rules/ }));
    const origins = page.getByLabelText("widget_admin_allowed_origins", { exact: true });
    await userEvent.fill(origins, "https://www.kommun.se\nhttps://ny.kommun.se");
    await userEvent.click(page.getByRole("tab", { name: /widget_admin_tab_appearance/ }));
    await vi.waitFor(() => expect(update).toHaveBeenCalledTimes(2), { timeout: 3000 });

    await userEvent.click(page.getByRole("button", { name: "widget_admin_template_reapply" }));
    await userEvent.click(
      page.getByRole("alertdialog").getByRole("button", { name: "widget_admin_template_reapply" })
    );
    await vi.waitFor(() => expect(linkTemplate).toHaveBeenCalledTimes(1));
    await expect
      .element(
        page.getByText("widget_admin_template_locked_parts(widget_admin_template_lock_persona)")
      )
      .toBeVisible();

    await userEvent.click(page.getByRole("tab", { name: /widget_admin_tab_content/ }));
    const lockedName = page.getByLabelText("widget_admin_persona_name", { exact: true });
    await expect.element(lockedName).toHaveValue("Kommunboten");
    await expect.element(lockedName).toBeDisabled();
    await expect.element(lockedName).toHaveAttribute("aria-invalid", "false");

    await userEvent.click(page.getByRole("tab", { name: /widget_admin_tab_rules/ }));
    const held = page.getByLabelText("widget_admin_allowed_origins", { exact: true });
    await expect.element(held).toHaveValue("https://www.kommun.se\nhttps://ny.kommun.se");
    await expect.element(held).toHaveAccessibleDescription(/widget_admin_origins_refused/);
  });
});
