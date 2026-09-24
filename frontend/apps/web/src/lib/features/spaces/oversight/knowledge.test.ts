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
  it("names a personal OneDrive folder without its own name", () => {
    expect(knowledgeName({ name: "Policyer" })).toBe("Policyer");
    expect(knowledgeName({ name: null })).toBe("admin_spaces_onedrive_name");
    expect(knowledgeName({})).toBe("admin_spaces_onedrive_name");
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
