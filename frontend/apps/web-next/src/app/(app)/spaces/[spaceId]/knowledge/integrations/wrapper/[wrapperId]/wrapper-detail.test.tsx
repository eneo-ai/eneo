// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { router, setRoute } from "@/test/navigation";
import { renderInApp, renderToHtml } from "@/test/render";
import type { Space } from "@/features/spaces/space";

type Answer = { data?: unknown; error?: unknown; status?: number };
type Query = { offset?: number; limit?: number };

const state = vi.hoisted(() => ({
  space: null as unknown,
  progress: [] as unknown[],
  /** An item's skipped list; "error" fails the request, a promise answers when it settles. */
  skipped: {} as Record<string, unknown>,
  /** An item's documents, or a function of the requested page. */
  documents: {} as Record<string, unknown>,
  requests: [] as string[],
  /** Runs on a delete, e.g. to take the item out of the space. */
  onDelete: () => {}
}));

vi.mock("next/navigation", () => import("@/test/navigation"));
vi.mock("@/features/spaces/use-space", async () => {
  const { useSpaceFromQuery } = await import("@/features/spaces/testing/space-query");
  return { useSpace: () => useSpaceFromQuery(() => state.space as Space) };
});
vi.mock("@/features/jobs/use-jobs", () => ({
  useJobs: () => ({ trackJob: () => {}, queueUploads: () => {} })
}));
vi.mock("@/lib/api/browser", () => {
  const reply = async (answer: Answer | Promise<Answer>) => {
    const { data, error, status = error === undefined ? 200 : 500 } = await answer;
    return { data, error, response: new Response(null, { status }) };
  };
  const get = (
    path: string,
    options?: { params?: { path?: { integration_knowledge_id?: string }; query?: Query } }
  ): Answer | Promise<Answer> => {
    const itemId = options?.params?.path?.integration_knowledge_id ?? "";
    if (path === "/api/v1/spaces/{id}/knowledge/integrations/sync-progress/") {
      return { data: { items: state.progress } };
    }
    if (path.endsWith("/documents/skipped/")) {
      state.requests.push(`skipped ${itemId}`);
      const skipped = state.skipped[itemId];
      if (skipped === "error") return { error: { message: "Boom" } };
      if (skipped instanceof Promise) return skipped.then((data: unknown) => ({ data }));
      return { data: skipped ?? { items: [], total: 0, truncated: false, synced_at: null } };
    }
    if (path.endsWith("/documents/")) {
      state.requests.push(`documents ${itemId} ${options?.params?.query?.offset ?? 0}`);
      const documents = state.documents[itemId];
      return {
        data:
          typeof documents === "function"
            ? (documents as (query: Query) => unknown)(options?.params?.query ?? {})
            : (documents ?? { items: [], total_count: 0, limit: 50, offset: 0, total_size: 0 })
      };
    }
    return { data: { items: [], count: 0 } };
  };
  return {
    browserApi: {
      GET: (path: string, options?: Parameters<typeof get>[1]) => reply(get(path, options)),
      DELETE: () => {
        state.onDelete();
        return reply({ status: 204 });
      }
    }
  };
});

import { makeIntegration, makeSpace } from "@/features/spaces/testing/space-fixture";
import { WrapperDetail } from "./wrapper-detail.client";

afterEach(() => {
  cleanup();
  // Astryx keeps one live region on <body>: no announcement may carry over.
  document.querySelectorAll("[data-astryx-live-region]").forEach((region) => region.remove());
  state.progress = [];
  state.skipped = {};
  state.documents = {};
  state.requests = [];
  state.onDelete = () => {};
  vi.restoreAllMocks();
  window.history.replaceState(null, "", "/");
});

function liveRegion() {
  return document.querySelector("[data-astryx-live-region='polite']")?.textContent ?? "";
}

const folder = { wrapper_id: "w1", wrapper_name: "Byggnad" };

function show(
  items: Record<string, unknown>[],
  route = "/spaces/space-1/knowledge/integrations/wrapper/w1"
) {
  state.space = makeSpace({
    integrations: items.map((item) => makeIntegration({ ...folder, ...item }))
  });
  setRoute(route);
  return renderInApp(<WrapperDetail wrapperId="w1" />);
}

