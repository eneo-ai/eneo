// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
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

function openDetails() {
  renderInApp(<AuditTable logs={[log]} />);
  fireEvent.click(screen.getAllByRole("button", { name: "Fullständiga detaljer" })[0]!);
}

describe("AuditTable", () => {
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
