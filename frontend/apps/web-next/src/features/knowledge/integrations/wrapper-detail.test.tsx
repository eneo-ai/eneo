// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import type { QueryClient } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { router, setRoute } from "@/test/navigation";
import { renderInApp, renderToHtml, testQueryClient } from "@/test/render";
import type { Space } from "@/features/spaces/space";

type Answer = { data?: unknown; error?: unknown; status?: number };
type Query = { offset?: number; limit?: number; skip?: number };

const state = vi.hoisted(() => ({
  space: null as unknown,
  /** The running syncs; a promise answers when it settles. */
  progress: [] as unknown[] | Promise<unknown[]>,
  /** An item's skipped list; "error" fails the request, a promise answers when it settles. */
  skipped: {} as Record<string, unknown>,
  /** An item's documents, or a function of the requested page (a promise answers when it settles). */
  documents: {} as Record<string, unknown>,
  /** An item's sync logs, newest first. */
  logs: {} as Record<string, unknown[]>,
  requests: [] as string[],
  /** The items a full sync was started for; listed here, they are refused. */
  synced: [] as string[],
  refuseSync: [] as string[],
  /** Runs on a delete, e.g. to take the item out of the space. */
  onDelete: () => {}
}));
const toasts = vi.hoisted(() => ({
  success: vi.fn(),
  info: vi.fn(),
  warning: vi.fn(),
  error: vi.fn()
}));
vi.mock("@/lib/toast", () => ({ toast: toasts }));

vi.mock("@/lib/navigation", () => import("@/test/navigation"));
/** The props each next/link gets: Astryx's links too, through the app's LinkProvider. */
const links = vi.hoisted(() => [] as Record<string, unknown>[]);
vi.mock("@/lib/link", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/link")>();
  const { createElement } = await import("react");
  return {
    default: (props: Record<string, unknown>) => {
      links.push(props);
      return createElement(
        actual.default,
        props as unknown as Parameters<typeof actual.default>[0]
      );
    }
  };
});
vi.mock("@/features/spaces/use-space", async () => {
  const { useSpaceFromQuery } = await import("@/features/spaces/testing/space-query");
  return { useSpace: () => useSpaceFromQuery(() => state.space as Space) };
});
const jobs = vi.hoisted(() => ({ trackJob: vi.fn(), queueUploads: () => {} }));
vi.mock("@/features/jobs/use-jobs", () => ({ useJobs: () => jobs }));
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
      return Promise.resolve(state.progress).then((items) => ({ data: { items } }));
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
      const data =
        typeof documents === "function"
          ? (documents as (query: Query) => unknown)(options?.params?.query ?? {})
          : (documents ?? { items: [], total_count: 0, limit: 50, offset: 0, total_size: 0 });
      return data instanceof Promise ? data.then((value: unknown) => ({ data: value })) : { data };
    }
    if (path === "/api/v1/integrations/sync-logs/{integration_knowledge_id}/") {
      state.requests.push(`logs ${itemId}`);
      const { skip = 0, limit = 10 } = options?.params?.query ?? {};
      const logs = state.logs[itemId] ?? [];
      return { data: { items: logs.slice(skip, skip + limit), total_count: logs.length } };
    }
    return { data: { items: [], count: 0 } };
  };
  return {
    browserApi: {
      GET: (path: string, options?: Parameters<typeof get>[1]) => reply(get(path, options)),
      DELETE: () => {
        state.onDelete();
        return reply({ status: 204 });
      },
      POST: (
        path: string,
        options?: {
          params?: { path?: { integration_knowledge_id?: string } };
          body?: { items: { integration_knowledge_id: string; offset: number }[]; limit: number };
        }
      ) => {
        if (path.endsWith("/sync-details/")) {
          return reply(
            (async () => {
              const items = [];
              for (const request of options?.body?.items ?? []) {
                const itemId = request.integration_knowledge_id;
                const skipped =
                  request.offset === 0
                    ? await get("/documents/skipped/", {
                        params: { path: { integration_knowledge_id: itemId } }
                      })
                    : { data: null };
                if (skipped.error) return skipped;
                const history = await get(
                  "/api/v1/integrations/sync-logs/{integration_knowledge_id}/",
                  {
                    params: {
                      path: { integration_knowledge_id: itemId },
                      query: { skip: request.offset, limit: options?.body?.limit }
                    }
                  }
                );
                items.push({
                  integration_knowledge_id: itemId,
                  history: {
                    ...(history.data as object),
                    offset: request.offset,
                    limit: options?.body?.limit
                  },
                  skipped: skipped.data
                });
              }
              return { data: { items } };
            })()
          );
        }
        const itemId = options?.params?.path?.integration_knowledge_id ?? "";
        if (!path.endsWith("/sync/")) return reply({ error: { message: `unexpected ${path}` } });
        state.synced.push(itemId);
        return reply(
          state.refuseSync.includes(itemId)
            ? {
                error: {
                  message:
                    "Admin permission is required to sync organization-wide SharePoint integrations.",
                  eneo_error_code: 9001
                },
                status: 403
              }
            : { data: { id: `job-${itemId}`, name: itemId, status: "queued" }, status: 202 }
        );
      }
    }
  };
});

import { WrapperActions } from "@/features/knowledge/integrations/actions";
import { resetPendingSyncs, trackSyncs } from "@/features/knowledge/integrations/pending-syncs";
import type { LoadedItems } from "@/features/knowledge/integrations/use-source-items";
import type { IntegrationKnowledge } from "@/features/knowledge/knowledge";
import { makeIntegration, makeSpace } from "@/features/spaces/testing/space-fixture";
import { WrapperDetail } from "@/features/knowledge/integrations/wrapper-detail.client";

afterEach(() => {
  cleanup();
  // Astryx keeps one live region on <body>: no announcement may carry over.
  document.querySelectorAll("[data-astryx-live-region]").forEach((region) => region.remove());
  state.progress = [];
  state.skipped = {};
  state.documents = {};
  state.logs = {};
  state.requests = [];
  state.synced = [];
  state.refuseSync = [];
  for (const shown of Object.values(toasts)) shown.mockClear();
  jobs.trackJob.mockClear();
  state.onDelete = () => {};
  links.length = 0;
  resetPendingSyncs();
  vi.restoreAllMocks();
  window.history.replaceState(null, "", "/");
});

