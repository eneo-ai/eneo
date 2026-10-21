import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { z } from "zod";
import { ToolError } from "../../errors";
import { exportFilename, toCsv } from "../files/csv";
import { fetchReference, fileReference, type ReferenceAccess } from "../files/reference";
import type { ChartConfig } from "../charts/config";
import { RichResult, type EmbeddedFile, type ToolDefinition, type ToolView } from "../types";
import { DEFAULT_FORECAST_MODEL, type ForecastConfig } from "./config";
import { HOLDOUT_REASONS } from "./evaluate";
import type { ForecastJob, ForecastResult } from "./ports";
import { DAY_MS, isoDay } from "./series";

/** Runs a forecast job in a sandbox child (see sandbox.ts); injected so tests can run in-process. */
export type ForecastRunner = (job: ForecastJob) => Promise<ForecastResult>;

const SHOWN =
  "The user sees an interactive chart of the recent history and the forecast with its interval, a table of each day, and the method with the check against the last days. Briefly explain what the forecast says and its limitations; do not repeat every value or draw a separate chart of it. For a report, call create_forecast again with the same arguments and display=none: the same forecast, as this chart in an image for create_document.";

const INTERVAL_NOTE =
  "P10-P90 is the model's interval for each day on its own: about 8 outcomes in 10 fall inside it when the model fits the data. Never add P10 or P90 across days; the sum of P50 is an approximate total without an interval.";

export function forecastTools(
  config: ForecastConfig,
  /** How Charts draws pictures; a forecast's picture is drawn the same way. */
  chart: ChartConfig,
  run: ForecastRunner,
  access: ReferenceAccess,
  resultView?: ToolView,
): ToolDefinition[] {
  // The columns sit beside the horizon rather than in the source: that is where models write
  // them, and a source that also repeats them is still the same file.
  const input = z.object({
    source: z
      .object({
        ...fileReference.shape,
        sheet: z
          .string()
          .max(200)
          .optional()
          .describe("Exact sheet name for an XLSX source. Omit for CSV or the default sheet."),
      })
      .describe(
        "The CSV or XLSX file with the daily series: the attached file itself, or the export of query_table, by its signed url and filename.",
      ),
    date_column: z
      .string()
      .max(200)
      .describe("Column in the source with one ISO date (YYYY-MM-DD) per row, one row per day, oldest first."),
    value_column: z
      .string()
      .max(200)
      .describe("Numeric column in the source to forecast. Empty cells are days without a value."),
    horizon: z
      .number()
      .int()
      .min(1)
      .max(config.max_horizon_days)
      .describe(
        `Days to forecast, from the day after the last day with a value in the file, at most ${config.max_horizon_days}.`,
      ),
    title: z
      .string()
      .max(120)
      .optional()
      .describe(
        "Short title saying what is forecast, in the user's language, such as 'Elförbrukning Solbackaskolan, 4 veckor framåt'.",
      ),
    export: z
      .boolean()
      .default(false)
      .describe(
        "Also attach the forecast as a CSV file (the recent history and each day's P10, P50 and P90), for a download, a spreadsheet or a chart.",
      ),
    export_filename: z
      .string()
      .max(120)
      .optional()
      .describe("Download name for the CSV, without a path."),
    format: z
      .enum(["auto", "png"])
      .default("auto")
      .describe(
        "Leave auto: capable hosts show an interactive forecast chart. Use png only when the user explicitly wants an image for downloading or a report. Hosts without app support get a PNG automatically.",
      ),
    display: z
      .enum(["inline", "none"])
      .default("inline")
      .describe(
        "Use none when the forecast is only an image input to create_document; Eneo keeps the image available to tools without showing it in chat. This produces PNG even when format is auto.",
      ),
  });
  return [
    {
      name: "create_forecast",
      title: "Create forecast",
      description:
        "Forecast the coming days of a daily series in a CSV or XLSX file: for each day the median (P50: half the outcomes are expected below it, half above) and an interval (P10-P90), with a check of how the same forecast would have done on the last days of the history. Use it when the user asks what a daily measure (cases, visits, bookings, energy use) will be in the coming days or weeks. The file needs one row per day: a date column (YYYY-MM-DD) and a numeric value column. The forecast starts the day after the last day with a value: empty days at the end of the file (a sheet laid out in advance) are left out, and history.empty_end_days says how many. When the data is per hour or per event, has missing days, or uses another date format, first use query_table to produce one row per day (0 where no activity means zero, empty where the value is unknown) with export=true and display=none, and pass that export. Leave out today if the day is not over. The model knows only the history: not the weather, holidays, school breaks or planned changes. Say so when it matters and add what you know about such days yourself. Never add P10 or P90 across days. Report the check against the last days as it is, including when it is unavailable. For a picture of the forecast in a document, call this tool with display=none rather than drawing P10, P50 and P90 with create_chart: the same arguments give the same forecast, drawn with its history and interval. When the user also asks to see the forecast, make the shown call as well.",
      ...(resultView ? { view: resultView } : {}),
      inputSchema: input.shape,
      readOnly: true,
      async execute(raw, ctx) {
        const args = input.parse(raw);
        // The model Eneo selected; without one (an older Eneo), the one this runtime has.
        if ((ctx.model ?? DEFAULT_FORECAST_MODEL) !== DEFAULT_FORECAST_MODEL)
          throw new ToolError(
            "MODEL_UNAVAILABLE",
            "The forecast model selected in Eneo is not installed in this tool service. Ask the operator to install it or select another model.",
          );
        const interactive =
          !!resultView && ctx.showsViews === true && args.format === "auto" && args.display !== "none";
        const file = await fetchReference(args.source, ctx, access);
        const directory = await mkdtemp(join(tmpdir(), "eneo-tool-runtime-forecast-"));
        let result: ForecastResult;
        try {
          const path = join(directory, "source-0");
          await writeFile(path, file.bytes, { mode: 0o600 });
          result = await run({
            kind: "forecast",
            horizon: args.horizon,
            config,
            source: {
              index: 0,
              path,
              isXlsx: file.isXlsx,
              ...(args.source.sheet ? { sheet: args.source.sheet } : {}),
              dateColumn: args.date_column,
              valueColumn: args.value_column,
            },
            ...(interactive
              ? {}
              : {
                  image: {
                    chart,
                    language: chart.number_locale.startsWith("sv") ? "sv" : "en",
                    ...(args.title ? { title: args.title } : {}),
                  },
                }),
          });
        } finally {
          await rm(directory, { recursive: true, force: true });
        }
        const source = {
          filename: args.source.filename,
          // A CSV has no sheets, whatever name a table tool gave its one table.
          ...(file.isXlsx && args.source.sheet ? { sheet: args.source.sheet } : {}),
          date_column: args.date_column,
          value_column: args.value_column,
        };
        const structured: Record<string, unknown> = {
          ...readable(result, config, args.title),
          source,
          ...(interactive
            ? { presentation: "interactive", shown: SHOWN }
            : {
                presentation: "image",
                shown_to_user: args.display !== "none",
                ...(args.display === "none"
                  ? {
                      use: "Document image asset. Pass the generated PNG reference URL to create_document images and insert its image:ID marker. Do not display or link this image again in the chat.",
                    }
                  : {}),
              }),
        };
        const files: EmbeddedFile[] = [];
        if (args.export) {
          const filename = exportFilename(args.export_filename, "prognos");
          structured.export = {
            filename,
            delivered:
              "The forecast is attached as a CSV file for the user. Use its reference url for further tools.",
          };
          files.push({
            uri: `eneo-tool-runtime://forecast/${crypto.randomUUID()}/${encodeURIComponent(filename)}`,
            mimeType: "text/csv",
            blob: Buffer.from(csv(result)).toString("base64"),
          });
        }
        const images = result.image ? [{ data: result.image.png_base64, mimeType: "image/png" }] : [];
        return files.length || images.length ? new RichResult(structured, files, images) : structured;
      },
    },
  ];
}

