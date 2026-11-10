// @vitest-environment jsdom
import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { PHONE_VIEWPORT, setViewport } from "@/test/setup-dom";
import { CrawlRunsTable } from "./crawl-runs";
import type { CrawlRun } from "./knowledge";

const failuresPage = vi.hoisted(() => ({
  items: [
    { id: "f1", url: "https://example.com/saknas", reason: "http_404", kind: "page" },
    { id: "f2", url: "https://example.com/tom", reason: "EMPTY_CONTENT", kind: "page" }
  ],
  total_count: 2,
  next_cursor: null,
  details_available: true,
  run: null as unknown
}));

vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    GET: (path: string) =>
      Promise.resolve({
        data: path === "/api/v1/crawl-runs/{id}/failures/" ? failuresPage : null,
        response: new Response("{}")
      })
  }
}));

afterEach(cleanup);

function run(overrides: Partial<CrawlRun> & Pick<CrawlRun, "id">): CrawlRun {
  return {
    created_at: "2024-03-01T10:00:00Z",
    finished_at: "2024-03-01T10:05:00Z",
    status: "complete",
    pages_crawled: 3,
    files_downloaded: 0,
    pages_failed: 0,
    files_failed: 0,
    result_location: null,
    origin: "manual",
    ...overrides
  } as CrawlRun;
}

const RUNS = [
  run({ id: "old", created_at: "2024-03-01T10:00:00Z", pages_crawled: 12 }),
  run({
    id: "failed",
    created_at: "2024-03-03T10:00:00Z",
    finished_at: null,
    status: "failed",
    result_location: "Timeout"
  }),
  run({ id: "new", created_at: "2024-03-05T10:00:00Z", pages_crawled: 4, pages_failed: 1 })
];

function statusColumn() {
  return within(screen.getByRole("table"))
    .getAllByRole("row")
    .slice(1)
    .map((row) => within(row).getAllByRole("cell")[1]!.textContent);
}

