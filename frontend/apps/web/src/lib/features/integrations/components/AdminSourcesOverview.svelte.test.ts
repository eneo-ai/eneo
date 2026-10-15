import type { Eneo, IntegrationKnowledge } from "@eneo/eneo-js";
import { page } from "vitest/browser";
import { render } from "vitest-browser-svelte";
import { describe, expect, it, vi } from "vitest";
import "../../../../app.css";
import { m } from "$lib/paraglide/messages";
import { expectNoAxeViolations } from "$lib/test/axe";
import AdminSourcesOverview from "./AdminSourcesOverview.svelte";

const CREDENTIALS =
  "SharePoint credentials are invalid or expired; an administrator must reconnect the integration";

function knowledge(
  id: string,
  name: string,
  fields: Partial<IntegrationKnowledge> = {},
  status = "success",
  error = "Graph timeout"
): IntegrationKnowledge {
  return {
    id,
    name,
    integration_type: "sharepoint",
    selected_item_type: "folder",
    wrapper_id: null,
    wrapper_name: null,
    embedding_model: { id: "model" },
    ...fields,
    metadata: {
      size: 0,
      document_count: 10,
      last_sync_status: status,
      last_sync_error: status === "error" ? error : null,
      last_synced_at: "2026-10-14T08:00:00Z"
    }
  } as IntegrationKnowledge;
}

const social = { id: "s1", name: "Socialtjänsten", organization: false, can_open: true };
const org = { id: "s2", name: "Organisationen", organization: true, can_open: true };
// A shared space the admin is not a member of: its pages would refuse them.
const closed = { id: "s3", name: "Ekonomi", organization: false, can_open: false };

type OverviewItem = { space: typeof social; knowledge: IntegrationKnowledge };

function show(extra: OverviewItem[] = []) {
  const knowledgeOverview = vi.fn(async () => ({
    items: [
      ...extra,
      { space: org, knowledge: knowledge("a", "Intranätet") },
      {
        space: social,
        knowledge: knowledge("b", "Rutiner", {
          wrapper_id: "w1",
          wrapper_name: "Socialförvaltningen"
        })
      },
      {
        space: social,
        knowledge: knowledge(
          "c",
          "Arkiv",
          { wrapper_id: "w1", wrapper_name: "Socialförvaltningen" },
          "error"
        )
      }
    ],
    personal: { items: 4, failing: 1 }
  }));
  render(AdminSourcesOverview, {
    eneo: { integrations: { admin: { knowledgeOverview } } } as unknown as Eneo
  });
  return knowledgeOverview;
}

function sourceLinks() {
  return page
    .getByRole("table", { name: m.admin_sources_heading() })
    .getByRole("link")
    .elements()
    .map((link) => link.textContent?.trim());
}

describe("AdminSourcesOverview", () => {
  it("sums up the organisation's sources and lists those that need attention first", async () => {
    show();

    await expect.element(page.getByText(m.admin_sources_in_spaces_one())).toBeVisible();
    await expect
      .element(page.getByText(m.admin_sources_personal_failing({ count: 1 })))
      .toBeVisible();
    expect(sourceLinks()).toEqual(["Socialförvaltningen", "Intranätet"]);
    await expect
      .element(page.getByRole("link", { name: "Socialförvaltningen" }))
      .toHaveAttribute("href", "/spaces/s1/knowledge/integrations/wrapper/w1");
    await expectNoAxeViolations();
  });

  it("names a source of a space the admin cannot open without linking to it", async () => {
    show([{ space: closed, knowledge: knowledge("d", "Fakturor", {}, "error", CREDENTIALS) }]);

    await expect.element(page.getByText("Fakturor")).toBeVisible();
    expect(page.getByRole("link", { name: "Fakturor" }).elements()).toHaveLength(0);
    expect(sourceLinks()).toEqual(["Socialförvaltningen", "Intranätet"]);
    await expect
      .element(page.getByText(m.admin_sources_in_spaces_other({ count: 2 })))
      .toBeVisible();
    await expectNoAxeViolations();
  });

  it("says why a source needs attention, in words for a refused sign-in", async () => {
    show([{ space: closed, knowledge: knowledge("d", "Fakturor", {}, "error", CREDENTIALS) }]);

    const table = page.getByRole("table", { name: m.admin_sources_heading() });
    await expect.element(table.getByText("Graph timeout")).toBeVisible();
    await expect.element(table.getByText(m.integration_problem_credentials_title())).toBeVisible();
    expect(table.getByText(/credentials are invalid/).elements()).toHaveLength(0);
  });

  it("narrows the list by status and by a search on source, folder or space", async () => {
    show();
    await expect.element(page.getByRole("link", { name: "Intranätet" })).toBeVisible();

    await page.getByRole("button", { name: m.integration_filter_ok({ count: 1 }) }).click();
    await expect.poll(sourceLinks).toEqual(["Intranätet"]);

    await page.getByRole("button", { name: m.integration_filter_all({ count: 2 }) }).click();
    await page.getByRole("searchbox", { name: m.admin_sources_search() }).fill("arkiv");
    await expect.poll(sourceLinks).toEqual(["Socialförvaltningen"]);
  });

  it("says how many folders of a source still wait for their first sync", async () => {
    const folder = { wrapper_id: "w2", wrapper_name: "Nämnden" };
    const waiting = knowledge("e", "Bilagor", folder);
    waiting.metadata = {
      ...waiting.metadata,
      last_sync_status: "never",
      last_synced_at: null,
      document_count: 0
    } as IntegrationKnowledge["metadata"];
    show([
      { space: social, knowledge: knowledge("d", "Protokoll", folder) },
      { space: social, knowledge: waiting }
    ]);

    await expect
      .element(page.getByRole("row").filter({ hasText: "Nämnden" }))
      .toHaveTextContent(m.integration_source_waiting_one());
  });
});
