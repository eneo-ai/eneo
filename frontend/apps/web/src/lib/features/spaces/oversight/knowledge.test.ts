import { describe, expect, it, vi } from "vitest";

vi.mock("$lib/paraglide/messages", () => ({
  m: new Proxy(
    {},
    {
      get: (_target, key) => (params?: Record<string, unknown>) =>
        params ? `${String(key)}(${Object.values(params).join("|")})` : String(key)
    }
  )
}));

import { knowledgeItemCount, knowledgeKindLabel, knowledgeName } from "./knowledge";

describe("oversight knowledge", () => {
  it("names a source by its own name only when the API gives one", () => {
    expect(knowledgeName({ kind: "collection", name: "Policyer" })).toBe("Policyer");
    expect(
      knowledgeName({
        kind: "integration",
        name: "Intranätet",
        integration_type: "sharepoint",
        integration_item: "site"
      })
    ).toBe("Intranätet");
  });

  it("labels a nameless file, folder or personal folder without its title", () => {
    const nameless = (
      integration_type: "sharepoint" | "confluence" | "onedrive" | null,
      integration_item: "site" | "folder" | "file" | null
    ) => knowledgeName({ kind: "integration", name: null, integration_type, integration_item });
    expect(nameless("sharepoint", "file")).toBe("admin_spaces_sharepoint_file");
    expect(nameless("sharepoint", "folder")).toBe("admin_spaces_sharepoint_folder");
    // A drive item not yet synced says neither.
    expect(nameless("sharepoint", null)).toBe("admin_spaces_sharepoint_item");
    for (const item of ["site", "folder", "file", null] as const) {
      expect(nameless("onedrive", item)).toBe("admin_spaces_onedrive_name");
    }
    expect(nameless("confluence", "folder")).toBe("admin_spaces_kind_confluence");
    expect(nameless(null, null)).toBe("admin_spaces_kind_integration");
  });

  it("names the kind, and the product of an integration when it is known", () => {
    expect(knowledgeKindLabel({ kind: "collection" })).toBe("admin_spaces_kind_collection");
    expect(knowledgeKindLabel({ kind: "website" })).toBe("admin_spaces_kind_website");
    expect(knowledgeKindLabel({ kind: "integration" })).toBe("admin_spaces_kind_integration");
    expect(knowledgeKindLabel({ kind: "integration", integration_type: "sharepoint" })).toBe(
      "admin_spaces_kind_sharepoint"
    );
    expect(knowledgeKindLabel({ kind: "integration", integration_type: "confluence" })).toBe(
      "admin_spaces_kind_confluence"
    );
    expect(knowledgeKindLabel({ kind: "integration", integration_type: "onedrive" })).toBe(
      "admin_spaces_kind_onedrive"
    );
  });

  it("counts pages for websites and documents otherwise, with a singular", () => {
    const format = (value: number) => `n=${value}`;
    expect(knowledgeItemCount({ kind: "website", item_count: 1 }, format)).toBe(
      "admin_spaces_knowledge_pages_one"
    );
    expect(knowledgeItemCount({ kind: "website", item_count: 0 }, format)).toBe(
      "admin_spaces_knowledge_pages(n=0)"
    );
    expect(knowledgeItemCount({ kind: "collection", item_count: 1 }, format)).toBe(
      "admin_spaces_knowledge_documents_one"
    );
    expect(knowledgeItemCount({ kind: "integration", item_count: 1200 }, format)).toBe(
      "admin_spaces_knowledge_documents(n=1200)"
    );
  });
});
