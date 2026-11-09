import { page, userEvent } from "vitest/browser";
import { render } from "vitest-browser-svelte";
import type { Widget } from "@eneo/eneo-js";
import { describe, expect, test, vi } from "vitest";
import "../../../../app.css";

vi.mock("$lib/paraglide/messages", () => ({
  m: new Proxy<Record<string, (params?: Record<string, string>) => string>>(
    {},
    {
      get: (_target, key) => (params?: Record<string, string>) =>
        params ? `${String(key)}(${Object.values(params).join("|")})` : String(key)
    }
  )
}));

import WidgetStatusBar from "./WidgetStatusBar.svelte";
import { WidgetAutosave } from "./widgetAutosave.svelte";

const casefiles = {
  id: "m1",
  name: "Ärendesystemet",
  tools: ["Skapa ärende", "Sök ärende"]
};

function widget(overrides: Partial<Widget> = {}): Widget {
  return {
    id: "w1",
    name: "Chatt",
    status: "draft",
    revision: 0,
    activated_at: null,
    allowed_origins: ["https://www.kommun.se"],
    activation_blockers: [],
    external_tools: [casefiles],
    external_tools_acknowledged: false,
    ...overrides
  } as unknown as Widget;
}

function renderBar(current: Widget) {
  const onActivate = vi.fn(async () => {});
  const noop = vi.fn(async () => {});
  render(WidgetStatusBar, {
    autosave: new WidgetAutosave(current, vi.fn()),
    isAdmin: true,
    onActivate,
    onPause: noop,
    onArchive: noop,
    onReload: noop
  });
  return { onActivate };
}

const click = (locator: { element: () => Element }) => (locator.element() as HTMLElement).click();

describe("WidgetStatusBar external MCP servers", () => {
  test("activation stops at a dialog until the admin has acknowledged the servers", async () => {
    const { onActivate } = renderBar(widget());
    await expect.element(page.getByText("widget_admin_external_tools_note")).toBeVisible();

    click(page.getByRole("button", { name: "widget_admin_activate" }));
    const dialog = page.getByRole("alertdialog");
    await expect.element(dialog).toBeVisible();
    await expect.element(dialog.getByText("Ärendesystemet")).toBeVisible();
    await expect
      .element(dialog.getByText("widget_admin_external_tools_tools(Skapa ärende, Sök ärende)"))
      .toBeVisible();
    expect(onActivate).not.toHaveBeenCalled();

    // The confirming button waits for the checkbox.
    const confirm = dialog.getByRole("button", { name: "widget_admin_activate" });
    await expect.element(confirm).toBeDisabled();
    await userEvent.click(dialog.getByRole("checkbox"));
    await expect.element(confirm).toBeEnabled();
    await userEvent.click(confirm);

    expect(onActivate).toHaveBeenCalledWith({ externalToolsAcknowledged: true });
  });

  test("cancelling the dialog activates nothing", async () => {
    const { onActivate } = renderBar(widget());
    click(page.getByRole("button", { name: "widget_admin_activate" }));
    const dialog = page.getByRole("alertdialog");
    await expect.element(dialog).toBeVisible();
    await userEvent.click(dialog.getByRole("button", { name: "cancel" }));
    expect(onActivate).not.toHaveBeenCalled();
  });

  test("an acknowledgement that covers the servers activates without asking again", async () => {
    const { onActivate } = renderBar(widget({ external_tools_acknowledged: true }));
    expect(document.body.textContent).not.toContain("widget_admin_external_tools_note");
    click(page.getByRole("button", { name: "widget_admin_activate" }));
    await vi.waitFor(() => expect(onActivate).toHaveBeenCalledTimes(1));
    expect(onActivate).toHaveBeenCalledWith({ externalToolsAcknowledged: false });
    expect(page.getByRole("alertdialog").elements()).toHaveLength(0);
  });

  test("a widget without external servers activates without asking", async () => {
    const { onActivate } = renderBar(
      widget({ external_tools: [], external_tools_acknowledged: true })
    );
    click(page.getByRole("button", { name: "widget_admin_activate" }));
    await vi.waitFor(() => expect(onActivate).toHaveBeenCalledTimes(1));
    expect(page.getByRole("alertdialog").elements()).toHaveLength(0);
  });

  test("an active widget whose servers changed since activation is flagged", async () => {
    renderBar(
      widget({
        status: "active",
        activated_at: "2026-09-01T00:00:00Z",
        activation_blockers: ["external_tools_changed_since_activation"]
      })
    );
    await expect.element(page.getByText("widget_admin_active_issues_title")).toBeVisible();
    await expect
      .element(page.getByText("widget_admin_blocker_external_tools_changed"))
      .toBeVisible();
  });
});
