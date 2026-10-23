// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import type { Entry, Version } from "./prompt-library";

const entry: Entry = {
  id: "entry-1",
  name: "Sammanfatta ett beslut",
  description: "Kort sammanfattning",
  current_version: 2,
  created_by_user_id: "user-1",
  created_at: "2026-09-01T08:00:00Z",
  updated_at: "2026-09-20T08:00:00Z"
};

const version = (overrides: Partial<Version>): Version => ({
  id: "version-1",
  prompt_library_id: "entry-1",
  version: 1,
  name: "Sammanfatta ett beslut",
  description: null,
  text: "Sammanfatta beslutet i två meningar.",
  created_by_user_id: "user-2",
  created_at: "2026-09-01T08:00:00Z",
  updated_at: "2026-09-01T08:00:00Z",
  ...overrides
});

const versions = [
  version({
    id: "version-2",
    version: 2,
    text: "Sammanfatta beslutet i tre meningar.",
    created_by_user_id: "user-1",
    created_at: "2026-09-20T08:00:00Z"
  }),
  version({})
];

const ok = (data: unknown) => Promise.resolve({ data, response: new Response("{}") });

const api = vi.hoisted(() => ({ GET: vi.fn(), PUT: vi.fn() }));
const toast = vi.hoisted(() => ({
  success: vi.fn(),
  info: vi.fn(),
  warning: vi.fn(),
  error: vi.fn()
}));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/toast", () => ({ toast }));

import { VersionHistoryDialog } from "./version-history-dialog";

function Harness() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Historik
      </button>
      <VersionHistoryDialog entry={entry} open={open} onOpenChange={setOpen} />
    </>
  );
}

async function openDialog() {
  renderInApp(<Harness />);
  const opener = screen.getByRole("button", { name: "Historik" });
  opener.focus();
  fireEvent.click(opener);
  const dialog = await screen.findByRole("dialog", {
    name: "Versionshistorik för Sammanfatta ett beslut"
  });
  await within(dialog).findByRole("table", { name: "Versionshistorik" });
  return { opener, dialog };
}

beforeEach(() => {
  api.GET.mockImplementation(() => ok({ items: [...versions].reverse(), count: 2 }));
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("VersionHistoryDialog", () => {
  it("lists the versions newest first, marks the current one and says who saved each", async () => {
    const { dialog } = await openDialog();
    const table = within(dialog).getByRole("table", { name: "Versionshistorik" });
    const rows = within(table).getAllByRole("row").slice(1);

    expect(rows[0]!.textContent).toContain("v2");
    expect(within(rows[0]!).getByText("Aktuell")).toBeTruthy();
    // The signed-in admin (user-1) saved v2; someone else saved v1.
    expect(within(rows[0]!).getByText("Du")).toBeTruthy();
    expect(within(rows[1]!).getByText("Annan administratör")).toBeTruthy();
    // Only an older version can be restored.
    expect(within(rows[0]!).queryByRole("button", { name: "Återställ version 2" })).toBeNull();
    expect(within(rows[1]!).getByRole("button", { name: "Återställ version 1" })).toBeTruthy();
    await expectNoAxeViolations(document.body);
  });

  it("shows a version read-only in a focusable content region, and goes back", async () => {
    const { dialog } = await openDialog();
    fireEvent.click(within(dialog).getByRole("button", { name: "Visa version 1" }));

    const view = await screen.findByRole("dialog", { name: "Version 1" });
    const region = within(view).getByRole("region", { name: "Innehåll i version 1" });
    expect(region.textContent).toBe("Sammanfatta beslutet i två meningar.");
    expect(region.getAttribute("tabindex")).toBe("0");
    expect(within(view).getByText("Annan administratör")).toBeTruthy();
    // Focus moved to the new title, as on open.
    expect(document.activeElement).toBe(within(view).getByRole("heading", { name: "Version 1" }));
    expect(within(view).getByRole("button", { name: "Återställ den här versionen" })).toBeTruthy();
    await expectNoAxeViolations(document.body);

    fireEvent.click(within(view).getByRole("button", { name: "Tillbaka till versionshistoriken" }));
    expect(
      await screen.findByRole("dialog", { name: "Versionshistorik för Sammanfatta ett beslut" })
    ).toBeTruthy();
  });

  it("has no restore action for the current version's view", async () => {
    const { dialog } = await openDialog();
    fireEvent.click(within(dialog).getByRole("button", { name: "Visa version 2" }));
    const view = await screen.findByRole("dialog", { name: "Version 2" });
    expect(within(view).queryByRole("button", { name: "Återställ den här versionen" })).toBeNull();
  });

  it("restores a version after confirmation and announces the new version", async () => {
    api.PUT.mockImplementation(() => ok({ ...entry, current_version: 3, text: "" }));
    const { dialog } = await openDialog();
    fireEvent.click(within(dialog).getByRole("button", { name: "Visa version 1" }));
    const view = await screen.findByRole("dialog", { name: "Version 1" });
    fireEvent.click(within(view).getByRole("button", { name: "Återställ den här versionen" }));

    const confirm = await screen.findByRole("alertdialog", {
      name: "Återställa den här versionen?"
    });
    expect(within(confirm).getByText(/version 1/)).toBeTruthy();
    fireEvent.click(within(confirm).getByRole("button", { name: "Återställ" }));

    await waitFor(() =>
      expect(api.PUT).toHaveBeenCalledWith("/api/v1/admin/prompt-library/{id}/", {
        params: { path: { id: "entry-1" } },
        body: {
          name: "Sammanfatta ett beslut",
          description: null,
          text: "Sammanfatta beslutet i två meningar."
        }
      })
    );
    const message = "Version 1 återställdes som version 3.";
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith(message));
    // Announced politely too (Astryx's shared live region).
    await waitFor(() => expect(document.body.textContent).toContain(message));
    // Back on the list, where the new version shows as current.
    expect(
      await screen.findByRole("dialog", { name: "Versionshistorik för Sammanfatta ett beslut" })
    ).toBeTruthy();
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
  });

  it("keeps the confirmation open and reports a failed restore", async () => {
    api.PUT.mockImplementation(() =>
      Promise.resolve({
        error: { message: "boom" },
        response: new Response(null, { status: 500 })
      })
    );
    const { dialog } = await openDialog();
    fireEvent.click(within(dialog).getByRole("button", { name: "Återställ version 1" }));
    const confirm = await screen.findByRole("alertdialog");
    fireEvent.click(within(confirm).getByRole("button", { name: "Återställ" }));

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(screen.getByRole("alertdialog")).toBeTruthy();
    expect(toast.success).not.toHaveBeenCalled();
  });

  it("closes with Escape and returns focus to the opener", async () => {
    const { opener, dialog } = await openDialog();
    fireEvent.keyDown(dialog, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(opener));
  });
});
