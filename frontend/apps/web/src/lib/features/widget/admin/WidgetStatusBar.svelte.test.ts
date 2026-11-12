import { page } from "vitest/browser";
import { render } from "vitest-browser-svelte";
import { EneoError, type Widget } from "@eneo/eneo-js";
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

function widget(overrides: Partial<Widget> = {}): Widget {
  return {
    id: "w1",
    name: "Chatt",
    status: "active",
    revision: 0,
    activated_at: "2026-09-01T00:00:00Z",
    allowed_origins: ["https://www.kommun.se"],
    activation_blockers: [],
    ...overrides
  } as unknown as Widget;
}

function renderBar(autosave: WidgetAutosave, isAdmin = true) {
  const noop = vi.fn(async () => {});
  render(WidgetStatusBar, {
    autosave,
    isAdmin,
    onActivate: noop,
    onAcknowledgeExternalTools: noop,
    onPause: noop,
    onArchive: noop,
    onReload: noop
  });
}

describe("WidgetStatusBar", () => {
  test("an active widget that is not serving as configured says so", async () => {
    renderBar(
      new WidgetAutosave(widget({ activation_blockers: ["target_not_published"] }), vi.fn())
    );
    await expect.element(page.getByText("widget_admin_active_issues_title")).toBeVisible();
    await expect.element(page.getByText("widget_admin_blocker_target_not_published")).toBeVisible();
  });

  test("a healthy active widget shows no warning", async () => {
    renderBar(new WidgetAutosave(widget(), vi.fn()));
    await expect.element(page.getByText("widget_admin_status_active")).toBeVisible();
    expect(document.body.textContent).not.toContain("widget_admin_active_issues_title");
    expect(document.body.textContent).not.toContain("widget_admin_blockers_title");
  });

  test("an inactive widget keeps the activation wording", async () => {
    renderBar(
      new WidgetAutosave(
        widget({ status: "draft", activated_at: null, activation_blockers: ["subtitle_empty"] }),
        vi.fn()
      )
    );
    await expect.element(page.getByText("widget_admin_blockers_title")).toBeVisible();
  });

  test("a paused widget tells a non-admin, without a tooltip, why it cannot be resumed", async () => {
    renderBar(new WidgetAutosave(widget({ status: "paused" }), vi.fn()), false);
    const resume = page.getByRole("button", { name: "widget_admin_resume" });
    await expect.element(page.getByText("widget_admin_resume_admin_only")).toBeVisible();
    await expect.element(resume).toHaveAttribute("aria-disabled", "true");
    await expect.element(resume).toHaveAccessibleDescription("widget_admin_resume_admin_only");
  });

  test("a blocked widget's activate button is described by what blocks it", async () => {
    renderBar(
      new WidgetAutosave(
        widget({ status: "draft", activated_at: null, activation_blockers: ["subtitle_empty"] }),
        vi.fn()
      )
    );
    await expect
      .element(page.getByRole("button", { name: "widget_admin_activate" }))
      .toHaveAccessibleDescription(/widget_admin_blocker_subtitle_empty/);
  });

  test("pausing leaves focus on the status heading, not the page", async () => {
    const autosave = new WidgetAutosave(widget(), vi.fn());
    const noop = vi.fn(async () => {});
    render(WidgetStatusBar, {
      autosave,
      isAdmin: true,
      onActivate: noop,
      onAcknowledgeExternalTools: noop,
      onPause: vi.fn(async () => autosave.replace(widget({ status: "paused" }))),
      onArchive: noop,
      onReload: noop
    });
    const pause = page.getByRole("button", { name: "widget_admin_pause" }).element() as HTMLElement;
    pause.focus();
    pause.click();

    await expect.element(page.getByRole("button", { name: "widget_admin_resume" })).toBeVisible();
    await vi.waitFor(() =>
      expect(document.activeElement).toBe(
        page.getByRole("heading", { name: "widget_admin_status" }).element()
      )
    );
  });

  test.each([
    {
      action: "activating",
      current: widget({ status: "draft", activated_at: null }),
      button: "widget_admin_activate",
      handler: "onActivate"
    },
    {
      action: "pausing",
      current: widget(),
      button: "widget_admin_pause",
      handler: "onPause"
    }
  ] as const)(
    "$action that fails gives focus back to its button",
    async ({ current, button, handler }) => {
      let fail!: (error: Error) => void;
      const noop = vi.fn(async () => {});
      const handlers = { onActivate: noop, onPause: noop };
      handlers[handler] = vi.fn(() => new Promise<void>((_, reject) => (fail = reject)));
      render(WidgetStatusBar, {
        autosave: new WidgetAutosave(current, vi.fn()),
        isAdmin: true,
        onAcknowledgeExternalTools: noop,
        onArchive: noop,
        onReload: noop,
        ...handlers
      });
      const pressed = page.getByRole("button", { name: button }).element() as HTMLElement;
      pressed.focus();
      pressed.click();

      // Busy, the button is disabled, which drops focus to the page.
      await vi.waitFor(() => expect(handlers[handler]).toHaveBeenCalledTimes(1));
      await vi.waitFor(() => expect(document.activeElement).toBe(document.body));
      fail(new Error("offline"));
      await vi.waitFor(() => expect(document.activeElement).toBe(pressed));
    }
  );

  test("lists what the server refused so it can be found on any tab", async () => {
    const autosave = new WidgetAutosave(
      widget(),
      vi.fn().mockRejectedValue(
        new EneoError("refused", "RESPONSE", 400, 0, {
          detail: {
            code: "widget_policy_violation",
            message: "raw",
            violations: ["retention_above_policy_maximum"]
          }
        })
      ),
      { delay: 0 }
    );
    renderBar(autosave);
    autosave.patch({ privacy: { retention_days: 400 } as Widget["privacy"] });
    await autosave.flush();

    await expect.element(page.getByText("widget_admin_save_refused")).toBeVisible();
    await expect.element(page.getByText("widget_admin_refusals_title")).toBeVisible();
    await expect.element(page.getByText("widget_admin_blocker_retention_max")).toBeVisible();
  });
});
