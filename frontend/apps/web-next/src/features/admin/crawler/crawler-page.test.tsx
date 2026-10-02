// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testAppContext } from "@/test/render";

type Run = Record<string, unknown>;

const run = (overrides: Run = {}): Run => ({
  id: "run-1",
  status: "complete",
  phase: "terminal",
  outcome: "partial",
  origin: "scheduled",
  pages_crawled: 40,
  pages_unchanged: 5,
  files_downloaded: 2,
  files_unchanged: 0,
  pages_failed: 3,
  files_failed: 0,
  failure_summary: { http_404: 3 },
  failure_code: "processing_failed",
  failure_detail: null,
  result_location: null,
  created_at: "2026-09-25T08:00:00Z",
  finished_at: "2026-09-25T08:10:00Z",
  cancel_requested_at: null,
  attempt_count: 1,
  ...overrides
});

const overview = () => ({
  as_of: "2026-09-25T09:00:00Z",
  summary: { ongoing: 2, queued: 1, issues: 4 },
  calendar: {
    time_zone: "Europe/Stockholm",
    today: { date: "2026-09-25", completed: 7, partial: 2, failed: 1, cancelled: 0 },
    yesterday: { date: "2026-09-24", completed: 9, partial: 0, failed: 0, cancelled: 1 }
  },
  items: [
    {
      run: run(),
      website_id: "website-1",
      website_name: "Intranätet",
      website_url: "https://intranet.example.se",
      space_name: "HR",
      started_at: "2026-09-25T08:01:00Z",
      last_indexed_at: "2026-09-25T08:10:00Z"
    }
  ],
  next_cursor: null,
  scheduler: {
    status: "degraded",
    ran_at: "2026-09-25T08:00:00Z",
    stale_after_minutes: 65,
    due: 3,
    admitted: 2,
    failed: 1
  }
});

const schedule = () => ({
  as_of: "2026-09-25T09:00:00Z",
  total_count: 1,
  next_cursor: null,
  items: [
    {
      website_id: "website-1",
      website_name: "Intranätet",
      website_url: "https://intranet.example.se",
      space_id: "space-1",
      space_name: "HR",
      update_interval: "daily",
      last_crawled_at: "2026-09-25T08:00:00Z",
      last_indexed_at: "2026-09-25T08:10:00Z",
      consecutive_failures: 0,
      next_retry_at: null,
      auto_disabled: false,
      latest_run: run(),
      active_run_id: null,
      interval_due_at: "2026-09-26T08:00:00Z",
      next_due_at: "2026-09-26T08:00:00Z",
      schedule_state: "due",
      blocked_until: null
    }
  ]
});

const details = () => ({
  run: run(),
  website_id: "website-1",
  website_name: "Intranätet",
  website_url: "https://intranet.example.se",
  space_name: "HR",
  space_id: "space-1",
  started_at: "2026-09-25T08:01:00Z",
  last_indexed_at: "2026-09-25T08:10:00Z",
  owner: { id: "u1", username: "Anna Lind", email: "anna.lind@example.se" },
  initiated_by: null,
  indexed_size: 2_500_000,
  stored_resources: 45,
  update_interval: "daily",
  next_retry_at: null,
  consecutive_failures: 0,
  active_run: null,
  latest_run: run()
});

const state = vi.hoisted(() => ({
  requests: [] as { path: string; query: Record<string, unknown> | undefined }[],
  posted: [] as string[]
}));

vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    GET: (path: string, options?: { params?: { query?: Record<string, unknown> } }) => {
      state.requests.push({ path, query: options?.params?.query });
      const data =
        path === "/api/v1/admin/crawler/"
          ? overview()
          : path === "/api/v1/admin/crawler/websites/"
            ? schedule()
            : path === "/api/v1/admin/crawler/runs/{id}/"
              ? details()
              : path === "/api/v1/admin/crawler/websites/{id}/runs/"
                ? { items: [run()], total_count: 1, next_cursor: null }
                : path === "/api/v1/admin/crawler/websites/{id}/matches/"
                  ? { items: [], next_cursor: null }
                  : {
                      items: [],
                      total_count: 0,
                      next_cursor: null,
                      details_available: true,
                      run: run()
                    };
      return Promise.resolve({ data, response: new Response("{}") });
    },
    POST: (path: string) => {
      state.posted.push(path);
      return Promise.resolve({
        data: run({ id: "run-2", phase: "queued", outcome: null, status: "queued" }),
        response: new Response("{}")
      });
    }
  }
}));

import { CrawlerPage } from "./crawler-page";

afterEach(() => {
  cleanup();
  state.requests = [];
  state.posted = [];
});

const show = () =>
  renderInApp(<CrawlerPage />, { appContext: testAppContext({ permissions: ["admin"] }) });

