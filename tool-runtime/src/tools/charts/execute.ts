// Runs inside sandbox children only: reads chart sources and rasterizes charts.
import { ToolError } from "../../errors";
import { readSource } from "../documents/sources";
import { RenderError, renderChart } from "./engine/render";
import type { ChartJob, ChartResult, ChartSource } from "./ports";
import { ChartSpecError, validateChartSpec, type ChartSpec } from "./spec";

export async function executeChart(job: ChartJob): Promise<ChartResult> {
  const spec = job.source ? await fromSource(job.spec, job.source) : job.spec;
  try {
    const points = validateChartSpec(spec, job.config.max_points);
    if (job.interactive) {
      const result = { chart: spec, points, locale: job.config.number_locale };
      // Stay below Eneo's 256 KiB structured-result limit, with room for metadata.
      if (Buffer.byteLength(JSON.stringify(result)) > 200 * 1024) {
        throw new ToolError(
          "CHART_DATA_TOO_LARGE",
          "Chart data exceeds the interactive view limit. Aggregate or filter the data, or request format=png.",
        );
      }
      return result;
    }
    return renderChart(spec, job.config, job.includeSvg);
  } catch (error) {
    if (error instanceof ToolError) throw error;
    if (error instanceof ChartSpecError) throw new ToolError("INVALID_CHART", error.message);
    if (error instanceof RenderError) throw new ToolError("IMAGE_TOO_LARGE", error.message);
    throw new ToolError("RENDER_FAILED", "The chart could not be rendered. Simplify the data.");
  }
}

/** Labels from one column, one series per value column; non-numbers become gaps. */
async function fromSource(spec: ChartSpec, source: ChartSource): Promise<ChartSpec> {
  const { columns, rows } = await readSource(source);
  const index = (name: string) => {
    const at = columns.indexOf(name);
    if (at < 0)
      throw new ToolError(
        "UNKNOWN_COLUMN",
        `The source has no column "${name}". Columns: ${columns.join(", ")}.`,
      );
    return at;
  };
  const labelAt = index(source.labelColumn);
  const x =
    spec.type === "scatter"
      ? rows.map((row) => {
          const value = row[labelAt];
          if (typeof value !== "number" || !Number.isFinite(value)) {
            throw new ToolError("INVALID_CHART", "Scatter x-axis source values must be numeric.");
          }
          return value;
        })
      : undefined;
  const series = source.valueColumns.map((name) => {
    const at = index(name);
    return {
      name: name.slice(0, 80),
      ...(x ? { x } : {}),
      values: rows.map((row) =>
        typeof row[at] === "number" && Number.isFinite(row[at]) ? (row[at] as number) : null,
      ),
    };
  });
  return {
    ...spec,
    labels:
      spec.type === "scatter" ? [] : rows.map((row) => String(row[labelAt] ?? "").slice(0, 80)),
    series,
  };
}
