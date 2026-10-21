import { describe, expect, it } from "vitest";
import { buildSharePointSelectionKey } from "./selectionKey";
import {
  createSharePointTreeNode,
  flattenVisibleSharePointTree,
  hasSelectedSharePointDescendant,
  isSharePointDescendantPath,
  isSharePointItemCovered,
  normalizeSharePointTreeQuery,
  resolveSharePointTreeKey,
  type SharePointTreeNode
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

describe("SharePoint tree keyboard pattern", () => {
  const file = (id: string, path: string) =>
    createSharePointTreeNode({ id, name: id, type: "file", path, has_children: false });
  const folder = (
    id: string,
    path: string,
    children: SharePointTreeNode[] | null
  ): SharePointTreeNode => ({
    ...createSharePointTreeNode({ id, name: id, type: "folder", path, has_children: true }),
    children,
    expanded: children !== null
  });
  const policies = folder("policies", "/Policies", [file("p1", "/Policies/p1.docx")]);
  const archive = folder("archive", "/Archive", null);
  const roots = [policies, archive, file("readme", "/readme.md")];
  const keys = roots.map(buildSharePointSelectionKey);
  const rows = flattenVisibleSharePointTree(roots, new Set([keys[0]]), false);

  it("lists expanded children in document order and marks rows covered by a selected parent", () => {
    expect(rows.map((row) => row.node.id)).toEqual(["policies", "p1", "archive", "readme"]);
    expect(rows[1]).toMatchObject({ parentKey: keys[0], parentSelected: true });
    expect(rows[2]).toMatchObject({ parentKey: null, parentSelected: false });
  });

  it.each([
    ["ArrowDown", keys[0], { type: "focus", key: rows[1].key }],
    ["ArrowUp", keys[0], null],
    ["ArrowUp", keys[2], { type: "focus", key: keys[1] }],
    ["Home", keys[2], { type: "focus", key: keys[0] }],
    ["End", keys[0], { type: "focus", key: keys[2] }],
    ["ArrowRight", keys[0], { type: "focus", key: rows[1].key }],
    ["ArrowRight", keys[1], { type: "expand", node: archive }],
    ["ArrowRight", keys[2], null],
    ["ArrowLeft", keys[0], { type: "collapse", node: policies }],
    ["ArrowLeft", rows[1].key, { type: "focus", key: keys[0] }],
    ["ArrowLeft", keys[2], null],
    [" ", keys[2], { type: "toggleSelect", node: roots[2] }],
    [" ", rows[1].key, null],
    ["Enter", keys[1], { type: "expand", node: archive }],
    ["Enter", keys[0], { type: "collapse", node: policies }],
    ["Enter", keys[2], null],
    ["a", keys[0], null]
  ] as const)("%s on %s", (key, currentKey, expected) => {
    expect(resolveSharePointTreeKey(rows, currentKey, key)).toEqual(expected);
  });
});
