import { describe, expect, test } from "bun:test";
import { renderSvg } from "../../src/tools/charts/engine/render";
import { init } from "../../src/tools/charts/echarts";
import { PALETTE, chartOptions, imageOptions, imageStyle, type PlotSpec } from "../../src/tools/charts/options";

// Three observed days, then two forecast days with an interval; the forecast line and its
// interval start at the last observed day so the picture has no gap.
const plot: PlotSpec = {
  type: "line",
  title: "Elförbrukning",
  labels: ["2026-10-17", "2026-10-18", "2026-10-19", "2026-10-20", "2026-10-21"],
  series: [
    { name: "Historik", values: [1800, 900, 1850, null, null] },
    { name: "Mittvärde (P50)", values: [null, null, 1850, 1820, 1790] },
  ],
  unit: "kWh",
  stacked: false,
  bands: [{ name: "Spann (P10–P90)", series: 1, lower: [null, null, 1850, 1600, 1550], upper: [null, null, 1850, 2100, 2080] }],
  markers: [{ at: 3, label: "Prognos" }],
  dates: true,
};
const style = { ...imageStyle(1200, "sv-SE"), textSize: 12 };
const view = { selected: {}, zoom: { start: 0, end: 100 } };

type Series = { id?: string; name?: string; stack?: string; data?: unknown[]; areaStyle?: { color?: string }; markLine?: unknown };