const mall = {
  id: "i1",
  name: "Mallar",
  folder_path: "/Mallar",
  metadata: {
    size: 0,
    last_sync_status: "success",
    last_synced_at: "2026-10-14T08:00:00Z",
    document_count: 12
  }
};
const protokoll = {
  id: "i2",
  name: "Protokoll",
  folder_path: "/Mallar/Protokoll",
  metadata: {
    size: 0,
    last_sync_status: "success",
    last_synced_at: "2026-10-14T08:00:00Z",
    document_count: 3
  }
};

describe("WrapperDetail", () => {
  it("shows the source with its folders, figures and the problems to look at", async () => {
    state.skipped.i1 = {
      items: [
        { file: "scan.pdf", reason: "No text layer (scanned document; OCR is not supported)" }
      ],
      total: 1,
      truncated: false,
      synced_at: "2026-10-14T08:00:00Z"
    };
    const { container } = show([mall, protokoll]);

    expect(screen.getByRole("heading", { level: 1, name: "Byggnad" })).toBeTruthy();
    const nav = screen.getByRole("navigation", { name: "Mappar" });
    expect(
      within(nav)
        .getByRole("link", { name: /Alla mappar/ })
        .getAttribute("aria-current")
    ).toBe("page");
    // The subfolder sits under its parent, which can be collapsed.
    fireEvent.click(within(nav).getByRole("button", { name: "Fäll ihop Mallar" }));
    expect(within(nav).queryByRole("link", { name: /Protokoll/ })).toBeNull();

    const overview = screen.getByRole("table", { name: "Mappar i Byggnad" });
    expect(within(overview).getByRole("link", { name: "Protokoll" }).getAttribute("href")).toBe(
      "/spaces/space-1/knowledge/integrations/wrapper/w1?folder=i2"
    );
    const searchable = screen.getByText("Sökbara dokument").closest("div")!;
    expect(within(searchable).getByText("15")).toBeTruthy();
    // The skipped list arrives after the first render.
    const problemsTab = screen.getByRole("tab", { name: /Problem/ });
    expect(await within(problemsTab).findByText("1")).toBeTruthy();
    await expectNoAxeViolations(container);
  });

  it("lists a chosen folder's documents and the files it could not read", async () => {
    state.documents.i1 = {
      items: [
        {
          id: "d1",
          title: "Avtalsmall.docx",
          relative_path: "/Mallar/Avtalsmall.docx",
          size: 2048,
          updated_at: "2026-10-01T08:00:00Z",
          source_metadata: []
        }
      ],
      total_count: 1,
      limit: 50,
      offset: 0,
      total_size: 2048
    };
    state.skipped.i1 = {
      items: [
        { file: "scan.pdf", reason: "No text layer (scanned document; OCR is not supported)" }
      ],
      total: 1,
      truncated: false,
      synced_at: "2026-10-14T08:00:00Z"
    };
    const { container } = show(
      [mall, protokoll],
      "/spaces/space-1/knowledge/integrations/wrapper/w1?folder=i1"
    );

    const documents = await screen.findByRole("table", { name: "Dokument i Mallar" });
    expect(within(documents).getByRole("button", { name: /Avtalsmall\.docx/ })).toBeTruthy();
    expect(within(documents).getByText("Sökbar")).toBeTruthy();
    await expectNoAxeViolations(container);

    fireEvent.click(await screen.findByRole("radio", { name: "Kunde inte läsas 1" }));
    const skipped = screen.getByRole("table", { name: "Filer i Mallar som inte gick att läsa" });
    expect(within(skipped).getByText("scan.pdf")).toBeTruthy();
    expect(
      within(skipped).getByText("Inget textlager (skannat dokument; OCR stöds inte)")
    ).toBeTruthy();
  });

  it("says when folders failed and leads to the problems", () => {
    show([
      mall,
      {
        ...protokoll,
        metadata: {
          ...protokoll.metadata,
          last_sync_status: "error",
          last_sync_error: "Graph timeout"
        }
      }
    ]);

    expect(screen.getByText("Senaste synken av 1 mapp misslyckades")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Visa problem" }).getAttribute("href")).toBe(
      "/spaces/space-1/knowledge/integrations/wrapper/w1?tab=problems"
    );

    // In the folder list each state has a shape of its own, not just a colour.
    const nav = screen.getByRole("navigation", { name: "Mappar" });
    const link = (path: string) => nav.querySelector<HTMLElement>(`a[title="${path}"]`)!;
    // The state's name is there for screen readers; the icon shows it to everyone else.
    expect(link("/Mallar/Protokoll").textContent).toContain("Synk misslyckades");
    expect(link("/Mallar/Protokoll").querySelector("svg")?.getAttribute("class")).toContain(
      "lucide-circle-x"
    );
    expect(link("/Mallar").querySelector("svg")?.getAttribute("class")).toContain(
      "lucide-circle-check"
    );
  });

  it("shows a running sync and, in its folder, the file being read", async () => {
    state.progress = [
      {
        integration_knowledge_id: "i1",
        sync_type: "full",
        phase: "processing",
        started_at: "2026-10-15T10:00:00Z",
        updated_at: "2026-10-15T10:01:00Z",
        total: 40,
        done: 10,
        indexed: 9,
        unchanged: 0,
        skipped: 1,
        deleted: 0,
        current: "Budget 2026.xlsx",
        recent: [{ name: "Plan.docx", outcome: "indexed" }]
      }
    ];
    show([mall, protokoll], "/spaces/space-1/knowledge/integrations/wrapper/w1?folder=i1");

    expect(await screen.findByRole("heading", { name: "Synk pågår" })).toBeTruthy();
    expect(screen.getByRole("progressbar", { name: "Synkförlopp för Byggnad" })).toBeTruthy();
    const live = screen.getByRole("region", { name: "Läses just nu" });
    expect(within(live).getByText("Budget 2026.xlsx")).toBeTruthy();
    expect(within(live).getByText("Plan.docx")).toBeTruthy();
  });
});

