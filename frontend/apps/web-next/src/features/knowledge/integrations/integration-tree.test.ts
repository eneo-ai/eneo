import type { IntegrationKnowledge } from "../knowledge";
import { describe, expect, it } from "vitest";
import {
  buildIntegrationTree,
  filterIntegrationTree,
  flattenIntegrationTree,
  folderPathKey,
  type IntegrationTreeNode
} from "./integration-tree";

function item(
  name: string,
  folder_path: string | null | undefined,
  selected_item_type = "folder"
): IntegrationKnowledge {
  return { id: name, name, folder_path, selected_item_type } as IntegrationKnowledge;
}

const swedish = new Intl.Collator("sv").compare;

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
    const tree = buildIntegrationTree(
      [
        item("Rutiner", "/Documents/Rutiner"),
        item("Protokoll", "/Documents/Protokoll"),
        item("Protokollbilagor", "/Documents/Protokollbilagor")
      ],
      swedish
    );
    expect(shape(tree)).toEqual([
      ["Protokoll", []],
      ["Protokollbilagor", []],
      ["Rutiner", []]
    ]);
  });

  it("nests an item under the deepest item whose path is a strict prefix, in any input order", () => {
    const tree = buildIntegrationTree(
      [
        item("2026", "/Documents/Protokoll/Bilagor/2026"),
        item("Protokoll", "/Documents/Protokoll"),
        item("KS-1.pdf", "/documents/protokoll/KS-1.pdf", "file"),
        item("Bilagor", "/Documents/Protokoll/Bilagor/")
      ],
      swedish
    );
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
    const tree = buildIntegrationTree(
      [
        item("Protokoll", "/Documents/Protokoll"),
        item("Hela intranätet", undefined, "site_root"),
        item("Arkiv", null, "site_root")
      ],
      swedish
    );
    expect(shape(tree)).toEqual([
      ["Arkiv", []],
      ["Hela intranätet", []],
      ["Protokoll", []]
    ]);
  });

  it("orders siblings with the locale's collator, so Swedish puts Ä after Z", () => {
    const items = [
      item("Äldreomsorg", "/Documents/Äldreomsorg"),
      item("Vuxen", "/Documents/Vuxen"),
      item("Arkiv", "/Documents/Arkiv"),
      item("Översikt", undefined, "site_root"),
      item("Alla", undefined, "site_root")
    ];
    expect(shape(buildIntegrationTree(items, swedish))).toEqual([
      ["Alla", []],
      ["Översikt", []],
      ["Arkiv", []],
      ["Vuxen", []],
      ["Äldreomsorg", []]
    ]);
    // English sorts Ä as an A: the order follows the collator, not the runtime's default.
    expect(shape(buildIntegrationTree(items, new Intl.Collator("en").compare))).toEqual([
      ["Alla", []],
      ["Översikt", []],
      ["Äldreomsorg", []],
      ["Arkiv", []],
      ["Vuxen", []]
    ]);
  });

  it("treats two imports of the same folder as siblings", () => {
    const tree = buildIntegrationTree(
      [
        item("Protokoll", "/Documents/Protokoll"),
        item("Protokoll (igen)", "/Documents/Protokoll/")
      ],
      swedish
    );
    expect(shape(tree)).toEqual([
      ["Protokoll", []],
      ["Protokoll (igen)", []]
    ]);
  });
});

describe("flattenIntegrationTree", () => {
  const tree = buildIntegrationTree(
    [
      item("Protokoll", "/Documents/Protokoll"),
      item("Bilagor", "/Documents/Protokoll/Bilagor"),
      item("Rutiner", "/Documents/Rutiner")
    ],
    swedish
  );

  it("lists expanded subtrees with their depth and hides collapsed ones", () => {
    const expandedRows = flattenIntegrationTree(tree, () => true);
    expect(expandedRows.map((row) => [row.item.name, row.depth, row.hasChildren])).toEqual([
      ["Protokoll", 0, true],
      ["Bilagor", 1, false],
      ["Rutiner", 0, false]
    ]);

    const collapsedRows = flattenIntegrationTree(tree, () => false);
    expect(collapsedRows.map((row) => row.item.name)).toEqual(["Protokoll", "Rutiner"]);
    expect(collapsedRows[0]?.expanded).toBe(false);
  });
});

describe("filterIntegrationTree", () => {
  it("keeps matching nodes and the ancestors of matching descendants", () => {
    const tree = buildIntegrationTree(
      [
        item("Protokoll", "/Documents/Protokoll"),
        item("Bilagor", "/Documents/Protokoll/Bilagor"),
        item("Rutiner", "/Documents/Rutiner")
      ],
      swedish
    );
    expect(shape(filterIntegrationTree(tree, "bil"))).toEqual([["Protokoll", [["Bilagor", []]]]]);
    expect(filterIntegrationTree(tree, "   ")).toBe(tree);
  });
});
