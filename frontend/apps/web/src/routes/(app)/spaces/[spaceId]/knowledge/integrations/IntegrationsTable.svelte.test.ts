import type { IntegrationKnowledge } from "@eneo/eneo-js";
import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { describe, expect, it, vi } from "vitest";
import "../../../../../../app.css";
import { m } from "$lib/paraglide/messages";

type Space = {
  id: string;
  routeId: string;
  embedding_models: { id: string }[];
  knowledge: { integrationKnowledge: IntegrationKnowledge[] };
};

const spaces = vi.hoisted(() => ({ current: null as unknown }));

vi.mock("$lib/core/Eneo", () => ({
  getEneo: () => ({ integrations: { knowledge: {} } })
}));
vi.mock("$lib/features/spaces/SpacesManager", () => ({
  getSpacesManager: () => ({
    refreshCurrentSpace: vi.fn(),
    state: {
      currentSpace: {
        subscribe: (run: (space: unknown) => void) => {
          run(spaces.current);
          return () => undefined;
        }
      }
    }
  })
}));

import IntegrationsTable from "./IntegrationsTable.svelte";

function item(id: string, name: string, url: string | null): IntegrationKnowledge {
  return {
    id,
    name,
    url,
    space_id: "space-1",
    wrapper_id: null,
    integration_type: "sharepoint",
    selected_item_type: "folder",
    embedding_model: { id: "em-1", name: "Embedder" },
    permissions: ["edit", "delete"],
    metadata: { size: 0, last_sync_status: "success", document_count: 1 }
  } as IntegrationKnowledge;
}

function show(items: IntegrationKnowledge[]) {
  const space: Space = {
    id: "space-1",
    routeId: "space-1",
    embedding_models: [{ id: "em-1" }],
    knowledge: { integrationKnowledge: items }
  };
  spaces.current = space;
  return render(IntegrationsTable);
}

describe("IntegrationsTable", () => {
  it("links to the source only for an http(s) URL", async () => {
    show([
      item("ik-1", "Protokoll", "javascript:alert(1)"),
      item("ik-2", "Rutiner", "https://contoso.sharepoint.com/sites/ks/Rutiner"),
      item("ik-3", "Arkiv", null)
    ]);

    await expect.element(page.getByRole("link", { name: "Arkiv" })).toBeVisible();
    const sourceLinks = page.getByRole("link", { name: m.open_in_sharepoint() }).elements();
    expect(sourceLinks.map((link) => link.getAttribute("href"))).toEqual([
      "https://contoso.sharepoint.com/sites/ks/Rutiner"
    ]);
    expect(page.getByRole("button", { name: m.open_in_sharepoint() }).elements()).toHaveLength(0);
  });
});