/** What the model reads: every number rounded for reading, the holdout computed before that. */
function readable(result: ForecastResult, config: ForecastConfig, title?: string) {
  const round = (values: (number | null)[]) => values.map((v) => (v === null ? null : significant(v, 4)));
  const { forecast, holdout } = result;
  return {
    ...(title ? { title } : {}),
    model: { name: config.model_name, parameters: result.parameters },
    history: result.history,
    forecast: {
      from: forecast.from,
      days: forecast.days,
      p10: round(forecast.p10),
      p50: round(forecast.p50),
      p90: round(forecast.p90),
    },
    recent: { from: result.recent.from, values: round(result.recent.values) },
    holdout:
      "mae" in holdout
        ? { ...holdout, mae: significant(holdout.mae, 4), baseline_mae: significant(holdout.baseline_mae, 4) }
        : { ...holdout, reason: HOLDOUT_REASONS[holdout.unavailable] },
    interval: INTERVAL_NOTE,
  };
}

/**
 * The recent history and the forecast, one row per day. History is written as the file holds
 * it; the forecast in the shortest digits that read back as the model's own single-precision
 * value, so nothing is lost and no float noise is added.
 */
function csv(result: ForecastResult): string {
  const start = Date.parse(`${result.recent.from}T00:00:00Z`);
  const rows: unknown[][] = result.recent.values.map((value, day) => [
    isoDay(start + day * DAY_MS),
    value,
    null,
    null,
    null,
  ]);
  const first = Date.parse(`${result.forecast.from}T00:00:00Z`);
  for (let day = 0; day < result.forecast.days; day++)
    rows.push([
      isoDay(first + day * DAY_MS),
      null,
      single(result.forecast.p10[day]!),
      single(result.forecast.p50[day]!),
      single(result.forecast.p90[day]!),
    ]);
  return toCsv(["date", "actual", "p10", "p50", "p90"], rows);
}

/** The shortest number that is the same single-precision value as `value`. */
function single(value: number): number {
  const target = Math.fround(value);
  // Nine significant digits always identify a single-precision value.
  for (let digits = 1; digits <= 9; digits++) {
    const short = Number(value.toPrecision(digits));
    if (Math.fround(short) === target) return short;
  }
  return target;
}

function significant(value: number, digits: number): number {
  return Number(value.toPrecision(digits));
}
