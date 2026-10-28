// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import type { AuditLog } from "./audit";
import { AuditTable } from "./audit-table";

const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock("@/lib/toast", () => ({ toast }));

const writeText = vi.fn<(text: string) => Promise<void>>();

const log = {
  id: "log-1",
  tenant_id: "tenant-1",
  actor_id: "5d0c7a2e-0000-4000-8000-000000000001",
  actor_type: "user",
  action: "user_created",
  entity_type: "user",
  entity_id: "5d0c7a2e-0000-4000-8000-000000000002",
  timestamp: "2026-09-25T08:30:00Z",
  description: "Användaren anna.lind@kommun.se skapades",
  metadata: { email: "anna.lind@kommun.se" },
  outcome: "success",
  created_at: "2026-09-25T08:30:00Z",
  updated_at: "2026-09-25T08:30:00Z"
} satisfies AuditLog;

beforeEach(() => {
  Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
});

afterEach(() => {
  cleanup();
  writeText.mockReset();
  toast.error.mockReset();
});

/** Opens the event's full details from its pinned cell; returns the dialog. */
function openDetails() {
  renderInApp(<AuditTable logs={[log]} />);
  fireEvent.click(screen.getByRole("button", { name: /^Användare skapad/ }));
  return screen.getByRole("dialog", { name: "Användare skapad" });
}

describe("AuditTable", () => {
  it("holds each event in view where the table scrolls sideways (decision 9)", async () => {
    renderInApp(<AuditTable logs={[log, { ...log, id: "log-9", outcome: "failure" }]} />);
    // Named like the tab and page it sits in, and so is its scroll region.
    const table = screen.getByRole("table", { name: "Granskningsloggar" });
    expect(screen.getByRole("group", { name: "Granskningsloggar" })).toBeTruthy();
    const pinned = within(table)
      .getAllByRole("columnheader")
      .filter((cell) => cell.style.insetInlineStart);
    expect(pinned.map((cell) => cell.textContent)).toEqual(["Händelse"]);
    // What happened, to what, and a failure: all in the pinned cell.
    const [, ok, failed] = within(table).getAllByRole("row");
    const event = within(ok!).getByRole("button", { name: /^Användare skapad/ });
    expect(event.getAttribute("aria-haspopup")).toBe("dialog");
    expect(event.textContent).toContain("Användaren anna.lind@kommun.se skapades");
    expect(within(failed!).getAllByText("Misslyckades")).toHaveLength(2);
    await expectNoAxeViolations(document.body);
  });

  it("shows the full details in a dialog: when, who, what, and the metadata", async () => {
    const dialog = openDetails();

    expect(within(dialog).getAllByText(/^25 sep\. 2026/).length).toBeGreaterThan(0);
    // The kind of actor with its id.
    expect(within(dialog).getByText(`Användare · ${log.actor_id}`)).toBeTruthy();
    const json = within(dialog).getByRole("region", { name: "Metadata (JSON)" });
    expect(json.tabIndex).toBe(0);
    await expectNoAxeViolations(document.body);
  });

  it("labels the crawler's probe, run and stop actions", () => {
    renderInApp(
      <AuditTable
        logs={[
          { ...log, id: "log-2", action: "website_crawl_probed", entity_type: "website" },
          { ...log, id: "log-3", action: "website_crawl_requested", entity_type: "website" },
          { ...log, id: "log-4", action: "website_crawl_stop_requested", entity_type: "website" }
        ]}
      />
    );
    expect(screen.getByText("Crawleranslutning testad")).toBeTruthy();
    expect(screen.getByText("Körning begärd")).toBeTruthy();
    expect(screen.getByText("Stopp av körning begärt")).toBeTruthy();
  });

  it("copies the metadata JSON and says so", async () => {
    writeText.mockResolvedValue();
    openDetails();

    fireEvent.click(screen.getByRole("button", { name: "Kopiera" }));

    await waitFor(() =>
      expect(writeText).toHaveBeenCalledWith(JSON.stringify(log.metadata, null, 2))
    );
    expect(await screen.findByRole("button", { name: "Kopierad!" })).toBeTruthy();
    await waitFor(() =>
      expect(document.querySelector('[data-astryx-live-region="polite"]')?.textContent).toBe(
        "Kopierat till urklipp"
      )
    );
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("shows an error when the browser refuses the clipboard", async () => {
    writeText.mockRejectedValue(new DOMException("denied", "NotAllowedError"));
    openDetails();

    fireEvent.click(screen.getByRole("button", { name: "Kopiera" }));

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "Det gick inte att kopiera. Försök igen eller markera texten och kopiera den."
      )
    );
    expect(screen.getByRole("button", { name: "Kopiera" })).toBeTruthy();
  });
});

it("says a system event's actor is the system, not that it was not recorded", () => {
  renderInApp(<AuditTable logs={[{ ...log, actor_type: "system", actor_id: null }]} />);
  fireEvent.click(screen.getByRole("button", { name: /^Användare skapad/ }));
  const dialog = screen.getByRole("dialog", { name: "Användare skapad" });
  expect(within(dialog).getByText("System")).toBeTruthy();
});
