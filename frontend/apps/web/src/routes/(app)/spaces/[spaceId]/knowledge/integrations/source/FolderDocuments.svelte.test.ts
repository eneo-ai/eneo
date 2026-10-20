import type { IntegrationKnowledge } from "@eneo/eneo-js";
import { page, userEvent } from "vitest/browser";
import { render } from "vitest-browser-svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import "../../../../../../../app.css";
import { m } from "$lib/paraglide/messages";
import { expectNoAxeViolations } from "$lib/test/axe";
import type {
  IntegrationDocument,
  IntegrationDocumentsPage
} from "$lib/features/integrations/integrationDocuments";

const api = vi.hoisted(() => ({
  listDocuments: vi.fn(),
  getInfoBlob: vi.fn(),
  addJob: vi.fn(),
  startFastUpdatePolling: vi.fn()
}));

vi.mock("$lib/core/Eneo", () => ({
  getEneo: () => ({
    integrations: { knowledge: { listDocuments: api.listDocuments } },
    infoBlobs: { get: api.getInfoBlob }
  })
}));
// The folder's actions menu reads the current space.
vi.mock("$lib/features/spaces/SpacesManager", async () => {
  const { writable } = await import("svelte/store");
  return {
    getSpacesManager: () => ({
      refreshCurrentSpace: vi.fn(),
      state: { currentSpace: writable({ id: "space-1", routeId: "space-1" }) }
    })
  };
});

vi.mock("$lib/features/jobs/JobManager", () => ({
  getJobManager: () => ({
    addJob: api.addJob,
    startFastUpdatePolling: api.startFastUpdatePolling
  })
}));

import FolderDocuments from "./FolderDocuments.svelte";

type Metadata = NonNullable<IntegrationKnowledge["metadata"]>;

