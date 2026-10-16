import type { IntegrationKnowledge } from "@eneo/eneo-js";
import { page, userEvent } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import "../../../../../../../app.css";
import { m } from "$lib/paraglide/messages";
import { expectNoAxeViolations } from "$lib/test/axe";
import type {
  IntegrationDocument,
  IntegrationDocumentsPage,
  IntegrationSkippedDocuments
} from "$lib/features/integrations/integrationDocuments";

type CompletionEvent = { timestamp: number; jobId: string } | null;

// Hoisted mocks cannot reach imports, so the store is a hand-rolled writable.
const api = vi.hoisted(() => {
  let value: CompletionEvent = null;
  const subscribers = new Set<(event: CompletionEvent) => void>();
  return {
    listDocuments: vi.fn(),
    listSkippedDocuments: vi.fn(),
    getInfoBlob: vi.fn(),
    jobCompletionEvents: {
      subscribe(run: (event: CompletionEvent) => void) {
        subscribers.add(run);
        run(value);
        return () => subscribers.delete(run);
      },
      set(next: CompletionEvent) {
        value = next;
        subscribers.forEach((run) => run(value));
      }
    }
  };
});

vi.mock("$lib/core/Eneo", () => ({
  getEneo: () => ({
    integrations: {
      knowledge: {
        listDocuments: api.listDocuments,
        listSkippedDocuments: api.listSkippedDocuments
      }
    },
    infoBlobs: { get: api.getInfoBlob }
  })
}));
vi.mock("$lib/features/jobs/JobManager", () => ({
  jobCompletionEvents: api.jobCompletionEvents,
  // The import dialogs behind the integration data need a job manager.
  getJobManager: () => ({ startFastUpdatePolling: vi.fn() })
}));

import IntegrationDocumentsView from "./IntegrationDocumentsView.svelte";

type Metadata = NonNullable<IntegrationKnowledge["metadata"]>;

function knowledge(metadata: Partial<Metadata> = {}): IntegrationKnowledge {
  return {
    id: "ik-1",
    name: "Protokoll",
    integration_type: "sharepoint",
    folder_path: "/Shared Documents/Protokoll",
    space_id: "space-1",
    url: "https://contoso.sharepoint.com/sites/ks/Shared%20Documents/Protokoll",
    metadata: {
      size: 0,
      last_sync_status: "success",
      document_count: 312,
      last_synced_at: new Date().toISOString(),
      ...metadata
    }
  } as IntegrationKnowledge;
}

function doc(index: number, overrides: Partial<IntegrationDocument> = {}): IntegrationDocument {
  return {
    id: `doc-${index}`,
    title: `Protokoll KS 2026-${String(index).padStart(2, "0")}.pdf`,
    relative_path: index % 2 === 0 ? "Bilagor/2026" : "",
    url: `https://contoso.sharepoint.com/sites/ks/KS-${index}.pdf`,
    size: 1024 * index,
    updated_at: "2026-10-13T08:00:00Z",
    source_metadata: [
      { name: "DocType", label: "Dokumenttyp", value: "Protokoll", kind: "choice" }
    ],
    ...overrides
  };
}

function pageOf(
  items: IntegrationDocument[],
  offset = 0,
  total = items.length
): IntegrationDocumentsPage {
  return { items, total_count: total, limit: 50, offset, total_size: 123456 };
}

const emptySkipped: IntegrationSkippedDocuments = {
  items: [],
  total: 0,
  truncated: false,
  synced_at: "2026-10-13T08:00:00Z"
};

function show(props: Partial<Parameters<typeof render<typeof IntegrationDocumentsView>>[1]> = {}) {
  return render(IntegrationDocumentsView, {
    knowledge: knowledge(),
    space: { id: "space-1" },
    initialDocuments: pageOf([doc(1), doc(2)]),
    initialSkipped: emptySkipped,
    ...props
  });
}

function lastDocumentsCall() {
  return api.listDocuments.mock.calls.at(-1)?.[0];
}

