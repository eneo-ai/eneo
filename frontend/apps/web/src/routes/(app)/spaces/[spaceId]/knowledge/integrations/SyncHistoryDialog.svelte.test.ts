import type { IntegrationKnowledge } from "@eneo/eneo-js";
import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { describe, expect, it, vi } from "vitest";
import { m } from "$lib/paraglide/messages";
import type { SyncLog } from "./syncHistory";

const getSyncLogs = vi.hoisted(() => vi.fn());
vi.mock("$lib/core/Eneo", () => ({
  getEneo: () => ({ integrations: { knowledge: { getSyncLogs } } })
}));

import SyncHistoryDialog from "./SyncHistoryDialog.svelte";

const knowledge = { id: "k-1", name: "Policies" } as IntegrationKnowledge;

function log(overrides: Partial<SyncLog>): SyncLog {
  return {
    id: "log-1",
    integration_knowledge_id: knowledge.id,
    sync_type: "delta",
    status: "success",
    started_at: "2026-10-01T10:00:00Z",
    completed_at: "2026-10-01T10:00:42Z",
    created_at: "2026-10-01T10:00:00Z",
    files_processed: 2,
    files_deleted: 0,
    pages_processed: 0,
    folders_processed: 0,
    skipped_items: 0,
    skipped_details: [],
    duration_seconds: 42,
    ...overrides
  } as SyncLog;
}

function respondWith(items: SyncLog[], total = items.length) {
  getSyncLogs.mockResolvedValue({
    items,
    total_count: total,
    page_size: 10,
    offset: 0,
    count: items.length,
    current_page: 1,
    total_pages: Math.max(1, Math.ceil(total / 10)),
    has_next: total > 10
  });
}

describe("SyncHistoryDialog", () => {
  it("lists the same skipped file name from several folders and says how many are not listed", async () => {
    respondWith([
      log({
        skipped_items: 5,
        skipped_details: [
          { file: "Protokoll.docx", reason: "too large" },
          { file: "Protokoll.docx", reason: "unsupported format" }
        ],
        metadata: { skipped_truncated: true, unchanged_items: 9 } as SyncLog["metadata"]
      })
    ]);
    render(SyncHistoryDialog, { knowledge, open: true });

    await page.getByText(m.item_s_skipped({ count: 5 }), { exact: true }).click();

    expect(page.getByText("Protokoll.docx").elements()).toHaveLength(2);
    await expect.element(page.getByText("too large")).toBeVisible();
    await expect.element(page.getByText("unsupported format")).toBeVisible();
    await expect.element(page.getByText(m.skipped_and_n_more({ count: 3 }))).toBeVisible();
    await expect
      .element(page.getByText(new RegExp(m.item_s_unchanged({ count: 9 }))))
      .toBeVisible();
  });

  it("translates the status, shows the reconcile warning and labels the statistics per page", async () => {
    respondWith(
      [
        log({
          id: "a",
          metadata: { reconcile_warning: "Delta token reset" } as SyncLog["metadata"]
        }),
        log({ id: "b", status: "error", error_message: "403", files_processed: 7 })
      ],
      23
    );
    render(SyncHistoryDialog, { knowledge, open: true });

    await expect.element(page.getByText(m.success(), { exact: true })).toBeVisible();
    await expect.element(page.getByText(m.error(), { exact: true })).toBeVisible();
    await expect.element(page.getByText("Delta token reset")).toBeVisible();
    await expect.element(page.getByText(m.page_statistics())).toBeVisible();
    await expect.element(page.getByText(m.page_x_of_y({ x: 1, y: 3 }))).toBeVisible();
    // Only the successful sync on this page counts towards the page totals.
    const filesRow = page.getByText(`${m.files_synced()}:`).element().parentElement;
    expect(filesRow?.textContent).toContain("2");
    expect(filesRow?.textContent).not.toContain("9");
  });

  it("reports a failed load in the UI language", async () => {
    // Rejecting after a macrotask, like a real request: a rejection in the same
    // microtask flush as the first expect.element poll is attributed to the test.
    getSyncLogs.mockImplementation(async () => {
      await new Promise((resolve) => setTimeout(resolve, 5));
      throw new Error("boom");
    });
    render(SyncHistoryDialog, { knowledge, open: true });

    await expect
      .element(page.getByRole("alert"))
      .toHaveTextContent(`${m.sync_history_load_failed()}: ${m.request_failed()}`);
  });
});
