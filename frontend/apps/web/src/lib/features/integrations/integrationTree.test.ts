import type { IntegrationKnowledge } from "@eneo/eneo-js";
import { describe, expect, it } from "vitest";
import {
  buildIntegrationTree,
  filterIntegrationTree,
  flattenIntegrationTree,
  folderPathKey,
  type IntegrationTreeNode
} from "./integrationTree";

function item(
  name: string,
  folder_path: string | null | undefined,
  selected_item_type = "folder"
): IntegrationKnowledge {
  return { id: name, name, folder_path, selected_item_type } as IntegrationKnowledge;
}

function shape(nodes: IntegrationTreeNode[]): unknown {
  return nodes.map((node) => [node.item.name, shape(node.children)]);
}

describe("folderPathKey", () => {
  it.each([
    ["/Shared Documents/Protokoll/", "/shared documents/protokoll"],
    ["Shared Documents\\Bilagor", "/shared documents/bilagor"],
    ["", null],
    ["  /  ", null],
    [null, null],
    [undefined, null]
  ])("normalises %j", (input, expected) => {
    expect(folderPathKey(input)).toBe(expected);
  });
});

describe("buildIntegrationTree", () => {
  it("keeps items whose paths are not prefixes of each other as siblings, sorted by name", () => {
    const tree = buildIntegrationTree([
      item("Rutiner", "/Documents/Rutiner"),
      item("Protokoll", "/Documents/Protokoll"),
      item("Protokollbilagor", "/Documents/Protokollbilagor")
    ]);
    expect(shape(tree)).toEqual([
      ["Protokoll", []],
      ["Protokollbilagor", []],
      ["Rutiner", []]
    ]);
  });

  it("nests an item under the deepest item whose path is a strict prefix, in any input order", () => {
    const tree = buildIntegrationTree([
      item("2026", "/Documents/Protokoll/Bilagor/2026"),
      item("Protokoll", "/Documents/Protokoll"),
      item("KS-1.pdf", "/documents/protokoll/KS-1.pdf", "file"),
      item("Bilagor", "/Documents/Protokoll/Bilagor/")
    ]);
    expect(shape(tree)).toEqual([
      [
        "Protokoll",
        [
          ["Bilagor", [["2026", []]]],
          ["KS-1.pdf", []]
        ]
      ]
    ]);
  });

  it("puts whole-site imports first and never nests folders under them", () => {
    const tree = buildIntegrationTree([
      item("Protokoll", "/Documents/Protokoll"),
      item("Hela intranätet", undefined, "site_root"),
      item("Arkiv", null, "site_root")
    ]);
    expect(shape(tree)).toEqual([
      ["Arkiv", []],
      ["Hela intranätet", []],
      ["Protokoll", []]
    ]);
  });

  it("treats two imports of the same folder as siblings", () => {
    const tree = buildIntegrationTree([
      item("Protokoll", "/Documents/Protokoll"),
      item("Protokoll (igen)", "/Documents/Protokoll/")
    ]);
    expect(shape(tree)).toEqual([
      ["Protokoll", []],
      ["Protokoll (igen)", []]
    ]);
  });
});

describe("flattenIntegrationTree", () => {
  const tree = buildIntegrationTree([
    item("Protokoll", "/Documents/Protokoll"),
    item("Bilagor", "/Documents/Protokoll/Bilagor"),
    item("Rutiner", "/Documents/Rutiner")
  ]);

  it("lists expanded subtrees with their depth and hides collapsed ones", () => {
    const expandedRows = flattenIntegrationTree(tree, () => true);
    expect(expandedRows.map((row) => [row.item.name, row.depth, row.hasChildren])).toEqual([
      ["Protokoll", 0, true],
      ["Bilagor", 1, false],
      ["Rutiner", 0, false]
    ]);

    const collapsedRows = flattenIntegrationTree(tree, () => false);
    expect(collapsedRows.map((row) => row.item.name)).toEqual(["Protokoll", "Rutiner"]);
    expect(collapsedRows[0].expanded).toBe(false);
  });
});

describe("filterIntegrationTree", () => {
  it("keeps matching nodes and the ancestors of matching descendants", () => {
    const tree = buildIntegrationTree([
      item("Protokoll", "/Documents/Protokoll"),
      item("Bilagor", "/Documents/Protokoll/Bilagor"),
      item("Rutiner", "/Documents/Rutiner")
    ]);
    expect(shape(filterIntegrationTree(tree, "bil"))).toEqual([["Protokoll", [["Bilagor", []]]]]);
    expect(filterIntegrationTree(tree, "   ")).toBe(tree);
  });
});
