// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import type { ChatPartner } from "@/lib/chat/types";
import { expectNoAxeViolations } from "@/test/axe";
import { HistoryAside } from "./history-panel";
import { RenameSessionDialog } from "./session-actions";
import { ChatTestProviders, installDomPolyfills } from "./testing";

const now = Date.now();
const day = 86_400_000;

type Row = { id: string; name: string; updated_at: string };

const api = vi.hoisted(() => ({
  /** The history the backend holds, newest first, served two per page. */
  rows: [] as Row[],
  cursors: [] as (string | undefined)[],
  GET: vi.fn(),
  PATCH: vi.fn(async () => ({ data: {}, response: new Response() })),
  POST: vi.fn(async () => ({ data: {}, response: new Response() })),
  DELETE: vi.fn(async (_path: string, init: { params: { path: { session_id: string } } }) => {
    api.rows = api.rows.filter((row) => row.id !== init.params.path.session_id);
    return { data: null, response: new Response(null, { status: 204 }) };
  })
}));
const toastSuccess = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("sonner", async (importOriginal) => {
  const original = await importOriginal<typeof import("sonner")>();
  return {
    ...original,
    toast: Object.assign(vi.fn(), { ...original.toast, success: toastSuccess })
  };
});

beforeAll(() => {
  installDomPolyfills();
  api.GET.mockImplementation(
    async (_path: string, init: { params: { query: { cursor?: string } } }) => {
      const cursor = init.params.query.cursor;
      api.cursors.push(cursor);
      const start = cursor ? Number(cursor) : 0;
      const items = api.rows.slice(start, start + 2);
      const next = start + 2 < api.rows.length ? String(start + 2) : null;
      return {
        data: { items, total_count: api.rows.length, next_cursor: next },
        response: new Response()
      };
    }
  );
});
beforeEach(() => {
  api.rows = [
    { id: "s1", name: "Upphandlingsanalys", updated_at: new Date(now).toISOString() },
    { id: "s2", name: "Protokoll KS", updated_at: new Date(now - 40 * day).toISOString() }
  ];
  api.cursors.length = 0;
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const partner: ChatPartner = {
  type: "assistant",
  id: "assistant-1",
  name: "Upphandlingsassistenten"
};

/** Opens a row's menu and returns the menu item with the given name. */
async function rowMenuItem(row: string, item: string) {
  const trigger = await screen.findByRole("button", { name: `Åtgärder för ${row}` });
  fireEvent.click(trigger);
  const menu = document.getElementById(trigger.getAttribute("aria-controls") ?? "");
  return within(menu!).getByRole("menuitem", { name: item });
}

function renderHistory({
  onClose = vi.fn(),
  onSelect = vi.fn(),
  onDeleted = vi.fn(),
  onRated = vi.fn()
} = {}) {
  render(
    <ChatTestProviders>
      <HistoryAside
        inline
        partner={partner}
        activeSessionId="s1"
        onSelect={onSelect}
        onDeleted={onDeleted}
        onRated={onRated}
        onClose={onClose}
      />
    </ChatTestProviders>
  );
  return { onClose, onSelect, onDeleted, onRated };
}

describe("HistoryAside", () => {
  it("groups conversations by date, marks the open one and selects on click", async () => {
    const { onSelect } = renderHistory();
    const aside = screen.getByRole("complementary", { name: "Historik" });
    await waitFor(() => expect(document.activeElement?.textContent).toBe("Historik"));

    const today = await within(aside).findByRole("region", { name: "Idag" });
    const current = within(today).getByRole("button", { name: "Upphandlingsanalys" });
    expect(current.getAttribute("aria-current")).toBe("true");
    const older = within(aside).getByRole("region", { name: "Äldre" });
    fireEvent.click(within(older).getByRole("button", { name: "Protokoll KS" }));
    expect(onSelect).toHaveBeenCalledWith("s2");
  });

  it("closes on Escape", async () => {
    const { onClose } = renderHistory();
    const heading = await screen.findByRole("heading", { name: "Historik" });
    fireEvent.keyDown(heading, { key: "Escape" });
    expect(onClose).toHaveBeenCalled();
  });

  it("adds older conversations below and moves focus to the first one it added", async () => {
    api.rows.push(
      { id: "s3", name: "Budget 2027", updated_at: new Date(now - 50 * day).toISOString() },
      { id: "s4", name: "Remissvar", updated_at: new Date(now - 60 * day).toISOString() },
      { id: "s5", name: "Delegationsordning", updated_at: new Date(now - 70 * day).toISOString() }
    );
    renderHistory();
    await screen.findByRole("button", { name: "Protokoll KS" });

    fireEvent.click(screen.getByRole("button", { name: "Visa fler konversationer" }));
    const added = await screen.findByRole("button", { name: "Budget 2027" });
    await waitFor(() => expect(document.activeElement).toBe(added));
    // The earlier conversations stay: the list grows instead of paging.
    expect(screen.getByRole("button", { name: "Upphandlingsanalys" })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Visa fler konversationer" }));
    const last = await screen.findByRole("button", { name: "Delegationsordning" });
    // No more pages: the button is gone, focus is on what it loaded.
    await waitFor(() => expect(document.activeElement).toBe(last));
    expect(screen.queryByRole("button", { name: "Visa fler konversationer" })).toBeNull();
    expect(api.cursors).toEqual([undefined, "2", "4"]);
  });

  it("deletes after a confirmation outside the menu, then keeps focus in the panel", async () => {
    const { onDeleted } = renderHistory();
    fireEvent.click(await rowMenuItem("Protokoll KS", "Ta bort"));

    const dialog = await screen.findByRole("alertdialog", { name: "Ta bort konversationen" });
    expect(within(dialog).getByText("Protokoll KS")).toBeTruthy();
    // The dialog is not part of the row's menu (Escape and focus belong to it).
    expect(dialog.closest('[role="menu"]')).toBeNull();

    fireEvent.click(within(dialog).getByRole("button", { name: "Bekräfta borttagning" }));
    await waitFor(() => expect(onDeleted).toHaveBeenCalledWith("s2"));
    expect(screen.queryByRole("button", { name: "Protokoll KS" })).toBeNull();
    await waitFor(() =>
      expect(document.activeElement).toBe(screen.getByRole("heading", { name: "Historik" }))
    );
  });

  it("confirms a rating and reports it", async () => {
    const { onRated } = renderHistory();
    fireEvent.click(await rowMenuItem("Upphandlingsanalys", "Betygsätt som bra"));
    await waitFor(() => expect(onRated).toHaveBeenCalledWith("s1", 1));
    expect(toastSuccess).toHaveBeenCalledWith("Tack för din återkoppling");
  });

  it("names untitled conversations", async () => {
    api.rows[1]!.name = "";
    renderHistory();
    expect(await screen.findByRole("button", { name: "Namnlös" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Åtgärder för Namnlös" })).toBeTruthy();
  });

  it("has no axe violations", async () => {
    renderHistory();
    await screen.findByRole("region", { name: "Idag" });
    await expectNoAxeViolations(document.body);
  });
});

describe("RenameSessionDialog", () => {
  it("renames with a visible label and saves on Enter", () => {
    const onSave = vi.fn();
    render(
      <ChatTestProviders>
        <RenameSessionDialog
          session={{ id: "s1", name: "Gammalt namn" }}
          pending={false}
          onCancel={vi.fn()}
          onSave={onSave}
        />
      </ChatTestProviders>
    );
    const input = screen.getByLabelText("Namn");
    fireEvent.change(input, { target: { value: "Nytt namn" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSave).toHaveBeenCalledWith("Nytt namn");
  });
});