/** Headers of the columns held in view (Astryx offsets them from the start). */
function pinnedHeaders(table: HTMLElement) {
  return within(table)
    .getAllByRole("columnheader")
    .filter((cell) => cell.style.insetInlineStart)
    .map((cell) => cell.textContent);
}

function liveRegion() {
  return document.querySelector("[data-astryx-live-region='polite']")?.textContent ?? "";
}

const folder = { wrapper_id: "w1", wrapper_name: "Byggnad" };

const WRAPPER_PAGE = "/spaces/space-1/knowledge/integrations/wrapper/w1";

/** The wrapper's items as the server page found them. */
function served(space = state.space as Space): LoadedItems {
  return {
    items: space.knowledge.integration_knowledge_list.items.filter(
      (item) => item.wrapper_id === "w1"
    )
  };
}

function show(items: Record<string, unknown>[], route = WRAPPER_PAGE) {
  state.space = makeSpace({
    integrations: items.map((item) => makeIntegration({ ...folder, ...item }))
  });
  setRoute(route);
  return renderInApp(<WrapperDetail wrapperId="w1" loaded={served()} />);
}

const job = (itemId: string) => ({ id: `job-${itemId}`, name: itemId, status: "queued" });

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
        {
          file: "scan.pdf",
          reason: "No text layer (scanned document; OCR is not supported)",
          code: "no_text_layer",
          params: {},
          retry: false
        }
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
    // The folder stays in view while its row scrolls sideways on a phone.
    expect(pinnedHeaders(overview)).toEqual(["Mapp"]);
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
        {
          file: "scan.pdf",
          reason: "No text layer (scanned document; OCR is not supported)",
          code: "no_text_layer",
          params: {},
          retry: false
        }
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
    expect(pinnedHeaders(documents)).toEqual(["Namn"]);
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
    // A link that switches this page's view is never prefetched; one that leaves it may be.
    const prefetch = (href: string) =>
      new Set(links.filter((props) => props.href === href).map((props) => props.prefetch));
    expect(prefetch("/spaces/space-1/knowledge/integrations/wrapper/w1?tab=problems")).toEqual(
      new Set([false])
    );
    expect(prefetch("/spaces/space-1/knowledge/integrations/wrapper/w1?folder=i2")).toEqual(
      new Set([false])
    );
    expect(prefetch("/spaces/space-1/knowledge?tab=integrations")).toEqual(new Set([undefined]));

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
        recent: [
          { name: "Plan.docx", outcome: "indexed" },
          {
            name: "Ritning.pdf",
            outcome: "skipped",
            reason: "No text layer (scanned document; OCR is not supported)",
            code: "no_text_layer"
          }
        ]
      }
    ];
    show([mall, protokoll], "/spaces/space-1/knowledge/integrations/wrapper/w1?folder=i1");

    expect(await screen.findByRole("heading", { name: "Synk pågår" })).toBeTruthy();
    expect(screen.getByRole("progressbar", { name: "Synkförlopp för Byggnad" })).toBeTruthy();
    const live = screen.getByRole("region", { name: "Läses just nu" });
    expect(within(live).getByText("Budget 2026.xlsx")).toBeTruthy();
    expect(within(live).getByText("Plan.docx")).toBeTruthy();
    // Why a file was skipped is there for everyone to read, not only screen readers.
    const reason = within(live).getByText("Inget textlager (skannat dokument; OCR stöds inte)");
    expect(reason.closest(".sr-only")).toBeNull();
    // A finished step says so in one phrase, its "done" for screen readers only.
    const steps = screen.getByRole("list", { name: "Synkens steg" });
    const [found] = within(steps).getAllByRole("listitem");
    expect(found?.textContent).toBe("Klart: Hitta filer");
    expect(within(found!).getByText("Klart:").className).toContain("sr-only");
  });

  it("says when a folder was last up to date in one phrase", () => {
    show([mall, protokoll], `${WRAPPER_PAGE}?folder=i1`);
    const heading = screen.getByRole("heading", { level: 2, name: "Mallar" });
    const line = heading.parentElement!;
    expect(within(line).getByText(/^Aktuell 14 okt\. 2026 \d{1,2}:\d{2}$/)).toBeTruthy();
  });

  it("shows a one-folder source's link and actions once, in the page header", () => {
    show([mall]);

    expect(screen.getAllByRole("link", { name: /Öppna i SharePoint/ })).toHaveLength(1);
    expect(screen.getAllByRole("button", { name: /^Fler åtgärder för/ })).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Fler åtgärder för Byggnad" })).toBeTruthy();
    // The folder's own heading stays, with its state.
    expect(screen.getByRole("heading", { level: 2, name: "Mallar" })).toBeTruthy();
  });

  it("says per folder whether SharePoint reports its changes", async () => {
    const hours = (count: number) => new Date(Date.now() + count * 3_600_000).toISOString();
    const watched = (item: typeof mall, expires: string | null) => ({
      ...item,
      metadata: { ...item.metadata, sharepoint_subscription_expires_at: expires }
    });
    show([watched(mall, hours(72)), watched(protokoll, hours(-2))]);

    const overview = screen.getByRole("table", { name: "Mappar i Byggnad" });
    expect(within(overview).getByRole("columnheader", { name: "Ändringsbevakning" })).toBeTruthy();
    const row = (name: string) => within(overview).getByRole("link", { name }).closest("tr")!;
    expect(within(row("Mallar")).getByText("På")).toBeTruthy();
    expect(within(row("Protokoll")).getByText("Har gått ut")).toBeTruthy();
    const stat = screen.getByText("Ändringsbevakning", { selector: "dt" }).nextElementSibling!;
    expect(within(stat as HTMLElement).getByText("1 bevakning har gått ut")).toBeTruthy();

    fireEvent.click(within(overview).getByRole("link", { name: "Protokoll" }));
    expect(await screen.findByText("Ändringsbevakning: Har gått ut")).toBeTruthy();
  });

  it("says when folders' change notifications are about to be renewed", () => {
    const inHours = new Date(Date.now() + 24 * 3_600_000).toISOString();
    const expiring = (item: typeof mall) => ({
      ...item,
      metadata: { ...item.metadata, sharepoint_subscription_expires_at: inHours }
    });
    show([expiring(mall), expiring(protokoll)]);

    const stat = screen.getByText("Ändringsbevakning", { selector: "dt" }).nextElementSibling!;
    expect(stat.textContent).toContain("På");
    expect(
      within(stat as HTMLElement).getByText("2 går ut inom 48 timmar och förnyas automatiskt")
    ).toBeTruthy();
    const overview = screen.getByRole("table", { name: "Mappar i Byggnad" });
    expect(within(overview).getAllByText("På, förnyas inom 48 timmar")).toHaveLength(2);
  });

  it("links to an item or document at its source only over https", async () => {
    state.documents.i1 = {
      items: [
        {
          id: "d1",
          title: "Avtalsmall.docx",
          relative_path: "/Mallar/Avtalsmall.docx",
          size: 2048,
          updated_at: null,
          url: "https://kommun.sharepoint.com/sites/avtal/Avtalsmall.docx",
          source_metadata: []
        },
        {
          id: "d2",
          title: "Gammal.docx",
          relative_path: "/Mallar/Gammal.docx",
          size: 2048,
          updated_at: null,
          url: "http://kommun.sharepoint.com/sites/avtal/Gammal.docx",
          source_metadata: []
        }
      ],
      total_count: 2,
      limit: 50,
      offset: 0,
      total_size: 4096
    };
    // Plain http, which Astryx's own link check lets through.
    show([mall, { ...protokoll, url: "http://kommun.sharepoint.com/sites/protokoll" }]);

    const overview = screen.getByRole("table", { name: "Mappar i Byggnad" });
    const external = (link: HTMLElement) => [
      link.getAttribute("href"),
      link.getAttribute("target"),
      link.getAttribute("rel")
    ];
    expect(
      external(within(overview).getByRole("link", { name: /Öppna i SharePoint: Mallar/ }))
    ).toEqual(["https://kommun.sharepoint.com/sites/avtal", "_blank", "noopener noreferrer"]);
    expect(
      within(overview).queryByRole("link", { name: /Öppna i SharePoint: Protokoll/ })
    ).toBeNull();
    expect(overview.querySelector('a[href^="http:"]')).toBeNull();

    fireEvent.click(within(overview).getByRole("link", { name: "Mallar" }));
    const documents = await screen.findByRole("table", { name: "Dokument i Mallar" });
    expect(external(within(documents).getByRole("link", { name: /Avtalsmall\.docx/ }))).toEqual([
      "https://kommun.sharepoint.com/sites/avtal/Avtalsmall.docx",
      "_blank",
      "noopener noreferrer"
    ]);
    expect(within(documents).queryByRole("link", { name: /Gammal\.docx/ })).toBeNull();
    const mallar = screen.getByRole("region", { name: "Mallar" });
    // The folder's own link, beside the document's.
    const folderLinks = within(mallar).getAllByRole("link", { name: /^Öppna i SharePoint(?!:)/ });
    expect(folderLinks.map(external)).toEqual([
      ["https://kommun.sharepoint.com/sites/avtal", "_blank", "noopener noreferrer"]
    ]);

    const nav = screen.getByRole("navigation", { name: "Mappar" });
    fireEvent.click(within(nav).getByRole("link", { name: /Protokoll/ }));
    const protokollSection = await screen.findByRole("region", { name: "Protokoll" });
    expect(
      within(protokollSection).queryByRole("link", { name: /^Öppna i SharePoint/ })
    ).toBeNull();
  });
});

