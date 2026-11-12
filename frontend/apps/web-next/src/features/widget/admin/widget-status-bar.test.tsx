// @vitest-environment jsdom
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { useSyncExternalStore } from "react";
import { describe, expect, it, vi } from "vitest";
import { apiErrorFromResponse } from "@/lib/api/errors";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { WidgetAutosave, type Widget } from "./autosave";
import { WidgetStatusBar } from "./widget-status-bar";

type ExternalTools = Widget["external_tools"];

const casefiles = {
  id: "m1",
  name: "Ärendesystemet",
  tools: [
    { id: "t1", name: "Skapa ärende" },
    { id: "t2", name: "Sök ärende" }
  ]
};
const booking = { id: "m2", name: "Bokningen", tools: [{ id: "t3", name: "Boka tid" }] };

const DIALOG = "Assistenten använder verktyg på MCP-servrar utanför Eneo";
const ACKNOWLEDGE = /^Jag förstår att anonyma besökare/;
const NOTE =
  "Assistenten använder verktyg på MCP-servrar utanför Eneo. Vid aktivering bekräftar du vad det innebär för anonyma besökare.";
const CHANGED =
  "Assistentens verktyg på MCP-servrar utanför Eneo har ändrats. Granska den aktuella listan.";
const UNTICKED = "Kryssa i rutan för att bekräfta verktygen.";
const LIVE_BLOCKER =
  "Verktyg på MCP-servrar utanför Eneo har slagits på efter den senaste bekräftelsen. Besökarnas turer körs utan dem tills en organisationsadministratör bekräftar dem.";

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

const live = (overrides: Partial<Widget> = {}) =>
  widget({
    status: "active",
    activated_at: "2026-09-01T00:00:00Z",
    activation_blockers: ["external_tools_unacknowledged"],
    ...overrides
  });

/** A refusal that carries the assistant's current list, as the API sends it. */
function refused(status: number, code: string, servers: ExternalTools) {
  return apiErrorFromResponse(new Response(null, { status }), {
    detail: { code, message: "raw", servers }
  });
}

/** The text of the elements an element's aria-describedby points at. */
function descriptionOf(element: Element) {
  return (element.getAttribute("aria-describedby") ?? "")
    .split(" ")
    .filter(Boolean)
    .map((id) => document.getElementById(id)?.textContent ?? "")
    .join(" ");
}

type Handlers = {
  onActivate: () => Promise<void>;
  onAcknowledgeExternalTools: (servers: ExternalTools) => Promise<void>;
};

/** The status bar as the editor mounts it: state read from the autosave store. */
function Bar({
  autosave,
  isAdmin,
  ...handlers
}: Handlers & { autosave: WidgetAutosave; isAdmin: boolean }) {
  const state = useSyncExternalStore(
    autosave.subscribe,
    autosave.getSnapshot,
    autosave.getSnapshot
  );
  const noop = async () => {};
  return (
    <WidgetStatusBar
      autosave={autosave}
      state={state}
      isAdmin={isAdmin}
      {...handlers}
      onPause={noop}
      onArchive={noop}
      onReload={noop}
    />
  );
}

function renderBar(
  current: Widget,
  {
    isAdmin = true,
    onActivate = vi.fn<Handlers["onActivate"]>(async () => {}),
    onAcknowledgeExternalTools = vi.fn<Handlers["onAcknowledgeExternalTools"]>(async () => {})
  }: Partial<Handlers> & { isAdmin?: boolean } = {}
) {
  const autosave = new WidgetAutosave(current, vi.fn());
  renderInApp(
    <Bar
      autosave={autosave}
      isAdmin={isAdmin}
      onActivate={onActivate}
      onAcknowledgeExternalTools={onAcknowledgeExternalTools}
    />
  );
  return { autosave, onActivate, onAcknowledgeExternalTools };
}

/** Presses a button the way a pointer does: it takes focus, then the click. */
function press(button: HTMLElement) {
  button.focus();
  fireEvent.click(button);
}

