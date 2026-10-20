import { describe, expect, it } from "vitest";
import {
  DEFAULT_INTEGRATION_DOCUMENTS_QUERY,
  documentsPageRange,
  groupSkippedByReason,
  integrationDocumentsHref,
  lastPageOffset,
  skippedDocumentsNotListed,
  toggleDocumentsSort
} from "./integrationDocuments";

describe("groupSkippedByReason", () => {
  it("groups by trimmed reason, largest group first, ties by first appearance", () => {
    const groups = groupSkippedByReason([
      { file: "a.xyz", reason: "Unsupported format" },
      { file: "scan1.pdf", reason: "No text layer" },
      { file: "scan2.pdf", reason: "No text layer " },
      { file: "b.xyz", reason: "Unsupported format" },
      { file: "big.docx", reason: "Too large" }
    ]);
    expect(groups).toEqual([
      { reason: "Unsupported format", files: ["a.xyz", "b.xyz"] },
      { reason: "No text layer", files: ["scan1.pdf", "scan2.pdf"] },
      { reason: "Too large", files: ["big.docx"] }
    ]);
  });
});

describe("skippedDocumentsNotListed", () => {
  it.each([
    [{ items: [{ file: "a", reason: "r" }], total: 17, truncated: true, synced_at: null }, 16],
    [{ items: [{ file: "a", reason: "r" }], total: 17, truncated: false, synced_at: null }, 0],
    [{ items: [{ file: "a", reason: "r" }], total: 1, truncated: true, synced_at: null }, 0]
  ])("counts what the capped list leaves out", (skipped, expected) => {
    expect(skippedDocumentsNotListed(skipped)).toBe(expected);
  });
});

describe("documentsPageRange", () => {
  it("is 1-based and clamps the last page to the total", () => {
    const items = Array.from({ length: 12 }, (_, index) => ({ id: String(index) }));
    expect(documentsPageRange({ items, offset: 300, total_count: 312 })).toEqual({
      from: 301,
      to: 312,
      total: 312
    });
  });

  it("is 0–0 of 0 for an empty page", () => {
    expect(documentsPageRange({ items: [], offset: 0, total_count: 0 })).toEqual({
      from: 0,
      to: 0,
      total: 0
    });
  });
});

describe("toggleDocumentsSort", () => {
  it("sorts a new column ascending from the first page and flips the current column", () => {
    const byName = toggleDocumentsSort(
      { ...DEFAULT_INTEGRATION_DOCUMENTS_QUERY, offset: 100 },
      "name"
    );
    expect(byName).toMatchObject({ sort: "name", order: "asc", offset: 0 });
    expect(toggleDocumentsSort(byName, "name")).toMatchObject({ sort: "name", order: "desc" });
  });
});

describe("integrationDocumentsHref", () => {
  it("points at the item's page and optionally its skipped tab", () => {
    expect(integrationDocumentsHref("personal", "ik-1")).toBe(
      "/spaces/personal/knowledge/integrations/ik-1"
    );
    expect(integrationDocumentsHref("space-1", "ik-1", "skipped")).toBe(
      "/spaces/space-1/knowledge/integrations/ik-1?tab=skipped"
    );
  });
});

describe("lastPageOffset", () => {
  it.each([
    [0, 50, 0],
    [1, 50, 0],
    [50, 50, 0],
    [51, 50, 50],
    [312, 50, 300],
    [40, 0, 0]
  ])("total %i with limit %i starts its last page at %i", (total, limit, expected) => {
    expect(lastPageOffset({ total_count: total }, limit)).toBe(expected);
  });
});
