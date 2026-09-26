// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testAppContext } from "@/test/render";
import type { Space } from "@/features/spaces/space";
import {
  makeCollection,
  makeIntegration,
  makeSpace,
  makeWebsite
} from "@/features/spaces/testing/space-fixture";

const state = vi.hoisted(() => ({
  space: null as unknown,
  tab: null as string | null,
  posted: [] as { path: string; body: unknown }[],
  deleted: [] as string[],
  bulkResult: { total: 0, queued: 0, failed: 0, crawl_runs: [], errors: [] } as unknown,
  toasts: [] as { kind: string; message: string; description?: string }[]
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: () => {}, prefetch: () => {} }),
  useSearchParams: () => new URLSearchParams(state.tab ? { tab: state.tab } : {})
}));
vi.mock("@/features/spaces/use-space", async () => {
  const { useSpaceFromQuery } = await import("@/features/spaces/testing/space-query");
  return { useSpace: () => useSpaceFromQuery(() => state.space as Space) };
});
vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    GET: () => Promise.resolve({ data: { items: [] }, response: new Response("{}") }),
    POST: (path: string, { body }: { body: unknown }) => {
      state.posted.push({ path, body });
      return Promise.resolve({ data: state.bulkResult, response: new Response("{}") });
    },
    DELETE: (path: string, { params }: { params: { path: { id: string } } }) => {
      state.deleted.push(`${path} ${params.path.id}`);
      return Promise.resolve({ data: null, response: new Response(null, { status: 204 }) });
    }
  }
}));
vi.mock("sonner", () => ({
  toast: {
    success: (message: string) => state.toasts.push({ kind: "success", message }),
    error: (message: string, options?: { description?: string }) =>
      state.toasts.push({ kind: "error", message, description: options?.description })
  }
}));
vi.mock("@/features/jobs/use-jobs", () => ({
  useJobs: () => ({ trackJob: () => {}, queueUploads: () => {} })
}));

import { KnowledgePage } from "./knowledge-page";

afterEach(() => {
  cleanup();
  state.posted = [];
  state.deleted = [];
  state.toasts = [];
});

function show(space: Space, tab: string | null = null) {
  state.space = space;
  state.tab = tab;
  return renderInApp(<KnowledgePage />, { appContext: testAppContext({ permissions: ["admin"] }) });
}

const liveRegion = () => document.querySelector("[data-astryx-live-region='polite']");

