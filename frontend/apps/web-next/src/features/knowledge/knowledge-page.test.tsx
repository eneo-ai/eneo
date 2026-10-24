// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
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
  progress: [] as unknown[],
  progressPolls: 0,
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
    GET: (path: string) => {
      if (path === "/api/v1/spaces/{id}/knowledge/integrations/sync-progress/") {
        state.progressPolls += 1;
      }
      return Promise.resolve({
        data:
          path === "/api/v1/spaces/{id}/"
            ? state.space
            : path === "/api/v1/spaces/{id}/knowledge/integrations/sync-progress/"
              ? { items: state.progress }
              : { items: [] },
        response: new Response("{}")
      });
    },
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
    info: (message: string) => state.toasts.push({ kind: "info", message }),
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
  // Astryx keeps one live region on <body>: no announcement may carry over.
  document.querySelectorAll("[data-astryx-live-region]").forEach((region) => region.remove());
  state.progress = [];
  state.progressPolls = 0;
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

    // One embedding model: no model headings, so the table takes the tab's name.
    const table = screen.getByRole("table", { name: "Samlingar" });
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

    const table = screen.getByRole("table", { name: "Webbplatser" });
    // The run's own state, as on the website page and the admin crawler page.
    expect(within(table).getByText("Inte indexerad ännu")).toBeTruthy();
    expect(within(table).getByText("Misslyckades")).toBeTruthy();
    expect(within(table).getAllByRole("link", { name: /Gå till webbplats/ })).toHaveLength(2);
    await expectNoAxeViolations(container);
  });

  it("updates a running website to indexed without reloading the page", async () => {
    const running = makeWebsite({
      latest_crawl: { ...(makeWebsite().latest_crawl as object), status: "in progress" }
    });
    show(makeSpace({ websites: [running] }), "websites");
    expect(screen.getByText("Pågår")).toBeTruthy();

    state.space = makeSpace({
      websites: [
        makeWebsite({
          latest_crawl: { ...(makeWebsite().latest_crawl as object), status: "complete" }
        })
      ]
    });
    expect(await screen.findByText("Klar", undefined, { timeout: 5_000 })).toBeTruthy();
  });

  it("selects websites for a bulk sync", () => {
    show(
      makeSpace({ websites: [makeWebsite(), makeWebsite({ id: "w2", name: "Intranätet" })] }),
      "websites"
    );
    expect(screen.getByRole("button", { name: "Anslut webbplats" })).toBeTruthy();

    fireEvent.click(screen.getByRole("checkbox", { name: "Markera Intranätet" }));
    expect(screen.getByRole("button", { name: "Synkronisera valda (1)" })).toBeTruthy();
    // The selection toolbar (Astryx TableSelectionToolbar) names the count and
    // offers "clear"; the tab's own actions stay where they were.
    const bulk = screen.getByRole("toolbar", { name: "Åtgärder för valda webbplatser" });
    expect(within(bulk).getByText("1 vald webbplats")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Anslut webbplats" })).toBeTruthy();

    fireEvent.click(screen.getByRole("checkbox", { name: "Markera alla rader" }));
    expect(screen.getByRole("button", { name: "Synkronisera valda (2)" })).toBeTruthy();
    expect(within(bulk).getByText("2 valda webbplatser")).toBeTruthy();

    fireEvent.click(within(bulk).getByRole("button", { name: "Rensa val" }));
    expect(screen.queryByRole("toolbar", { name: "Åtgärder för valda webbplatser" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Synkronisera valda (2)" })).toBeNull();
  });

  it("lists one row per source with its state, and leads to each source's page", async () => {
    const credentials =
      "SharePoint credentials are invalid or expired; an administrator must reconnect the integration";
    const { container } = show(
      makeSpace({
        integrations: [
          makeIntegration({
            id: "i1",
            name: "Ärendehandbok",
            integration_type: "confluence",
            metadata: { size: 0, last_synced_at: "2026-09-20T08:00:00Z", document_count: 5 }
          }),
          makeIntegration({
            id: "i2",
            name: "Avtalsmallar",
            metadata: { size: 0, last_synced_at: null, sharepoint_subscription_expires_at: null }
          }),
          makeIntegration({ id: "i3", name: "Mall 1", wrapper_id: "w1", wrapper_name: "Byggnad" }),
          makeIntegration({
            id: "i4",
            name: "Mall 2",
            wrapper_id: "w1",
            wrapper_name: "Byggnad",
            metadata: { size: 0, last_sync_status: "error", last_sync_error: credentials }
          })
        ]
      }),
      "integrations"
    );

    const table = await screen.findByRole("table", { name: "Integrationer" });
    const rows = () => within(table).getAllByRole("row").slice(1);
    const sources = () => rows().map((row) => within(row).getAllByRole("link")[0]!.textContent);
    // Name, ascending, in Swedish order (Ä after Z); a wrapper is one source.
    expect(sources()).toEqual(["Avtalsmallar", "Byggnad", "Ärendehandbok"]);
    expect(within(table).getByRole("link", { name: "Byggnad" }).getAttribute("href")).toBe(
      "/spaces/space-1/knowledge/integrations/wrapper/w1"
    );
    expect(within(table).getByRole("link", { name: "Avtalsmallar" }).getAttribute("href")).toBe(
      "/spaces/space-1/knowledge/integrations/i2"
    );
    const row = (name: string) => within(table).getByRole("link", { name }).closest("tr")!;
    expect(within(row("Avtalsmallar")).getByText("Väntar på första synken")).toBeTruthy();
    expect(within(row("Byggnad")).getByText("Behöver åtgärd")).toBeTruthy();
    expect(within(row("Byggnad")).getByText("2 mappar")).toBeTruthy();
    expect(within(row("Ärendehandbok")).getByText("Aktuell")).toBeTruthy();

    // Only the refused sign-in gets a banner: no space member can fix it. It is
    // not an assertive alert, read out again on every visit to the tab.
    expect(screen.getByText("1 källa uppdateras inte")).toBeTruthy();
    expect(document.querySelector("[role='alert']")).toBeNull();
    expect(screen.getByRole("link", { name: "Öppna källan" }).getAttribute("href")).toBe(
      "/spaces/space-1/knowledge/integrations/wrapper/w1?tab=problems"
    );
    await expectNoAxeViolations(container);

    fireEvent.click(screen.getByRole("radio", { name: "Behöver åtgärd 1" }));
    expect(sources()).toEqual(["Byggnad"]);
    fireEvent.click(screen.getByRole("radio", { name: "Alla 3" }));

    fireEvent.click(screen.getByRole("button", { name: "Sortera efter Status" }));
    expect(sources()[0]).toBe("Byggnad");
  });

  it("shows a running sync as progress on its source", async () => {
    state.progress = [
      {
        integration_knowledge_id: "i1",
        sync_type: "full",
        phase: "processing",
        started_at: "2026-10-15T10:00:00Z",
        updated_at: "2026-10-15T10:01:00Z",
        total: null,
        done: 3,
        indexed: 3,
        unchanged: 0,
        skipped: 0,
        deleted: 0
      }
    ];
    show(
      makeSpace({ integrations: [makeIntegration({ id: "i1", name: "Avtalsmallar" })] }),
      "integrations"
    );

    expect(
      await screen.findByRole("progressbar", { name: "Synkförlopp för Avtalsmallar" })
    ).toBeTruthy();
    expect(screen.getByText("Synkar · 3 klara")).toBeTruthy();
    const row = screen.getByRole("link", { name: "Avtalsmallar" }).closest("tr")!;
    expect(within(row).getByText("Uppdateras nu")).toBeTruthy();
  });

  it("sorts by the last update, or the last attempt for a source that never finished a sync", () => {
    show(
      makeSpace({
        integrations: [
          makeIntegration({
            id: "i1",
            name: "Avtal",
            metadata: { size: 0, last_synced_at: "2026-10-01T08:00:00Z", document_count: 1 }
          }),
          makeIntegration({
            id: "i2",
            name: "Bygglov",
            metadata: {
              size: 0,
              last_sync_status: "error",
              last_sync_error: "Graph timeout",
              last_sync_attempted_at: "2026-10-10T08:00:00Z"
            }
          }),
          makeIntegration({
            id: "i3",
            name: "Cirkulär",
            metadata: { size: 0, last_synced_at: "2026-10-05T08:00:00Z", document_count: 1 }
          })
        ]
      }),
      "integrations"
    );
    const table = screen.getByRole("table", { name: "Integrationer" });
    fireEvent.click(within(table).getByRole("button", { name: "Sortera efter Uppdaterad" }));
    const sources = within(table)
      .getAllByRole("row")
      .slice(1)
      .map((row) => within(row).getAllByRole("link")[0]!.textContent);
    expect(sources).toEqual(["Avtal", "Cirkulär", "Bygglov"]);
  });

  it("has one sign-in notice, status filter and search above every embedding model's table", async () => {
    const other = { id: "embed-2", name: "text-embedding-3" };
    const signInRefused = {
      size: 0,
      last_sync_status: "error",
      last_sync_error:
        "SharePoint credentials are invalid or expired; an administrator must reconnect the integration"
    };
    show(
      makeSpace({
        integrations: [
          makeIntegration({ id: "i1", name: "Avtal", metadata: signInRefused }),
          makeIntegration({
            id: "i2",
            name: "Bygglov",
            embedding_model: other,
            metadata: signInRefused
          }),
          makeIntegration({
            id: "i3",
            name: "Cirkulär",
            embedding_model: other,
            metadata: { size: 0, last_synced_at: "2026-10-01T08:00:00Z", document_count: 2600 }
          })
        ],
        overrides: {
          embedding_models: [
            { id: "embed-1", name: "multilingual-e5-large", nickname: null, is_deprecated: false },
            { ...other, nickname: null, is_deprecated: false }
          ]
        }
      }),
      "integrations"
    );
    const names = (table: HTMLElement) =>
      within(table)
        .getAllByRole("row")
        .slice(1)
        .map((row) => within(row).getAllByRole("link")[0]!.textContent);

    expect(screen.getAllByText("2 källor uppdateras inte")).toHaveLength(1);
    expect(screen.getAllByRole("radio", { name: /^Alla/ })).toHaveLength(1);
    expect(screen.getAllByRole("textbox", { name: "Filtrera integrationer" })).toHaveLength(1);
    const second = screen.getByRole("table", { name: "text-embedding-3" });
    expect(within(second).getByText("2 600")).toBeTruthy();

    // "Show them" filters every group and goes away; focus stays on the notice.
    const notice = screen.getByText("2 källor uppdateras inte").closest<HTMLElement>("[tabindex]")!;
    const showThem = screen.getByRole("button", { name: "Visa dem" });
    showThem.focus();
    fireEvent.click(showThem);
    expect(screen.queryByRole("button", { name: "Visa dem" })).toBeNull();
    await waitFor(() => expect(document.activeElement).toBe(notice));
    expect(names(screen.getByRole("table", { name: "multilingual-e5-large" }))).toEqual(["Avtal"]);
    expect(names(screen.getByRole("table", { name: "text-embedding-3" }))).toEqual(["Bygglov"]);

    // The search spans the groups; a group it empties is left out.
    fireEvent.change(screen.getByRole("textbox", { name: "Filtrera integrationer" }), {
      target: { value: "bygg" }
    });
    expect(screen.queryByRole("table", { name: "multilingual-e5-large" })).toBeNull();
    expect(names(screen.getByRole("table", { name: "text-embedding-3" }))).toEqual(["Bygglov"]);
    await expectNoAxeViolations(document.body);
  });

  it("keeps the status filter and a way back when the chosen filter no longer matches", async () => {
    const failing = { size: 0, last_sync_status: "error", last_sync_error: "Graph timeout" };
    const wrapped = { wrapper_id: "w1", wrapper_name: "Byggnad" };
    const { container, queryClient } = show(
      makeSpace({
        integrations: [
          makeIntegration({ id: "i1", name: "Mall 1", ...wrapped }),
          makeIntegration({ id: "i2", name: "Mall 2", ...wrapped }),
          makeIntegration({ id: "i3", name: "HR-handboken", metadata: failing })
        ]
      }),
      "integrations"
    );
    fireEvent.click(await screen.findByRole("radio", { name: "Behöver åtgärd 1" }));
    screen.getByRole("link", { name: "HR-handboken" }).focus();

    // The wrapper is deleted and HR-handboken recovers: one source, none failing.
    state.space = makeSpace({
      integrations: [
        makeIntegration({
          id: "i3",
          name: "HR-handboken",
          metadata: { size: 0, last_synced_at: "2026-10-14T08:00:00Z", document_count: 4 }
        })
      ]
    });
    await act(() => queryClient.invalidateQueries({ queryKey: ["spaces", "space-1"] }));

    const showAll = await screen.findByRole("button", { name: "Visa alla" });
    // The focused link went with the table; the filter in use takes focus, not <body>.
    await waitFor(() =>
      expect(document.activeElement).toBe(screen.getByRole("radio", { name: "Behöver åtgärd 0" }))
    );
    expect(screen.getByText("Inga källor matchar filtret.", { selector: "p" })).toBeTruthy();
    expect(screen.queryByText("Inga resultat hittades")).toBeNull();
    expect(screen.getByRole("radiogroup", { name: "Filtrera på status" })).toBeTruthy();
    await waitFor(() => expect(liveRegion()?.textContent).toBe("Inga källor matchar filtret."));
    await expectNoAxeViolations(container);

    showAll.focus();
    fireEvent.click(showAll);
    expect(screen.getByRole("link", { name: "HR-handboken" })).toBeTruthy();
    // The pressed button is gone; focus is on the filter now in use, which stays.
    const all = screen.getByRole("radio", { name: "Alla 1" });
    expect(document.activeElement).toBe(all);
    expect(all.getAttribute("aria-checked")).toBe("true");
    expect(screen.getByRole("radiogroup", { name: "Filtrera på status" })).toBeTruthy();
  });

  it("says when some folders of a source still wait for their first sync", () => {
    const wrapped = { wrapper_id: "w1", wrapper_name: "Byggnad" };
    show(
      makeSpace({
        integrations: [
          makeIntegration({
            id: "i1",
            name: "Mall 1",
            ...wrapped,
            metadata: { size: 0, last_synced_at: "2026-10-14T08:00:00Z", document_count: 4 }
          }),
          makeIntegration({
            id: "i2",
            name: "Mall 2",
            ...wrapped,
            metadata: { size: 0, last_synced_at: null }
          }),
          makeIntegration({
            id: "i3",
            name: "Avtal",
            metadata: { size: 0, last_synced_at: "2026-10-14T08:00:00Z", document_count: 2 }
          })
        ]
      }),
      "integrations"
    );

    const row = screen.getByRole("link", { name: "Byggnad" }).closest("tr")!;
    expect(within(row).getByText("Aktuell")).toBeTruthy();
    expect(within(row).getByText("1 mapp väntar på sin första synk")).toBeTruthy();

    fireEvent.click(screen.getByRole("radio", { name: "Väntar 1" }));
    const table = screen.getByRole("table", { name: "Integrationer" });
    expect(
      within(table)
        .getAllByRole("row")
        .slice(1)
        .map((tr) => within(tr).getAllByRole("link")[0]!.textContent)
    ).toEqual(["Byggnad"]);
  });

  it("sorts a source that syncs right now as the most recently updated", async () => {
    state.progress = [
      {
        integration_knowledge_id: "i1",
        sync_type: "delta",
        phase: "processing",
        started_at: "2026-10-15T10:00:00Z",
        updated_at: "2026-10-15T10:01:00Z",
        total: null,
        done: 1,
        indexed: 1,
        unchanged: 0,
        skipped: 0,
        deleted: 0
      }
    ];
    show(
      makeSpace({
        integrations: [
          makeIntegration({
            id: "i1",
            name: "Avtal",
            metadata: { size: 0, last_synced_at: "2026-10-01T08:00:00Z", document_count: 1 }
          }),
          makeIntegration({
            id: "i2",
            name: "Bygglov",
            metadata: { size: 0, last_synced_at: "2026-10-10T08:00:00Z", document_count: 1 }
          }),
          makeIntegration({
            id: "i3",
            name: "Cirkulär",
            metadata: { size: 0, last_synced_at: "2026-10-05T08:00:00Z", document_count: 1 }
          })
        ]
      }),
      "integrations"
    );
    const table = screen.getByRole("table", { name: "Integrationer" });
    await within(table).findByText("Uppdateras nu");

    fireEvent.click(within(table).getByRole("button", { name: "Sortera efter Uppdaterad" }));
    const sources = within(table)
      .getAllByRole("row")
      .slice(1)
      .map((row) => within(row).getAllByRole("link")[0]!.textContent);
    // Oldest first: Avtal synced last on 1 October, but it is updating now.
    expect(sources).toEqual(["Cirkulär", "Bygglov", "Avtal"]);
  });

  it("heads the empty result under the model groups' headings when the search empties them all", () => {
    const other = { id: "embed-2", name: "text-embedding-3" };
    show(
      makeSpace({
        integrations: [
          makeIntegration({ id: "i1", name: "Avtal" }),
          makeIntegration({ id: "i2", name: "Bygglov", embedding_model: other })
        ],
        overrides: {
          embedding_models: [
            { id: "embed-1", name: "multilingual-e5-large", nickname: null, is_deprecated: false },
            { ...other, nickname: null, is_deprecated: false }
          ]
        }
      }),
      "integrations"
    );
    expect(screen.getByRole("heading", { level: 3, name: "text-embedding-3" })).toBeTruthy();

    fireEvent.change(screen.getByRole("textbox", { name: "Filtrera integrationer" }), {
      target: { value: "ekonomi" }
    });

    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.getByRole("heading", { level: 3, name: "Inga resultat hittades" })).toBeTruthy();
  });

  it("announces a refused sign-in politely when it happens, not on every visit", async () => {
    const signInRefused = {
      size: 0,
      last_sync_status: "error",
      last_sync_error:
        "SharePoint credentials are invalid or expired; an administrator must reconnect the integration"
    };
    const avtal = makeIntegration({ id: "i1", name: "Avtal", metadata: signInRefused });
    const { queryClient } = show(
      makeSpace({ integrations: [avtal, makeIntegration({ id: "i2", name: "Bygglov" })] }),
      "integrations"
    );
    // Already there when the tab opened: the banner shows it, nothing is read out.
    expect(screen.getByText("1 källa uppdateras inte")).toBeTruthy();
    expect(liveRegion()?.textContent ?? "").toBe("");

    state.space = makeSpace({
      integrations: [avtal, makeIntegration({ id: "i2", name: "Bygglov", metadata: signInRefused })]
    });
    await act(() => queryClient.invalidateQueries({ queryKey: ["spaces", "space-1"] }));

    await waitFor(() => expect(liveRegion()?.textContent).toBe("2 källor uppdateras inte"));
  });

  it("polls the sync progress only on the integrations tab of a space with its own", async () => {
    const own = makeSpace({ integrations: [makeIntegration({ id: "i1", name: "Avtal" })] });
    show(own);
    expect(screen.getByRole("tab", { name: "Samlingar" }).getAttribute("aria-selected")).toBe(
      "true"
    );
    await act(async () => {});
    expect(state.progressPolls).toBe(0);

    fireEvent.click(screen.getByRole("tab", { name: "Integrationer" }));
    await waitFor(() => expect(state.progressPolls).toBe(1));
    cleanup();

    // Only a source shared in from another space: it syncs there.
    state.progressPolls = 0;
    show(
      makeSpace({ integrations: [makeIntegration({ id: "i9", space_id: "space-0" })] }),
      "integrations"
    );
    expect(screen.getByRole("heading", { name: "Inga integrationer ännu" })).toBeTruthy();
    await act(async () => {});
    expect(state.progressPolls).toBe(0);
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

  it("offers no move between spaces for a collection", async () => {
    show(makeSpace({ collections: [makeCollection()] }));
    fireEvent.click(screen.getByRole("button", { name: "Fler åtgärder för Upphandlingspolicy" }));
    await screen.findByRole("menuitem", { name: "Ta bort" });
    expect(screen.queryByRole("menuitem", { name: "Flytta" })).toBeNull();
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
        {
          kind: "error",
          message:
            "De valda synkroniseringarna kunde inte startas. Kontrollera statusen och försök igen.",
          description: undefined
        }
      ])
    );
    // The website that could not be synced stays selected, for a retry.
    expect(screen.getByRole("button", { name: "Synkronisera valda (1)" })).toBeTruthy();
  });

  it("stops selected crawls only within the visible filter", async () => {
    const running = (id: string, name: string) =>
      makeWebsite({
        id,
        name,
        latest_crawl: {
          ...(makeWebsite().latest_crawl as object),
          id: `run-${id}`,
          status: "in progress",
          phase: "running",
          outcome: null
        }
      });
    show(
      makeSpace({ websites: [running("w1", "Webben"), running("w2", "Intranätet")] }),
      "websites"
    );
    fireEvent.click(screen.getByRole("checkbox", { name: "Markera alla rader" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Filtrera webbplatser" }), {
      target: { value: "intranät" }
    });
    fireEvent.click(screen.getByRole("button", { name: "Stoppa valda (1)" }));
    const dialog = await screen.findByRole("alertdialog", {
      name: "Stoppa aktiva synkroniseringar? (1)"
    });
    state.bulkResult = {
      total: 1,
      stopped: 1,
      not_running: 0,
      failed: 0,
      crawl_runs: [],
      errors: []
    };
    fireEvent.click(within(dialog).getByRole("button", { name: "Stoppa" }));
    await waitFor(() =>
      expect(state.posted).toEqual([
        { path: "/api/v1/websites/bulk/stop/", body: { website_ids: ["w2"] } }
      ])
    );
  });

  it("stops every active crawl from the toolbar after a confirmation", async () => {
    const running = (id: string, name: string) =>
      makeWebsite({
        id,
        name,
        latest_crawl: {
          ...(makeWebsite().latest_crawl as object),
          id: `run-${id}`,
          status: "in progress",
          phase: "running",
          outcome: null
        }
      });
    show(
      makeSpace({ websites: [running("w1", "Intranätet"), makeWebsite({ id: "w2" })] }),
      "websites"
    );

    fireEvent.click(screen.getByRole("button", { name: "Stoppa alla aktiva (1)" }));
    const dialog = await screen.findByRole("alertdialog", {
      name: "Stoppa aktiva synkroniseringar? (1)"
    });
    state.bulkResult = {
      total: 1,
      stopped: 1,
      not_running: 0,
      failed: 0,
      crawl_runs: [],
      errors: []
    };
    fireEvent.click(within(dialog).getByRole("button", { name: "Stoppa" }));

    await waitFor(() =>
      expect(state.posted).toEqual([
        { path: "/api/v1/websites/bulk/stop/", body: { website_ids: ["w1"] } }
      ])
    );
    await waitFor(() =>
      expect(state.toasts).toEqual([{ kind: "success", message: "Skickade stoppbegäranden: 1." }])
    );
  });

  it("removes selected websites through the bulk endpoint and keeps the ones that wait for the crawler", async () => {
    show(
      makeSpace({ websites: [makeWebsite(), makeWebsite({ id: "w2", name: "Intranätet" })] }),
      "websites"
    );
    fireEvent.click(screen.getByRole("checkbox", { name: "Markera alla rader" }));
    fireEvent.click(screen.getByRole("button", { name: "Ta bort valda (2)" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Ta bort webbplatskällor? (2)" });
    state.bulkResult = {
      total: 2,
      deleted: 1,
      not_found: 0,
      failed: 1,
      errors: [{ website_id: "w2", error: "crawl_stop_requested" }]
    };
    fireEvent.click(within(dialog).getByRole("button", { name: "Ta bort källor" }));

    await waitFor(() =>
      expect(state.posted).toEqual([
        { path: "/api/v1/websites/bulk/delete/", body: { website_ids: ["website-1", "w2"] } }
      ])
    );
    await waitFor(() => expect(state.toasts.map((toast) => toast.kind)).toEqual(["info"]));
    expect(state.toasts[0]!.message).toMatch(/^Vissa källor togs bort\./);
    // The website the crawler still has to stop stays selected.
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Ta bort valda (1)" })).toBeTruthy()
    );
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
            latest_crawl: crawl({ status: "failed", failure_code: "timed_out" })
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
            last_indexed_at: daysAgo(12),
            latest_crawl: crawl({ finished_at: daysAgo(12) })
          }),
          makeWebsite({ id: "new", name: "Ny", latest_crawl: null })
        ]
      }),
      "websites"
    );

    const row = (name: string) => screen.getByRole("link", { name }).closest("tr")!;
    const cells = (name: string) => within(row(name)).getAllByRole("cell");
    // Status (visible detail, no tooltip), then Senast indexerad, then Automatiska uppdateringar.
    expect(cells("Trasig")[3]!.textContent).toBe(
      "MisslyckadesWebbplatsen svarade inte inom tidsgränsen. Försök igen senare.Visa detaljer"
    );
    expect(cells("Trasig")[4]!.textContent).toBe("—");
    // The failed pages link to the run's details.
    expect(cells("Varningar")[3]!.textContent).toBe("Delvis klarKunde inte indexeras:Sidor: 1");
    expect(
      within(cells("Varningar")[3]!).getByRole("button", {
        name: "Visa sidor som inte kunde indexeras (1)"
      })
    ).toBeTruthy();
    expect(cells("Varningar")[5]!.textContent).toMatch(/^Varje dagNästa indexering: \d/);
    expect(cells("Gammal")[4]!.textContent).toMatch(/Över 10 dagar sedan$/);
    expect(cells("Gammal")[5]!.textContent).toBe("Aldrig");
    expect(cells("Ny")[5]!.textContent).toBe(
      "VeckovisNästa indexering schemaläggs efter den första"
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

/*
 * Decision 9: a knowledge table keeps all its columns on a phone and scrolls
 * sideways in its own region, with its name held in view. Its short columns
 * are as wide as what they hold, so an iPad held upright shows it whole.
 */
describe("knowledge tables on phones and tablets", () => {
  // What an iPad held upright (820 px) leaves a space's table: the page's
  // 24 px insets and the frame's border.
  const IPAD_PORTRAIT_WIDTH = 770;
  // Headers of the columns held in view (Astryx offsets them from the start).
  const pinned = (table: HTMLElement) =>
    within(table)
      .getAllByRole("columnheader")
      .filter((cell) => cell.style.insetInlineStart)
      .map((cell) => cell.textContent);
  const minWidth = (table: HTMLElement) => Number.parseFloat(table.style.minWidth);

  it("holds a collection's name in view and fits an iPad", () => {
    show(makeSpace({ collections: [makeCollection()] }));
    const table = screen.getByRole("table", { name: "Samlingar" });
    expect(pinned(table)).toEqual(["Namn"]);
    expect(minWidth(table)).toBeLessThanOrEqual(IPAD_PORTRAIT_WIDTH);
  });

  it("holds a website's checkbox and name in view and fits an iPad", () => {
    show(makeSpace({ websites: [makeWebsite()] }), "websites");
    const table = screen.getByRole("table", { name: "Webbplatser" });
    expect(pinned(table)).toEqual([expect.stringContaining("Markera alla rader"), "Webbplats"]);
    expect(minWidth(table)).toBeLessThanOrEqual(IPAD_PORTRAIT_WIDTH);
  });

  it("holds a source's name in view and fits an iPad", async () => {
    show(makeSpace({ integrations: [makeIntegration()] }), "integrations");
    const table = await screen.findByRole("table", { name: "Integrationer" });
    expect(pinned(table)).toEqual(["Källa"]);
    expect(minWidth(table)).toBeLessThanOrEqual(IPAD_PORTRAIT_WIDTH);
  });
});
