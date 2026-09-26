// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { renderToString } from "react-dom/server";
import { afterEach, describe, expect, it } from "vitest";
import { AstryxProvider } from "@/components/providers/astryx-provider";
import messages from "@/lib/i18n/messages/sv.json";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { CrawlRunsTable } from "./crawl-runs";
import type { CrawlRun } from "./knowledge";

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
    expect(statusColumn()).toEqual(["Slutförd med varningar", "MisslyckadesTimeout", "Slutförd"]);
    expect(
      screen.getByRole("button", { name: "Sortera efter Startad, sorterat fallande" })
    ).toBeTruthy();
    const filter = screen.getByRole("textbox", { name: "Filtrera indexeringar" });
    // The placeholder says the same as the label.
    expect(filter.getAttribute("placeholder")).toBe("Filtrera indexeringar…");
    await expectNoAxeViolations(container);
  });

  it("counts pages and files with plural forms and shows why they failed", () => {
    renderInApp(
      <CrawlRunsTable
        runs={[
          run({
            id: "one",
            pages_crawled: 4,
            files_downloaded: 1,
            pages_failed: 1,
            failure_summary: { EMPTY_CONTENT: 1 }
          })
        ]}
      />
    );
    const results = within(screen.getByRole("table")).getAllByRole("row")[1]!;
    const cell = within(results).getAllByRole("cell")[2]!;
    expect(within(cell).getByText("Indexerade 4 sidor och 1 fil")).toBeTruthy();
    expect(within(cell).getByText("3 sidor och 1 fil lyckades")).toBeTruthy();
    expect(within(cell).getByText("1 sida misslyckades")).toBeTruthy();
    // The breakdown is text, reachable without a pointer (no title tooltip).
    expect(within(cell).getByText("Tomma sidor: 1")).toBeTruthy();
    expect(cell.querySelector("[title]")).toBeNull();
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
    expect(statusColumn()[0]).toBe("MisslyckadesTimeout");

    fireEvent.change(screen.getByRole("textbox", { name: "Filtrera indexeringar" }), {
      target: { value: "timeout" }
    });
    expect(statusColumn()).toEqual(["MisslyckadesTimeout"]);

    fireEvent.change(screen.getByRole("textbox", { name: "Filtrera indexeringar" }), {
      target: { value: "saknas" }
    });
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("says so when the website was never crawled", () => {
    renderInApp(<CrawlRunsTable runs={[]} />);
    expect(
      screen.getByRole("heading", { name: "Denna webbplats har inte crawlats tidigare" })
    ).toBeTruthy();
  });
});
