// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import type { IntegrationKnowledge } from "../../knowledge";
import type { SyncLog } from "../queries";
import { ActivityView } from "./activity-view";

const { get } = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: { GET: get } }));

afterEach(() => {
  cleanup();
  get.mockReset();
});

function folder(id: string, name: string, syncedAt = "2026-10-01T08:00:00Z"): IntegrationKnowledge {
  return {
    id,
    name,
    folder_path: `/Delade dokument/${name}`,
    metadata: { size: 0, last_synced_at: syncedAt }
  } as IntegrationKnowledge;
}

const avtal = folder("a", "Avtal");
const mallar = folder("b", "Mallar");

// Noon UTC keeps every sync on the same local day in any test time zone.
function log(id: string, day: number, overrides: Partial<SyncLog> = {}): SyncLog {
  const startedAt = `2026-10-${String(day).padStart(2, "0")}T12:00:00Z`;
  return {
    id,
    integration_knowledge_id: "a",
    sync_type: "delta",
    status: "success",
    started_at: startedAt,
    completed_at: `2026-10-${String(day).padStart(2, "0")}T12:00:30Z`,
    created_at: startedAt,
    files_processed: 0,
    files_deleted: 0,
    pages_processed: 0,
    folders_processed: 0,
    skipped_items: 0,
    skipped_details: [],
    duration_seconds: 30,
    ...overrides
  } as SyncLog;
}

const HOUR = 60 * 60 * 1000;

/** `count` hourly syncs of an item, the newest at `newest`. */
function hourly(prefix: string, count: number, newest: string, overrides: Partial<SyncLog> = {}) {
  return Array.from({ length: count }, (_, index) => {
    const startedAt = new Date(new Date(newest).getTime() - index * HOUR).toISOString();
    return log(`${prefix}${index}`, 1, {
      started_at: startedAt,
      completed_at: null,
      files_processed: 1,
      ...overrides
    });
  });
}

type Request = { item: string; skip: number; limit: number };

/**
 * Serves each item's logs newest first, a page at a time, like the endpoint:
 * it refuses a limit over 100. `fail` rejects the requests it matches.
 */
function serve(logs: Record<string, SyncLog[]>, fail?: (request: Request) => boolean) {
  get.mockImplementation(
    (
      _path: string,
      {
        params
      }: {
        params: {
          path: { integration_knowledge_id: string };
          query: { skip: number; limit: number };
        };
      }
    ) => {
      const request = {
        item: params.path.integration_knowledge_id,
        skip: params.query.skip,
        limit: params.query.limit
      };
      if (request.limit > 100 || fail?.(request)) {
        return Promise.resolve({
          error: { message: "Boom" },
          response: new Response("{}", { status: request.limit > 100 ? 422 : 500 })
        });
      }
      const all = logs[request.item] ?? [];
      return Promise.resolve({
        data: {
          items: all.slice(request.skip, request.skip + request.limit),
          total_count: all.length,
          page_size: request.limit,
          offset: request.skip
        },
        response: new Response("{}")
      });
    }
  );
}

function requests(): Request[] {
  return get.mock.calls.map(([, options]) => {
    const { params } = options as {
      params: {
        path: { integration_knowledge_id: string };
        query: { skip: number; limit: number };
      };
    };
    return {
      item: params.path.integration_knowledge_id,
      skip: params.query.skip,
      limit: params.query.limit
    };
  });
}

/** The source page's folder state: the selector changes it, like the page's address. */
function Activity({ items }: { items: IntegrationKnowledge[] }) {
  const [selected, setSelected] = useState<string | null>(null);
  return <ActivityView items={items} selectedId={selected} onSelect={setSelected} />;
}

function timelineRows(): HTMLElement[] {
  const events = screen.getByRole("region", { name: "Synkhändelser" });
  return within(events)
    .getAllByRole("list")
    .filter((list) => list.tagName === "OL")
    .flatMap((list) =>
      within(list)
        .getAllByRole("listitem")
        .filter((li) => li.parentElement === list)
    );
}

const showOlder = () => screen.queryByRole("button", { name: "Visa äldre händelser" });

const dayHeading = (iso: string) =>
  new Intl.DateTimeFormat("sv", { year: "numeric", month: "short", day: "numeric" }).format(
    new Date(iso)
  );

async function chooseFolder(name: string) {
  fireEvent.keyDown(screen.getByRole("combobox", { name: "Mapp" }), { key: "Enter" });
  fireEvent.click(await screen.findByRole("option", { name }));
}

