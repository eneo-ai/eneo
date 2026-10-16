import type { IntegrationKnowledge } from "@eneo/eneo-js";
import { page, userEvent } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { describe, expect, it, vi } from "vitest";
import "../../../../../../app.css";
import { m } from "$lib/paraglide/messages";
import { expectNoAxeViolations } from "$lib/test/axe";

vi.mock("$lib/core/Eneo", () => ({
  getEneo: () => ({ integrations: { knowledge: {} } })
}));
vi.mock("$lib/features/spaces/SpacesManager", () => ({
  getSpacesManager: () => ({
    refreshCurrentSpace: vi.fn(),
    state: {
      currentSpace: {
        subscribe: (run: (space: { id: string }) => void) => {
          run({ id: "space-1" });
          return () => undefined;
        }
      }
    }
  })
}));

import IntegrationTreeTable from "./IntegrationTreeTable.svelte";

function item(
  id: string,
  name: string,
  folder_path: string | null,
  documentCount = 1
): IntegrationKnowledge {
  return {
    id,
    name,
    folder_path,
    selected_item_type: folder_path ? "folder" : "site_root",
    integration_type: "sharepoint",
    url: `https://contoso.sharepoint.com/${id}`,
    permissions: ["edit", "delete"],
    metadata: {
      size: 0,
      last_sync_status: "success",
      document_count: documentCount,
      last_synced_at: new Date().toISOString()
    }
  } as IntegrationKnowledge;
}

const items = [
  item("bilagor", "Bilagor", "/Documents/Protokoll/Bilagor", 3),
  item("protokoll", "Protokoll", "/Documents/Protokoll", 12),
  item("rutiner", "Rutiner", "/Documents/Rutiner", 5)
];

function rowNames() {
  return page
    .getByRole("row")
    .elements()
    .slice(1)
    .map((row) => row.querySelector("a")?.textContent?.trim());
}

describe("IntegrationTreeTable", () => {
  it("nests child folders under their parent, indented, with every row linked and actionable", async () => {
    render(IntegrationTreeTable, { items, spaceRouteId: "space-1" });

    expect(rowNames()).toEqual(["Protokoll", "Bilagor", "Rutiner"]);
    const childLink = page.getByRole("link", { name: "Bilagor" });
    await expect
      .element(childLink)
      .toHaveAttribute("href", "/spaces/space-1/knowledge/integrations/bilagor");
    const childCell = childLink.element().closest("td")?.firstElementChild as HTMLElement;
    expect(childCell.style.paddingLeft).toBe("1.5rem");
    await expect
      .element(page.getByRole("link", { name: m.integration_documents_other({ count: 3 }) }))
      .toHaveAttribute("href", "/spaces/space-1/knowledge/integrations/bilagor");
    expect(page.getByRole("button", { name: m.actions() }).elements()).toHaveLength(3);
    await expectNoAxeViolations();
  });

  it("links to the source only for an http(s) URL", async () => {
    render(IntegrationTreeTable, {
      items: [
        { ...item("skript", "Skript", "/Documents/Skript"), url: "javascript:alert(1)" },
        item("rutiner", "Rutiner", "/Documents/Rutiner")
      ],
      spaceRouteId: "space-1"
    });

    await expect.element(page.getByRole("link", { name: "Skript" })).toBeVisible();
    const sourceLinks = page.getByRole("link", { name: m.open_in_sharepoint() }).elements();
    expect(sourceLinks.map((link) => link.getAttribute("href"))).toEqual([
      "https://contoso.sharepoint.com/rutiner"
    ]);
    expect(page.getByRole("button", { name: m.open_in_sharepoint() }).elements()).toHaveLength(0);
  });

  it("collapses and expands a parent from the keyboard", async () => {
    render(IntegrationTreeTable, { items, spaceRouteId: "space-1" });
    const toggle = page.getByRole("button", {
      name: m.sharepoint_collapse_folder_named({ name: "Protokoll" })
    });
    await expect.element(toggle).toHaveAttribute("aria-expanded", "true");

    (toggle.element() as HTMLElement).focus();
    await userEvent.keyboard("{Enter}");

    const collapsedToggle = page.getByRole("button", {
      name: m.sharepoint_expand_folder_named({ name: "Protokoll" })
    });
    await expect.element(collapsedToggle).toHaveAttribute("aria-expanded", "false");
    expect(rowNames()).toEqual(["Protokoll", "Rutiner"]);

    await collapsedToggle.click();
    await expect.element(toggle).toHaveAttribute("aria-expanded", "true");
    expect(rowNames()).toEqual(["Protokoll", "Bilagor", "Rutiner"]);
  });

  it("filters by name and keeps the parent of a matching child, collapsed or not", async () => {
    render(IntegrationTreeTable, { items, spaceRouteId: "space-1" });
    await page
      .getByRole("button", { name: m.sharepoint_collapse_folder_named({ name: "Protokoll" }) })
      .click();
    await expect.poll(rowNames).toEqual(["Protokoll", "Rutiner"]);

    await userEvent.fill(page.getByRole("searchbox", { name: m.ui_filter() }), "bil");
    await expect.poll(rowNames).toEqual(["Protokoll", "Bilagor"]);

    await userEvent.fill(page.getByRole("searchbox", { name: m.ui_filter() }), "zzz");
    await expect.element(page.getByText(m.no_results_found())).toBeVisible();
  });

  it("offers no collapse toggle while filtering and brings it back with its state", async () => {
    render(IntegrationTreeTable, { items, spaceRouteId: "space-1" });
    const collapse = page.getByRole("button", {
      name: m.sharepoint_collapse_folder_named({ name: "Protokoll" })
    });
    const expand = page.getByRole("button", {
      name: m.sharepoint_expand_folder_named({ name: "Protokoll" })
    });
    await collapse.click();
    await expect.poll(rowNames).toEqual(["Protokoll", "Rutiner"]);

    await userEvent.fill(page.getByRole("searchbox", { name: m.ui_filter() }), "bil");
    await expect.poll(rowNames).toEqual(["Protokoll", "Bilagor"]);
    expect(collapse.elements()).toHaveLength(0);
    expect(expand.elements()).toHaveLength(0);

    await userEvent.fill(page.getByRole("searchbox", { name: m.ui_filter() }), "");
    await expect.element(expand).toHaveAttribute("aria-expanded", "false");
    expect(rowNames()).toEqual(["Protokoll", "Rutiner"]);
  });
});
