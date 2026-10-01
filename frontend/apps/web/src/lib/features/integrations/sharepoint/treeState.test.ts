import { describe, expect, it } from "vitest";
import {
  countSharePointTreeMatches,
  createSharePointTreeNode,
  hasSelectedSharePointDescendant,
  isSharePointDescendantPath,
  normalizeSharePointTreeQuery,
  sharePointTreeHasMatchingDescendant,
  sharePointTreeItemMatches,
  sharePointTreeNodeVisible,
  type SharePointTreeItem
} from "./treeState";

describe("SharePoint tree state", () => {
  it("creates folders as lazily loaded collapsed nodes", () => {
    const node = createSharePointTreeNode({
      id: "policies",
      name: "Policies",
      type: "folder",
      path: "/Governance/Policies",
      has_children: true
    });

    expect(node).toMatchObject({
      children: null,
      expanded: false,
      loading: false,
      loadError: false
    });
  });

  it("detects nested selections without confusing similarly prefixed folders", () => {
    expect(
      hasSelectedSharePointDescendant(
        ["/Projects/Aurora/Plan.docx", "/Project archive/Old.pdf"],
        "/Projects"
      )
    ).toBe(true);
    expect(isSharePointDescendantPath("/Project archive/Old.pdf", "/Project")).toBe(false);
  });

  it("treats every non-root path as a descendant of the selected site", () => {
    expect(isSharePointDescendantPath("/Policies/Security.pdf", "/")).toBe(true);
    expect(isSharePointDescendantPath("/", "/")).toBe(false);
  });
});

describe("SharePoint tree search", () => {
  const file = (name: string, source_metadata?: SharePointTreeItem["source_metadata"]) =>
    createSharePointTreeNode({
      id: name,
      name,
      type: "file",
      path: `/${name}`,
      has_children: false,
      source_metadata
    });

  it("matches names and document properties, case-insensitively", () => {
    const rutin = file("Rutin larm.docx", [
      { name: "Dokumenttyp", label: "Dokumenttyp", value: "Rutin", kind: "choice" },
      {
        name: "Verksamhet",
        label: "Verksamhet",
        value: ["Äldreomsorg", "Hemtjänst"],
        kind: "choice"
      }
    ]);

    expect(sharePointTreeItemMatches(rutin, normalizeSharePointTreeQuery("  LARM "))).toBe(true);
    expect(sharePointTreeItemMatches(rutin, "hemtjänst")).toBe(true);
    expect(sharePointTreeItemMatches(rutin, "verksamhet")).toBe(true);
    expect(sharePointTreeItemMatches(rutin, "policy")).toBe(false);
    expect(sharePointTreeItemMatches(rutin, "")).toBe(true);
  });

  it("keeps a folder visible through a loaded descendant and opens it", () => {
    const folder = createSharePointTreeNode({
      id: "f",
      name: "Rutiner",
      type: "folder",
      path: "/Rutiner",
      has_children: true
    });
    folder.children = [file("Larm.docx"), file("Brand.docx")];

    expect(sharePointTreeNodeVisible(folder, "brand")).toBe(true);
    expect(sharePointTreeHasMatchingDescendant(folder, "brand")).toBe(true);
    expect(sharePointTreeNodeVisible(folder, "lön")).toBe(false);
    expect(sharePointTreeHasMatchingDescendant(folder, "")).toBe(false);
  });

  it("cannot see into folders that were never opened", () => {
    const unopened = createSharePointTreeNode({
      id: "u",
      name: "Arkiv",
      type: "folder",
      path: "/Arkiv",
      has_children: true
    });

    expect(sharePointTreeNodeVisible(unopened, "arkiv")).toBe(true);
    expect(sharePointTreeNodeVisible(unopened, "larm")).toBe(false);
  });

  it("counts matching loaded items across levels", () => {
    const folder = createSharePointTreeNode({
      id: "f",
      name: "Larmrutiner",
      type: "folder",
      path: "/Larmrutiner",
      has_children: true
    });
    folder.children = [file("Larm.docx"), file("Brand.docx")];

    expect(countSharePointTreeMatches([folder, file("Larmlista.xlsx")], "larm")).toBe(3);
    expect(countSharePointTreeMatches([folder], "")).toBe(0);
  });
});
