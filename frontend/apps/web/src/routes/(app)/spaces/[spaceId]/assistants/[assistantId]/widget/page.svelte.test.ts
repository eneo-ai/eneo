/* eslint-disable eneo/no-raw-color -- fixtures use literal widget colours */
import { page, userEvent } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { readable } from "svelte/store";
import type { Eneo, Widget, WidgetTemplate } from "@eneo/eneo-js";
import { describe, expect, test, vi } from "vitest";
import type { PageData } from "./$types";
import { toastError } from "$lib/core/errors";

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
vi.mock("$lib/core/errors", () => ({ toastError: vi.fn() }));
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

function routeData(
  assistantId: string,
  currentWidget: Widget | null,
  widgets: Partial<Eneo["widgets"]>
): PageData {
  const pending = () => new Promise<never>(() => {});
  return {
    widget: currentWidget,
    assistant: {
      id: assistantId,
      name: `Assistant ${assistantId}`,
      published: true,
      mcp_servers: []
    },
    currentSpace: { id: "s1" },
    eneo: { widgets: { previewToken: pending, usage: pending, ...widgets } },
    isAdmin: true,
    policy: null,
    release: null,
    templates: []
  } as unknown as PageData;
}

async function confirmArchive() {
  click(page.getByRole("button", { name: "widget_admin_archive" }));
  const dialog = page.getByRole("alertdialog");
  await vi.waitFor(() => expect(dialog.element().contains(document.activeElement)).toBe(true));
  click(dialog.getByRole("button", { name: "widget_admin_archive" }));
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((ok, fail) => {
    resolve = ok;
    reject = fail;
  });
  return { promise, resolve, reject };
}

