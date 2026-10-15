import type { IntegrationKnowledge } from "@eneo/eneo-js";
import { page } from "vitest/browser";
import { writable } from "svelte/store";
import { render } from "vitest-browser-svelte";
import { describe, expect, it, vi } from "vitest";
import "../../../../../../app.css";
import { m } from "$lib/paraglide/messages";

vi.mock("$lib/core/Eneo", () => ({
  getEneo: () => ({
    integrations: { knowledge: { getSyncProgress: vi.fn(async () => ({ items: [] })) } }
  })
}));

function knowledge(
  id: string,
  name: string,
  fields: Partial<IntegrationKnowledge> = {},
  documents = 3,
  status = "success"
): IntegrationKnowledge {
  return {
    id,
    name,
    integration_type: "sharepoint",
    selected_item_type: "folder",
    space_id: "space-1",
    permissions: ["edit", "delete"],
    wrapper_id: null,
    wrapper_name: null,
    embedding_model: { id: "model", name: "Model" },
    ...fields,
    metadata: {
      size: 0,
      last_sync_status: status,
      last_sync_error: status === "error" ? "Graph timeout" : null,
      document_count: documents,
      last_synced_at: "2026-10-13T08:00:00Z"
    }
  } as IntegrationKnowledge;
}

const currentSpace = writable({
  id: "space-1",
  routeId: "space-1",
  embedding_models: [{ id: "model" }],
  knowledge: {
    integrationKnowledge: [
      knowledge("a", "Protokoll", { wrapper_id: "w1", wrapper_name: "Kommunstyrelsen" }, 40),
      knowledge("b", "Bilagor", { wrapper_id: "w1", wrapper_name: "Kommunstyrelsen" }, 2),
      knowledge("c", "HR-handboken", {}, 100, "error")
    ]
  }
});
vi.mock("$lib/features/spaces/SpacesManager", () => ({
  getSpacesManager: () => ({ state: { currentSpace }, refreshCurrentSpace: vi.fn() })
}));

import IntegrationsTable from "./IntegrationsTable.svelte";

function sourceNames() {
  return page
    .getByRole("link")
    .elements()
    .map((link) => link.textContent?.trim())
    .filter((name) => name === "Kommunstyrelsen" || name === "HR-handboken");
}

describe("IntegrationsTable", () => {
  it("finds a source by its own name or a folder's name", async () => {
    render(IntegrationsTable);
    await expect.element(page.getByRole("link", { name: "HR-handboken" })).toBeVisible();

    const filter = page.getByRole("textbox", { name: m.ui_filter() }).element() as HTMLInputElement;
    filter.value = "bilag";
    filter.dispatchEvent(new Event("input", { bubbles: true }));

    await expect.poll(sourceNames).toEqual(["Kommunstyrelsen"]);
  });

  it("sorts the sources by their document count", async () => {
    render(IntegrationsTable);
    await expect.element(page.getByRole("link", { name: "HR-handboken" })).toBeVisible();

    (
      page
        .getByRole("button", { name: m.integration_source_column_contents() })
        .element() as HTMLElement
    ).click();

    // Alphabetically HR-handboken comes first; by documents (42 against 100) it comes last.
    await expect.poll(sourceNames).toEqual(["Kommunstyrelsen", "HR-handboken"]);
  });

  it("narrows the list to the sources that need attention", async () => {
    render(IntegrationsTable);
    await expect.element(page.getByRole("link", { name: "HR-handboken" })).toBeVisible();

    (
      page
        .getByRole("button", { name: m.integration_filter_attention({ count: 1 }) })
        .element() as HTMLElement
    ).click();

    await expect.poll(sourceNames).toEqual(["HR-handboken"]);
  });
});
