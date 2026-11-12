import { page, userEvent } from "vitest/browser";
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

const casefiles = {
  id: "m1",
  name: "Ärendesystemet",
  tools: [
    { id: "t1", name: "Skapa ärende" },
    { id: "t2", name: "Sök ärende" }
  ]
};
const booking = { id: "m2", name: "Bokningen", tools: [{ id: "t3", name: "Boka tid" }] };

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

function refused(status: number, code: string, servers: unknown[]) {
  return new EneoError("raw", "RESPONSE", status, 0, {
    detail: { code, message: "raw", servers }
  });
}

function renderBar(
  current: Widget,
  {
    isAdmin = true,
    autosave = new WidgetAutosave(current, vi.fn()),
    onActivate = vi.fn(async () => {}),
    onAcknowledgeExternalTools = vi.fn(async () => {})
  } = {}
) {
  const noop = vi.fn(async () => {});
  render(WidgetStatusBar, {
    autosave,
    isAdmin,
    onActivate,
    onAcknowledgeExternalTools,
    onPause: noop,
    onArchive: noop,
    onReload: noop
  });
  return { onActivate, onAcknowledgeExternalTools };
}

const click = (locator: { element: () => Element }) => (locator.element() as HTMLElement).click();
// Pressed from the keyboard, so the button holds focus when the dialog opens.
const press = (locator: { element: () => Element }) => {
  (locator.element() as HTMLElement).focus();
  click(locator);
};
const statusHeading = () => page.getByRole("heading", { name: "widget_admin_status" }).element();

