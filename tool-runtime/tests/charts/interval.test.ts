import { describe, expect, test } from "bun:test";
import { renderSvg } from "../../src/tools/charts/engine/render";
import { PALETTE, chartOptions, imageStyle, type PlotSpec } from "../../src/tools/charts/options";

// Three observed days, then two forecast days with an interval; the forecast line and its
// interval start at the last observed day so the picture has no gap.
const plot: PlotSpec = {
  type: "line",
  title: "Elförbrukning",
  labels: ["2026-10-17", "2026-10-18", "2026-10-19", "2026-10-20", "2026-10-21"],
  series: [
    { name: "Historik", values: [1800, 900, 1850, null, null] },
    { name: "Mest troligt (P50)", values: [null, null, 1850, 1820, 1790] },
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
    expect(read(3)).toContain("Mest troligt (P50): 1 820 kWh");
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
    const marked = option.series.find((s) => s.markLine);
    expect(marked!.markLine).toMatchObject({ data: [{ xAxis: 3 }], label: { formatter: "Prognos" } });
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
});
