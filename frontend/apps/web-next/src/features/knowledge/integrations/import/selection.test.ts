import { describe, expect, it } from "vitest";
import {
  buildBatchItems,
  buildSelectionKey,
  dedupeNestedSelection,
  normalizeSharePointPath,
  type SelectedImportItem,
  type SelectedTreeItem
} from "./selection";

function makeEntry(overrides: Partial<SelectedTreeItem>, importName?: string): SelectedImportItem {
  const item: SelectedTreeItem = {
    id: "id-1",
    name: "Item",
    type: "file",
    path: "/item",
    ...overrides
  };
  return {
    selectionKey: buildSelectionKey(item),
    item,
    importName: importName ?? item.name
  };
}

describe("normalizeSharePointPath", () => {
  it("adds a leading slash, collapses duplicates and strips the trailing slash", () => {
    expect(normalizeSharePointPath("docs//reports/")).toBe("/docs/reports");
    expect(normalizeSharePointPath("/")).toBe("/");
    expect(normalizeSharePointPath(null)).toBe("/");
  });
});

describe("buildSelectionKey", () => {
  it("uses a fixed key for the site root", () => {
    expect(buildSelectionKey({ type: "site_root", id: "x", path: "/y" })).toBe("site_root:root:/");
  });

  it("falls back to the path when the id is blank", () => {
    expect(buildSelectionKey({ type: "folder", id: " ", path: "/docs", name: "Docs" })).toBe(
      "folder:/docs:/docs:Docs"
    );
  });
});

describe("dedupeNestedSelection", () => {
  it("excludes children covered by a selected ancestor folder", () => {
    const parent = makeEntry({ id: "p", name: "Docs", type: "folder", path: "/docs" });
    const child = makeEntry({ id: "c", name: "Report", type: "file", path: "/docs/report.pdf" });
    const sibling = makeEntry({ id: "s", name: "Other", type: "file", path: "/other.pdf" });

    const result = dedupeNestedSelection([child, parent, sibling]);
    expect(result.effectiveEntries.map((entry) => entry.item.id)).toEqual(["p", "s"]);
    expect(result.excludedKeys.has(child.selectionKey)).toBe(true);
  });

  it("lets the site root cover everything else", () => {
    const root = makeEntry({ id: "", name: "Site", type: "site_root", path: "/" });
    const folder = makeEntry({ id: "f", name: "Docs", type: "folder", path: "/docs" });

    const result = dedupeNestedSelection([folder, root]);
    expect(result.effectiveEntries).toHaveLength(1);
    expect(result.effectiveEntries[0]?.item.type).toBe("site_root");
  });

  it("does not let files block descendants", () => {
    const file = makeEntry({ id: "a", name: "docs", type: "file", path: "/docs" });
    const nested = makeEntry({ id: "b", name: "inner", type: "file", path: "/docs/inner" });

    const result = dedupeNestedSelection([file, nested]);
    expect(result.effectiveEntries).toHaveLength(2);
  });
});

describe("buildBatchItems", () => {
  const site = { key: "site-key", name: "Site", url: "https://sp/site", type: "site" };

  it("maps a site_root selection to the site itself", () => {
    const root = makeEntry({ id: "", name: "Site", type: "site_root", path: "/" }, "My import");
    expect(buildBatchItems(site, [root])).toEqual([
      {
        key: "site-key",
        name: "My import",
        url: "https://sp/site",
        selected_item_type: "site_root",
        resource_type: "site"
      }
    ]);
  });

  it("maps folder selections with their path and falls back to the item name", () => {
    const folder = makeEntry(
      { id: "f1", name: "Docs", type: "folder", path: "/docs", web_url: "https://sp/docs" },
      "   "
    );
    expect(buildBatchItems(site, [folder])).toEqual([
      {
        key: "site-key",
        name: "Docs",
        url: "https://sp/docs",
        folder_id: "f1",
        folder_path: "/docs",
        selected_item_type: "folder",
        resource_type: "site"
      }
    ]);
  });

  it("marks onedrive imports with the onedrive resource type", () => {
    const drive = { ...site, type: "onedrive" };
    const root = makeEntry({ id: "", name: "OneDrive", type: "site_root", path: "/" });
    expect(buildBatchItems(drive, [root])[0]?.resource_type).toBe("onedrive");
  });
});
