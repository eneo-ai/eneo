// @vitest-environment jsdom
import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { renderInApp } from "@/test/render";
import { expectNoAxeViolations } from "@/test/axe";
import { UsageAreaChart } from "./usage-area-chart";
import type { InsightRange } from "@/features/insights/insights-range";

const range = { start: "2026-06-01", end: "2026-08-31" } as InsightRange;
const data = {
  assistants: [],
  sessions: [{ created_at: "2026-06-15T12:00:00Z", count: 3 }],
  questions: [{ created_at: "2026-06-15T13:00:00Z", count: 7 }]
};
afterEach(cleanup);

describe("overview chart", () => {
  it("switches metric and real hourly/weekday groups with a matching text table", async () => {
    const { container } = renderInApp(<UsageAreaChart data={data} range={range} />);
    fireEvent.click(screen.getByRole("radio", { name: "Ny fråga" }));
    fireEvent.click(screen.getByRole("radio", { name: "Efter timme" }));
    const table = screen.getByRole("table");
    expect(within(table).getByRole("columnheader", { name: "Ny fråga" })).toBeTruthy();
    expect(within(table).getByText("7")).toBeTruthy();
    expect(within(table).getAllByRole("row")).toHaveLength(25);
    fireEvent.click(screen.getByRole("radio", { name: "Efter veckodag" }));
    expect(within(table).getAllByRole("row")).toHaveLength(8);
    await expectNoAxeViolations(container);
  });

  it("bounds long date views and allows keyboard-operable navigation to earlier activity", () => {
    renderInApp(<UsageAreaChart data={data} range={range} />);
    const previous = screen.getByRole("button", { name: "Tidigare dagar" });
    const next = screen.getByRole("button", { name: "Senare dagar" });
    expect(previous.getAttribute("disabled")).toBeNull();
    expect(next.getAttribute("disabled")).not.toBeNull();
    expect(within(screen.getByRole("table")).getAllByRole("row").length).toBeLessThanOrEqual(46);
    fireEvent.click(previous);
    expect(within(screen.getByRole("table")).getByText("3")).toBeTruthy();
    expect(next.getAttribute("disabled")).toBeNull();
    expect(screen.getByText(/Första registrerade aktivitet i vald period/)).toBeTruthy();
  });

  it("shows an empty state for the selected metric even if assistants exist", () => {
    renderInApp(
      <UsageAreaChart
        data={{
          assistants: [{ created_at: "2026-06-15T12:00:00Z", count: 2 }],
          sessions: [],
          questions: []
        }}
        range={range}
      />
    );
    expect(screen.getByText("Ingen aktivitet")).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
  });
});