describe("ActivityView", () => {
  it("merges the items' syncs newest first, by day, with totals", async () => {
    serve({
      a: [
        log("a2", 14, {
          files_processed: 2,
          files_deleted: 1,
          metadata: {
            changed_details: [
              { file: "avtal.docx", change: "added" },
              { file: "gammal.docx", change: "deleted" }
            ],
            changed_total: 2
          } as SyncLog["metadata"]
        }),
        log("a1", 12)
      ],
      b: [log("b1", 13, { status: "error", error_message: "Graph timeout" })]
    });
    const { container } = renderInApp(<Activity items={[avtal, mallar]} />);

    await screen.findByRole("heading", { name: "De senaste 3 synkarna" });
    const events = screen.getByRole("region", { name: "Synkhändelser" });
    expect(
      within(events)
        .getAllByRole("heading", { level: 2 })
        .map((h) => h.textContent)
    ).toEqual([14, 13, 12].map((day) => dayHeading(`2026-10-${day}T12:00:00Z`)));
    expect(timelineRows().map((row) => row.querySelector("p")?.textContent)).toEqual([
      "2 fil(er) synkad, 1 fil(er) borttagen",
      "Synken misslyckades",
      "Allt aktuellt, inga ändringar"
    ]);
    expect(screen.getByText("Graph timeout")).toBeTruthy();
    expect(screen.getByText("Mallar · Delta-synk · 30 s")).toBeTruthy();

    const files = screen.getByRole("button", { name: "Visa 2 filer" });
    expect(files.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(files);
    expect(files.getAttribute("aria-expanded")).toBe("true");
    const list = within(document.getElementById(files.getAttribute("aria-controls") ?? "")!);
    expect(list.getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      "Nyavtal.docx",
      "Borttagengammal.docx"
    ]);

    const totals = screen.getByRole("region", { name: "De senaste 3 synkarna" });
    const value = (label: string) =>
      within(totals).getByText(label).nextElementSibling?.textContent;
    expect(value("Misslyckade")).toBe("1");
    expect(value("Nya eller ändrade filer")).toBe("2");
    expect(value("Borttagna")).toBe("1");

    await expectNoAxeViolations(container);
  });

  it("words a single sync and a single file in the singular", async () => {
    serve({
      a: [
        log("a1", 14, {
          files_processed: 1,
          metadata: {
            changed_details: [{ file: "avtal.docx", change: "updated" }],
            changed_total: 1
          } as SyncLog["metadata"]
        })
      ]
    });
    renderInApp(<Activity items={[avtal]} />);

    expect(await screen.findByRole("heading", { name: "Den senaste synken" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Visa 1 fil" })).toBeTruthy();
    // One folder: no selector, and the events need not name their folder.
    expect(screen.queryByRole("combobox", { name: "Mapp" })).toBeNull();
  });

  it("reads a history longer than the endpoint's limit, ten syncs at a time", async () => {
    serve({ a: hourly("a", 120, "2026-10-15T12:00:00Z") });
    renderInApp(<Activity items={[avtal]} />);
    await screen.findByText("av totalt 120 synkar");

    for (let page = 1; page < 12; page++) {
      fireEvent.click(showOlder()!);
      await waitFor(() => expect(requests()).toHaveLength(page + 1));
      await waitFor(() => expect(timelineRows()).toHaveLength((page + 1) * 10));
    }

    expect(showOlder()).toBeNull();
    expect(screen.getByRole("heading", { name: "De senaste 120 synkarna" })).toBeTruthy();
    expect(requests()).toEqual(
      Array.from({ length: 12 }, (_, index) => ({ item: "a", skip: index * 10, limit: 10 }))
    );
  });

  it("pages only the folders the timeline waits for", async () => {
    // Avtal has twelve daily syncs; Mallar synced once, before all of them.
    serve({
      a: Array.from({ length: 12 }, (_, i) => log(`a${i}`, 14 - i)),
      b: [log("b1", 2, { status: "error" })]
    });
    renderInApp(<Activity items={[avtal, mallar]} />);

    await screen.findByText("av totalt 13 synkar");
    expect(timelineRows()).toHaveLength(10);
    // Mallar's older sync would sit below Avtal's unloaded ones, so it waits.
    expect(screen.queryByText("Synken misslyckades")).toBeNull();

    fireEvent.click(showOlder()!);

    await screen.findByText("Synken misslyckades");
    // Mallar's one sync is loaded already: only Avtal is paged.
    expect(requests()).toEqual([
      { item: "a", skip: 0, limit: 10 },
      { item: "b", skip: 0, limit: 10 },
      { item: "a", skip: 10, limit: 10 }
    ]);
    expect(timelineRows()).toHaveLength(13);
    expect(showOlder()).toBeNull();
  });

  it("reaches a quiet folder's history through the folder selector", async () => {
    const busy = folder("busy", "Protokoll");
    const quiet = folder("quiet", "Kvartalsrapporter");
    serve({
      busy: hourly("busy", 30, "2026-10-15T12:00:00Z"),
      quiet: hourly("quiet", 2, "2026-06-01T09:00:00Z", {
        status: "error",
        error_message: "Quiet folder failure"
      })
    });
    const { container } = renderInApp(<Activity items={[busy, quiet]} />);

    expect(await screen.findByRole("heading", { name: "De senaste 10 synkarna" })).toBeTruthy();
    // Every folder at once stops where the busy folder's loaded history runs out.
    expect(screen.queryByText("Quiet folder failure")).toBeNull();
    await expectNoAxeViolations(container);

    await chooseFolder("Kvartalsrapporter");

    expect(await screen.findByRole("heading", { name: "De senaste 2 synkarna" })).toBeTruthy();
    expect(screen.getAllByText("Quiet folder failure")).toHaveLength(2);
    expect(showOlder()).toBeNull();
    // The events of one folder need not name it.
    expect(screen.queryByText(/^Kvartalsrapporter ·/)).toBeNull();
    await expectNoAxeViolations(container);

    await chooseFolder("Alla mappar");
    expect(await screen.findByRole("heading", { name: "De senaste 10 synkarna" })).toBeTruthy();
    // Both folders' first pages were loaded once; choosing them again fetches nothing.
    expect(requests()).toHaveLength(2);
  });

  it("reloads only the folder whose sync finished, keeping the pages it loaded", async () => {
    const busy = folder("busy", "Protokoll");
    const quiet = folder("quiet", "Kvartalsrapporter");
    const logs = {
      busy: hourly("busy", 30, "2026-10-15T12:00:00Z"),
      quiet: hourly("quiet", 2, "2026-06-01T09:00:00Z")
    };
    serve(logs);
    const { rerender } = renderInApp(<Activity items={[busy, quiet]} />);
    fireEvent.click(await screen.findByRole("button", { name: "Visa äldre händelser" }));
    expect(await screen.findByRole("heading", { name: "De senaste 20 synkarna" })).toBeTruthy();
    expect(requests()).toHaveLength(3);

    // A new sync of Protokoll lands; the space shows it with a new revision.
    logs.busy = [...hourly("new", 1, "2026-10-15T13:00:00Z", { files_processed: 7 }), ...logs.busy];
    const answer = get.getMockImplementation()!;
    let release: () => void = () => {};
    get.mockImplementationOnce(
      (...args: unknown[]) => new Promise((resolve) => (release = () => resolve(answer(...args))))
    );
    rerender(<Activity items={[folder("busy", "Protokoll", "2026-10-15T13:00:30Z"), quiet]} />);

    // While its newest page loads again, the history shown stays.
    expect(timelineRows()).toHaveLength(20);
    expect(screen.queryByText("Laddar synkhistorik...")).toBeNull();
    await act(async () => release());

    expect(await screen.findByText("7 fil(er) synkad")).toBeTruthy();
    expect(requests()).toHaveLength(4);
    expect(requests()[3]).toEqual({ item: "busy", skip: 0, limit: 10 });
    // The second page loaded before stays: 20 earlier syncs and the new one.
    expect(await screen.findByRole("heading", { name: "De senaste 21 synkarna" })).toBeTruthy();
  });

  it("keeps the shown events when older ones fail to load, until a retry works", async () => {
    const logs = { a: Array.from({ length: 12 }, (_, i) => log(`a${i}`, 14 - i)) };
    serve(logs, ({ skip }) => skip > 0);
    renderInApp(<Activity items={[avtal]} />);

    fireEvent.click(await screen.findByRole("button", { name: "Visa äldre händelser" }));

    await screen.findByText("Kunde inte läsa in synkhistoriken");
    expect(timelineRows()).toHaveLength(10);
    expect(showOlder()).toBeTruthy();

    serve(logs);
    fireEvent.click(screen.getByRole("button", { name: "Försök igen" }));
    await waitFor(() => expect(timelineRows()).toHaveLength(12));
    expect(screen.queryByText("Kunde inte läsa in synkhistoriken")).toBeNull();
  });

  it("says so when an item has never synced", async () => {
    serve({ a: [] });
    renderInApp(<Activity items={[avtal]} />);
    expect(screen.getByRole("status").textContent).toContain("Laddar synkhistorik...");
    await waitFor(() => expect(screen.getByText("Ingen synk registrerad")).toBeTruthy());
  });
});
