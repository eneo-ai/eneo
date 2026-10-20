import { describe, expect, test } from "bun:test";
import { PLOT_TEXTS, forecastPlot } from "../../src/tools/forecast/plot";

const data = {
  recent: { from: "2026-10-17", values: [1800, null, 1850] },
  forecast: { from: "2026-10-20", days: 2, p10: [1600, 1550], p50: [1820, 1790], p90: [2100, 2080] },
};

describe("a forecast's chart", () => {
  test("draws the history, then the median and its interval from the last observed day", () => {
    const plot = forecastPlot(data, PLOT_TEXTS.sv, "El");
    expect(plot).toMatchObject({
      type: "line",
      title: "El",
      dates: true,
      labels: ["2026-10-17", "2026-10-18", "2026-10-19", "2026-10-20", "2026-10-21"],
      series: [
        { name: "Historik", values: [1800, null, 1850, null, null] },
        { name: "Mest troligt (P50)", values: [null, null, 1850, 1820, 1790] },
      ],
      bands: [{ name: "Spann (P10–P90)", series: 1, lower: [null, null, 1850, 1600, 1550], upper: [null, null, 1850, 2100, 2080] }],
      markers: [{ at: 3, label: "Prognos" }],
    });
  });

  test("leaves a gap rather than joining the forecast to a day without a value", () => {
    const plot = forecastPlot({ ...data, recent: { from: "2026-10-17", values: [1800, 1850, null] } }, PLOT_TEXTS.en);
    expect(plot.series[1]!.values).toEqual([null, null, null, 1820, 1790]);
    expect(plot.series.map((s) => s.name)).toEqual(["History", "Most likely (P50)"]);
  });
});