const lastOverviewQuery = () =>
  state.requests.filter((request) => request.path === "/api/v1/admin/crawler/").at(-1)?.query;

describe("CrawlerPage", () => {
  it("shows the summary, the scheduler's health, the day cards and the runs", async () => {
    const { container } = show();

    expect(screen.getByRole("heading", { level: 1, name: "Crawler" })).toBeTruthy();
    const scheduler = await screen.findByRole("group", { name: "Schemaläggare" });
    expect(within(scheduler).getByText("Delvis fel")).toBeTruthy();
    expect(within(scheduler).getByText("Att köra 3 · Startade 2 · Misslyckade 1")).toBeTruthy();
    expect(
      screen.getByText(
        "Några schemalagda körningar kunde inte startas. Se felen per webbplats i arbetarloggen."
      )
    ).toBeTruthy();

    const today = screen.getByRole("group", { name: "Idag" });
    expect(within(today).getByRole("button", { name: "Visa Klara · Idag" }).textContent).toContain(
      "7"
    );

    const table = screen.getByRole("table", { name: "Alla" });
    const row = within(table).getAllByRole("row")[1]!;
    expect(within(row).getByRole("button", { name: "Intranätet" })).toBeTruthy();
    expect(within(row).getByText("HR")).toBeTruthy();
    expect(within(row).getByText("Delvis klar")).toBeTruthy();
    // The run's counts, with the failed pages as plain numbers (no link for admins here).
    expect(within(row).getByRole("table", { name: "Resultat för denna körning" })).toBeTruthy();
    await expectNoAxeViolations(container);
  });

  it("filters the finished runs by a day card and clears the filters again", async () => {
    show();
    // The cards wait for the overview before they can be pressed.
    await screen.findByRole("table", { name: "Alla" });
    const card = screen.getByRole("button", { name: "Visa Misslyckade · Igår" });
    fireEvent.click(card);

    await waitFor(() =>
      expect(lastOverviewQuery()).toMatchObject({
        view: "recent",
        period: "yesterday",
        status: "unsuccessful"
      })
    );
    expect(card.getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("tab", { name: "Avslutade" }).getAttribute("aria-selected")).toBe(
      "true"
    );

    fireEvent.click(screen.getByRole("button", { name: "Rensa filter" }));
    await waitFor(() =>
      expect(lastOverviewQuery()).toMatchObject({ view: "recent", status: undefined })
    );
  });

  it("lists the scheduled websites under the Schema tab, sorted by the server", async () => {
    show();
    fireEvent.click(await screen.findByRole("tab", { name: "Schema" }));

    const table = await screen.findByRole("table", { name: "Schemalagda webbplatser" });
    const row = within(table).getAllByRole("row")[1]!;
    expect(within(row).getByText("Dagligen")).toBeTruthy();
    expect(within(row).getByText("Dags att köra")).toBeTruthy();
    expect(screen.getByText("1 schemalagda webbplatser", { exact: false })).toBeTruthy();

    fireEvent.click(within(table).getByRole("button", { name: /Sortera efter Webbplats/ }));
    await waitFor(() =>
      expect(
        state.requests
          .filter((request) => request.path === "/api/v1/admin/crawler/websites/")
          .at(-1)?.query
      ).toMatchObject({ sort: "url" })
    );
  });

  it("opens a run's details, with the source and a confirmed re-run", async () => {
    show();
    fireEvent.click(await screen.findByRole("button", { name: "Intranätet" }));

    const dialog = await screen.findByRole("dialog", { name: "Intranätet" });
    expect(await within(dialog).findByText(/Begärd av: Startad enligt schema/)).toBeTruthy();
    // The failures of the run come from the admin endpoint.
    await waitFor(() =>
      expect(
        state.requests.some((r) => r.path === "/api/v1/admin/crawler/runs/{id}/failures/")
      ).toBe(true)
    );

    fireEvent.click(within(dialog).getByRole("tab", { name: "Källa" }));
    expect(within(dialog).getByText("Ägande yta")).toBeTruthy();
    expect(within(dialog).getByText("Anna Lind")).toBeTruthy();
    expect(within(dialog).getByText("45")).toBeTruthy();

    fireEvent.click(within(dialog).getByRole("button", { name: "Försök köra igen" }));
    const confirm = await screen.findByRole("alertdialog", { name: "Försök köra igen" });
    expect(confirm.textContent).toContain("Kör Intranätet igen");
    fireEvent.click(within(confirm).getByRole("button", { name: "Försök köra igen" }));

    await waitFor(() => expect(state.posted).toEqual(["/api/v1/admin/crawler/websites/{id}/run/"]));
  });
});
