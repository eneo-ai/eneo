import { describe, expect, it } from "vitest";
import { buildSharePointSelectionKey } from "./selectionKey";
import {
  createSharePointTreeNode,
  hasSelectedSharePointDescendant,
  isSharePointDescendantPath,
  isSharePointItemCovered,
  normalizeSharePointTreeQuery,
  splitSharePointMatches
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

describe("splitSharePointMatches", () => {
  it("marks every case-insensitive occurrence in order", () => {
    expect(splitSharePointMatches("Larm – larmlista", "larm")).toEqual([
      { text: "Larm", match: true },
      { text: " – ", match: false },
      { text: "larm", match: true },
      { text: "lista", match: false }
    ]);
  });

  it("returns the text untouched without a query or a hit", () => {
    expect(splitSharePointMatches("Policy", "")).toEqual([{ text: "Policy", match: false }]);
    expect(splitSharePointMatches("Policy", "larm")).toEqual([{ text: "Policy", match: false }]);
  });
});

describe("selection coverage", () => {
  it("treats items under a selected folder or the site root as covered", () => {
    const item = createSharePointTreeNode({
      id: "Larm natt.docx",
      name: "Larm natt.docx",
      type: "file",
      path: "/Larmrutiner/Larm natt.docx",
      has_children: false
    });

    expect(isSharePointItemCovered(item, new Set(), [])).toBe(false);
    expect(isSharePointItemCovered(item, new Set(), ["/Larmrutiner"])).toBe(true);
    expect(isSharePointItemCovered(item, new Set(), ["/"])).toBe(true);
    expect(isSharePointItemCovered(item, new Set(), ["/Larm"])).toBe(false);
    expect(isSharePointItemCovered(item, new Set([buildSharePointSelectionKey(item)]), [])).toBe(
      true
    );
  });

  it("normalises a query by trimming and case-folding", () => {
    expect(normalizeSharePointTreeQuery("  LARM ")).toBe("larm");
    expect(normalizeSharePointTreeQuery("   ")).toBe("");
  });
});