const NO_TEXT = "No text layer (scanned document; OCR is not supported)";

function skippedList(...files: string[]) {
  return {
    items: files.map((file) => ({ file, reason: NO_TEXT })),
    total: files.length,
    truncated: false,
    synced_at: "2026-10-14T08:00:00Z"
  };
}

/** A folder of `total()` documents, served a page at a time. */
function documentPages(total: () => number) {
  return ({ offset = 0, limit = 50 }: Query) => {
    const count = total();
    const length = Math.max(0, Math.min(limit, count - offset));
    return {
      items: Array.from({ length }, (_, index) => ({
        id: `d${offset + index + 1}`,
        title: `Dokument ${offset + index + 1}.docx`,
        relative_path: `/Mallar/Dokument ${offset + index + 1}.docx`,
        size: 1024,
        updated_at: null,
        source_metadata: []
      })),
      total_count: count,
      limit,
      offset,
      total_size: count * 1024
    };
  };
}

/** Every text the polite live region is given from now on, in order. */
function recordAnnouncements() {
  const said: string[] = [];
  let last = liveRegion();
  const observer = new MutationObserver(() => {
    const text = liveRegion();
    if (text && text !== last) said.push(text);
    last = text;
  });
  observer.observe(document.body, { childList: true, subtree: true, characterData: true });
  return { said, stop: () => observer.disconnect() };
}

/** Browsers move focus to <body> when the focused element becomes disabled; jsdom keeps it. */
function focusFixup() {
  act(() => {
    document.body.tabIndex = -1;
    document.body.focus();
    document.body.removeAttribute("tabindex");
  });
}

describe("WrapperDetail in Swedish", () => {
  const folders = [
    { ...mall, id: "a1", name: "Äldreomsorg", folder_path: "/Äldreomsorg" },
    { ...mall, id: "a2", name: "Vuxen", folder_path: "/Vuxen" },
    {
      ...mall,
      id: "a3",
      name: "Arkiv",
      folder_path: "/Arkiv",
      metadata: { ...mall.metadata, document_count: 2600 }
    }
  ];
  const folderOrder = (root: ParentNode) =>
    [...root.querySelectorAll("nav a[title]")].map((link) => link.getAttribute("title"));
  const overviewOrder = (root: ParentNode) =>
    [...root.querySelectorAll("table tbody tr")].map((row) => row.querySelector("a")?.textContent);

  it("orders the folders by the Swedish alphabet on the server and in the browser alike", () => {
    state.space = makeSpace({
      integrations: folders.map((item) => makeIntegration({ ...folder, ...item }))
    });
    setRoute("/spaces/space-1/knowledge/integrations/wrapper/w1");
    const server = document.createElement("div");
    server.innerHTML = renderToHtml(<WrapperDetail wrapperId="w1" />);
    const { container } = renderInApp(<WrapperDetail wrapperId="w1" />);

    for (const root of [server, container]) {
      expect(folderOrder(root)).toEqual(["/Arkiv", "/Vuxen", "/Äldreomsorg"]);
      expect(overviewOrder(root)).toEqual(["Arkiv", "Vuxen", "Äldreomsorg"]);
    }
  });

  it("writes document counts with the locale's digit grouping on the server and in the browser", () => {
    state.space = makeSpace({
      integrations: folders.map((item) => makeIntegration({ ...folder, ...item }))
    });
    setRoute("/spaces/space-1/knowledge/integrations/wrapper/w1");
    const html = renderToHtml(<WrapperDetail wrapperId="w1" />);
    renderInApp(<WrapperDetail wrapperId="w1" />);

    // 2 600 + 12 + 12, grouped with a no-break space as in Swedish (the
    // queries below see it as a plain space; not "2,624" as in English).
    expect(html).toContain("2\u00a0624");
    const searchable = screen.getByText("Sökbara dokument").closest("div")!;
    expect(within(searchable).getByText("2 624")).toBeTruthy();
    const arkiv = within(screen.getByRole("table", { name: "Mappar i Byggnad" }))
      .getByRole("link", { name: "Arkiv" })
      .closest("tr")!;
    expect(within(arkiv).getByText("2 600")).toBeTruthy();
  });
});

