import { z } from "zod";

export const chartTypes = ["bar", "line", "pie", "scatter"] as const;
export type ChartType = (typeof chartTypes)[number];
export const MAX_SERIES = 8;
export const MAX_PIE_SLICES = 12;
const label = z.string().max(80);
// A union rather than `.nullable()`: zod serialises the latter as `type: ["number", "null"]`,
// which some MCP clients reject, while a described null branch becomes a portable `anyOf`.
const value = z.union([z.number().finite(), z.null().describe("A missing value.")]);
export const chartSpecSchema = z
  .object({
    type: z
      .enum(chartTypes)
      .describe(
        "bar for comparing categories, line for change over time, pie for shares of one whole (one series, at most 12 slices), scatter for two numeric measures.",
      ),
    title: z.string().max(120).optional().describe("Short chart title shown above the plot."),
    labels: z
      .array(label)
      .max(20_000)
      .default([])
      .describe(
        "Category or x-axis labels, one per value in each series (years, months, municipalities, ...). Not used by scatter.",
      ),
    series: z
      .array(
        z
          .object({
            name: label.min(1).describe("Series name shown in the legend."),
            values: z
              .array(value)
              .min(1)
              .max(20_000)
              .describe("Numeric values in label order. Use null for a missing value."),
            x: z
              .array(z.number().finite())
              .max(20_000)
              .optional()
              .describe("Scatter only: x coordinate for each value."),
          })
          .strict(),
      )
      .min(1)
      .max(MAX_SERIES)
      .describe(`One to ${MAX_SERIES} data series, in the order they should be drawn.`),
    x_label: label.optional().describe("Axis title for the x axis."),
    y_label: label.optional().describe("Axis title for the y axis."),
    unit: z.string().max(12).optional().describe("Unit suffix for values, such as %, kr or st."),
    stacked: z
      .boolean()
      .default(false)
      .describe("Bar only: stack the series instead of grouping them side by side."),
  })
  .strict();
export type ChartSpec = z.infer<typeof chartSpecSchema>;

export class ChartSpecError extends Error {}
/** Structural rules zod cannot express; the total number of data points is returned. */
export function validateChartSpec(spec: ChartSpec, maxPoints: number): number {
  let points = 0;
  for (const series of spec.series) {
    points += series.values.length;
    if (spec.type === "scatter") {
      if (!series.x || series.x.length !== series.values.length)
        throw new ChartSpecError(
          `Scatter series "${series.name}" needs x with one coordinate per value.`,
        );
    } else if (series.values.length !== spec.labels.length) {
      throw new ChartSpecError(
        `Series "${series.name}" has ${series.values.length} values but there are ${spec.labels.length} labels.`,
      );
    }
  }
  if (spec.type === "pie") {
    if (spec.series.length !== 1) throw new ChartSpecError("A pie chart takes exactly one series.");
    const values = spec.series[0]!.values;
    if (values.length > MAX_PIE_SLICES)
      throw new ChartSpecError(
        `A pie chart shows at most ${MAX_PIE_SLICES} slices; group small ones as "Other" or use a bar chart.`,
      );
    if (values.some((v) => v !== null && v < 0))
      throw new ChartSpecError("Pie values must be zero or positive.");
    if (!values.some((v) => v !== null && v > 0))
      throw new ChartSpecError("A pie chart needs at least one positive value.");
  }
  if (spec.stacked && spec.type !== "bar")
    throw new ChartSpecError("stacked applies only to bar charts.");
  if (points > maxPoints)
    throw new ChartSpecError(`Chart has ${points} data points; the limit is ${maxPoints}.`);
  return points;
}
