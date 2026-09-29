import { describe, expect, test } from "bun:test";
import { runIsolated } from "../../src/sandbox";
import { chartConfigSchema } from "../../src/tools/charts/config";
import { renderChart, renderPng } from "../../src/tools/charts/engine/render";
import { executeChart } from "../../src/tools/charts/execute";
import type { ChartRendering } from "../../src/tools/charts/ports";
import { chartSpecSchema, validateChartSpec } from "../../src/tools/charts/spec";
import { escapeXml, niceTicks, palette, renderSvg } from "../../src/tools/charts/svg";
import { chartTools } from "../../src/tools/charts/tool";
import { RichResult, type CallContext } from "../../src/tools/types";

const bars = chartSpecSchema.parse({
  type: "bar",
  title: 'Befolkning <b>"2025"</b>',
  labels: ["Sundsvall", "Ånge"],
  series: [
    { name: "Kvinnor", values: [49800, 4600] },
    { name: "Män", values: [50100, null] },
  ],
  unit: "st",
});
describe("chart specification", () => {
  test("enforces label counts, pie rules and point limits", () => {
    expect(validateChartSpec(bars, 100)).toBe(4);
    expect(() => validateChartSpec(chartSpecSchema.parse({ ...bars, labels: ["x"] }), 100)).toThrow(
      "labels",
    );
    expect(() => validateChartSpec(bars, 3)).toThrow("limit");
    expect(() => validateChartSpec(chartSpecSchema.parse({ ...bars, type: "pie" }), 100)).toThrow(
      "exactly one series",
    );
    const pie = chartSpecSchema.parse({
      type: "pie",
      labels: ["a", "b"],
      series: [{ name: "s", values: [1, -1] }],
    });
    expect(() => validateChartSpec(pie, 100)).toThrow("positive");
    const scatter = chartSpecSchema.parse({
      type: "scatter",
      series: [{ name: "s", values: [1, 2] }],
    });
    expect(() => validateChartSpec(scatter, 100)).toThrow("x");
    expect(() =>
      chartSpecSchema.parse({ ...bars, series: Array(9).fill(bars.series[0]) }),
    ).toThrow();
  });
});
describe("SVG drawing", () => {
  test("escapes user text, names every series and uses the fixed palette order", () => {
    const svg = renderSvg(bars, { width: 1200, height: 675, locale: "sv-SE" });
    expect(svg).toContain("&lt;b&gt;&quot;2025&quot;&lt;/b&gt;");
    expect(svg).not.toContain("<b>");
    expect(svg).toContain("Kvinnor");
    expect(svg).toContain("Män");
    expect(svg).toContain(`fill="${palette[0]}"`);
    expect(svg).toContain(`fill="${palette[1]}"`);
    expect(svg).toContain("49 800 st");
    expect(
      svg.startsWith('<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="675"'),
    ).toBe(true);
    expect(escapeXml("a&b")).toBe("a&amp;b");
  });
  test("draws every chart type, breaks lines at missing values and rotates long labels", () => {
    const line = chartSpecSchema.parse({
      type: "line",
      labels: ["2019", "2020", "2021"],
      series: [{ name: "A", values: [1, null, 3] }],
    });
    const lineSvg = renderSvg(line, { width: 800, height: 450, locale: "en-GB" });
    expect(lineSvg.match(/<path d="M[^"]*" fill="none"/g)).toHaveLength(1);
    expect(lineSvg).toMatch(/d="M[\d. ]+M[\d. ]+" fill="none"/);
    const pie = chartSpecSchema.parse({
      type: "pie",
      labels: ["Förskola", "Grundskola"],
      series: [{ name: "Elever", values: [25, 75] }],
    });
    const pieSvg = renderSvg(pie, { width: 800, height: 600, locale: "sv-SE" });
    expect(pieSvg).toContain("75 %");
    expect(pieSvg.match(/<path d="M[^"]*A[^"]*"/g)).toHaveLength(2);
    const scatter = chartSpecSchema.parse({
      type: "scatter",
      series: [{ name: "S", values: [1, 2], x: [10, 20] }],
    });
    expect(renderSvg(scatter, { width: 800, height: 600, locale: "sv-SE" })).toContain("<circle");
    const wide = chartSpecSchema.parse({
      type: "bar",
      labels: Array.from({ length: 30 }, (_, i) => `Kommun med långt namn ${i}`),
      series: [{ name: "A", values: Array.from({ length: 30 }, (_, i) => i) }],
    });
    expect(renderSvg(wide, { width: 1200, height: 675, locale: "sv-SE" })).toContain("rotate(-35)");
  });
  test("follows the host theme and font and marks every value for the widget", () => {
    const dark = renderSvg(bars, {
      width: 800,
      height: 450,
      locale: "sv-SE",
      theme: "dark",
      font: "Inter, sans-serif",
    });
    expect(dark).toContain('fill="#1b1b1a"');
    expect(dark).toContain('font-family="Inter, sans-serif"');
    expect(dark).toContain('data-series="1" data-index="0"');
    expect(dark).toContain('data-legend="1"');
    const light = renderSvg(bars, { width: 800, height: 450, locale: "sv-SE" });
    expect(light).toContain('fill="#fcfcfb"');
    expect(light).not.toContain("#1b1b1a");
  });
  test("chooses readable tick steps", () => {
    expect(niceTicks(0, 97)).toEqual([0, 20, 40, 60, 80, 100]);
    expect(niceTicks(-5, 5)).toEqual([-6, -4, -2, 0, 2, 4, 6]);
    expect(niceTicks(3, 3)).toEqual([0, 2, 4, 6]);
  });
});
describe("PNG rendering", () => {
  const config = chartConfigSchema.parse({ width: 800, height: 450 });
  test("produces a PNG with visible text within the size limit", () => {
    const rendered = renderChart(bars, config, true);
    const png = Buffer.from(rendered.png_base64, "base64");
    expect(png.subarray(0, 8)).toEqual(
      Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    );
    expect(rendered.bytes).toBe(png.length);
    expect(rendered.bytes).toBeLessThanOrEqual(config.max_image_bytes);
    expect(rendered.svg).toContain("<svg");
    // A title-less rendering must differ: identical bytes mean fonts are missing and text is dropped.
    const untitled = renderChart({ ...bars, title: undefined }, config);
    expect(untitled.png_base64).not.toBe(rendered.png_base64);
    expect(untitled.svg).toBeUndefined();
  });
  test("rejects images over the configured byte limit", () => {
    const tiny = chartConfigSchema.parse({ width: 2000, height: 1400, max_image_bytes: 32 * 1024 });
    const noisy = chartSpecSchema.parse({
      type: "scatter",
      series: Array.from({ length: 8 }, (_, s) => ({
        name: `S${s}`,
        values: Array.from({ length: 200 }, (_, i) => Math.sin(i * 7 + s) * 100),
        x: Array.from({ length: 200 }, (_, i) => Math.cos(i * 3 + s) * 100),
      })),
    });
    expect(() => renderChart(noisy, tiny)).toThrow("size limit");
    expect(
      renderPng("<svg xmlns='http://www.w3.org/2000/svg' width='10' height='10'/>", 10).length,
    ).toBeGreaterThan(0);
  });
});
describe("create_chart", () => {
  const ORIGIN = "http://backend:8000";
  const ctx: CallContext = { tenantId: "", userId: "", fileOrigin: ORIGIN };
  const config = chartConfigSchema.parse({ width: 800, height: 450 });
  const csv = Buffer.from("förvaltning,budget,utfall\nVård,251231,269572\nSkola,277519,267350\n");
  const access = {
    allowedFileOrigins: [],
    maxBytes: 1024 * 1024,
    timeoutMs: 5_000,
    download: (async () => ({ bytes: csv, contentType: "text/csv", name: "x" })) as never,
  };
  const jobs: unknown[] = [];
  const [tool] = chartTools(
    config,
    async (job) => {
      jobs.push(job);
      return executeChart(job);
    },
    access,
  );
  const url = `${ORIGIN}/api/v1/files/11111111-1111-4111-8111-111111111111/original/download/?token=t`;

  test("returns the chart as a PNG image block", async () => {
    const result = await tool!.execute(
      { type: "bar", labels: bars.labels, series: bars.series },
      ctx,
    );
    expect(result).toBeInstanceOf(RichResult);
    const { structured, images, files } = result as RichResult;
    expect(files).toEqual([]);
    expect(images[0]!.mimeType).toBe("image/png");
    expect(Buffer.from(images[0]!.data, "base64").subarray(1, 4).toString()).toBe("PNG");
    expect(structured).toMatchObject({ type: "bar", points: 4, shown_to_user: true });
  });

  test("draws columns of a source file without the data passing through the model", async () => {
    const { structured } = (await tool!.execute(
      {
        type: "bar",
        source: {
          url,
          filename: "resultat.csv",
          label_column: "förvaltning",
          value_columns: ["budget", "utfall"],
        },
      },
      ctx,
    )) as RichResult;
    expect(structured).toMatchObject({ series: ["budget", "utfall"], points: 4 });
    await expect(
      tool!.execute(
        {
          type: "bar",
          source: { url, filename: "r.csv", label_column: "saknas", value_columns: ["budget"] },
        },
        ctx,
      ),
    ).rejects.toMatchObject({ code: "UNKNOWN_COLUMN" });
  });

  test("needs either series or a source, and checks inline data before rendering", async () => {
    const before = jobs.length;
    await expect(tool!.execute({ type: "bar", labels: ["a"] }, ctx)).rejects.toThrow(
      "either series",
    );
    await expect(
      tool!.execute({ type: "pie", labels: ["a"], series: [{ name: "s", values: [-1] }] }, ctx),
    ).rejects.toMatchObject({ code: "INVALID_CHART" });
    expect(jobs.length).toBe(before);
  });

  test("renders in a sandbox child", async () => {
    const rendering = (await runIsolated(
      { job: { kind: "render_chart", spec: bars, includeSvg: false, config } },
      25_000,
    )) as ChartRendering;
    expect(rendering.points).toBe(4);
    expect(rendering.bytes).toBeGreaterThan(0);
  });
});