describe("IntegrationDocumentsView", () => {
  beforeEach(() => {
    api.listDocuments.mockReset();
    api.listSkippedDocuments.mockReset();
    api.getInfoBlob.mockReset();
    api.jobCompletionEvents.set(null);
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders the folder path, a row per document and opens the preview from the title", async () => {
    api.getInfoBlob.mockResolvedValue({
      id: "doc-2",
      text: "Extracted text",
      original_available: false
    });
    show();

    await expect.element(page.getByText("/Shared Documents/Protokoll")).toBeVisible();
    const table = page.getByRole("table", {
      name: m.integration_documents_table_label({ name: "Protokoll" })
    });
    await expect.element(table).toBeVisible();
    expect(table.getByRole("row").elements()).toHaveLength(3);
    await expect.element(page.getByText("Bilagor/2026")).toBeVisible();
    await expect.element(page.getByText("Dokumenttyp").first()).toBeVisible();
    const external = page.getByRole("link", { name: m.open_in_sharepoint() }).first();
    await expect.element(external).toHaveAttribute("target", "_blank");
    await expectNoAxeViolations();

    await page.getByRole("button", { name: "Protokoll KS 2026-02.pdf" }).click();
    await expect.element(page.getByRole("dialog")).toBeVisible();
    await expect.element(page.getByText("Extracted text")).toBeVisible();
    expect(api.getInfoBlob).toHaveBeenCalledWith(expect.objectContaining({ id: "doc-2" }));
  });

  it("searches on the server after the input settles", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    api.listDocuments.mockResolvedValue(pageOf([doc(7)]));
    show();

    const input = page.getByRole("searchbox", { name: m.integration_documents_search_label() });
    await userEvent.fill(input, "bil");
    expect(api.listDocuments).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(300);

    expect(api.listDocuments).toHaveBeenCalledTimes(1);
    expect(lastDocumentsCall()).toMatchObject({
      knowledge: expect.objectContaining({ id: "ik-1" }),
      space: { id: "space-1" },
      q: "bil",
      sort: "path",
      order: "asc",
      limit: 50,
      offset: 0
    });
    await expect.element(page.getByText("Protokoll KS 2026-07.pdf")).toBeVisible();
  });

  it("shows no results for a search that matches nothing", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    api.listDocuments.mockResolvedValue(pageOf([]));
    show();
    await userEvent.fill(
      page.getByRole("searchbox", { name: m.integration_documents_search_label() }),
      "zzz"
    );
    await vi.advanceTimersByTimeAsync(300);
    await expect.element(page.getByText(m.no_results_found())).toBeVisible();
  });

  it("toggles the sort column and order through the API and announces it", async () => {
    api.listDocuments.mockResolvedValue(pageOf([doc(1)]));
    show();

    const sortBySize = page.getByRole("button", { name: m.size() });
    const headerSort = () => sortBySize.element().closest("th")?.getAttribute("aria-sort");
    expect(headerSort()).toBe("none");

    await sortBySize.click();
    expect(lastDocumentsCall()).toMatchObject({ sort: "size", order: "asc", offset: 0 });
    await expect.poll(headerSort).toBe("ascending");

    await sortBySize.click();
    expect(lastDocumentsCall()).toMatchObject({ sort: "size", order: "desc" });
    await expect.poll(headerSort).toBe("descending");
  });

  it("paginates with a range label and prev/next buttons", async () => {
    const firstPage = pageOf(
      Array.from({ length: 50 }, (_, index) => doc(index + 1)),
      0,
      312
    );
    const secondPage = pageOf(
      Array.from({ length: 50 }, (_, index) => doc(index + 51)),
      50,
      312
    );
    api.listDocuments.mockResolvedValue(secondPage);
    show({ initialDocuments: firstPage });

    await expect
      .element(
        page.getByText(m.integration_documents_showing_range({ from: 1, to: 50, total: 312 }))
      )
      .toBeVisible();
    await expect.element(page.getByRole("button", { name: m.previous() })).toBeDisabled();

    await page.getByRole("button", { name: m.next() }).click();
    expect(lastDocumentsCall()).toMatchObject({ offset: 50, limit: 50 });
    await expect
      .element(
        page.getByText(m.integration_documents_showing_range({ from: 51, to: 100, total: 312 }))
      )
      .toBeVisible();
    await expect.element(page.getByRole("button", { name: m.previous() })).toBeEnabled();
  });

  it("groups the skipped files by translated reason and notes the ones the capped list leaves out", async () => {
    show({
      initialSkipped: {
        items: [
          { file: "scan1.pdf", reason: "No text layer (scanned document; OCR is not supported)" },
          { file: "a.xyz", reason: "Unsupported format" },
          { file: "scan2.pdf", reason: "No text layer (scanned document; OCR is not supported)" },
          { file: "b.pdf", reason: "Error: Incomplete download of 'b.pdf' (1 of 2 bytes)" },
          { file: "c.pdf", reason: "Error: Incomplete download of 'c.pdf' (3 of 4 bytes)" }
        ],
        total: 17,
        truncated: true,
        synced_at: "2026-10-13T08:00:00Z"
      }
    });

    const skippedTab = page.getByRole("tab", {
      name: m.integration_documents_skipped_tab_count({ count: 17 })
    });
    await skippedTab.click();

    for (const [reason, count] of [
      [m.skip_reason_no_text_layer(), 2],
      [m.skip_reason_incomplete_download(), 2],
      ["Unsupported format", 1]
    ] as const) {
      await expect
        .element(
          page.getByRole("heading", {
            name: m.integration_skipped_group_heading({ reason, count })
          })
        )
        .toBeVisible();
    }
    await expect.element(page.getByText("scan2.pdf")).toBeVisible();
    await expect.element(page.getByText(m.skipped_and_n_more({ count: 12 }))).toBeVisible();
    await expectNoAxeViolations();
  });

  it("follows the tab the navigation asks for", async () => {
    const { rerender } = show();
    await expect
      .element(page.getByRole("tab", { name: m.documents() }))
      .toHaveAttribute("aria-selected", "true");

    await rerender({ initialTab: "skipped" });

    await expect
      .element(
        page.getByRole("tab", { name: m.integration_documents_skipped_tab_count({ count: 0 }) })
      )
      .toHaveAttribute("aria-selected", "true");
  });

  it("falls back to the last page when the requested one is past the end", async () => {
    const firstPage = pageOf(
      Array.from({ length: 50 }, (_, index) => doc(index + 1)),
      0,
      60
    );
    // Documents were deleted between the two requests: 60 became 40.
    api.listDocuments
      .mockResolvedValueOnce(pageOf([], 50, 40))
      .mockResolvedValueOnce(pageOf([doc(40)], 0, 40));
    show({ initialDocuments: firstPage });

    await page.getByRole("button", { name: m.next() }).click();

    await expect.element(page.getByText("Protokoll KS 2026-40.pdf")).toBeVisible();
    expect(api.listDocuments.mock.calls.map(([call]) => call.offset)).toEqual([50, 0]);
    await expect
      .element(page.getByText(m.integration_documents_showing_range({ from: 1, to: 1, total: 40 })))
      .toBeVisible();
  });

  it("says so when the latest sync skipped nothing", async () => {
    show();
    await page
      .getByRole("tab", { name: m.integration_documents_skipped_tab_count({ count: 0 }) })
      .click();
    await expect.element(page.getByText(m.integration_skipped_empty())).toBeVisible();
  });

  it("explains an item that never synced", async () => {
    show({
      knowledge: knowledge({ last_sync_status: "never", document_count: 0, last_synced_at: null }),
      initialDocuments: pageOf([]),
      initialSkipped: null
    });
    await expect
      .element(page.getByText(m.integration_documents_empty_never_synced()))
      .toBeVisible();
    await expect
      .element(page.getByText(m.integration_sync_status_never(), { exact: true }))
      .toBeVisible();
  });

  it("points a synced but empty item at the skipped tab", async () => {
    show({
      knowledge: knowledge({ document_count: 0 }),
      initialDocuments: pageOf([]),
      initialSkipped: {
        items: [{ file: "scan.pdf", reason: "No text layer" }],
        total: 1,
        truncated: false,
        synced_at: null
      }
    });
    await expect.element(page.getByText(m.integration_documents_empty_synced())).toBeVisible();
    await page.getByRole("button", { name: m.integration_documents_empty_see_skipped() }).click();
    await expect.element(page.getByText("scan.pdf")).toBeVisible();
  });

  it("reloads the documents and skipped files when a job completes", async () => {
    api.listDocuments.mockResolvedValue(pageOf([doc(9)]));
    api.listSkippedDocuments.mockResolvedValue(emptySkipped);
    show({ initialDocuments: pageOf([]), initialSkipped: null });

    api.jobCompletionEvents.set({ timestamp: Date.now(), jobId: "any" });

    await expect.element(page.getByText("Protokoll KS 2026-09.pdf")).toBeVisible();
    expect(api.listSkippedDocuments).toHaveBeenCalledTimes(1);
  });
});