function knowledge(metadata: Partial<Metadata> = {}): IntegrationKnowledge {
  return {
    id: "ik-1",
    name: "Protokoll",
    integration_type: "sharepoint",
    folder_path: "/Shared Documents/Protokoll",
    space_id: "space-1",
    permissions: ["edit", "delete"],
    url: "https://contoso.sharepoint.com/sites/ks/Shared%20Documents/Protokoll",
    metadata: {
      size: 0,
      last_sync_status: "success",
      document_count: 312,
      last_synced_at: "2026-10-13T08:00:00Z",
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

function show(props: Partial<Parameters<typeof render<typeof FolderDocuments>>[1]> = {}) {
  return render(FolderDocuments, {
    knowledge: knowledge(),
    space: { id: "space-1" },
    progress: {},
    skipped: { items: [], total: 0, truncated: false, synced_at: null },
    problemsHref: "/spaces/space-1/knowledge/integrations/wrapper/w1?tab=problems",
    ...props
  });
}

function lastDocumentsCall() {
  return api.listDocuments.mock.calls.at(-1)?.[0];
}

describe("FolderDocuments", () => {
  beforeEach(() => {
    api.listDocuments.mockReset();
    api.getInfoBlob.mockReset();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("loads the folder's documents and opens the preview from the title", async () => {
    api.listDocuments.mockResolvedValue(pageOf([doc(1), doc(2)]));
    api.getInfoBlob.mockResolvedValue({
      id: "doc-2",
      text: "Extracted text",
      original_available: false
    });
    show();

    await expect.element(page.getByRole("heading", { name: "Protokoll" })).toBeVisible();
    await expect.element(page.getByText("/Shared Documents/Protokoll")).toBeVisible();
    await expect
      .element(page.getByText(m.integration_source_state_ok(), { exact: true }))
      .toBeVisible();
    const table = page.getByRole("table", {
      name: m.integration_documents_table_label({ name: "Protokoll" })
    });
    await expect.element(table).toBeVisible();
    expect(table.getByRole("row").elements()).toHaveLength(3);
    expect(lastDocumentsCall()).toMatchObject({
      knowledge: expect.objectContaining({ id: "ik-1" }),
      space: { id: "space-1" },
      q: "",
      sort: "path",
      order: "asc",
      limit: 50,
      offset: 0
    });
    // Properties differ per library, so they live on the document's card, not in a column.
    expect(page.getByText("Dokumenttyp").elements()).toHaveLength(0);
    await expect
      .element(table.getByText(m.integration_source_doc_searchable()).first())
      .toBeVisible();
    await expectNoAxeViolations();

    await page.getByRole("button", { name: "Protokoll KS 2026-02.pdf" }).click();
    await expect.element(page.getByRole("dialog")).toBeVisible();
    await expect.element(page.getByText("Extracted text")).toBeVisible();
    await expect.element(page.getByRole("dialog").getByText("Dokumenttyp")).toBeVisible();
  });

  it("searches on the server after the input settles", async () => {
    api.listDocuments.mockResolvedValue(pageOf([doc(1)]));
    show();
    await expect.element(page.getByText("Protokoll KS 2026-01.pdf")).toBeVisible();
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    api.listDocuments.mockResolvedValue(pageOf([]));

    await userEvent.fill(
      page.getByRole("searchbox", { name: m.integration_documents_search_label() }),
      "zzz"
    );
    expect(api.listDocuments).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(300);

    expect(lastDocumentsCall()).toMatchObject({ q: "zzz", offset: 0 });
    // Shown, and said once in the status line.
    await expect.poll(() => page.getByText(m.no_results_found()).elements().length).toBe(2);
    await expect
      .element(page.getByRole("status").getByText(m.no_results_found()))
      .toBeInTheDocument();
  });

  it("toggles the sort column and order through the API and announces it", async () => {
    api.listDocuments.mockResolvedValue(pageOf([doc(1)]));
    show();

    const sortBySize = page.getByRole("button", { name: m.size() });
    await expect.element(sortBySize).toBeVisible();
    const headerSort = () => sortBySize.element().closest("th")?.getAttribute("aria-sort");
    expect(headerSort()).toBe("none");

    await sortBySize.click();
    expect(lastDocumentsCall()).toMatchObject({ sort: "size", order: "asc", offset: 0 });
    await expect.poll(headerSort).toBe("ascending");

    await sortBySize.click();
    expect(lastDocumentsCall()).toMatchObject({ sort: "size", order: "desc" });
    await expect.poll(headerSort).toBe("descending");
    await expect
      .element(
        page
          .getByRole("status")
          .getByText(m.integration_documents_showing_range({ from: 1, to: 1, total: 1 }))
      )
      .toBeInTheDocument();
  });

  it("speaks a sort's result again when it reads the same as the last one", async () => {
    api.listDocuments.mockResolvedValue(pageOf([doc(1)]));
    show();
    const sortBySize = page.getByRole("button", { name: m.size() });
    await expect.element(sortBySize).toBeVisible();
    const status = () =>
      [...document.querySelectorAll('[role="status"]')].map((node) => node.textContent?.trim());
    const range = m.integration_documents_showing_range({ from: 1, to: 1, total: 1 });

    await sortBySize.click();
    await expect.poll(status).toContain(range);
    const region = [...document.querySelectorAll('[role="status"]')].find(
      (node) => node.textContent?.trim() === range
    )!;
    const changes: string[] = [];
    const observer = new MutationObserver(() => changes.push(region.textContent?.trim() ?? ""));
    observer.observe(region, { childList: true, characterData: true, subtree: true });
    await sortBySize.click();
    await expect.poll(() => changes.at(-1)).toBe(range);
    observer.disconnect();
    expect(changes).toContain("");
  });

  it("pages forward and falls back to the last page when documents disappeared meanwhile", async () => {
    api.listDocuments
      .mockResolvedValueOnce(
        pageOf(
          Array.from({ length: 50 }, (_, index) => doc(index + 1)),
          0,
          60
        )
      )
      // Documents were deleted between the two requests: 60 became 40.
      .mockResolvedValueOnce(pageOf([], 50, 40))
      .mockResolvedValueOnce(pageOf([doc(40)], 0, 40));
    show();

    await expect
      .element(
        page.getByText(m.integration_documents_showing_range({ from: 1, to: 50, total: 60 }))
      )
      .toBeVisible();
    await expect.element(page.getByRole("button", { name: m.previous() })).toBeDisabled();
    await page.getByRole("button", { name: m.next() }).click();

    await expect.element(page.getByText("Protokoll KS 2026-40.pdf")).toBeVisible();
    expect(api.listDocuments.mock.calls.map(([call]) => call.offset)).toEqual([0, 50, 0]);
  });

  it("lists the files the latest sync could not read, with the reason", async () => {
    api.listDocuments.mockResolvedValue(pageOf([doc(1)]));
    show({
      skipped: {
        items: [
          {
            file: "scan.pdf",
            reason: "No text layer (scanned document; OCR is not supported)",
            code: "no_text_layer",
            params: {},
            retry: false
          }
        ],
        total: 3,
        truncated: true,
        synced_at: null
      }
    });

    await page
      .getByRole("button", { name: m.integration_source_view_unreadable({ count: 3 }) })
      .click();

    const table = page.getByRole("table", {
      name: m.integration_source_skipped_table_label({ name: "Protokoll" })
    });
    await expect.element(table.getByText("scan.pdf")).toBeVisible();
    await expect.element(table.getByText(m.skip_reason_no_text_layer())).toBeVisible();
    await expect.element(page.getByText(m.skipped_and_n_more({ count: 2 }))).toBeVisible();
    await expect
      .element(page.getByRole("link", { name: m.integration_source_show_in_problems() }))
      .toHaveAttribute("href", "/spaces/space-1/knowledge/integrations/wrapper/w1?tab=problems");
  });

  it("shows the file being read and the latest outcomes while the folder syncs", async () => {
    api.listDocuments.mockResolvedValue(pageOf([doc(1)]));
    show({
      progress: {
        "ik-1": {
          integration_knowledge_id: "ik-1",
          sync_type: "full",
          phase: "processing",
          started_at: "2026-10-15T08:00:00Z",
          updated_at: "2026-10-15T08:01:00Z",
          total: 20,
          done: 3,
          indexed: 2,
          unchanged: 0,
          skipped: 1,
          deleted: 0,
          current: "Protokoll KS 2026-04.pdf",
          recent: [
            {
              name: "Bild.png",
              outcome: "skipped",
              reason: "Unsupported file type (image)",
              code: "unsupported_type",
              params: { label: "image" }
            },
            { name: "Protokoll KS 2026-03.pdf", outcome: "indexed" }
          ]
        }
      }
    });

    const feed = page.getByRole("region", { name: m.integration_live_heading() });
    await expect.element(feed.getByText("Protokoll KS 2026-04.pdf")).toBeVisible();
    await expect.element(feed.getByText(m.integration_live_reading())).toBeVisible();
    await expect.element(feed.getByText(m.integration_live_skipped())).toBeVisible();
    await expect.element(feed.getByText(m.integration_live_indexed())).toBeVisible();
    // The reason is on screen, not only in a tooltip.
    await expect
      .element(
        feed.getByText(m.skip_reason_unsupported_type({ label: m.skip_reason_type_image() }))
      )
      .toBeVisible();
    await expectNoAxeViolations();
  });

  it("explains a folder that never synced", async () => {
    api.listDocuments.mockResolvedValue(pageOf([]));
    show({
      knowledge: knowledge({ last_sync_status: "never", document_count: 0, last_synced_at: null })
    });
    await expect
      .element(page.getByText(m.integration_documents_empty_never_synced()))
      .toBeVisible();
    await expect
      .element(page.getByText(m.integration_source_state_never(), { exact: true }))
      .toBeVisible();
  });

  it("reloads when a sync of the folder finishes", async () => {
    api.listDocuments.mockResolvedValueOnce(pageOf([])).mockResolvedValue(pageOf([doc(9)]));
    const { rerender } = show();
    await expect.element(page.getByText(m.integration_documents_empty_synced())).toBeVisible();

    await rerender({
      knowledge: knowledge({ last_synced_at: "2026-10-14T09:00:00Z", document_count: 313 })
    });

    await expect.element(page.getByText("Protokoll KS 2026-09.pdf")).toBeVisible();
    expect(api.listDocuments).toHaveBeenCalledTimes(2);
  });

  it("leaves the heading and actions to the page when the source is this one folder", async () => {
    api.listDocuments.mockResolvedValue(pageOf([doc(1)]));
    show({ showHeader: false });

    await expect.element(page.getByText("Protokoll KS 2026-01.pdf")).toBeVisible();
    expect(page.getByRole("heading", { name: "Protokoll", exact: true }).elements()).toHaveLength(
      0
    );
    expect(page.getByRole("button", { name: m.actions() }).elements()).toHaveLength(0);
  });
});
