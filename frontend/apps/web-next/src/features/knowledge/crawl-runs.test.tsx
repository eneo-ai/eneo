// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { renderToString } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AstryxProvider } from "@/components/providers/astryx-provider";
import messages from "@/lib/i18n/messages/sv.json";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
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
  it("lists runs newest first with their state as a status dot and text", async () => {
    const { container } = renderInApp(<CrawlRunsTable runs={RUNS} />);

    // Named like the website page's tab it fills.
    expect(screen.getByRole("table", { name: "Indexeringar" })).toBeTruthy();
    expect(statusColumn()).toEqual(["Delvis klar", "Misslyckades", "Klar"]);
    expect(
      screen.getByRole("button", { name: "Sortera efter Startad, sorterat fallande" })
    ).toBeTruthy();
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
      within(cell).getByRole("button", { name: "Visa sidor som inte kunde indexeras (1)" })
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

  it("renders dates only after hydration, in the viewer's time zone", () => {
    const html = renderToString(
      <QueryClientProvider client={new QueryClient()}>
        <NextIntlClientProvider locale="sv" messages={messages} timeZone="Europe/Stockholm">
          <AstryxProvider>
            <CrawlRunsTable runs={[run({ id: "old", created_at: "2024-03-01T10:00:00Z" })]} />
          </AstryxProvider>
        </NextIntlClientProvider>
      </QueryClientProvider>
    );
    // The server does not know the viewer's zone: no date in its HTML to mismatch.
    expect(html).not.toContain("2024");
    expect(html).not.toContain("<time");

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

    fireEvent.click(screen.getByRole("button", { name: "Sortera efter Status" }));
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
