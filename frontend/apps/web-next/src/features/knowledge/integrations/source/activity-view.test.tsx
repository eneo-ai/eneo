// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
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

const avtal = { id: "a", name: "Avtal" } as IntegrationKnowledge;
const mallar = { id: "b", name: "Mallar" } as IntegrationKnowledge;

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

/** Serves each item's logs newest first, `limit` at a time; `fail` rejects matching requests. */
function serve(logs: Record<string, SyncLog[]>, fail?: (limit: number) => boolean) {
  get.mockImplementation(
    (
      _path: string,
      {
        params
      }: { params: { path: { integration_knowledge_id: string }; query: { limit: number } } }
    ) => {
      const { limit } = params.query;
      if (fail?.(limit)) {
        return Promise.resolve({
          error: { message: "Boom" },
          response: new Response("{}", { status: 500 })
        });
      }
      const all = logs[params.path.integration_knowledge_id] ?? [];
      return Promise.resolve({
        data: { items: all.slice(0, limit), total_count: all.length, page_size: limit, offset: 0 },
        response: new Response("{}")
      });
    }
  );
}

function requestedLimits(): number[] {
  return get.mock.calls.map(
    ([, options]) => (options as { params: { query: { limit: number } } }).params.query.limit
  );
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

const dayHeading = (iso: string) =>
  new Intl.DateTimeFormat("sv", { year: "numeric", month: "short", day: "numeric" }).format(
    new Date(iso)
  );

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
    const { container } = renderInApp(<ActivityView items={[avtal, mallar]} showFolders />);

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

  it("shows older events by loading a bigger window for every item", async () => {
    // Avtal has twelve daily syncs; Mallar synced once, before all of them.
    serve({
      a: Array.from({ length: 12 }, (_, i) => log(`a${i}`, 14 - i)),
      b: [log("b1", 2, { status: "error" })]
    });
    renderInApp(<ActivityView items={[avtal, mallar]} showFolders />);

    await screen.findByText("av totalt 13 synkar");
    expect(timelineRows()).toHaveLength(10);
    // Mallar's older sync would sit below Avtal's unloaded ones, so it waits.
    expect(screen.queryByText("Synken misslyckades")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Visa äldre händelser" }));

    await screen.findByText("Synken misslyckades");
    expect(requestedLimits()).toEqual([10, 10, 20, 20]);
    expect(timelineRows()).toHaveLength(13);
    expect(screen.queryByRole("button", { name: "Visa äldre händelser" })).toBeNull();
  });

  it("keeps the shown events when older ones fail to load, until a retry works", async () => {
    const logs = { a: Array.from({ length: 12 }, (_, i) => log(`a${i}`, 14 - i)) };
    serve(logs, (limit) => limit > 10);
    renderInApp(<ActivityView items={[avtal]} showFolders={false} />);

    fireEvent.click(await screen.findByRole("button", { name: "Visa äldre händelser" }));

    await screen.findByText("Kunde inte läsa in synkhistoriken");
    expect(timelineRows()).toHaveLength(10);
    expect(screen.getByRole("button", { name: "Visa äldre händelser" })).toBeTruthy();

    serve(logs);
    fireEvent.click(screen.getByRole("button", { name: "Försök igen" }));
    await waitFor(() => expect(timelineRows()).toHaveLength(12));
    expect(screen.queryByText("Kunde inte läsa in synkhistoriken")).toBeNull();
  });

  it("says so when an item has never synced", async () => {
    serve({ a: [] });
    renderInApp(<ActivityView items={[avtal]} showFolders={false} />);
    expect(screen.getByRole("status").textContent).toContain("Laddar synkhistorik...");
    await waitFor(() => expect(screen.getByText("Ingen synk registrerad")).toBeTruthy());
  });
});
