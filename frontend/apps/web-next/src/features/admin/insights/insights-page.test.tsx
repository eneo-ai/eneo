// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { EneoApiError } from "@/lib/api/errors";
import { renderInApp } from "@/test/render";

const state = vi.hoisted(() => ({ aggregated: "pending" as "pending" | "fail" | "ok" }));
vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    GET: (path: string) => {
      const ok = (data: unknown) => Promise.resolve({ data, response: new Response("{}") });
      switch (path) {
        case "/api/v1/analysis/counts/":
          return ok({ assistants: 3, sessions: 12, questions: 40 });
        case "/api/v1/analysis/metadata-statistics/aggregated/":
          if (state.aggregated === "fail") {
            return Promise.reject(new EneoApiError("boom", { status: 500, code: 9024 }));
          }
          if (state.aggregated === "pending") return new Promise(() => {});
          return ok({ assistants: [], sessions: [], questions: [] });
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
});
afterEach(cleanup);

const busyRegions = () =>
  screen.getAllByRole("status").filter((region) => region.getAttribute("aria-busy") === "true");

describe("InsightsPage", () => {
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
});
