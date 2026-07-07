import { describe, expect, it } from "vitest";
import type { Collection, IntegrationKnowledge, Website } from "../knowledge";
import {
  availableKnowledge,
  byOrigin,
  collectionInfoBlobCount,
  integrationOptions,
  isOrgItem,
  isPersonalItem,
  selectedIntegrationDisplay,
  websiteFailedPageCount,
  websiteIndexedResultCount
} from "./logic";

const model = (id: string) => ({ id, name: `model-${id}` });

function collection(id: string, modelId = "m1", spaceId = "current"): Collection {
  return {
    id,
    name: `collection-${id}`,
    space_id: spaceId,
    embedding_model: model(modelId),
    metadata: { num_info_blobs: 1, size: 0 }
  } as unknown as Collection;
}

function website(id: string, modelId = "m1", spaceId = "current"): Website {
  return {
    id,
    name: `site-${id}`,
    url: `https://${id}.example.com`,
    space_id: spaceId,
    embedding_model: model(modelId)
  } as unknown as Website;
}

function integration(
  id: string,
  overrides: Partial<IntegrationKnowledge> = {}
): IntegrationKnowledge {
  return {
    id,
    name: `integration-${id}`,
    space_id: "current",
    embedding_model: model("m1"),
    integration_type: "sharepoint",
    ...overrides
  } as IntegrationKnowledge;
}

describe("origin", () => {
  it("treats unowned or current-space items as personal", () => {
    expect(isPersonalItem({ space_id: null }, "current")).toBe(true);
    expect(isPersonalItem({ space_id: "current" }, "current")).toBe(true);
    expect(isPersonalItem({ space_id: "other" }, "current")).toBe(false);
  });

  it("matches org by the configured org space, else any foreign space", () => {
    expect(isOrgItem({ space_id: "org" }, "current", "org")).toBe(true);
    expect(isOrgItem({ space_id: "other" }, "current", "org")).toBe(false);
    expect(isOrgItem({ space_id: "other" }, "current", undefined)).toBe(true);
  });

  it("filters lists by origin", () => {
    const items = [
      { id: "a", space_id: "current" },
      { id: "b", space_id: "org" }
    ];
    expect(byOrigin(items, "personal", "current", "org").map((item) => item.id)).toEqual(["a"]);
    expect(byOrigin(items, "organization", "current", "org").map((item) => item.id)).toEqual(["b"]);
  });
});

describe("integrationOptions", () => {
  it("offers a wrapper as one option until fully selected", () => {
    const items = [
      integration("a", { wrapper_id: "w", wrapper_name: "Wrapper" }),
      integration("b", { wrapper_id: "w", wrapper_name: "Wrapper" }),
      integration("c")
    ];
    const open = integrationOptions(items, []);
    expect(open.map((entry) => entry.key)).toEqual(["integration:c", "wrapper:w"]);

    const partly = integrationOptions(items, [{ id: "a" }]);
    expect(partly.map((entry) => entry.key)).toEqual(["integration:c", "wrapper:w"]);

    const full = integrationOptions(items, [{ id: "a" }, { id: "b" }]);
    expect(full.map((entry) => entry.key)).toEqual(["integration:c"]);
  });
});

describe("selectedIntegrationDisplay", () => {
  const all = [
    integration("a", { wrapper_id: "w", wrapper_name: "Wrapper" }),
    integration("b", { wrapper_id: "w", wrapper_name: "Wrapper" })
  ];

  it("collapses a fully selected wrapper into one row", () => {
    const display = selectedIntegrationDisplay(all, all);
    expect(display).toHaveLength(1);
    expect(display[0]?.type).toBe("wrapper");
  });

  it("shows partially selected wrapper items individually", () => {
    const display = selectedIntegrationDisplay([all[0]!], all);
    expect(display).toHaveLength(1);
    expect(display[0]).toMatchObject({ type: "single", key: "integration:a" });
  });
});

describe("availableKnowledge", () => {
  const space = {
    knowledge: {
      collections: [collection("c1", "m1"), collection("c2", "m2")],
      websites: [website("w1", "m1")],
      integrationKnowledge: [integration("i1")]
    },
    embeddingModelIds: ["m1"]
  };
  const none = { collections: [], websites: [], integrationKnowledge: [] };

  it("sections per embedding model and flags disabled models", () => {
    const { sections, showHeaders } = availableKnowledge(space, none);
    expect(showHeaders).toBe(true);
    const m2 = sections.find((section) => section.modelId === "m2");
    expect(m2?.isEnabled).toBe(false);
    expect(m2?.collections.map((item) => item.id)).toEqual(["c2"]);
  });

  it("marks other models incompatible once something is selected", () => {
    const { sections } = availableKnowledge(space, {
      ...none,
      collections: [collection("x", "m1")]
    });
    const m2 = sections.find((section) => section.modelId === "m2");
    expect(m2?.isCompatible).toBe(false);
    expect(m2?.collections).toHaveLength(0);
  });

  it("drops selected items and applies the text filter to name and url", () => {
    const { sections } = availableKnowledge(
      space,
      { ...none, websites: [website("w1", "m1")] },
      "c1"
    );
    const m1 = sections.find((section) => section.modelId === "m1");
    expect(m1?.websites).toHaveLength(0);
    expect(m1?.collections.map((item) => item.id)).toEqual(["c1"]);
  });
});

describe("selected knowledge blob counts", () => {
  it("uses collection blob metadata", () => {
    expect(collectionInfoBlobCount(collection("c", "m1"))).toBe(1);
  });

  it("uses crawled pages and downloaded files for websites", () => {
    const item = website("w") as Website;
    item.latest_crawl = {
      pages_crawled: 3,
      files_downloaded: 2,
      pages_failed: 1
    } as Website["latest_crawl"];

    expect(websiteIndexedResultCount(item)).toBe(5);
    expect(websiteFailedPageCount(item)).toBe(1);
  });
});
