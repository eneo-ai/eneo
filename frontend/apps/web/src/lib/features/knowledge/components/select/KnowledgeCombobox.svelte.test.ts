import type { EmbeddingModel, IntegrationKnowledge, WebsiteSparse } from "@eneo/eneo-js";
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

function integration(
  name: string,
  metadata: Partial<NonNullable<IntegrationKnowledge["metadata"]>>
): IntegrationKnowledge {
  return {
    id: `integration-${name}`,
    name,
    space_id: "personal-space",
    integration_type: "sharepoint",
    embedding_model: model,
    metadata: { size: 0, ...metadata }
  } as unknown as IntegrationKnowledge;
}

describe("KnowledgeCombobox", () => {
  it("warns about crawl failures before selection and selects the website", async () => {
    const onAddWebsite = vi.fn();

    render(KnowledgeCombobox, {
      origin: "space",
      space,
      currentSpaceId: "personal-space",
      organizationSpaceId: "organization-space",
      selectedCollections: [],
      selectedWebsites: [],
      selectedIntegrationKnowledge: [],
      onAddCollection: vi.fn(),
      onAddWebsite,
      onAddIntegration: vi.fn()
    });

    await page.getByRole("button", { name: m.add_knowledge_space() }).click();

    await expect.element(page.getByText(m.pages_failed({ count: 3 }))).toBeVisible();
    await page.getByText("Documentation").click();

    expect(onAddWebsite).toHaveBeenCalledOnce();
    expect(onAddWebsite).toHaveBeenCalledWith(website);
  });

  it("flags integrations whose last sync failed or found nothing, like failed crawls", async () => {
    render(KnowledgeCombobox, {
      origin: "space",
      space: {
        ...space,
        knowledge: {
          groups: [],
          websites: [],
          integrationKnowledge: [
            integration("Broken", { last_sync_status: "error", last_sync_error: "403" }),
            integration("Empty", { last_sync_status: "success", document_count: 0 }),
            integration("Healthy", { last_sync_status: "success", document_count: 4 })
          ]
        }
      },
      currentSpaceId: "personal-space",
      organizationSpaceId: "organization-space",
      selectedCollections: [],
      selectedWebsites: [],
      selectedIntegrationKnowledge: [],
      onAddCollection: vi.fn(),
      onAddWebsite: vi.fn(),
      onAddIntegration: vi.fn()
    });

    await page.getByRole("button", { name: m.add_knowledge_space() }).click();

    await expect.element(page.getByText(m.integration_sync_status_error())).toBeVisible();
    await expect.element(page.getByText(m.integration_sync_status_empty())).toBeVisible();
    const broken = page.getByRole("option", { name: /Broken/ }).element();
    expect(broken.className).toContain("border-negative-default");
    const empty = page.getByRole("option", { name: /Empty/ }).element();
    expect(empty.className).toContain("border-warning-default");
    expect(empty.className).not.toContain("border-negative-default");
    const healthy = page.getByRole("option", { name: /Healthy/ }).element();
    expect(healthy.className).not.toMatch(/border-(negative|warning)-default/);
    expect(healthy.textContent).not.toContain(m.integration_sync_status_success());
  });
});
