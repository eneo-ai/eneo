import { describe, expect, test } from "vitest";
import type { IntegrationKnowledge } from "@intric/intric-js";
import {
  getIntegrationKnowledgeOptions,
  getSelectedIntegrationDisplay,
  getSortedWrapperItems,
  getWrapperCountBadges,
  getWrapperItemTypeCounts,
  groupIntegrationByWrapper,
  isWrapperFolderItem
} from "./knowledgeIntegration";

/** Build a minimal IntegrationKnowledge stub; only the fields the helpers read are set. */
function item(partial: Partial<IntegrationKnowledge> & { id: string }): IntegrationKnowledge {
  return { name: partial.id, ...partial } as IntegrationKnowledge;
}

describe("isWrapperFolderItem", () => {
  test("folder and site_root are folder-like, file is not", () => {
    expect(isWrapperFolderItem(item({ id: "a", selected_item_type: "folder" }))).toBe(true);
    expect(isWrapperFolderItem(item({ id: "b", selected_item_type: "site_root" }))).toBe(true);
    expect(isWrapperFolderItem(item({ id: "c", selected_item_type: "file" }))).toBe(false);
    expect(isWrapperFolderItem(item({ id: "d" }))).toBe(false);
  });
});

describe("getWrapperItemTypeCounts", () => {
  test("counts by type, treating site and site_root as sites", () => {
    const counts = getWrapperItemTypeCounts([
      item({ id: "1", selected_item_type: "file" }),
      item({ id: "2", selected_item_type: "file" }),
      item({ id: "3", selected_item_type: "folder" }),
      item({ id: "4", selected_item_type: "site_root" }),
      item({ id: "5", selected_item_type: "site" }),
      item({ id: "6", selected_item_type: "mystery" })
    ]);
    expect(counts).toEqual({ files: 2, folders: 1, sites: 2, unknown: 1, total: 6 });
  });
});

describe("getWrapperCountBadges", () => {
  test("one badge per non-empty type", () => {
    const badges = getWrapperCountBadges([
      item({ id: "1", selected_item_type: "file" }),
      item({ id: "2", selected_item_type: "folder" })
    ]);
    expect(badges).toEqual([
      { type: "files", count: 1 },
      { type: "folders", count: 1 }
    ]);
  });

  test("falls back to a generic items badge when nothing is typed", () => {
    const badges = getWrapperCountBadges([item({ id: "1" }), item({ id: "2" })]);
    expect(badges).toEqual([{ type: "items", count: 2 }]);
  });
});

describe("groupIntegrationByWrapper", () => {
  test("groups by wrapper_id and collects ungrouped singles", () => {
    const { wrappers, singles } = groupIntegrationByWrapper([
      item({ id: "1", wrapper_id: "w1" }),
      item({ id: "2", wrapper_id: "w1" }),
      item({ id: "3" })
    ]);
    expect(wrappers.get("w1")?.map((i) => i.id)).toEqual(["1", "2"]);
    expect(singles.map((i) => i.id)).toEqual(["3"]);
  });
});

describe("getSortedWrapperItems", () => {
  test("sorts by name without mutating the input", () => {
    const input = [item({ id: "b", name: "Beta" }), item({ id: "a", name: "Alpha" })];
    expect(getSortedWrapperItems(input).map((i) => i.name)).toEqual(["Alpha", "Beta"]);
    expect(input.map((i) => i.id)).toEqual(["b", "a"]);
  });
});

describe("getIntegrationKnowledgeOptions", () => {
  const items = [
    item({ id: "1", wrapper_id: "w1", wrapper_name: "Site", integration_type: "sharepoint" }),
    item({ id: "2", wrapper_id: "w1", wrapper_name: "Site", integration_type: "sharepoint" }),
    item({ id: "single", name: "Solo" })
  ];

  test("offers a wrapper while any of its items remain unselected", () => {
    const options = getIntegrationKnowledgeOptions(items, [{ id: "1" }]);
    const wrapper = options.find((o) => o.type === "wrapper");
    expect(wrapper).toBeDefined();
    expect(wrapper?.type === "wrapper" && wrapper.wrapper.name).toBe("Site");
  });

  test("drops a wrapper once all its items are selected", () => {
    const options = getIntegrationKnowledgeOptions(items, [{ id: "1" }, { id: "2" }]);
    expect(options.some((o) => o.type === "wrapper")).toBe(false);
  });

  test("excludes already-selected singles", () => {
    const options = getIntegrationKnowledgeOptions(items, [{ id: "single" }]);
    expect(options.some((o) => o.type === "single" && o.knowledge.id === "single")).toBe(false);
  });
});

describe("getSelectedIntegrationDisplay", () => {
  const all = [
    item({ id: "1", wrapper_id: "w1", wrapper_name: "Site", integration_type: "sharepoint" }),
    item({ id: "2", wrapper_id: "w1", wrapper_name: "Site", integration_type: "sharepoint" })
  ];

  test("collapses a fully-selected wrapper into a single wrapper row", () => {
    const display = getSelectedIntegrationDisplay(all, all);
    expect(display).toHaveLength(1);
    expect(display[0].type).toBe("wrapper");
  });

  test("shows individual items when a wrapper is only partially selected", () => {
    const display = getSelectedIntegrationDisplay([all[0]], all);
    expect(display).toHaveLength(1);
    expect(display[0].type).toBe("single");
    expect(display[0].type === "single" && display[0].knowledge.id).toBe("1");
  });
});
