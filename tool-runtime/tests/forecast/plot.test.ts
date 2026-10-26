import { describe, expect, test } from "bun:test";
import { init } from "../../src/tools/charts/echarts";
import { chartOptions, imageStyle } from "../../src/tools/charts/options";
import { PLOT_TEXTS, focused, forecastPlot, openingZoom } from "../../src/tools/forecast/plot";

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
        { name: "Mittvärde (P50)", values: [null, null, 1850, 1820, 1790] },
      ],
      bands: [{ name: "Spann (P10–P90)", series: 1, lower: [null, null, 1850, 1600, 1550], upper: [null, null, 1850, 2100, 2080] }],
      markers: [{ at: 3, label: "Prognos" }],
    });
  });

  test("shows the days ahead with the weeks before them, as the view opens", () => {
    const long = {
      recent: { from: "2026-04-01", values: Array.from({ length: 180 }, (_, i) => 1000 + i) },
      forecast: { ...data.forecast, from: "2026-09-28" },
    };
    // 56 days before a short forecast, twice the horizon before a long one.
    expect(focused(long).recent).toEqual({ from: "2026-08-03", values: long.recent.values.slice(-56) });
    const far = { ...long, forecast: { ...long.forecast, days: 40 } };
    expect(focused(far).recent.values).toHaveLength(80);
    expect(focused(data)).toEqual(data);
  });

  test("leaves a gap rather than joining the forecast to a day without a value", () => {
    const plot = forecastPlot({ ...data, recent: { from: "2026-10-17", values: [1800, 1850, null] } }, PLOT_TEXTS.en);
    expect(plot.series[1]!.values).toEqual([null, null, null, 1820, 1790]);
    expect(plot.series.map((s) => s.name)).toEqual(["History", "Median (P50)"]);
  });

  test("opens the view on the same first day the picture starts on", () => {
    for (const [recentDays, horizon] of [[180, 14], [180, 28], [180, 120], [40, 7]] as const) {
      const long = {
        recent: { from: "2026-04-01", values: Array.from({ length: recentDays }, (_, i) => 1000 + i) },
        forecast: { from: "2026-09-28", days: horizon, p10: Array(horizon).fill(1), p50: Array(horizon).fill(2), p90: Array(horizon).fill(3) },
      };
      const chart = init(null, undefined, { renderer: "svg", ssr: true, width: 800, height: 400 });
      chart.setOption(chartOptions(forecastPlot(long, PLOT_TEXTS.sv), imageStyle(800, "sv-SE"), { selected: {}, zoom: openingZoom(long) }));
      const [first, last] = (chart as any).getModel().getComponent("xAxis", 0).axis.scale.getExtent();
      expect(first).toBe(recentDays - focused(long).recent.values.length);
      expect(last).toBe(recentDays + horizon - 1);
      chart.dispose();
    }
  });
});