describe("intervals around a line", () => {
  test("fill the area between the bounds in the colour of the line they belong to", () => {
    const option = chartOptions(plot, style, view) as { series: Series[] };
    const [lower, span] = option.series.filter((s) => s.stack === "interval-0");
    expect(lower).toMatchObject({ name: "Spann (P10–P90)", data: [null, null, 1850, 1600, 1550] });
    expect(span).toMatchObject({ name: "Spann (P10–P90)", data: [null, null, 0, 500, 530] });
    expect(span!.areaStyle!.color).toContain(PALETTE.light[1].slice(1, 3));
    expect(lower!.areaStyle).toBeUndefined();
  });

  test("show the interval as lowest–highest under the pointer, never as two series", () => {
    const option = chartOptions(plot, style, view) as { tooltip: { formatter: (p: unknown) => string } };
    const at = (index: number) =>
      (chartOptions(plot, style, view) as { series: Series[] }).series.map((s, seriesIndex) => ({
        seriesId: s.id,
        seriesName: s.name,
        seriesIndex,
        dataIndex: index,
        value: s.data?.[index] ?? null,
        marker: "",
        axisValue: plot.labels[index],
      }));
    // Swedish numbers group with no-break spaces; compare the words, not the kind of space.
    const read = (index: number) => option.tooltip.formatter(at(index)).replace(/\s/g, " ");
    expect(read(3)).toContain("tis 20 okt. 2026");
    expect(read(3)).toContain("Mittvärde (P50): 1 820 kWh");
    expect(read(3)).toContain("Spann (P10–P90): 1 600–2 100 kWh");
    expect(read(3)).not.toContain("500");
    expect(read(0)).toContain("Historik: 1 800 kWh");
  });

  test("mark where the forecast starts and read dates as days on the axis", () => {
    const option = chartOptions(plot, style, view) as {
      series: Series[];
      xAxis: { axisLabel: { formatter: (label: string) => string } };
    };
    expect(option.xAxis.axisLabel.formatter("2026-10-20")).toBe("20 okt.");
    // On a series of its own without a name, so hiding a line in the legend keeps the marker.
    const marked = option.series.find((s) => s.id === "markers")!;
    expect(marked.name).toBeUndefined();
    expect(marked.markLine).toMatchObject({ data: [{ xAxis: 3, label: { formatter: "Prognos" } }] });
  });

  test("give each marker its own label", () => {
    const two = { ...plot, markers: [{ at: 1, label: "Lov" }, { at: 3, label: "Prognos" }] };
    const marked = (chartOptions(two, style, view) as { series: Series[] }).series.find((s) => s.id === "markers")!;
    expect(marked.markLine).toMatchObject({
      data: [{ xAxis: 1, label: { formatter: "Lov" } }, { xAxis: 3, label: { formatter: "Prognos" } }],
    });
  });

  test("draw an image's short day-by-day lines without a point on every day or a name at their end", () => {
    const option = imageOptions(plot, style, { width: 1200, height: 675 }) as { series: Record<string, unknown>[] };
    const [history, median] = option.series;
    expect(history!.showSymbol).toBe(false);
    // The legend names the lines; a name where the history ends would sit on the forecast.
    expect(history!.endLabel).toBeUndefined();
    expect(median!.endLabel).toBeUndefined();
  });

  test("speak a chart's own description instead of the generated one", () => {
    const option = chartOptions({ ...plot, description: "Linjediagram: historik och prognos." }, style, view) as {
      aria: { label?: { description?: string } };
    };
    expect(option.aria.label?.description).toBe("Linjediagram: historik och prognos.");
  });

  test("keep an image's many dates upright, letting the ones that collide give way", () => {
    const labels = Array.from({ length: 120 }, (_, i) => new Date(Date.UTC(2026, 5, 1 + i)).toISOString().slice(0, 10));
    const values = labels.map((_, i) => 1000 + i);
    const long: PlotSpec = { ...plot, labels, series: [{ name: "Historik", values }], bands: [], markers: [] };
    const svg = renderSvg(long, { width: 1200, height: 675, locale: "sv-SE" });
    // Tilted labels are drawn turned by 35 degrees.
    expect(svg).not.toMatch(/transform="matrix\(0\.819,-0\.574/);
    expect(svg).toContain("1 juni");
  });

  test("name the interval in an image's legend and draw it", () => {
    const svg = renderSvg(plot, { width: 1200, height: 675, locale: "sv-SE" });
    expect(svg).toContain("Spann (P10–P90)");
    expect(svg).toContain("Prognos");
    expect(svg).toContain("20 okt.");
  });

  test("shade each interval from its lower to its upper bound, below zero as above", () => {
    const signed: PlotSpec = {
      ...plot,
      labels: ["2026-01-01", "2026-01-02", "2026-01-03"],
      series: [{ name: "Saldo", values: [0, -4, 2] }],
      bands: [{ name: "Spann", series: 0, lower: [-2, -5, 1], upper: [1, -3, 3] }],
      markers: [],
    };
    const chart = init(null, undefined, { renderer: "svg", ssr: true, width: 800, height: 400 });
    chart.setOption(chartOptions(signed, style, view));
    const width = (chart as any).getModel().getSeries().find((s: any) => s.id === "interval-0-width");
    const data = width.getData();
    const top = data.getCalculationInfo("stackResultDimension");
    expect([0, 1, 2].map((i) => data.get(top, i))).toEqual([1, -3, 3]);
    chart.dispose();
  });

  test("draw a day with no neighbour as a dot, and its interval as a bar, in the view and the image", () => {
    // One forecast day after a history that ends without a value.
    const alone: PlotSpec = {
      ...plot,
      labels: ["2026-10-17", "2026-10-18", "2026-10-19"],
      series: [
        { name: "Historik", values: [10, null, null] },
        { name: "Mittvärde (P50)", values: [null, null, 20] },
      ],
      bands: [{ name: "Spann (P10–P90)", series: 1, lower: [null, null, 15], upper: [null, null, 25] }],
      markers: [{ at: 2, label: "Prognos" }],
    };
    for (const option of [chartOptions(alone, style, view), imageOptions(alone, style, { width: 1200, height: 675 })] as any[]) {
      const [history, median] = option.series;
      expect(history.markPoint.data).toEqual([{ coord: [0, 10] }]);
      expect(median.markPoint.data).toEqual([{ coord: [2, 20] }]);
      const width = option.series.find((s: any) => s.id === "interval-0-width");
      expect(width.markLine.data).toEqual([[{ coord: [2, 15] }, { coord: [2, 25] }]]);
    }
    // ECharts draws them in a picture too long to show its points: 70 days, the last missing,
    // one day alone between two gaps, then one forecast day.
    const history = Array.from({ length: 70 }, (_, i) => (i === 64 || i === 66 || i === 69 ? null : 100 + i));
    const labels = Array.from({ length: 71 }, (_, i) => new Date(Date.UTC(2026, 7, 11 + i)).toISOString().slice(0, 10));
    const long: PlotSpec = {
      ...plot,
      labels,
      series: [
        { name: "Historik", values: [...history, null] },
        { name: "Mittvärde (P50)", values: [...Array(70).fill(null), 180] },
      ],
      bands: [{ name: "Spann (P10–P90)", series: 1, lower: [...Array(70).fill(null), 170], upper: [...Array(70).fill(null), 190] }],
      markers: [{ at: 70, label: "Prognos" }],
    };
    const svg = renderSvg(long, { width: 1200, height: 675, locale: "sv-SE" });
    const dots = (color: string) => svg.match(new RegExp(`<path d="M1 0A1 1 0 1 1 1 -0.1A1 1 0 0 1 1 0"[^>]*fill="${color}"`, "g"))?.length ?? 0;
    expect(dots(PALETTE.light[0]!)).toBe(1);
    expect(dots(PALETTE.light[1]!)).toBe(1);
    // A line with neighbours needs no dots.
    const option = chartOptions(plot, style, view) as any;
    expect(option.series[1].markPoint).toBeUndefined();
  });
});
