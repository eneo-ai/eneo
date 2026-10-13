import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { z } from "zod";
import { ToolError } from "../../errors";
import {
  fetchReference,
  fileReference,
  type ReferenceAccess,
} from "../files/reference";
import { RichResult, type ToolDefinition, type ToolView } from "../types";
import type { ChartConfig } from "./config";
import type { ChartJob, ChartResult } from "./ports";
import {
  ChartSpecError,
  MAX_SERIES,
  SERIES_LIMIT_GUIDANCE,
  chartSpecSchema,
  validateChartSpec,
} from "./spec";

/** Runs a chart job in a sandbox child (see sandbox.ts); injected so tests can run in-process. */
export type ChartRunner = (job: ChartJob) => Promise<ChartResult>;

export function chartTools(
  config: ChartConfig,
  run: ChartRunner,
  access: ReferenceAccess,
  resultView?: ToolView,
): ToolDefinition[] {
  const input = chartSpecSchema
    .extend({
      format: z
        .enum(["auto", "png"])
        .default("auto")
        .describe(
          "Leave auto for ordinary chart requests: capable hosts show an interactive chart with hover values, series controls and zoom. Use png when the user explicitly wants an image for downloading or a report. Hosts without app support get a PNG automatically.",
        ),
      display: z
        .enum(["inline", "none"])
        .default("inline")
        .describe(
          "Use none when exporting a chart only as an image input to create_document; Eneo keeps the image available to tools without showing it again in chat. This produces PNG even when format is auto. Leave inline for charts or images the user should see.",
        ),
      series: chartSpecSchema.shape.series
        .optional()
        .describe(
          `One to ${MAX_SERIES} data series, in the order they should be drawn. Leave out when the data comes from source. ${SERIES_LIMIT_GUIDANCE}`,
        ),
      source: fileReference
        .extend({
          sheet: z
            .string()
            .max(200)
            .optional()
            .describe(
              "Exact sheet name for an XLSX source. Omit for CSV or the default sheet.",
            ),
          label_column: z
            .string()
            .max(200)
            .describe(
              "Column whose values become category labels, or numeric x coordinates for scatter.",
            ),
          value_columns: z
            .array(z.string().max(200))
            .min(1)
            .max(MAX_SERIES, SERIES_LIMIT_GUIDANCE)
            .describe(
              `One to ${MAX_SERIES} numeric column names, one series each; the column name is the legend. ${SERIES_LIMIT_GUIDANCE}`,
            ),
        })
        .strict()
        .optional()
        .describe(
          "Instead of labels and series: a CSV or XLSX file (for example the export of query_table) by its signed url and filename, with the columns to draw. This avoids copying rows through your context; it does not increase the eight-series limit. Choose at most eight value_columns per call.",
        ),
      include_svg: z
        .boolean()
        .default(false)
        .describe(
          "Also return the SVG source. Leave false unless the user asked for SVG.",
        ),
    })
    .refine((args) => (args.source ? !args.series : !!args.series), {
      message: "Give either series (with labels) or a source file",
    });
  return [
    {
      name: "create_chart",
      title: "Create chart",
      ...(resultView ? { view: resultView } : {}),
      description:
        "Create a bar, line, pie or scatter chart. Ordinary requests such as 'compare budget and actual' or 'show the trend' automatically use an interactive chart when the host supports apps; the user does not need to request an app or name a tool. Leave format=auto unless the user asks for an image file. Use it when the user asks for a chart, graph, diagram or visualisation, or when a comparison or trend over more than a handful of values is clearer as a picture. When querying a file to prepare this chart, use query_table with display=none unless the user also requested a separate table. Give labels and up to eight named numeric series for small data you already have, or a source file (such as the CSV export of query_table) with one label_column and at most eight value_columns for datasets with more rows. The same eight-series limit applies to BOTH inputs. If the user requests more than eight series, plan multiple create_chart calls before calling this tool: split the series into clearly titled groups of at most eight, reuse the same source file and label_column (or inline labels), and include every requested series exactly once. For example, ten departments can be shown as two charts with five value_columns each. Do not retry the unchanged oversized input or silently omit departments. The tool sizes axes, formats numbers and colours series itself. Pie charts take one series of non-negative values and at most twelve slices. The chart is shown to the user automatically; in your reply, mention what it shows and any limitation of the data, without inventing values. Do not use it for tables of exact figures or a single number.",
      inputSchema: input.shape,
      readOnly: true,
      async execute(raw, ctx) {
        const { include_svg, format, display, source, series, ...rest } =
          input.parse(raw);
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
        const interactive =
          !!resultView &&
          ctx.showsViews === true &&
          format === "auto" &&
          display !== "none" &&
          !include_svg;
        let rendering: ChartResult;
        if (source) {
          const file = await fetchReference(source, ctx, access);
          const directory = await mkdtemp(
            join(tmpdir(), "eneo-tool-runtime-chart-"),
          );
          try {
            const path = join(directory, "source-0");
            await writeFile(path, file.bytes, { mode: 0o600 });
            rendering = await run({
              kind: "render_chart",
              spec,
              includeSvg: include_svg,
              interactive,
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
          rendering = await run({
            kind: "render_chart",
            spec,
            includeSvg: include_svg,
            interactive,
            config,
          });
        }
        if ("chart" in rendering) {
          return {
            ...rendering,
            presentation: "interactive",
            shown:
              "The user sees an interactive chart with hover values, series or slice controls and a data table. Bar, line and scatter charts also have x-axis zoom. Briefly explain the findings and any data limitations; do not create a duplicate image or repeat all values.",
          };
        }
        return new RichResult(
          {
            presentation: "image",
            type: spec.type,
            ...(spec.title ? { title: spec.title } : {}),
            series: source
              ? source.value_columns
              : (series ?? []).map((s) => s.name),
            points: rendering.points,
            locale: config.number_locale,
            image: {
              format: "png",
              width: rendering.width,
              height: rendering.height,
            },
            shown_to_user: display !== "none",
            ...(display === "none"
              ? {
                  use: "Document image asset. Pass the generated PNG reference URL to create_document images and insert its image:ID marker. Do not display or link this image again in the chat.",
                }
              : {}),
            ...(rendering.svg ? { svg: rendering.svg } : {}),
          },
          [],
          [{ data: rendering.png_base64, mimeType: "image/png" }],
        );
      },
    },
  ];
}
