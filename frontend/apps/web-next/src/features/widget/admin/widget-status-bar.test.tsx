// @vitest-environment jsdom
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { useSyncExternalStore } from "react";
import { describe, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import { WidgetAutosave, type Widget } from "./autosave";
import { WidgetStatusBar } from "./widget-status-bar";

function widget(overrides: Partial<Widget> = {}): Widget {
  return {
    id: "w1",
    name: "Chatt",
    status: "draft",
    revision: 0,
    activated_at: null,
    allowed_origins: ["https://www.kommun.se"],
    activation_blockers: [],
    external_tools: [],
    ...overrides
  } as unknown as Widget;
}

const live = (overrides: Partial<Widget> = {}) =>
  widget({
    status: "active",
    activated_at: "2026-09-01T00:00:00Z",
    ...overrides
  });

type Handlers = {
  onActivate: () => Promise<void>;
  onPause: () => Promise<void>;
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
    onPause = vi.fn<Handlers["onPause"]>(async () => {})
  }: Partial<Handlers> & { isAdmin?: boolean } = {}
) {
  const autosave = new WidgetAutosave(current, vi.fn());
  renderInApp(
    <Bar autosave={autosave} isAdmin={isAdmin} onActivate={onActivate} onPause={onPause} />
  );
  return { autosave, onActivate, onPause };
}

/** Presses a button the way a pointer does: it takes focus, then the click. */
function press(button: HTMLElement) {
  button.focus();
  fireEvent.click(button);
}

describe("WidgetStatusBar activation notice", () => {
  it.each(["draft", "paused"] as const)("describes %s activation to an admin", (status) => {
    renderBar(widget({ status }));
    const note = screen.getByText(/Widgeten följer assistentens verktygsval/);
    const action = screen.getByRole("button", {
      name: status === "draft" ? "Aktivera" : "Återuppta"
    });
    expect(note.id).toBeTruthy();
    expect(action.getAttribute("aria-describedby")?.split(" ")).toContain(note.id);
  });

  it.each([
    ["active", true],
    ["draft", false],
    ["paused", false]
  ] as const)("omits the activation notice for %s with admin=%s", (status, isAdmin) => {
    renderBar(widget({ status }), { isAdmin });
    expect(screen.queryByText(/Widgeten följer assistentens verktygsval/)).toBeNull();
  });
});

describe("WidgetStatusBar focus", () => {
  it.each([
    {
      action: "activating",
      from: widget({ external_tools: [] }),
      button: "Aktivera",
      to: { status: "active", activated_at: "2026-09-01T00:00:00Z" },
      next: "Pausa"
    },
    {
      action: "pausing",
      from: live({ activation_blockers: [] }),
      button: "Pausa",
      to: { status: "paused" },
      next: "Återuppta"
    }
  ] as const)(
    "$action hands focus to the status heading, not to the button that takes its place",
    async ({ from, button, to, next }) => {
      const onActivate = vi.fn<Handlers["onActivate"]>();
      const onPause = vi.fn<Handlers["onPause"]>();
      const { autosave } = renderBar(from, { onActivate, onPause });
      const done = async () => autosave.replace({ ...from, ...to } as Widget);
      onActivate.mockImplementation(done);
      onPause.mockImplementation(done);

      press(screen.getByRole("button", { name: button }));
      await screen.findByRole("button", { name: next });
      await waitFor(() =>
        expect(document.activeElement).toBe(screen.getByRole("heading", { name: "Status" }))
      );
    }
  );
});
