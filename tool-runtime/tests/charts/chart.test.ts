import { describe, expect, test } from "bun:test";
import { runIsolated } from "../../src/sandbox";
import { chartConfigSchema } from "../../src/tools/charts/config";
import { renderChart, renderPng, renderSvg } from "../../src/tools/charts/engine/render";
import { executeChart } from "../../src/tools/charts/execute";
import type { ChartRendering } from "../../src/tools/charts/ports";
import { chartSpecSchema, validateChartSpec } from "../../src/tools/charts/spec";
import { PALETTE, chartOptions, imageStyle } from "../../src/tools/charts/options";
import { chartView } from "../../src/tools/charts/view";
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
describe("chart image", () => {
  test("escapes user text, names every series and keeps the palette order", () => {
    const svg = renderSvg(bars, { width: 1200, height: 675, locale: "sv-SE" });
    expect(svg).toContain("&lt;b&gt;&quot;2025&quot;&lt;/b&gt;");
    expect(svg).not.toContain("<b>");
    expect(svg).toContain("Kvinnor");
    expect(svg).toContain("Män");
    expect(svg).toContain(`fill="${PALETTE.light[0]}"`);
    expect(svg).toContain(`fill="${PALETTE.light[1]}"`);
    expect(svg).toContain("49 800 st");
    expect(svg.startsWith('<svg width="1200" height="675"')).toBe(true);
  });
  test("draws every chart type, breaks lines at missing values and tilts long labels", () => {
    const line = chartSpecSchema.parse({
      type: "line",
      labels: ["2019", "2020", "2021"],
      series: [{ name: "A", values: [1, null, 3] }],
    });
    const lineSvg = renderSvg(line, { width: 800, height: 450, locale: "en-GB" });
    const drawn = new RegExp(`<path d="([^"]*)" fill="none"[^>]*stroke="${PALETTE.light[0]}"`);
    // The pen lifts over the missing value: two starts, no stroke between them.
    expect(drawn.exec(lineSvg)?.[1]?.match(/M/g)).toHaveLength(2);
    const pie = chartSpecSchema.parse({
      type: "pie",
      labels: ["Förskola", "Grundskola"],
      series: [{ name: "Elever", values: [25, 75] }],
    });
    const pieSvg = renderSvg(pie, { width: 800, height: 600, locale: "sv-SE" });
    expect(pieSvg).toContain("Grundskola: 75\u00a0%");
    expect(pieSvg).toContain(`fill="${PALETTE.light[1]}"`);
    const scatter = chartSpecSchema.parse({
      type: "scatter",
      series: [{ name: "S", values: [1, 2], x: [10, 20] }],
    });
    const scatterSvg = renderSvg(scatter, { width: 800, height: 600, locale: "sv-SE" });
    expect(scatterSvg.match(new RegExp(`fill="${PALETTE.light[0]}"`, "g"))).toHaveLength(2);
    const wide = chartSpecSchema.parse({
      type: "bar",
      labels: Array.from({ length: 30 }, (_, i) => `Kommun med långt namn ${i}`),
      series: [{ name: "A", values: Array.from({ length: 30 }, (_, i) => i) }],
    });
    expect(renderSvg(wide, { width: 1200, height: 675, locale: "sv-SE" })).toMatch(
      /transform="matrix\(0\.819,-0\.574[^"]*"[^>]*>Kommun med långt namn 0</,
    );
  });
  test("sums each stack above it and names a few lines where they end", () => {
    const stacked = chartSpecSchema.parse({
      type: "bar",
      stacked: true,
      labels: ["Q1", "Q2"],
      unit: "mnkr",
      series: [
        { name: "Skatt", values: [120, 135] },
        { name: "Avvikelse", values: [-12, 8] },
      ],
    });
    const stackedSvg = renderSvg(stacked, { width: 1200, height: 675, locale: "sv-SE" });
    expect(stackedSvg).toContain(">108\u00a0mnkr<");
    expect(stackedSvg).toContain(">143\u00a0mnkr<");
    const lines = chartSpecSchema.parse({
      type: "line",
      labels: ["jan", "feb"],
      series: [
        { name: "Skola", values: [1, 2] },
        { name: "Vård", values: [2, 3] },
      ],
    });
    const linesSvg = renderSvg(lines, { width: 1200, height: 675, locale: "sv-SE" });
    // Once in the legend and once at the end of its line.
    expect(linesSvg.match(/>Skola</g)).toHaveLength(2);
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

describe("interactive charts", () => {
  const config = chartConfigSchema.parse({ width: 800, height: 450 });
  const access = { allowedFileOrigins: [], maxBytes: 1024 * 1024, timeoutMs: 5000 };
  const ctx = { tenantId: "", userId: "", showsViews: true };
  const view = { uri: "ui://charts/test", html: "<p>Chart</p>" };
  test("defaults to validated app data without rendering an image, and keeps explicit PNG and old-client output", async () => {
    const tool = chartTools(config, executeChart, access, view)[0]!;
    const result = await tool.execute(bars, ctx);
    expect(result).not.toBeInstanceOf(RichResult);
    expect(result).toMatchObject({ presentation: "interactive", chart: bars, points: 4 });
    expect(result).not.toHaveProperty("png_base64");
    expect(
      ((await tool.execute({ ...bars, format: "png" }, ctx)) as RichResult).images[0]?.mimeType,
    ).toBe("image/png");
    expect(
      ((await tool.execute(bars, { ...ctx, showsViews: false })) as RichResult).images,
    ).toHaveLength(1);
    expect(
      ((await chartTools(config, executeChart, access)[0]!.execute(bars, ctx)) as RichResult)
        .images,
    ).toHaveLength(1);
    const svg = (await tool.execute({ ...bars, include_svg: true }, ctx)) as RichResult;
    expect(svg.structured.svg).toContain("<svg");
    expect(svg.structured.presentation).toBe("image");
  });
  test("resolves source data in the isolated job and never exposes its signed reference in app data", async () => {
    const origin = "http://backend:8000";
    const url =
      origin + "/api/v1/files/11111111-1111-4111-8111-111111111111/original/download/?token=secret";
    const tool = chartTools(
      config,
      executeChart,
      {
        ...access,
        download: (async () => ({
          bytes: Buffer.from("year,amount\n2024,10\n2025,20\n"),
          contentType: "text/csv",
        })) as never,
      },
      view,
    )[0]!;
    const result = await tool.execute(
      {
        type: "scatter",
        source: { url, filename: "data.csv", label_column: "year", value_columns: ["amount"] },
      },
      { ...ctx, fileOrigin: origin },
    );
    expect(result).toMatchObject({
      chart: { type: "scatter", series: [{ name: "amount", x: [2024, 2025], values: [10, 20] }] },
    });
    expect(JSON.stringify(result)).not.toContain("token=");
  });
  test("rejects interactive payloads that would be dropped by the host instead of silently truncating them", async () => {
    const spec = chartSpecSchema.parse({
      type: "line",
      labels: Array(2000).fill("å".repeat(80)),
      series: [{ name: "s", values: Array(2000).fill(1) }],
    });
    await expect(
      executeChart({ kind: "render_chart", spec, config, interactive: true, includeSvg: false }),
    ).rejects.toMatchObject({ code: "CHART_DATA_TOO_LARGE" });
  });
  test("the app is self-contained and fits the host's resource limit", async () => {
    const app = await chartView();
    expect(app.uri).toMatch(/^ui:\/\/charts\/chart-[a-f0-9]{12}\.html$/);
    expect(Buffer.byteLength(app.html)).toBeLessThan(2 * 1024 * 1024);
    expect(app.ui).toEqual({ prefersBorder: true });
    expect(app.html).not.toMatch(/<(?:script|link)\b[^>]*(?:src|href)=["']https?:\/\//i);
  });
  test("maps nulls, stacks and scatter coordinates to ECharts without accepting raw options", () => {
    const style = { ...imageStyle(1200, "en-GB"), textSize: 12 };
    const option = chartOptions(
      { ...bars, stacked: true },
      style,
      { selected: { Män: false }, zoom: { start: 10, end: 70 } },
    );
    expect(option).toMatchObject({
      color: [...PALETTE.light],
      tooltip: { renderMode: "richText" },
      legend: { selected: { Män: false } },
      dataZoom: [{ type: "slider", start: 10, end: 70 }],
      series: [
        { stack: "values", data: [49800, 4600] },
        { stack: "values", data: [50100, null] },
      ],
    });
    const scatter = chartSpecSchema.parse({
      type: "scatter",
      series: [{ name: "s", x: [2, 4], values: [3, null] }],
    });
    const unzoomed = { selected: {}, zoom: { start: 0, end: 100 } };
    expect(chartOptions(scatter, { ...style, dark: true }, unzoomed)).toMatchObject({
      color: [...PALETTE.dark],
      xAxis: { type: "value" },
      series: [
        {
          data: [
            [2, 3],
            [4, null],
          ],
        },
      ],
    });
  });
});
