// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { IntegrationKnowledge } from "@/features/knowledge/knowledge";
import type { KnowledgeOverview } from "@/features/knowledge/integrations/queries";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";

const api = vi.hoisted(() => ({ GET: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));

import { SourcesOverview } from "./sources-overview";

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
      last_synced_at: status === "never" ? null : "2026-10-14T08:00:00Z",
      ...(status === "never" ? { document_count: 0 } : {})
    }
  } as IntegrationKnowledge;
}

const social = { id: "s1", name: "Socialtjänsten", organization: false, can_open: true };
const org = { id: "s2", name: "Organisationen", organization: true, can_open: true };
// A shared space the admin is not a member of: its pages would refuse them.
const closed = { id: "s3", name: "Ekonomi", organization: false, can_open: false };
const wrapper = { wrapper_id: "w1", wrapper_name: "Socialförvaltningen" };

const overview: KnowledgeOverview = {
  items: [
    { space: org, knowledge: knowledge("a", "Intranätet") },
    { space: social, knowledge: knowledge("b", "Rutiner", wrapper) },
    { space: social, knowledge: knowledge("c", "Arkiv", wrapper, "error") }
  ],
  personal: { items: 4, failing: 1 }
};

function respond(data: KnowledgeOverview) {
  api.GET.mockImplementation((path: string) =>
    path === "/api/v1/admin/integrations/knowledge/"
      ? Promise.resolve({ data, response: new Response("{}") })
      : Promise.reject(new Error(`unexpected GET ${path}`))
  );
}

async function show() {
  const view = renderInApp(<SourcesOverview />);
  const table = await screen.findByRole("table", { name: "Källor i organisationen" });
  return { table, container: view.container };
}

function sourceLinks(table: HTMLElement): string[] {
  return within(table)
    .queryAllByRole("link")
    .map((link) => link.textContent?.trim() ?? "");
}

function stat(label: string): string {
  const term = screen.getByText(label, { selector: "dt" });
  return term.nextElementSibling?.textContent ?? "";
}

beforeEach(() => respond(overview));
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("SourcesOverview", () => {
  it("sums up the organisation's sources and lists those that need attention first", async () => {
    const { table, container } = await show();

    expect(stat("Källor")).toBe("2");
    expect(stat("Behöver åtgärd")).toBe("1 i 1 utrymme");
    expect(stat("Sökbara dokument")).toBe("30");
    // Personal spaces are counted, never listed.
    expect(stat("I personliga utrymmen")).toBe("4 1 med fel");
    expect(sourceLinks(table)).toEqual(["Socialförvaltningen", "Intranätet"]);

    const [, first, second] = within(table).getAllByRole("row");
    expect(within(first!).getByText("Behöver åtgärd")).toBeTruthy();
    // Why: the folder's first failure.
    expect(within(first!).getByText("Graph timeout")).toBeTruthy();
    expect(within(first!).getByText("2 mappar")).toBeTruthy();
    expect(within(second!).getByText("(Organisation)")).toBeTruthy();
    await expectNoAxeViolations(container);
  });

  it("links each source to its page in its space", async () => {
    const { table } = await show();

    expect(
      within(table).getByRole("link", { name: "Socialförvaltningen" }).getAttribute("href")
    ).toBe("/spaces/s1/knowledge/integrations/wrapper/w1");
    expect(within(table).getByRole("link", { name: "Intranätet" }).getAttribute("href")).toBe(
      "/spaces/organization/knowledge/integrations/a"
    );
  });

  it("narrows the list by status and by a search on source, folder or space", async () => {
    const { table } = await show();

    fireEvent.click(screen.getByRole("radio", { name: "Aktuella 1" }));
    await waitFor(() => expect(sourceLinks(table)).toEqual(["Intranätet"]));

    fireEvent.click(screen.getByRole("radio", { name: "Alla 2" }));
    const search = screen.getByRole("textbox", { name: "Sök källa, mapp eller utrymme" });
    fireEvent.change(search, { target: { value: "arkiv" } });
    await waitFor(() => expect(sourceLinks(table)).toEqual(["Socialförvaltningen"]));

    fireEvent.change(search, { target: { value: "organisationen" } });
    await waitFor(() => expect(sourceLinks(table)).toEqual(["Intranätet"]));

    fireEvent.change(search, { target: { value: "ekonomi" } });
    expect(await within(table).findByText("Inga resultat hittades")).toBeTruthy();
  });

  it("names a source of a space the admin cannot open without linking to it", async () => {
    respond({
      ...overview,
      items: [...overview.items, { space: closed, knowledge: knowledge("d", "Fakturor") }]
    });
    const { table, container } = await show();

    expect(within(table).getByText("Fakturor")).toBeTruthy();
    expect(within(table).queryByRole("link", { name: "Fakturor" })).toBeNull();
    expect(sourceLinks(table)).toEqual(["Socialförvaltningen", "Intranätet"]);
    await expectNoAxeViolations(container);
  });

  it("says why a source needs attention, in words for a refused sign-in", async () => {
    respond({
      ...overview,
      items: [
        ...overview.items,
        { space: closed, knowledge: knowledge("d", "Fakturor", {}, "error", CREDENTIALS) }
      ]
    });
    const { table } = await show();

    expect(within(table).getByText("Graph timeout")).toBeTruthy();
    const fakturor = within(table).getByText("Fakturor").closest("tr")!;
    expect(within(fakturor).getByText("Inloggningen till SharePoint har gått ut")).toBeTruthy();
    expect(within(table).queryByText(/credentials are invalid/)).toBeNull();
    expect(stat("Behöver åtgärd")).toBe("2 i 2 utrymmen");
  });

  it("says how many folders of a source still wait for their first sync", async () => {
    const nämnden = { wrapper_id: "w2", wrapper_name: "Nämnden" };
    respond({
      ...overview,
      items: [
        ...overview.items,
        { space: social, knowledge: knowledge("d", "Protokoll", nämnden) },
        { space: social, knowledge: knowledge("e", "Bilagor", nämnden, "never") }
      ]
    });
    const { table } = await show();

    const row = within(table).getByRole("link", { name: "Nämnden" }).closest("tr")!;
    expect(within(row).getByText("Aktuell")).toBeTruthy();
    expect(within(row).getByText("1 mapp väntar på sin första synk")).toBeTruthy();
  });

  it("orders spaces and sources by the Swedish alphabet, Å, Ä and Ö after Z", async () => {
    const space = (id: string, name: string) => ({ id, name, organization: false, can_open: true });
    respond({
      items: [
        { space: space("s1", "Äldreförvaltningen"), knowledge: knowledge("a", "Rutiner") },
        { space: space("s2", "Vård"), knowledge: knowledge("b", "Översikt") },
        { space: space("s2", "Vård"), knowledge: knowledge("c", "Arkiv") },
        { space: space("s3", "Barn"), knowledge: knowledge("d", "Protokoll") }
      ],
      personal: { items: 0, failing: 0 }
    });
    const { table } = await show();

    expect(sourceLinks(table)).toEqual(["Protokoll", "Arkiv", "Översikt", "Rutiner"]);
  });

  it("says so when no shared space has imported anything", async () => {
    respond({ items: [], personal: { items: 2, failing: 0 } });
    renderInApp(<SourcesOverview />);

    expect(
      await screen.findByText("Ingen kunskap har importerats till delade utrymmen än.")
    ).toBeTruthy();
    expect(stat("I personliga utrymmen")).toBe("2");
    expect(screen.queryByRole("table")).toBeNull();
  });
});
