import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { z } from "zod";
import { ToolError } from "../../errors";
import { fetchReference, fileReference, type ReferenceAccess } from "../files/reference";
import { RichResult, type ToolDefinition } from "../types";
import type { ChartConfig } from "./config";
import type { ChartJob, ChartRendering } from "./ports";
import { ChartSpecError, MAX_SERIES, chartSpecSchema, validateChartSpec } from "./spec";

/** Runs a chart job in a sandbox child (see sandbox.ts); injected so tests can run in-process. */
export type ChartRunner = (job: ChartJob) => Promise<ChartRendering>;

export function chartTools(
  config: ChartConfig,
  run: ChartRunner,
  access: ReferenceAccess,
): ToolDefinition[] {
  const input = chartSpecSchema
    .extend({
      series: chartSpecSchema.shape.series
        .optional()
        .describe(
          `One to ${MAX_SERIES} data series, in the order they should be drawn. Leave out when the data comes from source.`,
        ),
      source: fileReference
        .extend({
          sheet: z.string().max(200).optional().describe("Sheet of an XLSX source."),
          label_column: z
            .string()
            .max(200)
            .describe("Column whose values become the category or x-axis labels."),
          value_columns: z
            .array(z.string().max(200))
            .min(1)
            .max(MAX_SERIES)
            .describe("Numeric columns to draw, one series each; the column name is the legend."),
        })
        .strict()
        .optional()
        .describe(
          "Instead of labels and series: a CSV or XLSX file (for example the export of query_table) by its signed url and filename, with the columns to draw. Use it so the data never passes through your context.",
        ),
      include_svg: z
        .boolean()
        .default(false)
        .describe("Also return the SVG source. Leave false unless the user asked for SVG."),
    })
    .refine((args) => (args.source ? !args.series : !!args.series), {
      message: "Give either series (with labels) or a source file",
    });
  return [
    {
      name: "create_chart",
      title: "Create chart",
      description:
        "Draw a bar, line, pie or scatter chart and show it to the user as an image. Use it when the user asks for a chart, graph, diagram or visualisation, or when a comparison or trend over more than a handful of values is clearer as a picture. Give labels and up to eight named numeric series for small data you already have, or a source file (such as the CSV export of query_table) with a label column and value columns for anything larger. The tool sizes axes, formats numbers and colours series itself. Pie charts take one series of non-negative values and at most twelve slices. The chart is shown to the user automatically; in your reply, mention what it shows and any limitation of the data, without inventing values. Do not use it for tables of exact figures or a single number.",
      inputSchema: input.shape,
      readOnly: true,
      async execute(raw, ctx) {
        const { include_svg, source, series, ...rest } = input.parse(raw);
        const spec = chartSpecSchema.parse({
          ...rest,
          // A source fills labels and series in the child; a placeholder keeps the shape valid.
          series: series ?? [{ name: "source", values: [0] }],
        });
        // Inline data is checked here, before a child starts; a source is checked once read.
        if (!source) {
          try {
            validateChartSpec(spec, config.max_points);
          } catch (error) {
            if (error instanceof ChartSpecError)
              throw new ToolError("INVALID_CHART", error.message);
            throw error;
          }
        }
        let rendering: ChartRendering;
        if (source) {
          const file = await fetchReference(source, ctx, access);
          const directory = await mkdtemp(join(tmpdir(), "eneo-tool-runtime-chart-"));
          try {
            const path = join(directory, "source-0");
            await writeFile(path, file.bytes, { mode: 0o600 });
            rendering = await run({
              kind: "render_chart",
              spec,
              includeSvg: include_svg,
              config,
              source: {
                index: 0,
                path,
                isXlsx: file.isXlsx,
                ...(source.sheet ? { sheet: source.sheet } : {}),
                labelColumn: source.label_column,
                valueColumns: source.value_columns,
              },
            });
          } finally {
            await rm(directory, { recursive: true, force: true });
          }
        } else {
          rendering = await run({ kind: "render_chart", spec, includeSvg: include_svg, config });
        }
        return new RichResult(
          {
            type: spec.type,
            ...(spec.title ? { title: spec.title } : {}),
            series: source ? source.value_columns : (series ?? []).map((s) => s.name),
            points: rendering.points,
            locale: config.number_locale,
            image: { format: "png", width: rendering.width, height: rendering.height },
            shown_to_user: true,
            ...(rendering.svg ? { svg: rendering.svg } : {}),
          },
          [],
          [{ data: rendering.png_base64, mimeType: "image/png" }],
        );
      },
    },
  ];
}