describe("assistant widget page", () => {
  test("revalidating the same assistant preserves its unsaved creation name", async () => {
    const data = routeData("a1", null, {});
    const screen = render(WidgetPage, { data });
    const name = page.getByLabelText("name", { exact: true });
    await userEvent.fill(name, "My draft name");

    await screen.rerender({ data: routeData("a1", null, {}) });

    await expect.element(name).toHaveValue("My draft name");
  });

  test("navigation to another assistant sends edits and archive to its widget", async () => {
    const next = { ...widget, id: "22222222-2222-4222-8222-222222222222", name: "Second widget" };
    const update = vi.fn(async ({ update }: Parameters<Eneo["widgets"]["update"]>[0]) => ({
      ...next,
      ...update,
      revision: 3
    }));
    const archive = vi.fn(async () => ({ ...next, status: "archived" as const }));
    const widgets = { update, archive };
    const screen = render(WidgetPage, { data: routeData("a1", widget, widgets) });

    await screen.rerender({ data: routeData("a2", next, widgets) });
    const name = page.getByLabelText("name", { exact: true });
    await expect.element(name).toHaveValue("Second widget");
    await userEvent.fill(name, "Changed second widget");
    await vi.waitFor(() => expect(update).toHaveBeenCalledTimes(1));
    expect(update.mock.calls[0][0].widget.id).toBe(next.id);
    await confirmArchive();
    await vi.waitFor(() => expect(archive).toHaveBeenCalledWith({ id: next.id }));
  });

  test.each(["success", "error"] as const)(
    "a late create %s cannot replace another assistant's widget or show an error",
    async (outcome) => {
      vi.mocked(toastError).mockClear();
      const request = deferred<Widget>();
      const create = vi.fn(() => request.promise);
      const next = { ...widget, id: "22222222-2222-4222-8222-222222222222", name: "Second widget" };
      const screen = render(WidgetPage, { data: routeData("a1", null, { create }) });
      click(page.getByRole("button", { name: "widget_admin_create", exact: true }));
      await vi.waitFor(() => expect(create).toHaveBeenCalledTimes(1));

      await screen.rerender({ data: routeData("a2", next, {}) });
      if (outcome === "success") request.resolve(widget);
      else request.reject(new Error("old request failed"));
      await request.promise.catch(() => {});

      await expect
        .element(page.getByLabelText("name", { exact: true }))
        .toHaveValue("Second widget");
      expect(toastError).not.toHaveBeenCalled();
    }
  );

  test("returning to an assistant starts a fresh create state and ignores its old request", async () => {
    const oldRequest = deferred<Widget>();
    const create = vi.fn(() => oldRequest.promise);
    const initial = routeData("a1", null, { create });
    const screen = render(WidgetPage, { data: initial });
    click(page.getByRole("button", { name: "widget_admin_create", exact: true }));
    await vi.waitFor(() => expect(create).toHaveBeenCalledTimes(1));

    await screen.rerender({ data: routeData("a2", null, { create }) });
    await expect
      .element(page.getByRole("button", { name: "widget_admin_create", exact: true }))
      .toBeEnabled();
    await screen.rerender({ data: initial });
    oldRequest.resolve(widget);
    await oldRequest.promise;

    await expect.element(page.getByLabelText("name", { exact: true })).toHaveValue("Assistant a1");
    await expect
      .element(page.getByRole("button", { name: "widget_admin_create", exact: true }))
      .toBeEnabled();
  });

  test("a late archive completion cannot remove the next assistant's editor", async () => {
    const request = deferred<Widget>();
    const archive = vi.fn(() => request.promise);
    const next = { ...widget, id: "22222222-2222-4222-8222-222222222222", name: "Second widget" };
    const screen = render(WidgetPage, { data: routeData("a1", widget, { archive }) });
    await confirmArchive();
    await vi.waitFor(() => expect(archive).toHaveBeenCalledWith({ id: widget.id }));

    await screen.rerender({ data: routeData("a2", next, {}) });
    request.resolve({ ...widget, status: "archived" });
    await request.promise;
    await expect.element(page.getByLabelText("name", { exact: true })).toHaveValue("Second widget");
    expect(page.getByText("widget_admin_archived_note").query()).toBeNull();
  });

  test("navigation resets the creation name, default template and archive notice", async () => {
    const template = {
      id: "template",
      name: "Default template",
      is_default: true,
      published_at: "2026-09-01T00:00:00Z",
      theme: widget.theme,
      texts: widget.texts,
      language: "sv",
      locked_groups: []
    } as unknown as WidgetTemplate;
    const archive = vi.fn(async () => ({ ...widget, status: "archived" as const }));
    const create = vi.fn(() => new Promise<never>(() => {}));
    const initial = { ...routeData("a1", widget, { archive, create }), templates: [template] };
    const screen = render(WidgetPage, { data: initial });
    await confirmArchive();
    await expect.element(page.getByText("widget_admin_archived_note")).toBeVisible();
    await userEvent.fill(page.getByLabelText("name", { exact: true }), "Unrelated name");
    click(page.getByRole("radio", { name: /widget_admin_template_none/ }));
    const next = { ...routeData("a2", null, { create }), templates: [template] };

    await screen.rerender({ data: next });
    await expect.element(page.getByLabelText("name", { exact: true })).toHaveValue("Assistant a2");
    expect(page.getByText("widget_admin_archived_note").query()).toBeNull();
    click(page.getByRole("button", { name: "widget_admin_create", exact: true }));
    await vi.waitFor(() =>
      expect(create).toHaveBeenCalledWith(
        expect.objectContaining({ target_id: "a2", name: "Assistant a2", template_id: template.id })
      )
    );
  });

  test("an organization space explains why a widget cannot be created", async () => {
    const create = vi.fn();
    render(WidgetPage, {
      data: {
        widget: null,
        assistant: { id: "a1", name: "Kontakt", published: true, mcp_servers: [] },
        currentSpace: { id: "s1", organization: true },
        eneo: { widgets: { create } },
        isAdmin: true,
        policy: null,
        release: null,
        templates: []
      } as never
    });

    await expect
      .element(page.getByText("widget_admin_blocker_organization_space_unsupported"))
      .toBeVisible();
    expect(page.getByRole("button", { name: "widget_admin_create" }).query()).toBeNull();
    expect(create).not.toHaveBeenCalled();
  });

  test("a personal space says widgets are not supported there yet", async () => {
    const create = vi.fn();
    render(WidgetPage, {
      data: {
        widget: null,
        assistant: { id: "a1", name: "Kontakt", published: true, mcp_servers: [] },
        currentSpace: { id: "s1", organization: false, personal: true },
        eneo: { widgets: { create } },
        isAdmin: true,
        policy: null,
        release: null,
        templates: []
      } as never
    });

    await expect
      .element(page.getByText("widget_admin_blocker_personal_space_unsupported"))
      .toBeVisible();
    expect(page.getByRole("button", { name: "widget_admin_create" }).query()).toBeNull();
    expect(create).not.toHaveBeenCalled();
  });

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
