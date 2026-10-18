import type { GroupSparse, IntegrationKnowledge, Space } from "@eneo/eneo-js";
import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { describe, expect, it } from "vitest";
import { m } from "$lib/paraglide/messages";
import SelectKnowledgeTestHost from "./SelectKnowledgeTestHost.svelte";

const model = { id: "model", name: "Embedding model", is_deprecated: false, open_source: false };
const owners = ["current", "org", "other"];
const collections: GroupSparse[] = owners.map((owner) => ({
  id: `collection-${owner}`,
  name: `Collection ${owner}`,
  space_id: owner,
  embedding_model: model,
  metadata: { num_info_blobs: 0, size: 0 }
}));
const websites: Space["knowledge"]["websites"]["items"] = owners.map((owner) => ({
  id: `website-${owner}`,
  name: `Website ${owner}`,
  url: `https://${owner}.example.com`,
  space_id: owner,
  embedding_model: model,
  download_files: false,
  crawl_type: "crawl",
  update_interval: "never",
  latest_crawl: null,
  last_indexed_at: null,
  metadata: { size: 0 },
  requires_http_auth: false,
  is_auto_disabled: false
}));
function integration(owner: string, id = `integration-${owner}`): IntegrationKnowledge {
  // The API schema's task enum is uninhabitable; the picker does not read that field.
  return {
    id,
    name: `Integration ${id}`,
    space_id: owner,
    url: "https://example.com",
    tenant_id: "tenant",
    user_integration_id: "user-integration",
    embedding_model: model,
    metadata: { size: 0 },
    integration_type: "sharepoint"
  } as IntegrationKnowledge;
}
const integrations = owners.map((owner) => integration(owner));

function space(organizationSpaceId: string | null = "org"): Space {
  return {
    id: "current",
    name: "Current space",
    description: null,
    personal: false,
    organization: false,
    organization_space_id: organizationSpaceId,
    embedding_models: [model],
    completion_models: [],
    transcription_models: [],
    linked_models: { completion_models: [], embedding_models: [], transcription_models: [] },
    knowledge: {
      groups: { items: collections, count: collections.length },
      websites: { items: websites, count: websites.length },
      integration_knowledge_list: { items: integrations, count: integrations.length }
    },
    members: { items: [], count: 0 },
    group_members: { items: [], count: 0 },
    skill_permissions: [],
    available_roles: [],
    security_classification: null
  };
}

