// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { IntlProvider } from "use-intl";
import en from "@/lib/i18n/messages/en.json";
import { EneoApiError } from "@/lib/api/errors";
import { renderInApp, testAppContext } from "@/test/render";

const state = vi.hoisted(() => ({
  aggregated: "pending" as "pending" | "fail" | "ok",
  calls: [] as { path: string; query?: Record<string, string> }[],
  firstStart: ""
}));
vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    GET: (path: string, init?: { params?: { query?: Record<string, string> } }) => {
      state.calls.push({ path, query: init?.params?.query });
      const ok = (data: unknown) => Promise.resolve({ data, response: new Response("{}") });
      switch (path) {
        case "/api/v1/analysis/counts/":
          return ok({ assistants: 3, sessions: 12, questions: 40123 });
        case "/api/v1/analysis/metadata-statistics/aggregated/":
          if (state.aggregated === "fail") {
            return Promise.reject(new EneoApiError("boom", { status: 500, code: 9024 }));
          }
          if (state.aggregated === "pending") return new Promise(() => {});
          if (!state.firstStart) state.firstStart = init!.params!.query!.start_date!;
          const previous = init!.params!.query!.end_date! < state.firstStart;
          return ok({
            assistants: [{ created_at: "2026-10-20T12:00:00Z", count: previous ? 6 : 3 }],
            sessions: [{ created_at: "2026-10-20T12:00:00Z", count: previous ? 6 : 12 }],
            questions: [{ created_at: "2026-10-20T12:00:00Z", count: previous ? 40123 : 40123 }]
          });
        case "/api/v1/token-usage/":
          return ok({
            total_token_usage: 1500,
            total_input_token_usage: 1200,
            total_output_token_usage: 300,
            models: []
          });
        case "/api/v1/analysis/assistant-activity/":
          return ok({
            active_assistant_count: 2,
            total_trackable_assistants: 3,
            active_user_count: 5
          });
        case "/api/v1/analysis/metadata-statistics/":
          return ok({ assistants: [], sessions: [], questions: [] });
        default:
          // /api/v1/assistants/
          return ok({ items: [], count: 0 });
      }
    }
  }
}));
// recharts needs layout; the chart itself is not under test.
vi.mock("./usage-area-chart", () => ({ UsageAreaChart: () => <div>chart</div> }));

import { InsightsPage } from "./insights-page";

beforeEach(() => {
  state.aggregated = "pending";
  state.calls.length = 0;
  state.firstStart = "";
});
afterEach(cleanup);

const busyRegions = () =>
  screen.getAllByRole("status").filter((region) => region.getAttribute("aria-busy") === "true");

describe("InsightsPage", () => {
  it("formats period totals in the selected UI language", async () => {
    state.aggregated = "ok";
    renderInApp(
      <IntlProvider locale="en" messages={en}>
        <InsightsPage />
      </IntlProvider>
    );
    expect(await screen.findByText("40,123")).toBeTruthy();
  });

  it("compares period totals and uses the same precise bounds for tokens", async () => {
    state.aggregated = "ok";
    renderInApp(<InsightsPage />, {
      appContext: testAppContext({ permissions: ["insights", "admin"] })
    });
    await screen.findByText("chart");
    fireEvent.click(screen.getByRole("switch", { name: "Jämför" }));
    expect(await screen.findByText(/\+100.*jämfört med föregående period/)).toBeTruthy();
    expect(screen.getByText(/−50.*jämfört med föregående period/)).toBeTruthy();
    const aggregate = state.calls.find((call) => call.path.endsWith("aggregated/"))!.query;
    const tokens = state.calls.find((call) => call.path === "/api/v1/token-usage/")!.query;
    expect(aggregate).toMatchObject(tokens!);
    expect(aggregate!.time_zone).toBe(Intl.DateTimeFormat().resolvedOptions().timeZone);
    expect(tokens!.end_date).toMatch(/\.999999Z$/);
    expect(screen.getByRole("link", { name: "Visa tokenanvändning" }).getAttribute("href")).toMatch(
      /tab=tokens&from=/
    );
    expect(state.calls.some((call) => call.path === "/api/v1/analysis/counts/")).toBe(false);
  });

  it("does not request or link to admin token usage for an insights-only user", async () => {
    state.aggregated = "ok";
    renderInApp(<InsightsPage />, { appContext: testAppContext({ permissions: ["insights"] }) });
    await screen.findByText("chart");
    expect(state.calls.some((call) => call.path === "/api/v1/token-usage/")).toBe(false);
    expect(screen.queryByRole("link", { name: "Visa tokenanvändning" })).toBeNull();
  });

  it("shows a chart-sized skeleton while the usage series loads", async () => {
    renderInApp(<InsightsPage />);
    // The activity cards and list have loaded: the one busy region left is the chart's.
    await screen.findByText("Aktiva assistenter");
    await waitFor(() => expect(busyRegions()).toHaveLength(1));
    expect(screen.queryByText("chart")).toBeNull();
  });

  it("shows the shared error state in the chart area and retries", async () => {
    state.aggregated = "fail";
    renderInApp(<InsightsPage />);
    expect(await screen.findByText("Innehållet kunde inte hämtas")).toBeTruthy();

    state.aggregated = "ok";
    fireEvent.click(screen.getByRole("button", { name: "Försök igen" }));
    expect(await screen.findByText("chart")).toBeTruthy();
  });

  it("insets the usage card like the totals above it on a phone", async () => {
    state.aggregated = "ok";
    renderInApp(<InsightsPage />);
    const heading = await screen.findByRole("heading", { name: "Assistentanvändning" });
    // jsdom applies no CSS: the inset is asserted as its classes. At p-6 the card's text
    // sat 8 px further in than the totals' (p-4) above it.
    const card = heading.closest(".astryx-card");
    expect(card?.className.split(" ")).toContain("p-4");
    expect(card?.className).toContain("sm:p-6");
    // And the activity cards after it, so the three kinds of card share one inset.
    for (const label of ["Aktiva assistenter", "Aktiva användare"]) {
      const activity = (await screen.findByText(label)).closest(".astryx-card");
      expect(activity?.className.split(" ")).toContain("p-4");
    }
  });
});
