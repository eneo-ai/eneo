// @vitest-environment jsdom
import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
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

    expect(statusColumn()).toEqual(["Slutförd med varningar", "MisslyckadesTimeout", "Slutförd"]);
    expect(
      screen.getByRole("button", { name: "Sortera efter Startad, sorterat fallande" })
    ).toBeTruthy();
    expect(screen.getByRole("textbox", { name: "Filtrera indexeringar" })).toBeTruthy();
    await expectNoAxeViolations(container);
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