describe("WidgetStatusBar tools on MCP servers outside Eneo", () => {
  it.each([
    { status: "draft", label: "Aktivera" },
    { status: "paused", label: "Återuppta" }
  ] as const)(
    "a $status widget acknowledges exactly the tools the dialog lists, then goes live",
    async ({ status, label }) => {
      const calls: string[] = [];
      const { onActivate, onAcknowledgeExternalTools } = renderBar(widget({ status }), {
        onActivate: vi.fn(async () => void calls.push("activate")),
        onAcknowledgeExternalTools: vi.fn(async () => void calls.push("acknowledge"))
      });
      // Said before the press, and read with the button.
      const activate = screen.getByRole("button", { name: label });
      expect(screen.getByText(NOTE)).toBeTruthy();
      expect(descriptionOf(activate)).toContain(NOTE);

      press(activate);
      const dialog = await screen.findByRole("dialog", { name: DIALOG });
      const servers = within(dialog).getByRole("list", { name: "MCP-servrar utanför Eneo" });
      expect(
        within(servers)
          .getAllByRole("listitem")
          .map((item) => item.textContent)
      ).toEqual(["ÄrendesystemetVerktyg: Skapa ärende, Sök ärende"]);
      fireEvent.click(within(dialog).getByRole("checkbox", { name: ACKNOWLEDGE }));
      fireEvent.click(within(dialog).getByRole("button", { name: label }));

      await waitFor(() => expect(calls).toEqual(["acknowledge", "activate"]));
      expect(onAcknowledgeExternalTools).toHaveBeenCalledWith([casefiles]);
      expect(onActivate).toHaveBeenCalledTimes(1);
      await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    }
  );

  it("the confirming button pressed before the box is ticked says so at the box, which takes focus", async () => {
    const { onActivate, onAcknowledgeExternalTools } = renderBar(widget());
    press(screen.getByRole("button", { name: "Aktivera" }));
    const dialog = await screen.findByRole("dialog", { name: DIALOG });

    fireEvent.click(within(dialog).getByRole("button", { name: "Aktivera" }));
    const checkbox = within(dialog).getByRole("checkbox", { name: ACKNOWLEDGE });
    await waitFor(() => expect(document.activeElement).toBe(checkbox));
    expect(checkbox.getAttribute("aria-invalid")).toBe("true");
    expect(descriptionOf(checkbox)).toContain(UNTICKED);
    expect(onAcknowledgeExternalTools).not.toHaveBeenCalled();
    expect(onActivate).not.toHaveBeenCalled();
    await act(async () => {
      await expectNoAxeViolations(document.body);
    });
  });

  it("cancelling acknowledges and activates nothing, and hands focus back", async () => {
    const { onActivate, onAcknowledgeExternalTools } = renderBar(widget());
    const activate = screen.getByRole("button", { name: "Aktivera" });
    press(activate);
    const dialog = await screen.findByRole("dialog", { name: DIALOG });
    fireEvent.click(within(dialog).getByRole("button", { name: "Avbryt" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(document.activeElement).toBe(activate);
    expect(onAcknowledgeExternalTools).not.toHaveBeenCalled();
    expect(onActivate).not.toHaveBeenCalled();
  });

  it("while the acknowledgement is under way, neither a second press nor Cancel acts", async () => {
    let answer = () => {};
    const onAcknowledgeExternalTools = vi.fn<Handlers["onAcknowledgeExternalTools"]>(
      () =>
        new Promise<void>((resolve) => {
          answer = () => resolve();
        })
    );
    const { onActivate } = renderBar(widget(), { onAcknowledgeExternalTools });
    press(screen.getByRole("button", { name: "Aktivera" }));
    const dialog = await screen.findByRole("dialog", { name: DIALOG });
    fireEvent.click(within(dialog).getByRole("checkbox", { name: ACKNOWLEDGE }));
    const confirm = within(dialog).getByRole("button", { name: "Aktivera" });
    press(confirm);
    await waitFor(() => expect(onAcknowledgeExternalTools).toHaveBeenCalledTimes(1));

    fireEvent.click(confirm);
    fireEvent.click(within(dialog).getByRole("button", { name: "Avbryt" }));
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(screen.getByRole("dialog", { name: DIALOG })).toBe(dialog);
    expect(document.activeElement).toBe(confirm);

    await act(async () => answer());
    await waitFor(() => expect(onActivate).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(onAcknowledgeExternalTools).toHaveBeenCalledTimes(1);
  });

  it.each([
    { case: "acknowledged tools", overrides: { external_tools_acknowledged: true } },
    {
      case: "no tools outside Eneo",
      overrides: { external_tools: [], external_tools_acknowledged: true }
    }
  ])("$case activate without asking", async ({ overrides }) => {
    const { onActivate, onAcknowledgeExternalTools } = renderBar(widget(overrides));
    expect(screen.queryByText(NOTE)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Aktivera" }));
    await waitFor(() => expect(onActivate).toHaveBeenCalledTimes(1));
    expect(onAcknowledgeExternalTools).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it.each([
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
    "a list that changed under the admin is shown again when the API refuses $case",
    async ({ current, refuse }) => {
      const onActivate = vi.fn<Handlers["onActivate"]>(async () => {});
      const onAcknowledgeExternalTools = vi.fn<Handlers["onAcknowledgeExternalTools"]>(
        async () => {}
      );
      if (refuse.acknowledge) onAcknowledgeExternalTools.mockRejectedValueOnce(refuse.acknowledge);
      if (refuse.activate) onActivate.mockRejectedValueOnce(refuse.activate);
      renderBar(current, { onActivate, onAcknowledgeExternalTools });

      press(screen.getByRole("button", { name: "Aktivera" }));
      const dialog = await screen.findByRole("dialog", { name: DIALOG });
      if (refuse.acknowledge) {
        fireEvent.click(within(dialog).getByRole("checkbox", { name: ACKNOWLEDGE }));
        fireEvent.click(within(dialog).getByRole("button", { name: "Aktivera" }));
      }

      expect((await within(dialog).findByRole("alert")).textContent).toBe(CHANGED);
      expect(within(dialog).getByText("Bokningen")).toBeTruthy();
      const checkbox = within(dialog).getByRole("checkbox", {
        name: ACKNOWLEDGE
      }) as HTMLInputElement;
      expect(checkbox.checked).toBe(false);
      expect(dialog.contains(document.activeElement)).toBe(true);

      fireEvent.click(checkbox);
      fireEvent.click(within(dialog).getByRole("button", { name: "Aktivera" }));
      await waitFor(() =>
        expect(onAcknowledgeExternalTools).toHaveBeenLastCalledWith([casefiles, booking])
      );
      await waitFor(() => expect(onActivate).toHaveBeenCalledTimes(refuse.activate ? 2 : 1));
      await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    }
  );

  it("a list emptied meanwhile leaves nothing to accept and activates", async () => {
    const onAcknowledgeExternalTools = vi.fn<Handlers["onAcknowledgeExternalTools"]>(
      async () => {}
    );
    onAcknowledgeExternalTools.mockRejectedValueOnce(refused(409, "external_tools_changed", []));
    const { onActivate } = renderBar(widget(), { onAcknowledgeExternalTools });
    press(screen.getByRole("button", { name: "Aktivera" }));
    const dialog = await screen.findByRole("dialog", { name: DIALOG });
    fireEvent.click(within(dialog).getByRole("checkbox", { name: ACKNOWLEDGE }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Aktivera" }));

    expect(
      await within(dialog).findByText(
        "Assistenten har inte längre några verktyg påslagna på MCP-servrar utanför Eneo."
      )
    ).toBeTruthy();
    expect(within(dialog).queryByRole("checkbox")).toBeNull();
    fireEvent.click(within(dialog).getByRole("button", { name: "Aktivera" }));
    await waitFor(() => expect(onAcknowledgeExternalTools).toHaveBeenLastCalledWith([]));
    await waitFor(() => expect(onActivate).toHaveBeenCalledTimes(1));
  });

  it("an admin acknowledges a live widget's newer tools in place, without pausing", async () => {
    const onAcknowledgeExternalTools = vi.fn<Handlers["onAcknowledgeExternalTools"]>();
    const { autosave, onActivate } = renderBar(live(), { onAcknowledgeExternalTools });
    // The answer clears the blocker, and with it the button that opened the dialog.
    onAcknowledgeExternalTools.mockImplementation(async () =>
      autosave.replace(live({ activation_blockers: [], external_tools_acknowledged: true }))
    );
    expect(screen.getByText("Widgeten är aktiv, men det här behöver åtgärdas")).toBeTruthy();
    expect(screen.getByText(LIVE_BLOCKER)).toBeTruthy();

    press(screen.getByRole("button", { name: "Granska och bekräfta verktygen" }));
    const dialog = await screen.findByRole("dialog", { name: DIALOG });
    fireEvent.click(within(dialog).getByRole("checkbox", { name: ACKNOWLEDGE }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Bekräfta" }));

    await waitFor(() => expect(onAcknowledgeExternalTools).toHaveBeenCalledWith([casefiles]));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(onActivate).not.toHaveBeenCalled();
    expect(screen.queryByText(LIVE_BLOCKER)).toBeNull();
    // Focus does not fall to the page with the button that opened the dialog.
    await waitFor(() =>
      expect(document.activeElement).toBe(screen.getByRole("heading", { name: "Status" }))
    );
  });

  it("an editor is told why a live widget's newer tools wait, with nothing to press", () => {
    renderBar(live(), { isAdmin: false });
    expect(screen.getByText(LIVE_BLOCKER)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Granska och bekräfta verktygen" })).toBeNull();
  });
});
