// Rasterization runs in sandbox children only: resvg is native code and must stay out of the
// HTTP process. The tool entrypoint (tool.ts) never imports this file.
import { Resvg } from "@resvg/resvg-js";
import type { ChartConfig } from "../config";
import type { ChartRendering } from "../ports";
import { validateChartSpec, type ChartSpec } from "../spec";
import { renderSvg } from "../svg";

export class RenderError extends Error {}
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