describe("WidgetStatusBar external MCP tools", () => {
  test("activation acknowledges exactly the tools the dialog listed, then activates", async () => {
    const calls: string[] = [];
    const { onActivate, onAcknowledgeExternalTools } = renderBar(widget(), {
      onActivate: vi.fn(async () => void calls.push("activate")),
      onAcknowledgeExternalTools: vi.fn(async () => void calls.push("acknowledge"))
    });
    await expect.element(page.getByText("widget_admin_external_tools_note")).toBeVisible();

    click(page.getByRole("button", { name: "widget_admin_activate" }));
    const dialog = page.getByRole("alertdialog");
    await expect.element(dialog.getByText("Ärendesystemet")).toBeVisible();
    await expect
      .element(dialog.getByText("widget_admin_external_tools_tools(Skapa ärende, Sök ärende)"))
      .toBeVisible();

    // The confirming button waits for the checkbox.
    const confirm = dialog.getByRole("button", { name: "widget_admin_activate" });
    await expect.element(confirm).toBeDisabled();
    await userEvent.click(dialog.getByRole("checkbox"));
    await userEvent.click(confirm);

    await vi.waitFor(() => expect(calls).toEqual(["acknowledge", "activate"]));
    expect(onAcknowledgeExternalTools).toHaveBeenCalledWith([casefiles]);
    expect(onActivate).toHaveBeenCalledTimes(1);
    await expect.element(dialog).not.toBeInTheDocument();
  });

  test("the Activate button is described by the note that a dialog follows", async () => {
    renderBar(widget());
    await expect
      .element(page.getByRole("button", { name: "widget_admin_activate" }))
      .toHaveAccessibleDescription("widget_admin_external_tools_note");
  });

  test("cancelling the dialog acknowledges and activates nothing", async () => {
    const { onActivate, onAcknowledgeExternalTools } = renderBar(widget());
    const activate = page.getByRole("button", { name: "widget_admin_activate" });
    press(activate);
    const dialog = page.getByRole("alertdialog");
    await expect.element(dialog).toBeVisible();
    await userEvent.click(dialog.getByRole("button", { name: "cancel" }));
    expect(onAcknowledgeExternalTools).not.toHaveBeenCalled();
    expect(onActivate).not.toHaveBeenCalled();
    // Disabled while it was busy, the button still gets focus back.
    await vi.waitFor(() => expect(document.activeElement).toBe(activate.element()));
  });

  test("activating through the dialog leaves focus on the status heading", async () => {
    const draft = widget();
    const autosave = new WidgetAutosave(draft, vi.fn());
    renderBar(draft, {
      autosave,
      onActivate: vi.fn(async () =>
        autosave.replace({ ...draft, status: "active", external_tools_acknowledged: true })
      )
    });
    press(page.getByRole("button", { name: "widget_admin_activate" }));
    const dialog = page.getByRole("alertdialog");
    await userEvent.click(dialog.getByRole("checkbox"));
    await userEvent.click(dialog.getByRole("button", { name: "widget_admin_activate" }));

    await expect.element(dialog).not.toBeInTheDocument();
    await expect.element(page.getByRole("button", { name: "widget_admin_pause" })).toBeVisible();
    await vi.waitFor(() => expect(document.activeElement).toBe(statusHeading()));
  });

  test.each([
    { case: "acknowledged tools", overrides: { external_tools_acknowledged: true } },
    {
      case: "no tools outside Eneo",
      overrides: { external_tools: [], external_tools_acknowledged: true }
    }
  ])("$case activate without asking", async ({ overrides }) => {
    const { onActivate, onAcknowledgeExternalTools } = renderBar(widget(overrides));
    expect(document.body.textContent).not.toContain("widget_admin_external_tools_note");
    click(page.getByRole("button", { name: "widget_admin_activate" }));
    await vi.waitFor(() => expect(onActivate).toHaveBeenCalledTimes(1));
    expect(onAcknowledgeExternalTools).not.toHaveBeenCalled();
    expect(page.getByRole("alertdialog").elements()).toHaveLength(0);
  });

  test.each([
    {
      case: "the acknowledgement",
      current: widget(),
      refuse: { acknowledge: refused(409, "external_tools_changed", [casefiles, booking]) }
    },
    {
      case: "an activation the page thought acknowledged",
      current: widget({ external_tools_acknowledged: true }),
      refuse: { activate: refused(400, "external_tools_unacknowledged", [casefiles, booking]) }
    }
  ])(
    "a list that changed under the admin is shown again when it refuses $case",
    async ({ current, refuse }) => {
      const onAcknowledgeExternalTools = vi.fn(async () => {});
      const onActivate = vi.fn(async () => {});
      if (refuse.acknowledge) onAcknowledgeExternalTools.mockRejectedValueOnce(refuse.acknowledge);
      if (refuse.activate) onActivate.mockRejectedValueOnce(refuse.activate);
      renderBar(current, { onActivate, onAcknowledgeExternalTools });

      click(page.getByRole("button", { name: "widget_admin_activate" }));
      const dialog = page.getByRole("alertdialog");
      if (refuse.acknowledge) {
        await userEvent.click(dialog.getByRole("checkbox"));
        await userEvent.click(dialog.getByRole("button", { name: "widget_admin_activate" }));
      }

      await expect
        .element(dialog.getByRole("alert"))
        .toHaveTextContent("widget_admin_external_tools_changed");
      await expect.element(dialog.getByText("Bokningen")).toBeVisible();
      const checkbox = dialog.getByRole("checkbox");
      await expect.element(checkbox).not.toBeChecked();
      await vi.waitFor(() => expect(dialog.element().contains(document.activeElement)).toBe(true));
      const confirm = dialog.getByRole("button", { name: "widget_admin_activate" });
      await expect.element(confirm).toBeDisabled();

      await userEvent.click(checkbox);
      await userEvent.click(confirm);
      await vi.waitFor(() =>
        expect(onAcknowledgeExternalTools).toHaveBeenLastCalledWith([casefiles, booking])
      );
      await vi.waitFor(() => expect(onActivate).toHaveBeenCalledTimes(refuse.activate ? 2 : 1));
    }
  );

  test("an admin acknowledges a live widget's newer tools in place, without pausing", async () => {
    const live = widget({
      status: "active",
      activated_at: "2026-09-01T00:00:00Z",
      activation_blockers: ["external_tools_unacknowledged"]
    });
    const { onActivate, onAcknowledgeExternalTools } = renderBar(live);
    await expect.element(page.getByText("widget_admin_active_issues_title")).toBeVisible();
    await expect
      .element(page.getByText("widget_admin_blocker_external_tools_unacknowledged"))
      .toBeVisible();

    await userEvent.click(page.getByRole("button", { name: "widget_admin_external_tools_review" }));
    const dialog = page.getByRole("alertdialog");
    await userEvent.click(dialog.getByRole("checkbox"));
    await userEvent.click(
      dialog.getByRole("button", { name: "widget_admin_external_tools_confirm" })
    );

    await vi.waitFor(() => expect(onAcknowledgeExternalTools).toHaveBeenCalledWith([casefiles]));
    await expect.element(dialog).not.toBeInTheDocument();
    expect(onActivate).not.toHaveBeenCalled();
  });

  test("acknowledging in place leaves focus on the status heading, not the page", async () => {
    const live = widget({
      status: "active",
      activated_at: "2026-09-01T00:00:00Z",
      activation_blockers: ["external_tools_unacknowledged"]
    });
    const autosave = new WidgetAutosave(live, vi.fn());
    renderBar(live, {
      autosave,
      onAcknowledgeExternalTools: vi.fn(async () =>
        autosave.replace({ ...live, activation_blockers: [], external_tools_acknowledged: true })
      )
    });
    const review = page.getByRole("button", { name: "widget_admin_external_tools_review" });
    press(review);
    const dialog = page.getByRole("alertdialog");
    await userEvent.click(dialog.getByRole("checkbox"));
    await userEvent.click(
      dialog.getByRole("button", { name: "widget_admin_external_tools_confirm" })
    );

    await expect.element(dialog).not.toBeInTheDocument();
    await expect.element(review).not.toBeInTheDocument();
    await vi.waitFor(() => expect(document.activeElement).toBe(statusHeading()));
  });

  test("an editor is told why a live widget's newer tools wait, with nothing to press", async () => {
    renderBar(
      widget({
        status: "active",
        activated_at: "2026-09-01T00:00:00Z",
        activation_blockers: ["external_tools_unacknowledged"]
      }),
      { isAdmin: false }
    );
    await expect
      .element(page.getByText("widget_admin_blocker_external_tools_unacknowledged"))
      .toBeVisible();
    expect(
      page.getByRole("button", { name: "widget_admin_external_tools_review" }).elements()
    ).toHaveLength(0);
  });
});