describe("WrapperDetail navigation", () => {
  it("opens Problems for an old link to the skipped files", () => {
    show([mall, protokoll], "/spaces/space-1/knowledge/integrations/wrapper/w1?tab=skipped");
    expect(screen.getByRole("tab", { name: /Problem/ }).getAttribute("aria-selected")).toBe("true");
  });

  it("switches tabs and folders in place and keeps real addresses on the folder links", async () => {
    const replaceState = vi.spyOn(window.history, "replaceState");
    const search = () => new URL(String(replaceState.mock.lastCall?.[2])).search;
    show([mall, protokoll]);

    fireEvent.click(screen.getByRole("tab", { name: "Aktivitet" }));
    expect(search()).toBe("?tab=activity");
    expect(screen.getByRole("tab", { name: "Aktivitet" }).getAttribute("aria-selected")).toBe(
      "true"
    );

    fireEvent.click(screen.getByRole("tab", { name: "Innehåll" }));
    const nav = screen.getByRole("navigation", { name: "Mappar" });
    const link = within(nav).getByRole("link", { name: /Protokoll/ });
    expect(link.getAttribute("href")).toBe(
      "/spaces/space-1/knowledge/integrations/wrapper/w1?folder=i2"
    );
    fireEvent.click(link);

    expect(await screen.findByRole("heading", { level: 2, name: "Protokoll" })).toBeTruthy();
    expect(link.getAttribute("aria-current")).toBe("page");
    expect(search()).toBe("?folder=i2");
    // No server navigation: the page and its metadata are not loaded again.
    expect(router.push).not.toHaveBeenCalled();
    expect(router.replace).not.toHaveBeenCalled();
  });

  it("goes back to the list after the last folder was deleted from its own menu", async () => {
    const only = { ...mall, permissions: ["read", "edit", "delete"] };
    show([only]);
    state.onDelete = () => {
      state.space = makeSpace();
    };

    fireEvent.click(screen.getByRole("button", { name: "Fler åtgärder för Mallar" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Ta bort" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Ta bort integrationskunskap" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Ta bort" }));

    await waitFor(() =>
      expect(router.push).toHaveBeenCalledWith("/spaces/space-1/knowledge?tab=integrations")
    );
  });
});

describe("WrapperDetail documents", () => {
  it("keeps focus in the folder when paging to the last page, and says what it shows", async () => {
    state.documents.i1 = documentPages(() => 60);
    show([mall, protokoll], "/spaces/space-1/knowledge/integrations/wrapper/w1?folder=i1");
    await screen.findByRole("button", { name: /Dokument 1\.docx/ });

    const next = screen.getByRole("button", { name: "Gå till nästa sida" });
    next.focus();
    fireEvent.click(next);

    expect(await screen.findByRole("button", { name: /Dokument 51\.docx/ })).toBeTruthy();
    expect(next.hasAttribute("disabled")).toBe(true);
    focusFixup();
    await waitFor(
      () => expect(document.activeElement).toBe(screen.getByRole("region", { name: "Mallar" })),
      { timeout: 1500 }
    );
    await waitFor(() => expect(liveRegion()).toBe("Visar 51–60 av 60"));
  });

  it("moves to the last page when a sync shrinks the folder under the current one", async () => {
    let total = 60;
    state.documents.i1 = documentPages(() => total);
    const { queryClient } = show(
      [mall, protokoll],
      "/spaces/space-1/knowledge/integrations/wrapper/w1?folder=i1"
    );
    await screen.findByRole("button", { name: /Dokument 1\.docx/ });
    fireEvent.click(screen.getByRole("button", { name: "Gå till nästa sida" }));
    await screen.findByRole("button", { name: /Dokument 51\.docx/ });
    await waitFor(() => expect(liveRegion()).toBe("Visar 51–60 av 60"));

    const announcements = recordAnnouncements();
    total = 40;
    await act(() => queryClient.invalidateQueries({ queryKey: ["integrations", "documents"] }));

    expect(await screen.findByRole("button", { name: /Dokument 40\.docx/ })).toBeTruthy();
    await waitFor(() => expect(liveRegion()).toBe("Visar 1–40 av 40"));
    announcements.stop();
    // Never an empty folder, never a range past the end.
    expect(screen.queryByText("Inga dokument kunde indexeras")).toBeNull();
    expect(announcements.said).toEqual(["Visar 1–40 av 40"]);
    // One page left: no pager.
    expect(screen.queryByRole("button", { name: "Gå till nästa sida" })).toBeNull();
  });
});

describe("WrapperDetail problems", () => {
  it("keeps the problems on screen while a finished sync's skipped list loads again", async () => {
    state.skipped.i1 = skippedList("scan.pdf");
    const { queryClient } = show(
      [mall, protokoll],
      "/spaces/space-1/knowledge/integrations/wrapper/w1?tab=problems"
    );
    expect(await screen.findByText("scan.pdf")).toBeTruthy();
    const fetches = () => state.requests.filter((request) => request === "skipped i1").length;
    expect(fetches()).toBe(1);

    // The space shows a new sync of Mallar; its skipped list is still on its way.
    let release: (value: unknown) => void = () => {};
    state.skipped.i1 = new Promise((resolve) => (release = resolve));
    state.space = makeSpace({
      integrations: [
        makeIntegration({
          ...folder,
          ...mall,
          metadata: { ...mall.metadata, last_synced_at: "2026-10-15T09:00:00Z" }
        }),
        makeIntegration({ ...folder, ...protokoll })
      ]
    });
    await act(() => queryClient.invalidateQueries({ queryKey: ["spaces", "space-1"] }));

    await waitFor(() => expect(fetches()).toBe(2));
    expect(screen.getByText("scan.pdf")).toBeTruthy();
    const skippedStat = screen.getByText("Hoppades över").closest("div")!;
    expect(within(skippedStat).getByText("1")).toBeTruthy();

    await act(async () => release(skippedList("ny.pdf", "annan.pdf")));
    expect(await screen.findByText("ny.pdf")).toBeTruthy();
    expect(within(skippedStat).getByText("2")).toBeTruthy();
    expect(fetches()).toBe(2);
  });

  it("moves focus to the panel once a retried list loaded and the retry button went", async () => {
    state.skipped.i2 = "error";
    show([mall, protokoll], "/spaces/space-1/knowledge/integrations/wrapper/w1?tab=problems");
    const retry = await screen.findByRole("button", { name: "Försök igen" });

    state.skipped.i2 = skippedList();
    retry.focus();
    fireEvent.click(retry);

    await waitFor(() => expect(screen.queryByRole("button", { name: "Försök igen" })).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("tabpanel")), {
      timeout: 1500
    });
  });

  it("shows failed folders politely: not again on every return from Problems, once when new", async () => {
    const failing = (item: typeof mall) => ({
      ...item,
      metadata: { ...item.metadata, last_sync_status: "error", last_sync_error: "Graph timeout" }
    });
    const { queryClient } = show([mall, failing(protokoll)]);
    expect(screen.getByText("Senaste synken av 1 mapp misslyckades")).toBeTruthy();
    expect(document.querySelector("[role='alert']")).toBeNull();

    fireEvent.click(screen.getByRole("tab", { name: /Problem/ }));
    fireEvent.click(screen.getByRole("tab", { name: "Innehåll" }));
    expect(screen.getByText("Senaste synken av 1 mapp misslyckades")).toBeTruthy();
    expect(liveRegion()).toBe("");

    // Another folder fails while the page is open.
    state.space = makeSpace({
      integrations: [failing(mall), failing(protokoll)].map((item) =>
        makeIntegration({ ...folder, ...item })
      )
    });
    await act(() => queryClient.invalidateQueries({ queryKey: ["spaces", "space-1"] }));
    await waitFor(() => expect(liveRegion()).toBe("Senaste synken av 2 mappar misslyckades"));
  });
});