describe("SelectKnowledge", () => {
  it.each(["org", null])(
    "lists a source linked from another space under this space and keeps it removable (org ID %s)",
    async (orgId) => {
      render(SelectKnowledgeTestHost, { space: space(orgId) });

      await page.getByRole("button", { name: m.add_knowledge_space() }).click();
      await page.getByRole("option", { name: /Collection other/ }).click();
      const current = page.getByRole("region", { name: m.knowledge(), exact: true });
      await expect.element(current.getByText("Collection other", { exact: true })).toBeVisible();
      await expect
        .element(page.getByTestId("knowledge-selection"))
        .toHaveTextContent('"collections":["collection-other"]');

      await current.getByRole("button", { name: m.remove(), exact: true }).click();
      await expect
        .element(current.getByText("Collection other", { exact: true }))
        .not.toBeInTheDocument();
      await expect
        .element(page.getByTestId("knowledge-selection"))
        .toHaveTextContent('"collections":[]');

      await page.getByRole("button", { name: m.add_knowledge_space() }).click();
      await expect.element(page.getByRole("option", { name: /Collection other/ })).toBeVisible();
    }
  );

  it.each([
    { orgId: "org", enabled: true, showHeadings: true },
    { orgId: null, enabled: true, showHeadings: true },
    { orgId: "org", enabled: false, showHeadings: true },
    { orgId: "org", enabled: true, showHeadings: false }
  ])(
    "shows every selected source once and removes all source types (%j)",
    async ({ orgId, enabled, showHeadings }) => {
      render(SelectKnowledgeTestHost, {
        space: { ...space(orgId), embedding_models: enabled ? [model] : [] },
        initialCollections: collections,
        initialWebsites: websites,
        initialIntegrationKnowledge: integrations,
        showHeadings
      });

      for (const owner of owners) {
        const label = owner === orgId ? m.organization_knowledge() : m.knowledge();
        const region = page.getByRole("region", { name: label, exact: true });
        for (const name of [
          `Collection ${owner}`,
          `Website ${owner}`,
          `Integration integration-${owner}`
        ]) {
          await expect.element(region.getByText(name, { exact: true })).toBeVisible();
          expect(page.getByText(name, { exact: true }).elements()).toHaveLength(1);
        }
      }
      for (const label of [m.knowledge(), m.organization_knowledge()]) {
        const removeButtons = page
          .getByRole("region", { name: label, exact: true })
          .getByRole("button", { name: m.remove(), exact: true });
        const selectedCount = removeButtons.elements().length;
        for (let index = 0; index < selectedCount; index++) await removeButtons.first().click();
      }
      await expect
        .element(page.getByTestId("knowledge-selection"))
        .toHaveTextContent('{"collections":[],"websites":[],"integrations":[]}');
    }
  );

  it("keeps previously selected sources removable when no longer in available knowledge", async () => {
    const currentSpace = space();
    currentSpace.knowledge = {
      groups: { items: [], count: 0 },
      websites: { items: [], count: 0 },
      integration_knowledge_list: { items: [], count: 0 }
    };
    render(SelectKnowledgeTestHost, {
      space: currentSpace,
      initialCollections: [collections[2]],
      initialWebsites: [websites[2]],
      initialIntegrationKnowledge: [integrations[2]]
    });
    const current = page.getByRole("region", { name: m.knowledge(), exact: true });
    await expect.element(current.getByText("Collection other", { exact: true })).toBeVisible();
    await expect.element(current.getByText("Website other", { exact: true })).toBeVisible();
    await expect
      .element(current.getByText("Integration integration-other", { exact: true }))
      .toBeVisible();
    for (let index = 0; index < 3; index++)
      await current.getByRole("button", { name: m.remove(), exact: true }).first().click();
    await expect
      .element(page.getByTestId("knowledge-selection"))
      .toHaveTextContent('{"collections":[],"websites":[],"integrations":[]}');
  });

  it.each([false, true])(
    "removes every saved item in a linked wrapper (partially available %s)",
    async (partiallyAvailable) => {
      const wrapped = ["first", "second"].map((id) => ({
        ...integration("other", id),
        wrapper_id: "wrapper",
        wrapper_name: "Linked site"
      }));
      const currentSpace = space();
      const available = partiallyAvailable ? [wrapped[0]] : wrapped;
      currentSpace.knowledge.integration_knowledge_list = {
        items: available,
        count: available.length
      };
      render(SelectKnowledgeTestHost, {
        space: currentSpace,
        initialIntegrationKnowledge: wrapped
      });
      const current = page.getByRole("region", { name: m.knowledge(), exact: true });
      await expect.element(current.getByText("Linked site", { exact: true })).toBeVisible();
      await current.getByRole("button", { name: "Linked site", exact: true }).click();
      await expect.element(current.getByText("Integration first", { exact: true })).toBeVisible();
      await expect.element(current.getByText("Integration second", { exact: true })).toBeVisible();
      await current.getByRole("button", { name: m.remove(), exact: true }).click();
      await expect
        .element(current.getByText("Linked site", { exact: true }))
        .not.toBeInTheDocument();
      await expect
        .element(page.getByTestId("knowledge-selection"))
        .toHaveTextContent('"integrations":[]');
    }
  );

  it("shows and removes an unavailable saved wrapper item instead of substituting an available item", async () => {
    const available = {
      ...integration("other", "available"),
      wrapper_id: "wrapper",
      wrapper_name: "Linked site"
    };
    const selected = {
      ...integration("other", "saved"),
      wrapper_id: "wrapper",
      wrapper_name: "Linked site"
    };
    const currentSpace = space();
    currentSpace.knowledge.integration_knowledge_list = { items: [available], count: 1 };
    render(SelectKnowledgeTestHost, {
      space: currentSpace,
      initialIntegrationKnowledge: [selected]
    });
    const current = page.getByRole("region", { name: m.knowledge(), exact: true });
    await expect.element(current.getByText("Integration saved", { exact: true })).toBeVisible();
    expect(current.getByText("Integration available", { exact: true }).elements()).toHaveLength(0);
    await current.getByRole("button", { name: m.remove(), exact: true }).click();
    await expect
      .element(page.getByTestId("knowledge-selection"))
      .toHaveTextContent('"integrations":[]');
  });

  it("shows the organization space's own sources once in its current-space section", async () => {
    render(SelectKnowledgeTestHost, {
      space: { ...space(), id: "org", organization: true },
      initialCollections: [collections[1]]
    });
    const current = page.getByRole("region", { name: m.knowledge(), exact: true });
    await expect.element(current.getByText("Collection org", { exact: true })).toBeVisible();
    expect(page.getByText("Collection org", { exact: true }).elements()).toHaveLength(1);
    await current.getByRole("button", { name: m.remove(), exact: true }).click();
    await expect
      .element(page.getByTestId("knowledge-selection"))
      .toHaveTextContent('"collections":[]');
  });
});