describe("CrawlRunsTable", () => {
  it("is a block per run on a phone, newest first, with the result and the duration in view", () => {
    setViewport(PHONE_VIEWPORT);
    renderInApp(<CrawlRunsTable runs={RUNS} />);

    expect(screen.queryByRole("table")).toBeNull();
    const rows = within(screen.getByRole("list", { name: "Indexeringar" })).getAllByRole(
      "listitem"
    );
    expect(rows).toHaveLength(3);
    // Three runs need no filter on a phone (useFilterShown).
    expect(screen.queryByRole("textbox", { name: "Filtrera indexeringar" })).toBeNull();
    // The newest first, as the table's default order.
    expect(within(rows[0]!).getByRole("button", { name: /5 mars 2024|2024-03-05/ })).toBeTruthy();
    // The date starts on the row's 16 px line: the ghost button's padding is pulled back.
    expect(
      within(rows[0]!).getByRole("button", { name: /5 mars 2024|2024-03-05/ }).className
    ).toContain("-ms-3");
    // No "—" line: a run without a result says nothing about it.
    expect(rows.map((row) => row.textContent?.includes("—"))).toEqual([false, false, false]);
    // A finished run says how long it took; the unfinished one says when it started.
    expect(rows[0]!.textContent).toMatch(/Varaktighet: \d/);
    expect(rows[1]!.textContent).not.toMatch(/Varaktighet/);
    expect(rows[1]!.textContent).toMatch(/Startad/);
  });

  it("starts a failed run's lone Visa detaljer on the same line as its date", () => {
    setViewport(PHONE_VIEWPORT);
    renderInApp(<CrawlRunsTable runs={RUNS} />);
    const rows = within(screen.getByRole("list", { name: "Indexeringar" })).getAllByRole(
      "listitem"
    );
    // The middle row is the failed run: no counts, so the button is the line's first thing.
    const errors = within(rows[1]!).getByRole("button", { name: "Visa detaljer" });
    expect(errors.parentElement!.className).toContain("-ms-3");
    // A run whose line starts with a label ("Ej indexerade") is not pulled back.
    expect(
      within(rows[0]!).getByRole("button", { name: /Sidor: 1, visa de som inte kunde indexeras/ })
        .parentElement!.className
    ).not.toContain("-ms-3");
  });

  it("leaves a queued run's empty result line out on a phone", () => {
    setViewport(PHONE_VIEWPORT);
    renderInApp(
      <CrawlRunsTable
        runs={[run({ id: "q", phase: "queued", finished_at: null, pages_crawled: 0 })]}
      />
    );
    const row = within(screen.getByRole("list", { name: "Indexeringar" })).getByRole("listitem");
    // The date and state, then when it started: no line for a result it does not have yet.
    expect(row.children).toHaveLength(2);
  });

  it("lists runs newest first with their state as a status dot and text", async () => {
    const { container } = renderInApp(<CrawlRunsTable runs={RUNS} />);

    // Named like the website page's tab it fills.
    expect(screen.getByRole("table", { name: "Indexeringar" })).toBeTruthy();
    expect(statusColumn()).toEqual(["Delvis klar", "Misslyckades", "Klar"]);
    // On a phone the start time stays in view while the run scrolls sideways
    // (Astryx offsets pinned cells); an iPad held upright (682 px beside the
    // icon rail) shows it whole.
    const table = screen.getByRole("table");
    expect(
      within(table)
        .getAllByRole("columnheader")
        .filter((cell) => cell.style.insetInlineStart)
        .map((cell) => cell.textContent)
    ).toEqual(["Startad"]);
    // The date's text starts on its header's line: the ghost button's padding shrinks to
    // 4 px and is pulled back by as much, so its focus ring stays inside the cell.
    const date = screen.getByRole("button", { name: /5 mars 2024|2024-03-05/ });
    expect(date.className).toContain("-ms-1");
    expect(date.className).toContain("px-1");
    // The widest English date and a running crawl's "Startad för 59 minuter sedan" each
    // fit one line, also at a touch screen's 15 px, and the four columns fit 682 px (an
    // upright iPad beside the icon rail).
    const width = (name: string) =>
      within(table).getByRole("columnheader", { name: new RegExp(name) }).style.width;
    expect([width("Startad"), width("Varaktighet")]).toEqual(["184px", "224px"]);
    expect(Number.parseFloat(table.style.minWidth)).toBeLessThanOrEqual(682);
    expect(screen.getByRole("columnheader", { name: "Startad" }).getAttribute("aria-sort")).toBe(
      "descending"
    );
    const filter = screen.getByRole("textbox", { name: "Filtrera indexeringar" });
    // The placeholder says the same as the label.
    expect(filter.getAttribute("placeholder")).toBe("Filtrera indexeringar…");
    await expectNoAxeViolations(container);
  });

  it("counts what succeeded and opens the failed pages in the run's details", async () => {
    const partial = run({
      id: "one",
      pages_crawled: 4,
      files_downloaded: 1,
      pages_unchanged: 2,
      pages_failed: 1,
      failure_summary: { http_404: 1 }
    });
    failuresPage.run = partial;
    renderInApp(<CrawlRunsTable runs={[partial]} />);
    const results = within(screen.getByRole("table")).getAllByRole("row")[1]!;
    const cell = within(results).getAllByRole("cell")[2]!;
    expect(within(cell).getByText("4 sidor och 1 filer lyckades")).toBeTruthy();
    expect(within(cell).getByText("2 sidor oförändrade")).toBeTruthy();
    expect(cell.querySelector("[title]")).toBeNull();

    // The failed count is a link to the run's failed addresses of that kind.
    fireEvent.click(
      within(cell).getByRole("button", { name: "Sidor: 1, visa de som inte kunde indexeras" })
    );
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("radio", { name: "Sidor" }).getAttribute("aria-checked")).toBe(
      "true"
    );
    const list = await within(dialog).findByRole("list", { name: "Misslyckade adresser" });
    expect(within(list).getByText("Adressen hittades inte (404)")).toBeTruthy();
    expect(within(list).getByRole("link", { name: /example\.com\/saknas/ })).toBeTruthy();
    // The reasons across the run, with what to do, behind a disclosure.
    fireEvent.click(within(dialog).getByRole("button", { name: "Felorsaker i hela körningen" }));
    expect(within(dialog).getByText(/Öppna länken och kontrollera/)).toBeTruthy();
  });

  it("renders dates in the viewer's time zone", () => {
    renderInApp(<CrawlRunsTable runs={[run({ id: "old", created_at: "2024-03-01T10:00:00Z" })]} />);
    const started = within(screen.getByRole("table")).getAllByRole("row")[1]!;
    expect(within(started).getAllByRole("cell")[0]!.querySelector("time")).toBeTruthy();
  });

  it("says when a running crawl started", () => {
    renderInApp(
      <CrawlRunsTable
        runs={[
          run({
            id: "running",
            status: "in progress",
            finished_at: null,
            created_at: new Date(Date.now() - 5 * 60_000).toISOString()
          })
        ]}
      />
    );
    const row = within(screen.getByRole("table")).getAllByRole("row")[1]!;
    expect(within(row).getAllByRole("cell")[3]!.textContent).toMatch(
      /^Startad för 5 minuter sedan$/
    );
  });

  it("sorts by its column headers and filters by the search box", () => {
    renderInApp(<CrawlRunsTable runs={RUNS} />);

    fireEvent.click(screen.getByRole("button", { name: "Status" }));
    expect(statusColumn()[0]).toBe("Misslyckades");

    fireEvent.change(screen.getByRole("textbox", { name: "Filtrera indexeringar" }), {
      target: { value: "timeout" }
    });
    expect(statusColumn()).toEqual(["Misslyckades"]);

    fireEvent.change(screen.getByRole("textbox", { name: "Filtrera indexeringar" }), {
      target: { value: "saknas" }
    });
    expect(screen.queryByRole("table")).toBeNull();
    // In the words of the filter box, not the English "crawls".
    expect(
      screen.getByRole("heading", { name: "Hittade inga indexeringar som matchar dina kriterier" })
    ).toBeTruthy();
  });

  it("says so when the website was never crawled", () => {
    renderInApp(<CrawlRunsTable runs={[]} />);
    expect(
      screen.getByRole("heading", { name: "Denna webbplats har inte indexerats tidigare" })
    ).toBeTruthy();
  });
});
