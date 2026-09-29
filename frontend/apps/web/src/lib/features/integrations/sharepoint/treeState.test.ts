import { describe, expect, it } from "vitest";
import {
  createSharePointTreeNode,
  hasSelectedSharePointDescendant,
  isSharePointDescendantPath
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
