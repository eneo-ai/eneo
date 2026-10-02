// Rasterization runs in sandbox children only: resvg is native code and must stay out of the
// HTTP process. The tool entrypoint (tool.ts) never imports this file.
import { Resvg } from "@resvg/resvg-js";
import type { ChartConfig } from "../config";
import { setPlatformAPI } from "echarts/core";
import { init } from "../echarts";
import { imageOptions, imageStyle } from "../options";
import type { ChartRendering } from "../ports";
import { validateChartSpec, type ChartSpec } from "../spec";

export class RenderError extends Error {}

// No canvas measures text here, and ECharts' own estimate assumes a narrower face than the
// DejaVu Sans the image is set in. Widths in em, by the kind of character.
const NARROW = /[ijlI.,:;'|!\s]/;
const WIDE = /[mwMW%@]/;
function measureText(text: string, font?: string) {
  const size = Number(/(\d+(?:\.\d+)?)px/.exec(font ?? "")?.[1] ?? 12);
  const bold = /\b(bold|[6-9]00)\b/.test(font ?? "") ? 1.1 : 1;
  let em = 0;
  for (const character of text)
    em += NARROW.test(character)
      ? 0.33
      : WIDE.test(character)
        ? 0.95
        : /[A-ZÅÄÖ\d]/.test(character)
          ? 0.67
          : 0.6;
  return { width: em * size * bold };
}
setPlatformAPI({ measureText });

/** The chart as SVG, drawn by ECharts without a browser. */
export function renderSvg(
  spec: ChartSpec,
  options: { width: number; height: number; locale: string },
): string {
  const { width, height } = options;
  const chart = init(null, null, { renderer: "svg", ssr: true, width, height });
  try {
    chart.setOption(imageOptions(spec, imageStyle(width, options.locale), { width, height }));
    return chart.renderToSVGString();
  } finally {
    chart.dispose();
  }
}
export function renderPng(svg: string, width: number): Buffer {
  const renderer = new Resvg(svg, {
    fitTo: { mode: "width", value: width },
    font: {
      // System font discovery misses Debian's font directories inside the container image,
      // so the packaged DejaVu directory is named explicitly; macOS/Linux hosts add their own.
      loadSystemFonts: true,
      fontDirs: ["/usr/share/fonts", "/usr/local/share/fonts"],
      defaultFontFamily: "DejaVu Sans",
      sansSerifFamily: "DejaVu Sans",
    },
    logLevel: "off",
  });
  return Buffer.from(renderer.render().asPng());
}
export function renderChart(
  spec: ChartSpec,
  config: ChartConfig,
  includeSvg = false,
): ChartRendering {
  const points = validateChartSpec(spec, config.max_points);
  const svg = renderSvg(spec, {
    width: config.width,
    height: config.height,
    locale: config.number_locale,
  });
  const png = renderPng(svg, config.width);
  if (png.length > config.max_image_bytes)
    throw new RenderError("Rendered image exceeds the configured size limit; reduce data points.");
  return {
    png_base64: png.toString("base64"),
    bytes: png.length,
    width: config.width,
    height: config.height,
    points,
    ...(includeSvg ? { svg } : {}),
  };
}
