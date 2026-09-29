// Runs inside sandbox children only: reads chart sources and rasterizes charts.
import { ToolError } from "../../errors";
import { readSource } from "../documents/sources";
import { RenderError, renderChart } from "./engine/render";
import type { ChartJob, ChartRendering, ChartSource } from "./ports";
import { ChartSpecError, type ChartSpec } from "./spec";

export async function executeChart(job: ChartJob): Promise<ChartRendering> {
  const spec = job.source ? await fromSource(job.spec, job.source) : job.spec;
  try {
    return renderChart(spec, job.config, job.includeSvg);
  } catch (error) {
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
  const series = source.valueColumns.map((name) => {
    const at = index(name);
    return {
      name,
      values: rows.map((row) => (typeof row[at] === "number" ? (row[at] as number) : null)),
    };
  });
  return {
    ...spec,
    labels: rows.map((row) => String(row[labelAt] ?? "").slice(0, 80)),
    series,
  };
}
