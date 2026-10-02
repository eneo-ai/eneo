import type { SheetSource } from "../documents/ports";
import type { ChartConfig } from "./config";
import type { ChartSpec } from "./spec";

/** Where a chart reads its data when it is not given inline: columns of a CSV or XLSX file. */
export type ChartSource = SheetSource & { labelColumn: string; valueColumns: string[] };

/** Child job: draw one chart (from inline series, or from `source`) and rasterize it. */
export type ChartJob = {
  kind: "render_chart";
  spec: ChartSpec;
  source?: ChartSource;
  includeSvg: boolean;
  /** Resolve and validate data for an app instead of rasterizing an image. */
  interactive?: boolean;
  config: ChartConfig;
};
export type ChartRendering = {
  png_base64: string;
  bytes: number;
  width: number;
  height: number;
  points: number;
  svg?: string;
};

/** Validated data only: never ECharts options, URLs, scripts or source credentials. */
export type InteractiveChart = { chart: ChartSpec; points: number; locale: string };
export type ChartResult = ChartRendering | InteractiveChart;