describe("KnowledgePage", () => {
  it("keeps the Kunskap heading and tabs, with one create button in an empty space", async () => {
    const { container } = show(makeSpace());

    expect(screen.getByRole("heading", { level: 2, name: "Kunskap" })).toBeTruthy();
    const tablist = screen.getByRole("tablist", { name: "Kunskapskällor" });
    expect(within(tablist).getAllByRole("tab")).toHaveLength(3);
    const collections = within(tablist).getByRole("tab", { name: "Samlingar" });
    expect(collections.getAttribute("aria-selected")).toBe("true");
    expect(within(tablist).getByRole("tab", { name: "Webbplatser" })).toBeTruthy();
    expect(within(tablist).getByRole("tab", { name: "Integrationer" })).toBeTruthy();
    expect(screen.getByRole("tabpanel", { name: "Samlingar" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Inga samlingar ännu" })).toBeTruthy();
    const create = screen.getAllByRole("button", { name: "Skapa samling" });
    expect(create).toHaveLength(1);
    await expectNoAxeViolations(container);

    fireEvent.click(create[0]!);
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByLabelText(/Namn/)).toBeTruthy();
  });

  it("lists collections in a bordered table with status and a named row menu", async () => {
    const { container } = show(
      makeSpace({
        collections: [
          makeCollection(),
          makeCollection({
            id: "c2",
            name: "Tom samling",
            metadata: { num_info_blobs: 0, size: 0 }
          })
        ]
      })
    );

    const table = screen.getByRole("table");
    const policy = within(table).getByRole("link", { name: "Upphandlingspolicy" }).closest("tr")!;
    expect(within(policy).getByText("42 filer")).toBeTruthy();
    expect(within(policy).getByText("Indexerad")).toBeTruthy();
    const empty = within(table).getByRole("link", { name: "Tom samling" }).closest("tr")!;
    expect(within(empty).getByText("Tom")).toBeTruthy();
    expect(
      within(policy).getByRole("button", { name: "Fler åtgärder för Upphandlingspolicy" })
    ).toBeTruthy();
    expect(screen.getByRole("textbox", { name: "Filtrera samlingar" })).toBeTruthy();
    await expectNoAxeViolations(container);
  });

  it("sorts collections by their column headers", () => {
    show(
      makeSpace({
        collections: [
          makeCollection({ id: "b", name: "Budget", metadata: { num_info_blobs: 3, size: 0 } }),
          makeCollection({ id: "a", name: "Ärenden", metadata: { num_info_blobs: 9, size: 0 } }),
          makeCollection({ id: "c", name: "Avtal", metadata: { num_info_blobs: 1, size: 0 } })
        ]
      })
    );
    const names = () =>
      within(screen.getByRole("table"))
        .getAllByRole("link")
        .map((link) => link.textContent);

    // Name, ascending, in Swedish order (Ä after Z).
    expect(names()).toEqual(["Avtal", "Budget", "Ärenden"]);
    expect(
      screen.getByRole("button", { name: "Sortera efter Namn, sorterat stigande" })
    ).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Sortera efter Innehåll" }));
    expect(names()).toEqual(["Avtal", "Budget", "Ärenden"]);
    fireEvent.click(
      screen.getByRole("button", { name: "Sortera efter Innehåll, sorterat stigande" })
    );
    expect(names()).toEqual(["Ärenden", "Budget", "Avtal"]);
  });

  it("shows website crawl states as status dots with text", async () => {
    const failed = makeWebsite({
      id: "w2",
      name: "Intranätet",
      latest_crawl: { ...(makeWebsite().latest_crawl as object), status: "failed" }
    });
    const { container } = show(
      makeSpace({ websites: [makeWebsite({ latest_crawl: null }), failed] }),
      "websites"
    );

    const table = screen.getByRole("table");
    // The same words as on the space overview.
    expect(within(table).getByText("Inte crawlad ännu")).toBeTruthy();
    expect(within(table).getByText("Synkfel")).toBeTruthy();
    expect(within(table).getAllByRole("link", { name: /Gå till webbplats/ })).toHaveLength(2);
    await expectNoAxeViolations(container);
  });

  it("selects websites for a bulk sync", () => {
    show(
      makeSpace({ websites: [makeWebsite(), makeWebsite({ id: "w2", name: "Intranätet" })] }),
      "websites"
    );
    expect(screen.getByRole("button", { name: "Anslut webbplats" })).toBeTruthy();

    fireEvent.click(screen.getByRole("checkbox", { name: "Markera Intranätet" }));
    expect(screen.getByRole("button", { name: "Synkronisera valda (1)" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Anslut webbplats" })).toBeNull();

    fireEvent.click(screen.getByRole("checkbox", { name: "Markera alla rader" }));
    expect(screen.getByRole("button", { name: "Synkronisera valda (2)" })).toBeTruthy();
  });

  it("lists integrations in a bordered table sorted by name, with folders and status dots", async () => {
    const { container } = show(
      makeSpace({
        integrations: [
          makeIntegration({ id: "i1", name: "Ärendehandbok", integration_type: "confluence" }),
          makeIntegration({
            id: "i2",
            name: "Avtalsmallar",
            metadata: { size: 0, last_synced_at: null, sharepoint_subscription_expires_at: null }
          }),
          makeIntegration({ id: "i3", name: "Mall 1", wrapper_id: "w1", wrapper_name: "Byggnad" }),
          makeIntegration({ id: "i4", name: "Mall 2", wrapper_id: "w1", wrapper_name: "Byggnad" })
        ]
      }),
      "integrations"
    );

    const table = await screen.findByRole("table");
    const names = () =>
      within(table)
        .getAllByRole("row")
        .slice(1)
        .map((row) => within(row).getAllByRole("cell")[0]!.textContent);
    // Name, ascending, in Swedish order (Ä after Z); the folder links to its page.
    expect(names()).toEqual(["Avtalsmallar", "Byggnad2 mappar", "Ärendehandbok"]);
    expect(within(table).getByRole("link", { name: "Byggnad" }).getAttribute("href")).toBe(
      "/spaces/space-1/knowledge/integrations/wrapper/w1"
    );
    const avtal = within(table).getByText("Avtalsmallar").closest("tr")!;
    expect(within(avtal).getByText("Ingen Webhook")).toBeTruthy();
    expect(
      within(avtal).getByRole("button", { name: /^Ingen synk registrerad ?, Synkhistorik$/ })
    ).toBeTruthy();
    // What the missing webhook means is text, not a hover-only tooltip.
    expect(within(avtal).getByText(/ändringar synkas inte automatiskt/)).toBeTruthy();
    expect(within(avtal).getByRole("link", { name: /Öppna i SharePoint/ })).toBeTruthy();
    expect(
      within(avtal).getByRole("button", { name: "Fler åtgärder för Avtalsmallar" })
    ).toBeTruthy();
    await expectNoAxeViolations(container);

    fireEvent.click(screen.getByRole("button", { name: "Sortera efter Status" }));
    expect(names()[0]).toBe("Avtalsmallar");
  });

  it("offers the next step for integrations in the empty state", () => {
    show(makeSpace(), "integrations");
    expect(screen.getByRole("heading", { name: "Inga integrationer ännu" })).toBeTruthy();
  });

  it("moves focus to the tab panel when a deleted collection's row goes away", async () => {
    show(makeSpace({ collections: [makeCollection()] }));
    // What the space holds once the collection is gone.
    state.space = makeSpace();

    const menuButton = screen.getByRole("button", { name: "Fler åtgärder för Upphandlingspolicy" });
    menuButton.focus();
    fireEvent.click(menuButton);
    fireEvent.click(await screen.findByRole("menuitem", { name: "Ta bort" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Radera samling" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Ta bort" }));

    await waitFor(() => expect(state.deleted).toEqual(["/api/v1/groups/{id}/ collection-1"]));
    await screen.findByRole("heading", { name: "Inga samlingar ännu" });
    await waitFor(() =>
      expect(document.activeElement).toBe(screen.getByRole("tabpanel", { name: "Samlingar" }))
    );
  });

  it("labels the move dialog's destination picker", async () => {
    show(makeSpace({ collections: [makeCollection()] }));
    fireEvent.click(screen.getByRole("button", { name: "Fler åtgärder för Upphandlingspolicy" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Flytta" }));
    const dialog = await screen.findByRole("dialog", { name: "Flytta samling" });
    expect(within(dialog).getByRole("combobox", { name: "Destination" })).toBeTruthy();
    await expectNoAxeViolations(dialog);
  });

  it("announces how many collections match the filter", async () => {
    show(
      makeSpace({
        collections: [makeCollection(), makeCollection({ id: "c2", name: "Avtal" })]
      })
    );
    fireEvent.change(screen.getByRole("textbox", { name: "Filtrera samlingar" }), {
      target: { value: "avtal" }
    });
    await waitFor(() => expect(liveRegion()?.textContent).toBe("1 träff"));
  });

  it("names each embedding model's table by its heading", () => {
    const other = { id: "embed-2", name: "text-embedding-3" };
    show(
      makeSpace({
        websites: [
          makeWebsite(),
          makeWebsite({ id: "w2", name: "Intranätet", embedding_model: other })
        ],
        overrides: {
          embedding_models: [
            { id: "embed-1", name: "multilingual-e5-large", nickname: null, is_deprecated: false },
            { ...other, nickname: null, is_deprecated: false }
          ]
        }
      }),
      "websites"
    );

    // Each group's "select all" checkbox is told apart by its table's name.
    const first = screen.getByRole("table", { name: "multilingual-e5-large" });
    const second = screen.getByRole("table", { name: "text-embedding-3" });
    expect(within(first).getByRole("checkbox", { name: "Markera alla rader" })).toBeTruthy();
    expect(within(second).getByRole("link", { name: "Intranätet" })).toBeTruthy();
  });

  it("syncs only the selected websites on screen and reports partial failures", async () => {
    show(
      makeSpace({ websites: [makeWebsite(), makeWebsite({ id: "w2", name: "Intranätet" })] }),
      "websites"
    );
    fireEvent.click(screen.getByRole("checkbox", { name: "Markera alla rader" }));
    expect(screen.getByRole("button", { name: "Synkronisera valda (2)" })).toBeTruthy();

    // The filter hides one of the two selected websites: it is not synced.
    fireEvent.change(screen.getByRole("textbox", { name: "Filtrera webbplatser" }), {
      target: { value: "intranät" }
    });
    state.bulkResult = {
      total: 1,
      queued: 0,
      failed: 1,
      crawl_runs: [],
      errors: [{ website_id: "w2", error: "Tidsgränsen överskreds" }]
    };
    fireEvent.click(screen.getByRole("button", { name: "Synkronisera valda (1)" }));

    await waitFor(() =>
      expect(state.posted).toEqual([
        { path: "/api/v1/websites/bulk/run/", body: { website_ids: ["w2"] } }
      ])
    );
    await waitFor(() =>
      expect(state.toasts).toEqual([
        { kind: "error", message: "0 köade, 1 misslyckades", description: "Tidsgränsen överskreds" }
      ])
    );
    expect(screen.getByRole("button", { name: "Anslut webbplats" })).toBeTruthy();
  });

  it("shows why crawls failed, what failed and when the next crawl runs", () => {
    const day = 24 * 60 * 60 * 1000;
    const daysAgo = (days: number) => new Date(Date.now() - days * day).toISOString();
    const crawl = (overrides: Record<string, unknown>) => ({
      ...(makeWebsite().latest_crawl as Record<string, unknown>),
      ...overrides
    });
    show(
      makeSpace({
        websites: [
          makeWebsite({
            id: "failed",
            name: "Trasig",
            latest_crawl: crawl({ status: "failed", result_location: "Tidsgränsen överskreds" })
          }),
          makeWebsite({
            id: "warnings",
            name: "Varningar",
            update_interval: "daily",
            latest_crawl: crawl({ pages_failed: 1, finished_at: daysAgo(1) })
          }),
          makeWebsite({
            id: "stale",
            name: "Gammal",
            update_interval: "never",
            latest_crawl: crawl({ finished_at: daysAgo(12) })
          }),
          makeWebsite({ id: "new", name: "Ny", latest_crawl: null })
        ]
      }),
      "websites"
    );

    const row = (name: string) => screen.getByRole("link", { name }).closest("tr")!;
    const cells = (name: string) => within(row(name)).getAllByRole("cell");
    // Status (visible detail, no tooltip), then Senast synkad, then Automatiska uppdateringar.
    expect(cells("Trasig")[3]!.textContent).toBe("SynkfelTidsgränsen överskreds");
    expect(cells("Trasig")[4]!.textContent).toBe("—");
    expect(cells("Varningar")[3]!.textContent).toBe(
      "Synkroniserad med varningar1 sida misslyckades"
    );
    expect(cells("Varningar")[5]!.textContent).toMatch(/^Varje dagNästa indexering: \d/);
    expect(cells("Gammal")[4]!.textContent).toMatch(/Över 10 dagar sedan$/);
    expect(cells("Gammal")[5]!.textContent).toBe("Aldrig");
    expect(cells("Ny")[5]!.textContent).toBe(
      "VeckovisNästa crawl schemaläggs efter första synkningen"
    );
    expect(screen.getByRole("table").querySelector("tbody [title]")).toBeNull();
  });

  it("explains a missing create permission in text instead of a tooltip", () => {
    show(makeSpace({ resourcePermissions: ["read"] }));
    expect(screen.queryByRole("button", { name: "Skapa samling" })).toBeNull();
    expect(
      screen.getByText(/Du har inte behörighet att lägga till samlingar/, { selector: "span" })
    ).toBeTruthy();
  });
});