const NO_TEXT = "No text layer (scanned document; OCR is not supported)";

function skippedList(...files: string[]) {
  return {
    items: files.map((file) => ({
      file,
      reason: NO_TEXT,
      code: "no_text_layer" as const,
      params: {},
      retry: false
    })),
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
    server.innerHTML = renderToHtml(<WrapperDetail wrapperId="w1" loaded={served()} />);
    const { container } = renderInApp(<WrapperDetail wrapperId="w1" loaded={served()} />);

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
    const html = renderToHtml(<WrapperDetail wrapperId="w1" loaded={served()} />);
    renderInApp(<WrapperDetail wrapperId="w1" loaded={served()} />);

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
    const search = () => window.location.search;
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
    // The page handles the click itself: no browser navigation.
    expect(fireEvent.click(link)).toBe(false);

    expect(await screen.findByRole("heading", { level: 2, name: "Protokoll" })).toBeTruthy();
    expect(link.getAttribute("aria-current")).toBe("page");
    expect(search()).toBe("?folder=i2");
    // No server navigation: the page and its metadata are not loaded again.
    expect(router.push).not.toHaveBeenCalled();
    expect(router.replace).not.toHaveBeenCalled();
  });

  it("follows a navigation to the source with other parameters while it is open", async () => {
    const { rerender } = show([mall, protokoll]);
    const selected = (name: string | RegExp) =>
      screen.getByRole("tab", { name }).getAttribute("aria-selected");
    expect(selected("Innehåll")).toBe("true");

    // The import result's Show leads to the folder's problems.
    setRoute(`${WRAPPER_PAGE}?tab=problems&folder=i2`);
    rerender(<WrapperDetail wrapperId="w1" loaded={served()} />);
    expect(selected(/Problem/)).toBe("true");

    setRoute(`${WRAPPER_PAGE}?folder=i2`);
    rerender(<WrapperDetail wrapperId="w1" loaded={served()} />);
    expect(selected("Innehåll")).toBe("true");
    expect(await screen.findByRole("heading", { level: 2, name: "Protokoll" })).toBeTruthy();

    // In place, as before.
    fireEvent.click(screen.getByRole("tab", { name: "Aktivitet" }));
    expect(selected("Aktivitet")).toBe("true");
  });

  it("moves focus to a folder's heading when it is picked from the overview", async () => {
    show([mall, protokoll]);
    const overview = screen.getByRole("table", { name: "Mappar i Byggnad" });
    const link = within(overview).getByRole("link", { name: "Protokoll" });
    link.focus();
    fireEvent.click(link);

    const heading = await screen.findByRole("heading", { level: 2, name: "Protokoll" });
    await waitFor(() => expect(document.activeElement).toBe(heading));
  });

  it("moves focus to the next folder's row when one is deleted from its row", async () => {
    const rutiner = { ...protokoll, id: "i3", name: "Rutiner", folder_path: "/Rutiner" };
    show([mall, protokoll, rutiner]);
    state.onDelete = () => {
      state.space = makeSpace({
        integrations: [mall, rutiner].map((item) => makeIntegration({ ...folder, ...item }))
      });
    };
    const overview = screen.getByRole("table", { name: "Mappar i Byggnad" });
    const row = within(overview).getByRole("link", { name: "Protokoll" }).closest("tr")!;
    const trigger = within(row).getByRole("button", { name: "Fler åtgärder för Protokoll" });
    trigger.focus();
    fireEvent.click(trigger);
    await waitFor(() => expect(trigger.getAttribute("aria-expanded")).toBe("true"));
    const menu = document.getElementById(trigger.getAttribute("aria-controls") ?? "")!;
    fireEvent.click(within(menu).getByRole("menuitem", { name: "Ta bort" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Ta bort integrationskunskap" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Ta bort" }));

    await waitFor(() =>
      expect(within(overview).queryByRole("link", { name: "Protokoll" })).toBeNull()
    );
    await waitFor(() =>
      expect(document.activeElement).toBe(
        within(screen.getByRole("table", { name: "Mappar i Byggnad" })).getByRole("link", {
          name: "Rutiner"
        })
      )
    );
  });

  it("replaces the page with the list once the source was deleted from its own menu", async () => {
    show([mall]);
    state.onDelete = () => {
      state.space = makeSpace();
    };
    // Whatever the page shows on its way out.
    const notFound: boolean[] = [];
    const observer = new MutationObserver(() =>
      notFound.push(screen.queryByText("Inga resultat hittades") !== null)
    );
    observer.observe(document.body, { childList: true, subtree: true });

    fireEvent.click(screen.getByRole("button", { name: "Fler åtgärder för Byggnad" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Ta bort grupp" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Ta bort grupp" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Ta bort" }));

    // Replaced, so Back does not lead to a page that is gone.
    await waitFor(() =>
      expect(router.replace).toHaveBeenCalledWith("/spaces/space-1/knowledge?tab=integrations")
    );
    observer.disconnect();
    expect(router.push).not.toHaveBeenCalled();
    expect(screen.queryByRole("heading", { level: 1, name: "Byggnad" })).toBeNull();
    // Not the "not found" state while the list loads.
    expect(notFound).not.toContain(true);
    expect(screen.queryByText("Inga resultat hittades")).toBeNull();
  });

  it("resyncs a one-folder source from the page header, which holds its one menu", async () => {
    show([mall]);

    fireEvent.click(screen.getByRole("button", { name: "Fler åtgärder för Byggnad" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Synka om alla objekt" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Synka om alla objekt" });
    expect(
      within(dialog).getByText(/^Detta startar en fullständig omsynkning av objektet i "Byggnad"\./)
    ).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Starta fullständig synk" }));

    await waitFor(() =>
      expect(toasts.success).toHaveBeenCalledWith("Omsynkning köad för 1 objekt")
    );
    expect(state.synced).toEqual(["i1"]);
    // Followed from the job it returned, so a sync done before the first poll still counts.
    expect(jobs.trackJob).toHaveBeenCalledWith([job("i1")]);
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
  });

  it("says how many folders could not be queued for a resync and why, and queues the rest once", async () => {
    state.refuseSync = ["i2"];
    show([mall, protokoll]);

    fireEvent.click(screen.getByRole("button", { name: "Fler åtgärder för Byggnad" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Synka om alla objekt" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Synka om alla objekt" });
    expect(within(dialog).getByText(/alla 2 objekt i "Byggnad"/)).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Starta fullständig synk" }));

    await waitFor(() =>
      expect(toasts.error).toHaveBeenCalledWith(
        `1 av 2 objekt kunde inte köas: ${protokoll.name}`,
        { description: "Du saknar behörighet att utföra denna åtgärd." }
      )
    );
    expect(state.synced).toEqual(["i1", "i2"]);
    expect(jobs.trackJob).toHaveBeenCalledWith([job("i1")]);
    expect(toasts.success).not.toHaveBeenCalled();
  });

  it("says why a one-folder source could not be resynced", async () => {
    state.refuseSync = ["i1"];
    show([mall]);

    fireEvent.click(screen.getByRole("button", { name: "Fler åtgärder för Byggnad" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Synka om alla objekt" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Synka om alla objekt" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Starta fullständig synk" }));

    await waitFor(() =>
      expect(toasts.error).toHaveBeenCalledWith("Omsynkningen kunde inte köas", {
        description: "Du saknar behörighet att utföra denna åtgärd."
      })
    );
    expect(jobs.trackJob).not.toHaveBeenCalled();
  });

  it("offers no rename or resync of folders the user may not edit", async () => {
    // The backend reports no edit for the organisation's SharePoint to non-admins.
    const readOnly = { permissions: ["read", "delete"] };
    show([
      { ...mall, ...readOnly },
      { ...protokoll, ...readOnly }
    ]);
    fireEvent.click(screen.getByRole("button", { name: "Fler åtgärder för Byggnad" }));

    expect(await screen.findByRole("menuitem", { name: "Ta bort grupp" })).toBeTruthy();
    expect(screen.queryByRole("menuitem", { name: "Synka om alla objekt" })).toBeNull();
    expect(screen.queryByRole("menuitem", { name: "Byt namn på grupp" })).toBeNull();
  });

  it("still says so when the source went away by other means", async () => {
    const { queryClient } = show([mall]);

    // Deleted in another tab, say: the page did not remove it, so it says it is gone.
    state.space = makeSpace();
    await act(() => queryClient.invalidateQueries({ queryKey: ["spaces", "space-1"] }));

    expect(await screen.findByText("Inga resultat hittades")).toBeTruthy();
    expect(router.replace).not.toHaveBeenCalled();
  });

  it("says the source is gone when Back leads to its page after a delete from the list", async () => {
    // The list's row menu deletes it ...
    const items = [makeIntegration({ ...folder, ...mall })] as IntegrationKnowledge[];
    state.space = makeSpace({ integrations: items });
    // What the server found then, and what the router's cache keeps of it.
    const before = served(state.space as Space);
    state.onDelete = () => {
      state.space = makeSpace();
    };
    setRoute("/spaces/space-1/knowledge?tab=integrations");
    const list = renderInApp(
      <WrapperActions wrapperId="w1" wrapperName="Byggnad" items={items} canEdit canDelete />
    );
    fireEvent.click(screen.getByRole("button", { name: "Fler åtgärder för Byggnad" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Ta bort grupp" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Ta bort grupp" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Ta bort" }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    list.unmount();

    // ... and Back shows its page again, from the router's cache.
    setRoute(WRAPPER_PAGE);
    renderInApp(<WrapperDetail wrapperId="w1" loaded={before} />, {
      queryClient: list.queryClient
    });

    expect(
      await screen.findByRole("heading", { level: 1, name: "Inga resultat hittades" })
    ).toBeTruthy();
  });

  it("shows the history of the folder chosen on Activity, and keeps that folder on Contents", async () => {
    const search = () => window.location.search;
    const sync = (id: string, startedAt: string, error: string | null = null) => ({
      id,
      integration_knowledge_id: "i2",
      sync_type: "delta",
      status: error ? "error" : "success",
      error_message: error,
      started_at: startedAt,
      completed_at: null,
      files_processed: 1,
      files_deleted: 0,
      pages_processed: 0,
      folders_processed: 0,
      skipped_items: 0,
      skipped_details: []
    });
    state.logs.i1 = Array.from({ length: 12 }, (_, index) =>
      sync(`m${index}`, `2026-10-${String(14 - index).padStart(2, "0")}T12:00:00Z`)
    );
    state.logs.i2 = [sync("p1", "2026-06-01T12:00:00Z", "Protokollet kunde inte läsas")];
    const { container } = show(
      [mall, protokoll],
      "/spaces/space-1/knowledge/integrations/wrapper/w1?tab=activity"
    );

    const folderPicker = await screen.findByRole("combobox", { name: "Mapp" });
    expect(await screen.findByRole("heading", { name: "De senaste 10 synkarna" })).toBeTruthy();
    expect(screen.queryByText("Protokollet kunde inte läsas")).toBeNull();
    await expectNoAxeViolations(container);

    fireEvent.keyDown(folderPicker, { key: "Enter" });
    fireEvent.click(await screen.findByRole("option", { name: "Protokoll" }));

    expect(await screen.findByText("Protokollet kunde inte läsas")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Den senaste synken" })).toBeTruthy();
    expect(search()).toBe("?tab=activity&folder=i2");

    fireEvent.click(screen.getByRole("tab", { name: "Innehåll" }));
    expect(await screen.findByRole("heading", { level: 2, name: "Protokoll" })).toBeTruthy();
    expect(search()).toBe("?folder=i2");
  });

  it("does not intercept a click that opens the folder somewhere else", () => {
    const replaceState = vi.spyOn(window.history, "replaceState");
    show([mall, protokoll]);
    const nav = screen.getByRole("navigation", { name: "Mappar" });
    const link = within(nav).getByRole("link", { name: /Protokoll/ });

    for (const modifier of [{ ctrlKey: true }, { metaKey: true }, { shiftKey: true }]) {
      // Records the click as it leaves the page, and stops jsdom's navigation after that.
      let prevented: boolean | undefined;
      const record = (event: Event) => {
        prevented = event.defaultPrevented;
        event.preventDefault();
      };
      document.addEventListener("click", record);
      fireEvent.click(link, modifier);
      document.removeEventListener("click", record);
      expect(prevented).toBe(false);
    }

    expect(replaceState).not.toHaveBeenCalled();
    expect(link.getAttribute("aria-current")).toBeNull();
    expect(
      within(nav)
        .getByRole("link", { name: /Alla mappar/ })
        .getAttribute("aria-current")
    ).toBe("page");
    expect(screen.queryByRole("heading", { level: 2, name: "Protokoll" })).toBeNull();
  });

  it("moves focus to the tab panel when the pressed Visa problem goes with the banner", async () => {
    show([
      mall,
      {
        ...protokoll,
        metadata: { ...protokoll.metadata, last_sync_status: "error", last_sync_error: "Boom" }
      }
    ]);
    const showProblems = screen.getByRole("link", { name: "Visa problem" });
    showProblems.focus();

    // In place: the click is the page's own, not a navigation.
    expect(fireEvent.click(showProblems)).toBe(false);

    expect(screen.getByRole("tab", { name: /Problem/ }).getAttribute("aria-selected")).toBe("true");
    expect(showProblems.isConnected).toBe(false);
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("tabpanel")));
  });
});

describe("WrapperDetail documents", () => {
  it("keeps focus in the folder when paging to the last page, which the pager announces", async () => {
    state.documents.i1 = documentPages(() => 60);
    show([mall, protokoll], "/spaces/space-1/knowledge/integrations/wrapper/w1?folder=i1");
    await screen.findByRole("button", { name: /Dokument 1\.docx/ });
    const announcements = recordAnnouncements();

    const next = screen.getByRole("button", { name: "Gå till nästa sida" });
    next.focus();
    fireEvent.click(next);
    // The last page is known from the first one: the button turns disabled at once,
    // and a browser drops its focus then (jsdom does not, so do it here).
    expect(next.hasAttribute("disabled")).toBe(true);
    focusFixup();

    expect(await screen.findByRole("button", { name: /Dokument 51\.docx/ })).toBeTruthy();
    await waitFor(() =>
      expect(document.activeElement).toBe(screen.getByRole("region", { name: "Mallar" }))
    );
    expect(screen.getByText(/^Visar 51–60 av 60/)).toBeTruthy();
    announcements.stop();
    // Astryx's Pagination says which page; the range is not read out after it.
    expect(announcements.said).toEqual(["Sida 2 av 2"]);
  });

  it("announces what a sort shows once it is in, and not a reload after a sync", async () => {
    state.documents.i1 = documentPages(() => 60);
    const { queryClient } = show(
      [mall, protokoll],
      "/spaces/space-1/knowledge/integrations/wrapper/w1?folder=i1"
    );
    await screen.findByRole("button", { name: /Dokument 1\.docx/ });
    const announcements = recordAnnouncements();

    fireEvent.click(screen.getByRole("button", { name: "Sortera efter Storlek" }));
    await waitFor(() => expect(announcements.said).toEqual(["Visar 1–50 av 60"]));

    // A sync wrote a new revision: the rows are replaced without a word.
    state.space = makeSpace({
      integrations: [mall, protokoll].map((item) =>
        makeIntegration({
          ...folder,
          ...item,
          metadata: { ...item.metadata, last_synced_at: "2026-10-19T08:05:00Z" }
        })
      )
    });
    await act(() => queryClient.invalidateQueries({ queryKey: ["spaces", "space-1"] }));
    await waitFor(() =>
      expect(state.requests.filter((request) => request.startsWith("documents i1"))).toHaveLength(3)
    );
    await act(() => new Promise((resolve) => setTimeout(resolve, 50)));
    announcements.stop();
    expect(announcements.said).toEqual(["Visar 1–50 av 60"]);
    expect(screen.queryByText("Läser in dokument...")).toBeNull();
  });

  it("announces what a search finds once it is in", async () => {
    state.documents.i1 = documentPages(() => 60);
    show([mall, protokoll], "/spaces/space-1/knowledge/integrations/wrapper/w1?folder=i1");
    await screen.findByRole("button", { name: /Dokument 1\.docx/ });
    // The first load is no result to announce.
    expect(liveRegion()).toBe("");

    fireEvent.change(screen.getByLabelText("Sök dokument på namn eller sökväg"), {
      target: { value: "dokument" }
    });

    await waitFor(() => expect(liveRegion()).toBe("Visar 1–50 av 60"));
    expect(state.requests.filter((request) => request.startsWith("documents i1"))).toHaveLength(2);
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

    const announcements = recordAnnouncements();
    total = 40;
    await act(() => queryClient.invalidateQueries({ queryKey: ["integrations", "documents"] }));

    expect(await screen.findByRole("button", { name: /Dokument 40\.docx/ })).toBeTruthy();
    announcements.stop();
    // Never an empty folder, never a range past the end.
    expect(screen.queryByText("Inga dokument kunde indexeras")).toBeNull();
    expect(screen.getByText(/^Visar 1–40 av 40/)).toBeTruthy();
    // The user turned no page and searched nothing: nothing to announce.
    expect(announcements.said).toEqual([]);
    // One page left: no pager.
    expect(screen.queryByRole("button", { name: "Gå till nästa sida" })).toBeNull();
  });

  it("shows the documents loading, not an empty folder, while it moves back from past the end", async () => {
    let total = 60;
    let release: () => void = () => {};
    const pages = documentPages(() => total);
    state.documents.i1 = (query: Query) =>
      total === 60 || (query.offset ?? 0) > 0
        ? pages(query)
        : new Promise((resolve) => (release = () => resolve(pages(query))));
    const { queryClient } = show(
      [mall, protokoll],
      "/spaces/space-1/knowledge/integrations/wrapper/w1?folder=i1"
    );
    await screen.findByRole("button", { name: /Dokument 1\.docx/ });
    fireEvent.click(screen.getByRole("button", { name: "Gå till nästa sida" }));
    await screen.findByRole("button", { name: /Dokument 51\.docx/ });

    // A sync leaves 40: under its revision page 2 comes back empty, and page 1 is on its way.
    total = 40;
    state.space = makeSpace({
      integrations: [
        makeIntegration({
          ...folder,
          ...mall,
          metadata: { ...mall.metadata, last_synced_at: "2026-10-15T09:00:00Z", document_count: 40 }
        }),
        makeIntegration({ ...folder, ...protokoll })
      ]
    });
    await act(() => queryClient.invalidateQueries({ queryKey: ["spaces", "space-1"] }));

    expect(await screen.findByText("Läser in dokument...")).toBeTruthy();
    expect(screen.queryByText("Inga dokument kunde indexeras")).toBeNull();
    expect(screen.queryByRole("table", { name: "Dokument i Mallar" })).toBeNull();

    await act(async () => release());
    expect(await screen.findByRole("button", { name: /Dokument 40\.docx/ })).toBeTruthy();
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
    const skippedStat = screen.getByText("Överhoppade").closest("div")!;
    expect(within(skippedStat).getByText("1")).toBeTruthy();

    await act(async () => release(skippedList("ny.pdf", "annan.pdf")));
    expect(await screen.findByText("ny.pdf")).toBeTruthy();
    expect(within(skippedStat).getByText("2")).toBeTruthy();
    expect(fetches()).toBe(2);
  });

  it("shows what a sync wrote while the page was closed as soon as it opens again", async () => {
    state.skipped.i1 = skippedList("scan.pdf");
    state.documents.i1 = documentPages(() => 2);
    const route = "/spaces/space-1/knowledge/integrations/wrapper/w1?folder=i1";
    const first = show([mall, protokoll], route);
    expect(await screen.findByRole("button", { name: /Dokument 2\.docx/ })).toBeTruthy();
    const problemsTab = screen.getByRole("tab", { name: /Problem/ });
    expect(await within(problemsTab).findByText("1")).toBeTruthy();
    first.unmount();

    // Elsewhere in the space meanwhile: a sync of Mallar finished, and the
    // space (refetched by whatever showed it) has its new revision.
    state.skipped.i1 = {
      ...skippedList("scan.pdf", "karta.pdf"),
      items: [
        ...skippedList("scan.pdf", "karta.pdf").items,
        {
          file: "stor.pdf",
          reason: "File too large (exceeds 50 MB limit)",
          code: "file_too_large" as const,
          params: { limit_mb: "50" },
          retry: false
        }
      ],
      total: 3
    };
    state.documents.i1 = documentPages(() => 3);
    state.space = makeSpace({
      integrations: [
        makeIntegration({
          ...folder,
          ...mall,
          metadata: { ...mall.metadata, last_synced_at: "2026-10-15T09:00:00Z", document_count: 3 }
        }),
        makeIntegration({ ...folder, ...protokoll })
      ]
    });
    first.queryClient.setQueryData(["spaces", "space-1"], state.space);
    setRoute(route);
    renderInApp(<WrapperDetail wrapperId="w1" loaded={served()} />, {
      queryClient: first.queryClient
    });

    // The cached lists were read before the sync; they are not shown as current.
    expect(await screen.findByRole("button", { name: /Dokument 3\.docx/ })).toBeTruthy();
    const tab = screen.getByRole("tab", { name: /Problem/ });
    // Two causes now: a scanned document and one too large.
    expect(await within(tab).findByText("2")).toBeTruthy();
    const skippedStat = screen.getByText("Överhoppade").closest("div")!;
    expect(within(skippedStat).getByText("3")).toBeTruthy();
  });

  it("counts the skipped files of the source's current folders only", async () => {
    state.skipped.i1 = skippedList("scan.pdf");
    state.skipped.i2 = skippedList("ritning.pdf", "karta.pdf");
    const { queryClient } = show([mall, protokoll]);
    const skippedStat = screen.getByText("Överhoppade").closest("div")!;
    expect(await within(skippedStat).findByText("3")).toBeTruthy();

    // Protokoll is deleted; its list stays in the cache for a while.
    state.space = makeSpace({ integrations: [makeIntegration({ ...folder, ...mall })] });
    await act(() => queryClient.invalidateQueries({ queryKey: ["spaces", "space-1"] }));

    await waitFor(() =>
      expect(screen.getByText("Överhoppade").closest("div")!.textContent).toContain("1")
    );
    expect(screen.getByText("Överhoppade").closest("div")!.textContent).not.toContain("3");
    expect(
      queryClient.getQueriesData({ queryKey: ["integrations", "skipped", "space-1", "i2"] })
    ).not.toHaveLength(0);
  });

  it("moves focus to the panel once a retried list loaded and the retry button went", async () => {
    state.skipped.i2 = "error";
    show([mall, protokoll], "/spaces/space-1/knowledge/integrations/wrapper/w1?tab=problems");
    const retry = await screen.findByRole("button", { name: "Försök igen" });

    state.skipped.i2 = skippedList();
    retry.focus();
    fireEvent.click(retry);

    await waitFor(() => expect(screen.queryByRole("button", { name: "Försök igen" })).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("tabpanel")));
  });

  it("shows failed folders without speaking the banner, on every return from Problems or later", async () => {
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

    // Another folder fails while the page is open, by no sync seen here.
    state.space = makeSpace({
      integrations: [failing(mall), failing(protokoll)].map((item) =>
        makeIntegration({ ...folder, ...item })
      )
    });
    await act(() => queryClient.invalidateQueries({ queryKey: ["spaces", "space-1"] }));
    expect(await screen.findByText("Senaste synken av 2 mappar misslyckades")).toBeTruthy();
    expect(liveRegion()).toBe("");
  });

  it("says nothing of a sync that already ran when the page opened", async () => {
    const { said } = recordAnnouncements();
    const answer = holdProgress();
    show([mall]);
    await nextFrame();

    answer([running("i1", 4)]);
    expect(await screen.findByRole("heading", { name: "Synk pågår" })).toBeTruthy();
    await nextFrame();
    expect(said).toEqual([]);
  });

  it("tells a sync that failed here once, by the sync's own announcement", async () => {
    const { said } = recordAnnouncements();
    const answer = holdProgress();
    const { queryClient } = show([mall]);
    await nextFrame();
    answer([running("i1", 4)]);
    expect(await screen.findByRole("heading", { name: "Synk pågår" })).toBeTruthy();
    await nextFrame();

    state.space = makeSpace({
      integrations: [
        makeIntegration({
          ...folder,
          ...mall,
          metadata: { ...mall.metadata, last_sync_status: "error", last_sync_error: "Boom" }
        })
      ]
    });
    state.progress = [];
    await act(() =>
      queryClient.invalidateQueries({ queryKey: ["integrations", "sync-progress", "space-1"] })
    );
    expect(await screen.findByText("Senaste synken av 1 mapp misslyckades")).toBeTruthy();
    await waitFor(() => expect(said).toEqual(["Synk av Byggnad misslyckades. Problem: 1"]));
    expect(said).not.toContain("Senaste synken av 1 mapp misslyckades");
  });
});

/** Holds the progress poll's answer back until it is given: the page opens before it knows what runs. */
function holdProgress() {
  let answer!: (items: unknown[]) => void;
  state.progress = new Promise((resolve) => {
    answer = resolve;
  });
  return answer;
}

/** Lets a frame pass: Astryx writes an announcement into its region in the next frame. */
function nextFrame() {
  return act(
    () => new Promise<void>((resolve) => requestAnimationFrame(() => setTimeout(resolve)))
  );
}

function running(itemId: string, done: number) {
  return {
    integration_knowledge_id: itemId,
    sync_type: "full",
    phase: "processing",
    started_at: "2026-10-19T08:00:00Z",
    updated_at: "2026-10-19T08:01:00Z",
    total: 12,
    done,
    indexed: done - 1,
    unchanged: 0,
    skipped: 1,
    deleted: 0
  };
}

describe("WrapperDetail sync status", () => {
  const QUEUED_NOTICE = "En synk är köad och startar så snart servern tar sig an den.";
  const refreshProgress = (queryClient: QueryClient) =>
    act(() =>
      queryClient.invalidateQueries({ queryKey: ["integrations", "sync-progress", "space-1"] })
    );

  it("shows a resync it started as queued until the worker reports, and offers no second one", async () => {
    const { queryClient } = show([mall]);
    const { said } = recordAnnouncements();

    fireEvent.click(screen.getByRole("button", { name: "Fler åtgärder för Byggnad" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Synka om alla objekt" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Synka om alla objekt" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Starta fullständig synk" }));

    expect(await screen.findByText(QUEUED_NOTICE)).toBeTruthy();
    expect(screen.getByText("Köad")).toBeTruthy();
    await waitFor(() => expect(said).toContain("Synk av Byggnad köad"));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    fireEvent.click(screen.getByRole("button", { name: "Fler åtgärder för Byggnad" }));
    const busy = await screen.findByRole("menuitem", {
      name: "En synk är redan köad eller pågår"
    });
    expect(busy.getAttribute("aria-disabled")).toBe("true");
    fireEvent.keyDown(busy, { key: "Escape" });

    // The worker takes it: the progress tells the rest.
    state.progress = [running("i1", 4)];
    await refreshProgress(queryClient);
    expect(await screen.findByRole("heading", { name: "Synk pågår" })).toBeTruthy();
    expect(screen.queryByText(QUEUED_NOTICE)).toBeNull();
    await waitFor(() => expect(said).toContain("Synk av Byggnad har startat"));

    // Once the sync is over the space is read again, and its rows tell how it went.
    state.space = makeSpace({
      integrations: [
        makeIntegration({
          ...folder,
          ...mall,
          metadata: { ...mall.metadata, last_synced_at: "2026-10-19T08:05:00Z" }
        })
      ]
    });
    state.progress = [];
    await refreshProgress(queryClient);
    await waitFor(() => expect(said).toContain("Synk av Byggnad klar"));
    expect(said).not.toContain("Synk av Byggnad pågår inte längre");
    expect(screen.queryByText(QUEUED_NOTICE)).toBeNull();
  });

  it("tells a folder queued for its first sync that its documents are on the way", async () => {
    trackSyncs([{ jobId: "job-i3", knowledgeId: "i3" }]);
    show(
      [mall, { id: "i3", name: "Nytt", folder_path: "/Nytt", metadata: { size: 0 } }],
      `${WRAPPER_PAGE}?folder=i3`
    );

    expect(
      await screen.findByText("Dokumenten visas här i takt med att synken läser dem.")
    ).toBeTruthy();
    expect(screen.queryByText("Inga dokument ännu. Första synken körs i bakgrunden.")).toBeNull();
  });

  it("marks a folder queued in the folder list by its icon and its name", async () => {
    show([mall, protokoll]);

    fireEvent.click(screen.getByRole("button", { name: "Fler åtgärder för Byggnad" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Synka om alla objekt" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Synka om alla objekt" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Starta fullständig synk" }));

    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    const nav = screen.getByRole("navigation", { name: "Mappar" });
    const mallar = await within(nav).findByRole("link", { name: /Mallar\s*, Köad/ });
    expect(mallar.querySelector("svg")?.getAttribute("class")).toContain("lucide-clock");
    // Each folder's own menu in the overview offers no second sync either.
    const overview = screen.getByRole("table", { name: "Mappar i Byggnad" });
    const row = within(overview).getByRole("link", { name: "Protokoll" }).closest("tr")!;
    const trigger = within(row).getByRole("button", { name: "Fler åtgärder för Protokoll" });
    fireEvent.click(trigger);
    await waitFor(() => expect(trigger.getAttribute("aria-expanded")).toBe("true"));
    const menu = document.getElementById(trigger.getAttribute("aria-controls") ?? "")!;
    const busy = within(menu).getByRole("menuitem", { name: "En synk är redan köad eller pågår" });
    expect(busy.getAttribute("aria-disabled")).toBe("true");
  });

  it("speaks a changed number of problems, not the first one it learns", async () => {
    state.skipped.i1 = skippedList("scan.pdf");
    const { queryClient } = show([mall, protokoll]);
    const tab = screen.getByRole("tab", { name: /Problem/ });
    expect(await within(tab).findByText("1")).toBeTruthy();
    const { said } = recordAnnouncements();

    // A sync of Protokoll finished meanwhile and could not read a file of its own.
    state.skipped.i2 = {
      items: [
        {
          file: "stor.pdf",
          reason: "File too large (exceeds 50 MB limit)",
          code: "file_too_large" as const,
          params: { limit_mb: "50" },
          retry: false
        }
      ],
      total: 1,
      truncated: false,
      synced_at: "2026-10-19T09:00:00Z"
    };
    state.space = makeSpace({
      integrations: [
        mall,
        {
          ...protokoll,
          metadata: { ...protokoll.metadata, last_synced_at: "2026-10-19T09:00:00Z" }
        }
      ].map((item) => makeIntegration({ ...folder, ...item }))
    });
    await act(() => queryClient.invalidateQueries({ queryKey: ["spaces", "space-1"] }));

    expect(await within(tab).findByText("2")).toBeTruthy();
    await waitFor(() => expect(said).toEqual(["Problem: 2"]));
  });

  it("shows a wrapper imported since the space was cached, as the server page found it", async () => {
    const imported = makeSpace({
      integrations: [mall, protokoll].map((item) => makeIntegration({ ...folder, ...item }))
    });
    // The browser's space is from before the import, and still fresh enough not to be read again.
    const queryClient = testQueryClient();
    queryClient.setQueryData(["spaces", "space-1"], makeSpace(), { updatedAt: Date.now() - 5_000 });
    state.space = imported;
    setRoute(WRAPPER_PAGE);
    const notFound: boolean[] = [];
    const observer = new MutationObserver(() =>
      notFound.push(screen.queryByText("Inga resultat hittades") !== null)
    );
    observer.observe(document.body, { childList: true, subtree: true });

    renderInApp(<WrapperDetail wrapperId="w1" loaded={served(imported)} />, {
      queryClient
    });

    expect(screen.getByRole("heading", { level: 1, name: "Byggnad" })).toBeTruthy();
    // The page reads the space again, which now holds the wrapper.
    await waitFor(() =>
      expect(
        queryClient.getQueryData<Space>(["spaces", "space-1"])?.knowledge.integration_knowledge_list
          .items
      ).toHaveLength(2)
    );
    observer.disconnect();
    expect(notFound).not.toContain(true);
    expect(screen.getByRole("navigation", { name: "Mappar" })).toBeTruthy();
  });

  it("says the wrapper is gone when the space read again lacks it too", async () => {
    const before = makeSpace({
      integrations: [mall].map((item) => makeIntegration({ ...folder, ...item }))
    });
    const queryClient = testQueryClient();
    queryClient.setQueryData(["spaces", "space-1"], makeSpace(), { updatedAt: Date.now() - 5_000 });
    // Deleted between the server's read and the browser's.
    state.space = makeSpace();
    setRoute(WRAPPER_PAGE);

    renderInApp(<WrapperDetail wrapperId="w1" loaded={served(before)} />, {
      queryClient
    });

    expect(screen.getByRole("heading", { level: 1, name: "Byggnad" })).toBeTruthy();
    expect(
      await screen.findByRole("heading", { level: 1, name: "Inga resultat hittades" })
    ).toBeTruthy();
  });
});
