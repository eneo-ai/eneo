import type { EmbeddingModel, WebsiteSparse } from "@eneo/eneo-js";
import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { describe, expect, it, vi } from "vitest";
import { m } from "$lib/paraglide/messages";
import KnowledgeCombobox from "./KnowledgeCombobox.svelte";

const model = {
  id: "model-1",
  name: "Embedding model"
} as EmbeddingModel;

const website = {
  id: "website-1",
  name: "Documentation",
  url: "https://example.com",
  space_id: "personal-space",
  embedding_model: model,
  latest_crawl: {
    pages_crawled: 12,
    pages_failed: 3
  }
} as WebsiteSparse;

const space = {
  embedding_models: [model],
  knowledge: {
    groups: [],
    websites: [website],
    integrationKnowledge: []
  }
};

describe("KnowledgeCombobox", () => {
  it("warns about crawl failures before selection and selects the website", async () => {
    const onAddWebsite = vi.fn();

    render(KnowledgeCombobox, {
      origin: "personal",
      space,
      currentSpaceId: "personal-space",
      selectedCollections: [],
      selectedWebsites: [],
      selectedIntegrationKnowledge: [],
      onAddCollection: vi.fn(),
      onAddWebsite,
      onAddIntegration: vi.fn()
    });

    await page.getByRole("button", { name: m.add_knowledge_personal() }).click();

    await expect.element(page.getByText(m.pages_failed({ count: 3 }))).toBeVisible();
    await page.getByText("Documentation").click();

    expect(onAddWebsite).toHaveBeenCalledOnce();
    expect(onAddWebsite).toHaveBeenCalledWith(website);
  });
});
