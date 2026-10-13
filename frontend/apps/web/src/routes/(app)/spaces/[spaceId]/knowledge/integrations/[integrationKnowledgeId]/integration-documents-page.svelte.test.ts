import type { IntegrationKnowledge } from "@eneo/eneo-js";
import { page } from "@vitest/browser/context";
import type { ComponentProps } from "svelte";
import { readable, writable } from "svelte/store";
import { render } from "vitest-browser-svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import "../../../../../../../app.css";
import { m } from "$lib/paraglide/messages";
import type {
  IntegrationDocumentsPage,
  IntegrationSkippedDocuments
} from "$lib/features/integrations/integrationDocuments";

const api = vi.hoisted(() => ({
  listDocuments: vi.fn(),
  listSkippedDocuments: vi.fn(),
  goto: vi.fn(),
  route: { url: new URL("http://localhost/spaces/space-1/knowledge/integrations/ik-a"), state: {} }
}));

vi.mock("$app/state", () => ({ page: api.route }));
vi.mock("$app/stores", () => ({ page: readable(api.route) }));
vi.mock("$app/navigation", () => ({
  afterNavigate: vi.fn(),
  beforeNavigate: vi.fn(),
  goto: api.goto,
  invalidate: vi.fn(),
  onNavigate: vi.fn(),
  pushState: vi.fn(),
  replaceState: vi.fn()
}));
vi.mock("$lib/core/Eneo", () => ({
  getEneo: () => ({
    integrations: {
      knowledge: {
        listDocuments: api.listDocuments,
        listSkippedDocuments: api.listSkippedDocuments,
        getSyncLogs: vi.fn()
      }
    },
    infoBlobs: { get: vi.fn() }
  })
}));
vi.mock("$lib/features/jobs/JobManager", () => ({
  jobCompletionEvents: writable(null),
  getJobManager: () => ({ startFastUpdatePolling: vi.fn() })
}));

function knowledge(id: string, name: string, wrapper = true): IntegrationKnowledge {
  return {
    id,
    name,
    integration_type: "sharepoint",
    folder_path: `/Shared Documents/${name}`,
    space_id: "space-1",
    url: `https://contoso.sharepoint.com/sites/ks/Shared%20Documents/${name}`,
    wrapper_id: wrapper ? "wrapper-1" : null,
    wrapper_name: wrapper ? "Kommunstyrelsen" : null,
    metadata: {
      size: 0,
      last_sync_status: "success",
      document_count: 1,
      last_synced_at: "2026-10-13T08:00:00Z"
    }
  } as IntegrationKnowledge;
}

const itemA = knowledge("ik-a", "Protokoll");
const itemB = knowledge("ik-b", "Rutiner", false);

const space = {
  id: "space-1",
  routeId: "space-1",
  name: "Kommunstyrelsen",
  personal: false,
  knowledge: { integrationKnowledge: [itemA, itemB] }
};
const currentSpace = writable(space);
vi.mock("$lib/features/spaces/SpacesManager", () => ({
  getSpacesManager: () => ({
    state: { currentSpace },
    refreshCurrentSpace: vi.fn(async () => {})
  })
}));

import DocumentsPage from "./+page.svelte";

function documents(title: string): IntegrationDocumentsPage {
  return {
    items: [
      {
        id: `${title}-1`,
        title,
        relative_path: "",
        url: null,
        size: 10,
        updated_at: "2026-10-13T08:00:00Z",
        source_metadata: []
      }
    ],
    total_count: 1,
    limit: 50,
    offset: 0,
    total_size: 10
  };
}

const skipped: IntegrationSkippedDocuments = {
  items: [],
  total: 0,
  truncated: false,
  synced_at: null
};

type PageData = ComponentProps<typeof DocumentsPage>["data"];

// The page reads only these fields of the layout chain's data.
function data(item: IntegrationKnowledge, title: string): PageData {
  return {
    currentSpace: space,
    knowledge: item,
    documents: documents(title),
    skipped,
    initialTab: "documents"
  } as unknown as PageData;
}

describe("integration documents page", () => {
  beforeEach(() => {
    api.listDocuments.mockReset();
    api.listSkippedDocuments.mockReset();
    currentSpace.set(space);
  });

  it("shows the item's documents and swaps them when the route moves to another item", async () => {
    const { rerender } = render(DocumentsPage, { data: data(itemA, "KS-1.pdf") });

    await expect.element(page.getByRole("heading", { level: 1 })).toHaveTextContent("Protokoll");
    await expect.element(page.getByText("KS-1.pdf")).toBeVisible();
    const crumbs = page.getByRole("navigation", { name: m.breadcrumb() }).getByRole("link");
    expect(crumbs.elements().map((link) => link.textContent?.trim())).toEqual([
      `←\u00a0${m.integrations()}`,
      "Kommunstyrelsen"
    ]);
    expect(crumbs.elements().map((link) => link.getAttribute("href"))).toEqual([
      "/spaces/space-1/knowledge?tab=integrations",
      "/spaces/space-1/knowledge/integrations/wrapper/wrapper-1"
    ]);

    await rerender({ data: data(itemB, "Rutin-1.pdf") });

    await expect.element(page.getByRole("heading", { level: 1 })).toHaveTextContent("Rutiner");
    await expect.element(page.getByText("Rutin-1.pdf")).toBeVisible();
    expect(page.getByText("KS-1.pdf").elements()).toHaveLength(0);
    expect(
      page
        .getByRole("navigation", { name: m.breadcrumb() })
        .getByRole("link")
        .elements()
        .map((link) => link.textContent?.trim())
    ).toEqual([`←\u00a0${m.integrations()}`]);
    expect(api.listDocuments).not.toHaveBeenCalled();
  });

  it("labels the source link after the item's integration", async () => {
    render(DocumentsPage, { data: data(itemA, "KS-1.pdf") });
    await expect
      .element(page.getByRole("link", { name: m.open_in_sharepoint() }))
      .toHaveAttribute("href", itemA.url as string);
  });
});
