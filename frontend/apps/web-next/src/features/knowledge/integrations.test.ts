import { describe, expect, it } from "vitest";
import { countSharePointItemTypes, groupIntegrationRows, wrapperDisplayName } from "./integrations";
import type { IntegrationKnowledge } from "./knowledge";

function makeItem(overrides: Partial<IntegrationKnowledge>): IntegrationKnowledge {
  return {
    id: "item-1",
    name: "Item",
    url: "https://example.com",
    space_id: "space-1",
    embedding_model: { id: "model-1" },
    metadata: { size: 0 },
    integration_type: "sharepoint",
    ...overrides
  } as IntegrationKnowledge;
}

describe("countSharePointItemTypes", () => {
  it("counts files, folders, sites and unknowns", () => {
    const counts = countSharePointItemTypes([
      makeItem({ selected_item_type: "file" }),
      makeItem({ selected_item_type: "File" }),
      makeItem({ selected_item_type: "folder" }),
      makeItem({ selected_item_type: "site_root" }),
      makeItem({ selected_item_type: "site" }),
      makeItem({ selected_item_type: null }),
      makeItem({ selected_item_type: "weird" })
    ]);
    expect(counts).toEqual({ files: 2, folders: 1, sites: 2, unknown: 2, total: 7 });
  });
});

describe("wrapperDisplayName", () => {
  it("prefers a non-empty wrapper_name", () => {
    expect(wrapperDisplayName(makeItem({ wrapper_name: "Docs", name: "fallback" }))).toBe("Docs");
  });

  it("falls back to the item name when wrapper_name is blank", () => {
    expect(wrapperDisplayName(makeItem({ wrapper_name: "  ", name: "fallback" }))).toBe("fallback");
    expect(wrapperDisplayName(makeItem({ wrapper_name: null, name: "fallback" }))).toBe("fallback");
  });
});

describe("groupIntegrationRows", () => {
  it("collapses sharepoint items sharing a wrapper_id into one wrapper row", () => {
    const rows = groupIntegrationRows([
      makeItem({ id: "a", name: "Alpha", wrapper_id: "w1", wrapper_name: "Wrapper" }),
      makeItem({ id: "b", name: "Beta", wrapper_id: "w1", wrapper_name: "Wrapper" })
    ]);
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({
      kind: "wrapper",
      wrapperId: "w1",
      wrapperName: "Wrapper",
      counts: { total: 2 }
    });
  });

  it("keeps a single-item wrapper as a plain row", () => {
    const rows = groupIntegrationRows([
      makeItem({ id: "a", name: "Alpha", wrapper_id: "w1", wrapper_name: "Wrapper" })
    ]);
    expect(rows).toHaveLength(1);
    expect(rows[0]?.kind).toBe("item");
  });

  it("never groups confluence items, even with a wrapper_id", () => {
    const rows = groupIntegrationRows([
      makeItem({ id: "a", name: "Alpha", wrapper_id: "w1", integration_type: "confluence" }),
      makeItem({ id: "b", name: "Beta", wrapper_id: "w1", integration_type: "confluence" })
    ]);
    expect(rows.map((row) => row.kind)).toEqual(["item", "item"]);
  });

  it("sorts wrapper and item rows together, case-insensitively", () => {
    const rows = groupIntegrationRows([
      makeItem({ id: "a", name: "zebra" }),
      makeItem({ id: "b", name: "B1", wrapper_id: "w1", wrapper_name: "Middle" }),
      makeItem({ id: "c", name: "B2", wrapper_id: "w1", wrapper_name: "Middle" }),
      makeItem({ id: "d", name: "Apple" })
    ]);
    expect(rows.map((row) => (row.kind === "wrapper" ? row.wrapperName : row.item.name))).toEqual([
      "Apple",
      "Middle",
      "zebra"
    ]);
  });

  it("takes the embedding model from the wrapper's first item", () => {
    const rows = groupIntegrationRows([
      makeItem({ id: "a", wrapper_id: "w1", embedding_model: { id: "model-x" } as never }),
      makeItem({ id: "b", wrapper_id: "w1", embedding_model: { id: "model-y" } as never })
    ]);
    expect(rows[0]?.embeddingModelId).toBe("model-x");
  });
});
